"""Expression evaluator for state triggers and constraints.

This module provides a safe expression evaluator for comparing entity states
with support for operators, string methods, and type conversion.
"""

from __future__ import annotations

import ast
import logging
import operator
from typing import Any

from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)

# Supported binary operators
OPERATORS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Eq: operator.eq,
    ast.NotEq: operator.ne,
    ast.Lt: operator.lt,
    ast.LtE: operator.le,
    ast.Gt: operator.gt,
    ast.GtE: operator.ge,
    ast.In: lambda a, b: a in b,
    ast.NotIn: lambda a, b: a not in b,
}

# Supported unary operators
UNARY_OPERATORS = {
    ast.Not: operator.not_,
    ast.UAdd: operator.pos,
    ast.USub: operator.neg,
}

# Supported boolean operators
BOOL_OPERATORS = {
    ast.And: all,
    ast.Or: any,
}

# Safe functions available in expressions
SAFE_FUNCTIONS = {
    "len": len,
    "abs": abs,
    "min": min,
    "max": max,
    "round": round,
    "int": int,
    "float": float,
    "str": str,
    "bool": bool,
}


class ExpressionEvaluator:
    """Evaluates expressions for state triggers and constraints.

    Supports:
    - Entity state access: sensor.temperature, light.living_room['brightness']
    - Operators: ==, !=, >, <, >=, <=, and, or, not, in
    - String methods: .upper(), .lower(), .startswith(), .endswith(), .strip(), .split()
    - Functions: len(), abs(), min(), max(), round(), int(), float()
    - Auto type conversion for comparisons
    """

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize the expression evaluator.

        Args:
            hass: Home Assistant instance for entity access.
        """
        self._hass = hass

    def evaluate(self, expression: str) -> bool:
        """Evaluate an expression and return the boolean result.

        Args:
            expression: The expression string to evaluate.

        Returns:
            Boolean result of the expression.

        Raises:
            ValueError: If expression is invalid or evaluation fails.
        """
        try:
            # Parse the expression
            tree = ast.parse(expression, mode="eval")

            # Evaluate the expression
            result = self._eval_node(tree.body)

            # Convert result to boolean
            return bool(result)
        except Exception as err:
            _LOGGER.warning("Failed to evaluate expression '%s': %s", expression, err)
            raise ValueError(f"Invalid expression: {err}") from err

    def _eval_node(self, node: ast.AST) -> Any:
        """Recursively evaluate an AST node.

        Args:
            node: The AST node to evaluate.

        Returns:
            The evaluation result.
        """
        if isinstance(node, ast.Constant):
            return node.value

        elif isinstance(node, ast.Name):
            # Entity access: sensor.temperature -> ast.Name(id='sensor')
            # This is part of an attribute chain, handled by ast.Attribute
            raise ValueError(f"Bare names not supported: {node.id}")

        elif isinstance(node, ast.Attribute):
            # Entity attribute access: sensor.temperature, light.room['brightness']
            return self._eval_attribute(node)

        elif isinstance(node, ast.Subscript):
            # Subscript access: entity['attribute']
            value = self._eval_node(node.value)
            key = self._eval_node(node.slice)

            if isinstance(value, dict):
                return value.get(key)
            elif isinstance(value, (list, tuple, str)):
                return value[key]
            else:
                raise ValueError(f"Cannot subscript type {type(value)}")

        elif isinstance(node, ast.List):
            return [self._eval_node(elt) for elt in node.elts]

        elif isinstance(node, ast.Tuple):
            return tuple(self._eval_node(elt) for elt in node.elts)

        elif isinstance(node, ast.BinOp):
            # Binary operation: a + b, a > b
            left = self._eval_node(node.left)
            right = self._eval_node(node.right)
            op = OPERATORS.get(type(node.op))
            if not op:
                raise ValueError(f"Unsupported operator: {type(node.op)}")

            # Auto type conversion for comparisons
            if isinstance(node.op, (ast.Eq, ast.NotEq, ast.Lt, ast.LtE, ast.Gt, ast.GtE)):
                left, right = self._auto_convert(left, right)

            return op(left, right)

        elif isinstance(node, ast.UnaryOp):
            # Unary operation: not x, -x
            operand = self._eval_node(node.operand)
            op = UNARY_OPERATORS.get(type(node.op))
            if not op:
                raise ValueError(f"Unsupported unary operator: {type(node.op)}")
            return op(operand)

        elif isinstance(node, ast.BoolOp):
            # Boolean operation: a and b, a or b
            op = BOOL_OPERATORS.get(type(node.op))
            if not op:
                raise ValueError(f"Unsupported bool operator: {type(node.op)}")

            values = [self._eval_node(v) for v in node.values]
            if isinstance(node.op, ast.And):
                return all(values)
            else:  # Or
                return any(values)

        elif isinstance(node, ast.Compare):
            # Comparison: a < b < c
            left = self._eval_node(node.left)

            for op, comparator in zip(node.ops, node.comparators):
                right = self._eval_node(comparator)
                op_func = OPERATORS.get(type(op))
                if not op_func:
                    raise ValueError(f"Unsupported comparison: {type(op)}")

                # Auto type conversion
                left_cmp, right_cmp = self._auto_convert(left, right)

                if not op_func(left_cmp, right_cmp):
                    return False
                left = right

            return True

        elif isinstance(node, ast.Call):
            # Function call: len(x), x.upper()
            return self._eval_call(node)

        else:
            raise ValueError(f"Unsupported node type: {type(node)}")

    def _eval_attribute(self, node: ast.Attribute) -> Any:
        """Evaluate attribute access (entity.state or value.method).

        Args:
            node: The attribute node.

        Returns:
            The attribute value or method result.
        """
        # Check if this is entity access or method call
        if isinstance(node.value, ast.Name):
            # This is entity access: domain.entity_name
            domain = node.value.id
            entity_name = node.attr
            entity_id = f"{domain}.{entity_name}"

            # Get entity state
            state_obj = self._hass.states.get(entity_id)
            if state_obj is None:
                _LOGGER.debug("Entity %s not found, treating as None", entity_id)
                return None

            # Return state value
            return state_obj.state

        elif isinstance(node.value, ast.Attribute):
            # Nested attribute: sensor.temp['brightness'] or value.method()
            value = self._eval_node(node.value)
            attr_name = node.attr

            # Check if it's a string method
            if isinstance(value, str) and hasattr(str, attr_name):
                return getattr(value, attr_name)

            # Check if it's a list method
            if isinstance(value, list) and hasattr(list, attr_name):
                return getattr(value, attr_name)

            raise ValueError(f"Attribute {attr_name} not found on {type(value)}")

        else:
            # Evaluate the base value
            value = self._eval_node(node.value)
            attr_name = node.attr

            # Handle string methods
            if isinstance(value, str) and hasattr(str, attr_name):
                return getattr(value, attr_name)

            # Handle list methods
            if isinstance(value, list) and hasattr(list, attr_name):
                return getattr(value, attr_name)

            raise ValueError(f"Attribute {attr_name} not supported")

    def _eval_call(self, node: ast.Call) -> Any:
        """Evaluate a function call.

        Args:
            node: The call node.

        Returns:
            The function result.
        """
        # Check if it's a method call (value.method())
        if isinstance(node.func, ast.Attribute):
            obj = self._eval_node(node.func.value)
            method_name = node.func.attr

            # Get the method
            if not hasattr(obj, method_name):
                raise ValueError(f"Method {method_name} not found on {type(obj)}")

            method = getattr(obj, method_name)

            # Evaluate arguments
            args = [self._eval_node(arg) for arg in node.args]
            kwargs = {kw.arg: self._eval_node(kw.value) for kw in node.keywords}

            # Call method
            return method(*args, **kwargs)  # type: ignore[arg-type]

        # Function call: len(x), abs(x)
        elif isinstance(node.func, ast.Name):
            func_name = node.func.id

            if func_name not in SAFE_FUNCTIONS:
                raise ValueError(f"Function {func_name} not allowed")

            func = SAFE_FUNCTIONS[func_name]
            args = [self._eval_node(arg) for arg in node.args]

            return func(*args)

        else:
            raise ValueError("Unsupported function call")

    def _auto_convert(self, left: Any, right: Any) -> tuple[Any, Any]:
        """Auto-convert values for comparison.

        Converts entity states (strings) to appropriate types for comparison.

        Args:
            left: Left value.
            right: Right value.

        Returns:
            Tuple of (converted_left, converted_right).
        """
        # If right is a string, no conversion needed
        if isinstance(right, str):
            left_str = str(left) if left is not None else ""
            return left_str, right

        # If right is a number, try to convert left to number
        if isinstance(right, (int, float)):
            if left is None:
                return 0, right
            try:
                if isinstance(right, int):
                    return int(left), right
                else:
                    return float(left), right
            except (ValueError, TypeError):
                _LOGGER.debug("Cannot convert %s to number", left)
                return str(left), str(right)

        # If right is a boolean or boolean-like string
        if isinstance(right, bool) or right in ("on", "off", "True", "False", "true", "false"):
            if left is None:
                return False, self._to_bool(right)
            return self._to_bool(left), self._to_bool(right)

        # If right is a list, ensure left is comparable
        if isinstance(right, (list, tuple)):
            # For 'in' operator
            return left, right

        # Default: compare as strings
        return str(left) if left is not None else "", str(right)

    def _to_bool(self, value: Any) -> bool:
        """Convert value to boolean.

        Args:
            value: Value to convert.

        Returns:
            Boolean value.
        """
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.lower() in ("on", "true", "yes", "1")
        return bool(value)
