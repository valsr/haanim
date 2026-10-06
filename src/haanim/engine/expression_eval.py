"""The state expression language of triggers and constraints.

See "Expression Syntax" in the design. An expression such as
``sensor.temperature > 25 and light.kitchen == 'on'`` is parsed once into an
:class:`Expression` and evaluated against a state lookup function. Evaluation
is pure: it reads states through the lookup and nothing else.

Entity states are strings. What a state is converted to depends on what it is
used with (the design's conversion table). If any value in the expression is
unusable (a missing entity, a failed conversion, a missing attribute), the
whole expression is false.
"""

from __future__ import annotations

import ast
import logging
import operator
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Protocol

from haanim.engine import operators
from haanim.engine.errors import AutomationSyntaxError

_LOGGER = logging.getLogger(__name__)

STRING_METHODS = frozenset({"upper", "lower", "startswith", "endswith", "strip", "split"})
LIST_METHODS = frozenset({"index"})
METHODS = STRING_METHODS | LIST_METHODS
NUMERIC_FUNCTIONS = frozenset({"abs", "min", "max", "round"})
FUNCTIONS = NUMERIC_FUNCTIONS | {"len", "int", "float"}

_TRUE_STATES = frozenset({"on", "true"})
_FALSE_STATES = frozenset({"off", "false"})

# The arithmetic of the language: a subset of Python's binary operators
_ARITHMETIC: dict[type[ast.operator], Callable[[Any, Any], Any]] = {
    kind: operators.BINARY[kind] for kind in (ast.Add, ast.Sub, ast.Mult, ast.Div, ast.FloorDiv, ast.Mod)
}

_NUMERIC: dict[str, Callable[..., Any]] = {"abs": abs, "min": min, "max": max}

_COMPARISONS: dict[type[ast.cmpop], Callable[[Any, Any], bool]] = {
    ast.Eq: operator.eq,
    ast.NotEq: operator.ne,
    ast.Lt: operator.lt,
    ast.LtE: operator.le,
    ast.Gt: operator.gt,
    ast.GtE: operator.ge,
}


class EntityState(Protocol):
    """What the lookup returns for an entity: its state string and its attributes."""

    @property
    def state(self) -> str | None:
        """The entity's state."""
        ...

    @property
    def attributes(self) -> Mapping[str, Any]:
        """The entity's attributes."""
        ...


# Returns the state of an entity, or None if the entity does not exist.
StateLookup = Callable[[str], EntityState | None]


class Unusable(Exception):
    """A value in the expression cannot be used; the whole expression is false."""


@dataclass(frozen=True)
class EntityOperand:
    """An entity as an operand: its state, not yet converted to anything.

    What the state is converted to depends on what it is used with; see
    ``compare()``, ``contains()`` and ``truth()``.
    """

    entity_id: str
    state: str
    attributes: Mapping[str, Any]

    def as_float(self) -> float:
        """Convert the state to a number."""
        try:
            return float(self.state)
        except ValueError:
            raise Unusable(f"{self.entity_id} is '{self.state}', which is not a number") from None

    def is_numeric(self) -> bool:
        """Return whether the state can be converted to a number."""
        try:
            float(self.state)
        except ValueError:
            return False
        return True

    def as_bool(self) -> bool:
        """Convert the state to a boolean: on/true or off/false, ignoring case."""
        lowered = self.state.lower()
        if lowered in _TRUE_STATES:
            return True
        if lowered in _FALSE_STATES:
            return False
        raise Unusable(f"{self.entity_id} is '{self.state}', which is not on, off, true or false")


@dataclass(frozen=True)
class Evaluation:
    """The outcome of evaluating an expression.

    Args:
        result: The value of the expression. False if a value was unusable.
        entities: The entities the expression refers to.
        unusable: Why the expression is false regardless of its logic; None if
            every value could be used.
    """

    result: bool
    entities: frozenset[str]
    unusable: str | None = None


def _is_number(value: Any) -> bool:
    """Return whether a value is an int or float, and not a bool."""
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _entity_id(node: ast.AST) -> str | None:
    """Return the entity ID a node spells (``domain.object_id``), or None if it is not one."""
    if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
        return f"{node.value.id}.{node.attr}"
    return None


class _Checker(ast.NodeVisitor):
    """Checks that an expression uses only the language of the design, and collects its entities."""

    def __init__(self) -> None:
        self.entities: set[str] = set()

    def generic_visit(self, node: ast.AST) -> None:
        raise _Invalid(node, f"{type(node).__name__} is not available in a state expression")

    def _visit_all(self, nodes: list[ast.expr]) -> None:
        for node in nodes:
            self.visit(node)

    def visit_Expression(self, node: ast.Expression) -> None:  # pylint: disable=invalid-name
        """Check the expression's body."""
        self.visit(node.body)

    def visit_BoolOp(self, node: ast.BoolOp) -> None:  # pylint: disable=invalid-name
        """Check ``and`` and ``or``."""
        self._visit_all(node.values)

    def visit_UnaryOp(self, node: ast.UnaryOp) -> None:  # pylint: disable=invalid-name
        """Check ``not`` and a sign."""
        if not isinstance(node.op, (ast.Not, ast.USub, ast.UAdd)):
            raise _Invalid(node, f"the operator {type(node.op).__name__} is not available")
        self.visit(node.operand)

    def visit_BinOp(self, node: ast.BinOp) -> None:  # pylint: disable=invalid-name
        """Check arithmetic."""
        if type(node.op) not in _ARITHMETIC:
            raise _Invalid(node, f"the operator {type(node.op).__name__} is not available")
        self.visit(node.left)
        self.visit(node.right)

    def visit_Compare(self, node: ast.Compare) -> None:  # pylint: disable=invalid-name
        """Check comparisons and membership."""
        for comparison in node.ops:
            if type(comparison) not in _COMPARISONS and not isinstance(comparison, (ast.In, ast.NotIn)):
                raise _Invalid(node, f"the operator {type(comparison).__name__} is not available")
        self.visit(node.left)
        self._visit_all(node.comparators)

    def visit_Constant(self, node: ast.Constant) -> None:  # pylint: disable=invalid-name
        """Check a literal: a string, a number, True or False."""
        if not isinstance(node.value, (str, int, float)):
            raise _Invalid(node, f"the literal {node.value!r} is not available")

    def visit_List(self, node: ast.List) -> None:  # pylint: disable=invalid-name
        """Check a list."""
        self._visit_all(node.elts)

    def visit_Tuple(self, node: ast.Tuple) -> None:  # pylint: disable=invalid-name
        """Check a tuple, which is treated as a list."""
        self._visit_all(node.elts)

    def visit_Name(self, node: ast.Name) -> None:  # pylint: disable=invalid-name
        """Reject a bare name: entities are ``domain.name`` and strings are quoted."""
        if node.id in ("on", "off", "true", "false"):
            raise _Invalid(
                node, f"'{node.id}' is not a literal; write True or False, or compare with '{node.id}'"
            )
        raise _Invalid(node, f"'{node.id}' is not an entity; an entity is written domain.name")

    def visit_Attribute(self, node: ast.Attribute) -> None:  # pylint: disable=invalid-name
        """Check ``domain.name``; anything else after a dot must be a method call."""
        entity_id = _entity_id(node)
        if entity_id is None:
            hint = "a method must be called" if node.attr in METHODS else "attributes use ['name']"
            raise _Invalid(node, f"'.{node.attr}' is not available here; {hint}")
        self.entities.add(entity_id)

    def visit_Subscript(self, node: ast.Subscript) -> None:  # pylint: disable=invalid-name
        """Check ``entity['attribute']`` and indexing."""
        self.visit(node.value)
        if isinstance(node.slice, ast.Slice):
            raise _Invalid(node, "slices are not available")
        self.visit(node.slice)

    def visit_Call(self, node: ast.Call) -> None:  # pylint: disable=invalid-name
        """Check a call of a standard function or of a string or list method."""
        if node.keywords:
            raise _Invalid(node, "keyword arguments are not available")
        if isinstance(node.func, ast.Name):
            if node.func.id not in FUNCTIONS:
                raise _Invalid(node, f"the function {node.func.id}() is not available")
        elif isinstance(node.func, ast.Attribute):
            if node.func.attr not in METHODS:
                raise _Invalid(node, f"the method .{node.func.attr}() is not available")
            self.visit(node.func.value)
        else:
            raise _Invalid(node, "only functions and methods can be called")
        self._visit_all(node.args)


class _Invalid(Exception):
    """The expression uses something the language does not have."""

    def __init__(self, node: ast.AST, message: str) -> None:
        super().__init__(message)
        self.col_offset: int = getattr(node, "col_offset", 0)


class _Evaluator:
    """Evaluates a checked expression tree against a state lookup."""

    def __init__(self, lookup: StateLookup) -> None:
        self._lookup = lookup

    def value(self, node: ast.AST) -> Any:
        """Evaluate a node to a value. An entity is returned unconverted."""
        return getattr(self, f"_{type(node).__name__.lower()}")(node)

    def truth(self, node: ast.AST) -> bool:
        """Evaluate a node used on its own or with ``and``, ``or`` or ``not``."""
        return truth(self.value(node))

    @staticmethod
    def _as_number(value: Any, what: str) -> Any:
        """Convert the operand of arithmetic or of a numeric function."""
        if isinstance(value, EntityOperand):
            return value.as_float()
        if _is_number(value):
            return value
        raise Unusable(f"{what} needs a number, not {value!r}")

    @staticmethod
    def _as_text(value: Any) -> Any:
        """Replace an entity by its state string; leave everything else."""
        return value.state if isinstance(value, EntityOperand) else value

    # --- Literals and entities --------------------------------------------------

    def _expression(self, node: ast.Expression) -> Any:
        return self.value(node.body)

    @staticmethod
    def _constant(node: ast.Constant) -> Any:
        return node.value

    def _list(self, node: ast.List | ast.Tuple) -> list[Any]:
        return [self.value(item) for item in node.elts]

    _tuple = _list

    def _attribute(self, node: ast.Attribute) -> EntityOperand:
        entity_id = _entity_id(node)
        assert entity_id is not None
        found = self._lookup(entity_id)
        if found is None or found.state is None:
            raise Unusable(f"{entity_id} does not exist")
        return EntityOperand(entity_id, str(found.state), found.attributes)

    def _subscript(self, node: ast.Subscript) -> Any:
        target = self.value(node.value)
        key = self._as_text(self.value(node.slice))
        if isinstance(target, EntityOperand):
            # Attribute values keep the type the host gives them
            if key not in target.attributes:
                raise Unusable(f"{target.entity_id} has no attribute {key!r}")
            return target.attributes[key]
        try:
            return target[key]
        except (LookupError, TypeError) as err:
            raise Unusable(f"cannot take [{key!r}] of {target!r}: {err}") from None

    # --- Operators --------------------------------------------------------------

    def _boolop(self, node: ast.BoolOp) -> bool:
        # Every operand is evaluated: an unusable value anywhere makes the expression false
        values = [self.truth(value) for value in node.values]
        return all(values) if isinstance(node.op, ast.And) else any(values)

    def _unaryop(self, node: ast.UnaryOp) -> Any:
        if isinstance(node.op, ast.Not):
            return not self.truth(node.operand)
        number = self._as_number(self.value(node.operand), "a sign")
        return -number if isinstance(node.op, ast.USub) else number

    def _binop(self, node: ast.BinOp) -> Any:
        left = self._as_number(self.value(node.left), "arithmetic")
        right = self._as_number(self.value(node.right), "arithmetic")
        try:
            return _ARITHMETIC[type(node.op)](left, right)
        except ZeroDivisionError:
            raise Unusable("division by zero") from None

    def _compare(self, node: ast.Compare) -> bool:
        # A chain a < b < c is a < b and b < c; all of it is evaluated
        operands = [self.value(node.left), *(self.value(comparator) for comparator in node.comparators)]
        results = [
            self._compare_pair(comparison, left, right)
            for comparison, left, right in zip(node.ops, operands, operands[1:])
        ]
        return all(results)

    def _compare_pair(self, comparison: ast.cmpop, left: Any, right: Any) -> bool:
        if isinstance(comparison, (ast.In, ast.NotIn)):
            contained = contains(right, left)
            return contained if isinstance(comparison, ast.In) else not contained
        return compare(_COMPARISONS[type(comparison)], left, right)

    # --- Calls ------------------------------------------------------------------

    def _call(self, node: ast.Call) -> Any:
        arguments = [self.value(argument) for argument in node.args]
        if isinstance(node.func, ast.Name):
            return self._function(node.func.id, arguments)
        assert isinstance(node.func, ast.Attribute)
        return self._method(self.value(node.func.value), node.func.attr, arguments)

    def _function(self, name: str, arguments: list[Any]) -> Any:
        try:
            if name == "len":
                (value,) = arguments
                return len(self._as_text(value))
            if name in ("int", "float"):
                (value,) = arguments
                number = float(self._as_text(value))
                return int(number) if name == "int" else number
            if name == "round":
                number = self._as_number(arguments[0], "round()")
                return round(number, *arguments[1:])
            numbers = [self._as_number(argument, f"{name}()") for argument in arguments]
            return _NUMERIC[name](*numbers)
        except (TypeError, ValueError, IndexError) as err:
            raise Unusable(f"{name}() cannot be applied: {err}") from None

    def _method(self, target: Any, name: str, arguments: list[Any]) -> Any:
        # A method called on an entity is applied to its state string
        target = self._as_text(target)
        arguments = [self._as_text(argument) for argument in arguments]
        allowed = (
            STRING_METHODS if isinstance(target, str) else LIST_METHODS if isinstance(target, list) else ()
        )
        if name not in allowed:
            raise Unusable(f".{name}() cannot be applied to {target!r}")
        try:
            return getattr(target, name)(*arguments)
        except (TypeError, ValueError) as err:
            raise Unusable(f".{name}() cannot be applied to {target!r}: {err}") from None


def compare(comparison: Callable[[Any, Any], bool], left: Any, right: Any) -> bool:
    """Compare two values, converting an entity by what it is compared with.

    Args:
        comparison: The comparison, such as ``operator.gt``.
        left: The left value; an ``EntityOperand`` for an entity.
        right: The right value; an ``EntityOperand`` for an entity.

    Returns:
        The result of the comparison.

    Raises:
        Unusable: If a conversion fails or the values cannot be compared.
    """
    left, right = _convert_pair(left, right)
    try:
        return bool(comparison(left, right))
    except TypeError:
        raise Unusable(f"cannot compare {left!r} with {right!r}") from None


def _convert_pair(left: Any, right: Any) -> tuple[Any, Any]:
    """Apply the conversion table to the two sides of a comparison."""
    if isinstance(left, EntityOperand) and isinstance(right, EntityOperand):
        if left.is_numeric() and right.is_numeric():
            return left.as_float(), right.as_float()
        return left.state, right.state
    if isinstance(left, EntityOperand):
        return _convert_entity(left, right), right
    if isinstance(right, EntityOperand):
        return left, _convert_entity(right, left)
    return left, right


def contains(container: Any, item: Any) -> bool:
    """Evaluate ``item in container`` for a list, or for a string or an entity's state.

    Raises:
        Unusable: If a conversion fails or the test cannot be made.
    """
    if isinstance(container, list):
        # Each item is compared using the rule for its own type.
        # A list, not a generator: every item is evaluated, so an unusable one is noticed
        matches = [compare(operator.eq, item, member) for member in container]
        return any(matches)
    text = container.state if isinstance(container, EntityOperand) else container
    item = item.state if isinstance(item, EntityOperand) else item
    if not isinstance(text, str) or not isinstance(item, str):
        raise Unusable(f"cannot test whether {item!r} is in {text!r}")
    return item in text


def truth(value: Any) -> bool:
    """Return the value used on its own: an entity's state as a boolean, anything else as in Python.

    Raises:
        Unusable: If an entity's state is not on, off, true or false.
    """
    return value.as_bool() if isinstance(value, EntityOperand) else bool(value)


def _convert_entity(entity: EntityOperand, other: Any) -> Any:
    """Convert an entity's state by the type of the value it is compared with."""
    if isinstance(other, bool):
        return entity.as_bool()
    if _is_number(other):
        return entity.as_float()
    # A string is never a conversion; neither is anything else
    return entity.state


class Expression:
    """A parsed state expression."""

    def __init__(self, source: str) -> None:
        """Parse and check an expression.

        Args:
            source: The expression text.

        Raises:
            AutomationSyntaxError: If the text is not a valid state expression.
        """
        self.source = source
        try:
            self._tree = ast.parse(source.strip(), mode="eval")
            checker = _Checker()
            checker.visit(self._tree)
        except SyntaxError as err:
            raise AutomationSyntaxError(
                f"Invalid state expression '{source}': {err.msg}", col_offset=err.offset
            ) from None
        except _Invalid as err:
            raise AutomationSyntaxError(
                f"Invalid state expression '{source}': {err}", col_offset=err.col_offset
            ) from None
        self.entities: frozenset[str] = frozenset(checker.entities)

    def __repr__(self) -> str:
        return f"Expression({self.source!r})"

    def evaluate(self, lookup: StateLookup) -> Evaluation:
        """Evaluate the expression.

        Args:
            lookup: Returns the state of an entity, or None if it does not exist.

        Returns:
            The result, the referenced entities, and the reason if a value was unusable.
        """
        try:
            result = _Evaluator(lookup).truth(self._tree)
        except Unusable as err:
            # Not a warning: entities are routinely unavailable for short periods
            _LOGGER.debug("Expression '%s' is false: %s", self.source, err)
            return Evaluation(False, self.entities, str(err))
        return Evaluation(result, self.entities)

    def holds(self, lookup: StateLookup) -> bool:
        """Return whether the expression is true. False if a value is unusable."""
        return self.evaluate(lookup).result

    def blocks(self, lookup: StateLookup) -> bool:
        """Return whether the expression, used as ``when_not``, blocks a trigger.

        It blocks when it is true, and also when a value is unusable.
        """
        evaluation = self.evaluate(lookup)
        return evaluation.result or evaluation.unusable is not None


@lru_cache(maxsize=1024)
def parse_expression(source: str) -> Expression:
    """Parse a state expression, for validation when an automation starts and for evaluation.

    Args:
        source: The expression text.

    Returns:
        The parsed expression. Parsing the same text again returns the same object.

    Raises:
        AutomationSyntaxError: If the text is not a valid state expression.
    """
    return Expression(source)


def evaluate_expression(source: str, lookup: StateLookup) -> tuple[bool, frozenset[str]]:
    """Evaluate a state expression.

    Args:
        source: The expression text.
        lookup: Returns the state of an entity, or None if it does not exist.

    Returns:
        The result and the entities the expression refers to.

    Raises:
        AutomationSyntaxError: If the text is not a valid state expression.
    """
    evaluation = parse_expression(source).evaluate(lookup)
    return evaluation.result, evaluation.entities
