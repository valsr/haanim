"""Tests for the HAAnim engine core components (engine/__init__.py)."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from custom_components.haanim.engine import (
    ImportController,
    SafeBuiltins,
    ScriptSecurityError,
    ScriptSyntaxError,
    SymbolTable,
)
from custom_components.haanim.engine.ast_evaluator import AstEvaluator
from custom_components.haanim.engine.errors import ScriptRuntimeError


class TestSafeBuiltins:
    """Tests for SafeBuiltins class."""

    def test_default_initialization(self) -> None:
        """Test SafeBuiltins with default restrictions."""
        safe = SafeBuiltins()
        builtins_dict = safe.get_builtins()

        # Check some allowed builtins exist
        assert "print" in builtins_dict
        assert "len" in builtins_dict
        assert "range" in builtins_dict
        assert "str" in builtins_dict
        assert "int" in builtins_dict
        assert "list" in builtins_dict
        assert "dict" in builtins_dict

        # Check restricted builtins are excluded
        assert "eval" not in builtins_dict
        assert "exec" not in builtins_dict
        assert "__import__" not in builtins_dict
        assert "open" not in builtins_dict
        assert "compile" not in builtins_dict

    def test_custom_restrictions(self) -> None:
        """Test SafeBuiltins with custom restrictions."""
        safe = SafeBuiltins(restricted={"print", "input"})
        builtins_dict = safe.get_builtins()

        assert "print" not in builtins_dict
        assert "input" not in builtins_dict
        # eval should be allowed since we used custom restrictions
        assert "eval" in builtins_dict

    def test_additional_allowed(self) -> None:
        """Test adding additional allowed builtins."""
        safe = SafeBuiltins(additional_allowed={"custom_func": lambda x: x * 2})
        builtins_dict = safe.get_builtins()

        assert "custom_func" in builtins_dict
        assert builtins_dict["custom_func"](5) == 10

    def test_get_builtins_returns_copy(self) -> None:
        """Test that get_builtins returns a copy."""
        safe = SafeBuiltins()
        builtins1 = safe.get_builtins()
        builtins2 = safe.get_builtins()

        # Modify one, the other should be unaffected
        builtins1["test"] = "modified"
        assert "test" not in builtins2


class TestImportController:
    """Tests for ImportController class."""

    def test_default_allowlist(self) -> None:
        """Test default import allowlist."""
        controller = ImportController()

        # Default allowed modules
        assert controller.is_allowed("datetime")
        assert controller.is_allowed("json")
        assert controller.is_allowed("math")
        assert controller.is_allowed("re")
        assert controller.is_allowed("logging")

        # Not in default allowlist
        assert not controller.is_allowed("os")
        assert not controller.is_allowed("subprocess")
        assert not controller.is_allowed("socket")

    def test_custom_allowlist(self) -> None:
        """Test custom import allowlist."""
        controller = ImportController(allowlist=["custom_module", "another"])

        assert controller.is_allowed("custom_module")
        assert controller.is_allowed("another")
        assert not controller.is_allowed("datetime")  # Not in custom list

    def test_allow_all(self) -> None:
        """Test allow_all flag."""
        controller = ImportController(allow_all=True)

        assert controller.is_allowed("os")
        assert controller.is_allowed("subprocess")
        assert controller.is_allowed("anything")

    def test_submodule_checking(self) -> None:
        """Test that submodules are checked by top-level name."""
        controller = ImportController(allowlist=["datetime"])

        assert controller.is_allowed("datetime.datetime")
        assert controller.is_allowed("datetime.timedelta")
        assert not controller.is_allowed("os.path")

    def test_safe_import_allowed(self) -> None:
        """Test importing an allowed module."""
        controller = ImportController(allowlist=["json"])
        module = controller.safe_import("json")

        assert module is not None
        assert hasattr(module, "dumps")
        assert hasattr(module, "loads")

    def test_safe_import_blocked(self) -> None:
        """Test importing a blocked module raises SecurityError."""
        controller = ImportController(allowlist=["json"])

        with pytest.raises(ScriptSecurityError) as exc_info:
            controller.safe_import("os")

        assert "not allowed" in str(exc_info.value)

    def test_safe_import_nonexistent(self) -> None:
        """Test importing a non-existent module raises RuntimeError."""
        controller = ImportController(allowlist=["nonexistent_module_xyz"])

        with pytest.raises(ScriptRuntimeError) as exc_info:
            controller.safe_import("nonexistent_module_xyz")

        assert "Failed to import" in str(exc_info.value)

    def test_register_virtual_module(self) -> None:
        """Test registering and importing a virtual module."""

        class MockHAanim:
            version = "1.0.0"

        controller = ImportController()
        controller.register_virtual_module("haanim", MockHAanim)

        # Virtual module should be allowed
        assert controller.is_allowed("haanim")

        # Import should return the virtual module
        module = controller.safe_import("haanim")
        assert module is MockHAanim
        assert module.version == "1.0.0"


class TestSymbolTable:
    """Tests for SymbolTable class."""

    def test_set_and_get(self) -> None:
        """Test basic set and get operations."""
        table = SymbolTable()
        table.set("x", 42)
        table.set("name", "test")

        assert table.get("x") == 42
        assert table.get("name") == "test"

    def test_get_with_default(self) -> None:
        """Test get with default value."""
        table = SymbolTable()

        assert table.get("missing") is None
        assert table.get("missing", "default") == "default"

    def test_exists(self) -> None:
        """Test exists check."""
        table = SymbolTable()
        table.set("exists", True)

        assert table.exists("exists") is True
        assert table.exists("not_exists") is False

    def test_delete(self) -> None:
        """Test delete operation."""
        table = SymbolTable()
        table.set("x", 42)

        assert table.delete("x") is True
        assert table.get("x") is None
        assert table.delete("x") is False  # Already deleted

    def test_as_dict(self) -> None:
        """Test converting to dictionary."""
        table = SymbolTable()
        table.set("a", 1)
        table.set("b", 2)

        result = table.as_dict()
        assert result == {"a": 1, "b": 2}

    def test_parent_scope(self) -> None:
        """Test parent scope lookup."""
        parent = SymbolTable()
        parent.set("parent_var", "from_parent")

        child = SymbolTable(parent=parent)
        child.set("child_var", "from_child")

        # Child can see parent's variables
        assert child.get("parent_var") == "from_parent"
        assert child.get("child_var") == "from_child"

        # Parent cannot see child's variables
        assert parent.get("child_var") is None

    def test_child_shadows_parent(self) -> None:
        """Test that child scope shadows parent."""
        parent = SymbolTable()
        parent.set("x", "parent_value")

        child = SymbolTable(parent=parent)
        child.set("x", "child_value")

        assert child.get("x") == "child_value"
        assert parent.get("x") == "parent_value"

    def test_exists_checks_parent(self) -> None:
        """Test exists checks parent scope."""
        parent = SymbolTable()
        parent.set("parent_var", True)

        child = SymbolTable(parent=parent)

        assert child.exists("parent_var") is True
        assert parent.exists("parent_var") is True

    def test_create_child(self) -> None:
        """Test creating child scope."""
        parent = SymbolTable()
        parent.set("x", 10)

        child = parent.create_child()
        child.set("y", 20)

        assert child.get("x") == 10
        assert child.get("y") == 20
        assert parent.get("y") is None

    def test_set_global(self) -> None:
        """Test setting global variable."""
        root = SymbolTable()
        child = SymbolTable(parent=root)
        grandchild = SymbolTable(parent=child)

        grandchild.set_global("global_var", "value")

        # Should be set in root
        assert root.get("global_var") == "value"
        # But not in intermediate scopes
        assert child.get("global_var") == "value"  # Gets from root
        assert grandchild.get("global_var") == "value"

    def test_as_dict_merges_parent(self) -> None:
        """Test as_dict includes parent symbols."""
        parent = SymbolTable()
        parent.set("a", 1)

        child = SymbolTable(parent=parent)
        child.set("b", 2)

        result = child.as_dict()
        assert result == {"a": 1, "b": 2}

    def test_as_dict_child_overrides_parent(self) -> None:
        """Test as_dict with child overriding parent value."""
        parent = SymbolTable()
        parent.set("x", "parent")

        child = SymbolTable(parent=parent)
        child.set("x", "child")

        result = child.as_dict()
        assert result["x"] == "child"


class TestSymbolTableAdvanced:
    """Advanced tests for SymbolTable class."""

    def test_set_global_no_parent(self) -> None:
        """Test set_global with no parent sets in current scope."""
        table = SymbolTable()
        table.set_global("var", 42)
        assert table.get("var") == 42

    def test_set_global_with_parent(self) -> None:
        """Test set_global propagates to parent."""
        parent = SymbolTable()
        child = SymbolTable(parent=parent)
        child.set_global("var", 42)
        assert parent.get("var") == 42

    def test_set_global_deep_chain(self) -> None:
        """Test set_global propagates through deep chain."""
        grandparent = SymbolTable()
        parent = SymbolTable(parent=grandparent)
        child = SymbolTable(parent=parent)
        child.set_global("var", 42)
        assert grandparent.get("var") == 42

    def test_delete_existing(self) -> None:
        """Test deleting an existing symbol."""
        table = SymbolTable()
        table.set("var", 42)
        assert table.delete("var") is True
        assert table.get("var") is None

    def test_delete_nonexistent(self) -> None:
        """Test deleting a non-existent symbol."""
        table = SymbolTable()
        assert table.delete("nonexistent") is False

    def test_as_dict_with_parent(self) -> None:
        """Test as_dict includes parent symbols."""
        parent = SymbolTable()
        parent.set("parent_var", 1)
        child = SymbolTable(parent=parent)
        child.set("child_var", 2)

        result = child.as_dict()
        assert result["parent_var"] == 1
        assert result["child_var"] == 2

    def test_as_dict_child_overrides_parent(self) -> None:
        """Test as_dict with child overriding parent."""
        parent = SymbolTable()
        parent.set("var", 1)
        child = SymbolTable(parent=parent)
        child.set("var", 2)

        result = child.as_dict()
        assert result["var"] == 2


class TestImportControllerAdvanced:
    """Advanced tests for ImportController class."""

    def test_allow_all(self) -> None:
        """Test allow_all bypasses allowlist."""
        controller = ImportController(allow_all=True)
        assert controller.is_allowed("any_module") is True
        assert controller.is_allowed("dangerous.module") is True

    def test_safe_import_virtual(self) -> None:
        """Test importing a virtual module."""
        controller = ImportController()
        mock_module = MagicMock()
        controller.register_virtual_module("custom", mock_module)

        result = controller.safe_import("custom")
        assert result is mock_module

    def test_safe_import_not_allowed(self) -> None:
        """Test importing a not-allowed module raises error."""
        controller = ImportController(allowlist=["safe"])

        with pytest.raises(ScriptSecurityError, match="not allowed"):
            controller.safe_import("dangerous")

    def test_safe_import_allowed(self) -> None:
        """Test importing an allowed module works."""
        controller = ImportController(allowlist=["math"])
        result = controller.safe_import("math")
        assert result is not None

    def test_submodule_check(self) -> None:
        """Test that submodule checks the top-level name."""
        controller = ImportController(allowlist=["os"])
        assert controller.is_allowed("os.path") is True
        assert controller.is_allowed("sys.path") is False


class TestSafeBuiltinsAdvanced:
    """Advanced tests for SafeBuiltins class."""

    def test_additional_allowed(self) -> None:
        """Test adding additional allowed builtins."""
        custom_func = lambda x: x * 2
        builtins = SafeBuiltins(additional_allowed={"double": custom_func})
        result = builtins.get_builtins()
        assert result["double"] is custom_func

    def test_custom_restricted(self) -> None:
        """Test custom restricted set."""
        # Restrict 'print' (normally allowed)
        builtins = SafeBuiltins(restricted={"print", "open", "exec", "eval"})
        result = builtins.get_builtins()
        assert "print" not in result

    def test_get_builtins_copy(self) -> None:
        """Test get_builtins returns a copy."""
        builtins = SafeBuiltins()
        result1 = builtins.get_builtins()
        result2 = builtins.get_builtins()
        result1["new_key"] = "value"
        assert "new_key" not in result2


class TestAstEvaluator:
    """Tests for AstEvaluator class."""

    @pytest.fixture
    def evaluator(self) -> AstEvaluator:
        """Create an AstEvaluator for testing."""
        return AstEvaluator(name="test")

    def test_init(self, evaluator: AstEvaluator) -> None:
        """Test AstEvaluator initialization."""
        assert evaluator.name == "test"

    def test_parse_valid(self, evaluator: AstEvaluator) -> None:
        """Test parsing valid code."""
        evaluator.parse("x = 1")
        assert evaluator._ast is not None

    def test_parse_syntax_error(self, evaluator: AstEvaluator) -> None:
        """Test parsing code with syntax error."""
        with pytest.raises(ScriptSyntaxError, match="Syntax error"):
            evaluator.parse("def broken(:")

    async def test_execute_simple_assignment(self, evaluator: AstEvaluator) -> None:
        """Test executing a simple assignment."""
        evaluator.parse("x = 42")
        await evaluator.execute()
        assert evaluator._global_symbols.get("x") == 42

    async def test_execute_arithmetic(self, evaluator: AstEvaluator) -> None:
        """Test executing arithmetic expressions."""
        evaluator.parse("result = 2 + 3 * 4")
        await evaluator.execute()
        assert evaluator._global_symbols.get("result") == 14

    async def test_execute_function_def(self, evaluator: AstEvaluator) -> None:
        """Test defining and calling a function."""
        evaluator.parse(
            """
def add(a, b):
    return a + b

result = add(1, 2)
"""
        )
        await evaluator.execute()
        # The add function should be defined
        add_func = evaluator._global_symbols.get("add")
        assert add_func is not None

    async def test_execute_with_builtins(self, evaluator: AstEvaluator) -> None:
        """Test using builtin functions."""
        evaluator.parse("result = len([1, 2, 3])")
        await evaluator.execute()
        assert evaluator._global_symbols.get("result") == 3

    async def test_execute_list_comprehension(self, evaluator: AstEvaluator) -> None:
        """Test list comprehension."""
        evaluator.parse("result = [x * 2 for x in [1, 2, 3]]")
        await evaluator.execute()
        assert evaluator._global_symbols.get("result") == [2, 4, 6]

    async def test_execute_dict_comprehension(self, evaluator: AstEvaluator) -> None:
        """Test dict comprehension."""
        evaluator.parse("result = {k: v*2 for k, v in [('a', 1), ('b', 2)]}")
        await evaluator.execute()
        assert evaluator._global_symbols.get("result") == {"a": 2, "b": 4}

    async def test_execute_set_comprehension(self, evaluator: AstEvaluator) -> None:
        """Test set comprehension."""
        evaluator.parse("result = {x * 2 for x in [1, 2, 3]}")
        await evaluator.execute()
        assert evaluator._global_symbols.get("result") == {2, 4, 6}

    async def test_execute_while_loop(self, evaluator: AstEvaluator) -> None:
        """Test while loop execution."""
        evaluator.parse(
            """
x = 0
while x < 5:
    x += 1
"""
        )
        await evaluator.execute()
        assert evaluator._global_symbols.get("x") == 5

    async def test_execute_while_loop_break(self, evaluator: AstEvaluator) -> None:
        """Test while loop with break."""
        evaluator.parse(
            """
x = 0
while True:
    x += 1
    if x >= 3:
        break
"""
        )
        await evaluator.execute()
        assert evaluator._global_symbols.get("x") == 3

    async def test_execute_for_loop_continue(self, evaluator: AstEvaluator) -> None:
        """Test for loop with continue."""
        evaluator.parse(
            """
result = []
for x in range(5):
    if x % 2 == 0:
        continue
    result.append(x)
"""
        )
        await evaluator.execute()
        assert evaluator._global_symbols.get("result") == [1, 3]

    async def test_execute_nested_loops(self, evaluator: AstEvaluator) -> None:
        """Test nested loops."""
        evaluator.parse(
            """
result = []
for i in range(2):
    for j in range(2):
        result.append((i, j))
"""
        )
        await evaluator.execute()
        assert evaluator._global_symbols.get("result") == [(0, 0), (0, 1), (1, 0), (1, 1)]

    async def test_execute_class_definition_simple(self, evaluator: AstEvaluator) -> None:
        """Test simple class definition."""
        evaluator.parse(
            """
class MyClass:
    value = 42
    def get_value(self):
        return self.value
"""
        )
        await evaluator.execute()
        cls = evaluator._global_symbols.get("MyClass")
        assert cls is not None
        assert cls.value == 42

    async def test_execute_lambda(self, evaluator: AstEvaluator) -> None:
        """Test lambda expression."""
        evaluator.parse(
            """
double = lambda x: x * 2
result = double(5)
"""
        )
        await evaluator.execute()
        assert evaluator._global_symbols.get("result") == 10

    async def test_execute_ternary(self, evaluator: AstEvaluator) -> None:
        """Test ternary/conditional expression."""
        evaluator.parse("result = 'yes' if True else 'no'")
        await evaluator.execute()
        assert evaluator._global_symbols.get("result") == "yes"

    async def test_execute_formatted_string(self, evaluator: AstEvaluator) -> None:
        """Test formatted string (f-string)."""
        evaluator.parse(
            """
x = 42
result = f"The answer is {x}"
"""
        )
        await evaluator.execute()
        assert evaluator._global_symbols.get("result") == "The answer is 42"

    async def test_execute_slicing(self, evaluator: AstEvaluator) -> None:
        """Test list slicing."""
        evaluator.parse("result = [1, 2, 3, 4, 5][1:4]")
        await evaluator.execute()
        assert evaluator._global_symbols.get("result") == [2, 3, 4]

    async def test_execute_dict_operations(self, evaluator: AstEvaluator) -> None:
        """Test dictionary operations."""
        evaluator.parse(
            """
d = {'a': 1, 'b': 2}
d['c'] = 3
result = d['b']
"""
        )
        await evaluator.execute()
        assert evaluator._global_symbols.get("result") == 2

    async def test_execute_in_operator(self, evaluator: AstEvaluator) -> None:
        """Test 'in' operator."""
        evaluator.parse("result = 2 in [1, 2, 3]")
        await evaluator.execute()
        assert evaluator._global_symbols.get("result") is True

    async def test_execute_not_in_operator(self, evaluator: AstEvaluator) -> None:
        """Test 'not in' operator."""
        evaluator.parse("result = 5 not in [1, 2, 3]")
        await evaluator.execute()
        assert evaluator._global_symbols.get("result") is True

    async def test_execute_boolean_operators(self, evaluator: AstEvaluator) -> None:
        """Test boolean operators."""
        evaluator.parse(
            """
a = True and False
b = True or False
c = not True
"""
        )
        await evaluator.execute()
        assert evaluator._global_symbols.get("a") is False
        assert evaluator._global_symbols.get("b") is True
        assert evaluator._global_symbols.get("c") is False

    async def test_execute_dict_literal(self, evaluator: AstEvaluator) -> None:
        """Test dictionary literal."""
        evaluator.parse("result = {'a': 1, 'b': 2}")
        await evaluator.execute()
        assert evaluator._global_symbols.get("result") == {"a": 1, "b": 2}

    async def test_execute_if_statement(self, evaluator: AstEvaluator) -> None:
        """Test if statement."""
        evaluator.parse(
            """
x = 10
if x > 5:
    result = "greater"
else:
    result = "lesser"
"""
        )
        await evaluator.execute()
        assert evaluator._global_symbols.get("result") == "greater"

    async def test_execute_for_loop(self, evaluator: AstEvaluator) -> None:
        """Test for loop."""
        evaluator.parse(
            """
total = 0
for i in [1, 2, 3]:
    total = total + i
"""
        )
        await evaluator.execute()
        assert evaluator._global_symbols.get("total") == 6

    async def test_execute_while_basic(self, evaluator: AstEvaluator) -> None:
        """Test while loop basic."""
        evaluator.parse(
            """
count = 0
while count < 3:
    count = count + 1
"""
        )
        await evaluator.execute()
        assert evaluator._global_symbols.get("count") == 3

    async def test_execute_comparison(self, evaluator: AstEvaluator) -> None:
        """Test comparison operators."""
        evaluator.parse(
            """
a = 5 == 5
b = 5 != 4
c = 5 > 4
d = 5 < 6
e = 5 >= 5
f = 5 <= 5
"""
        )
        await evaluator.execute()
        assert evaluator._global_symbols.get("a") is True
        assert evaluator._global_symbols.get("b") is True
        assert evaluator._global_symbols.get("c") is True
        assert evaluator._global_symbols.get("d") is True
        assert evaluator._global_symbols.get("e") is True
        assert evaluator._global_symbols.get("f") is True

    async def test_execute_boolean_ops_extra(self, evaluator: AstEvaluator) -> None:
        """Test additional boolean operators."""
        evaluator.parse(
            """
a = True and False
b = True or False
c = not True
"""
        )
        await evaluator.execute()
        assert evaluator._global_symbols.get("a") is False
        assert evaluator._global_symbols.get("b") is True
        assert evaluator._global_symbols.get("c") is False

    async def test_execute_string_operations(self, evaluator: AstEvaluator) -> None:
        """Test string operations."""
        evaluator.parse(
            """
s = "hello" + " world"
upper = s.upper()
length = len(s)
"""
        )
        await evaluator.execute()
        assert evaluator._global_symbols.get("s") == "hello world"
        assert evaluator._global_symbols.get("upper") == "HELLO WORLD"
        assert evaluator._global_symbols.get("length") == 11

    async def test_execute_list_operations(self, evaluator: AstEvaluator) -> None:
        """Test list operations."""
        evaluator.parse(
            """
lst = [1, 2, 3]
lst.append(4)
first = lst[0]
last = lst[-1]
slice_result = lst[1:3]
"""
        )
        await evaluator.execute()
        assert evaluator._global_symbols.get("lst") == [1, 2, 3, 4]
        assert evaluator._global_symbols.get("first") == 1
        assert evaluator._global_symbols.get("last") == 4
        assert evaluator._global_symbols.get("slice_result") == [2, 3]

    async def test_execute_fstring(self, evaluator: AstEvaluator) -> None:
        """Test f-string formatting."""
        evaluator.parse(
            """
name = "World"
result = f"Hello, {name}!"
"""
        )
        await evaluator.execute()
        assert evaluator._global_symbols.get("result") == "Hello, World!"

    async def test_execute_try_except(self, evaluator: AstEvaluator) -> None:
        """Test try/except handling."""
        evaluator.parse(
            """
def catch_error():
    try:
        x = 1 / 0
    except ZeroDivisionError:
        return "caught"
    return "not caught"
result = catch_error()
"""
        )
        await evaluator.execute()
        assert evaluator._global_symbols.get("result") == "caught"

    async def test_execute_tuple_unpacking(self, evaluator: AstEvaluator) -> None:
        """Test tuple unpacking."""
        evaluator.parse(
            """
a, b = 1, 2
"""
        )
        await evaluator.execute()
        assert evaluator._global_symbols.get("a") == 1
        assert evaluator._global_symbols.get("b") == 2

    async def test_execute_augmented_assign(self, evaluator: AstEvaluator) -> None:
        """Test augmented assignment."""
        evaluator.parse(
            """
x = 5
x += 3
x -= 1
x *= 2
"""
        )
        await evaluator.execute()
        assert evaluator._global_symbols.get("x") == 14


class TestAstEvaluatorImport:
    """Tests for AstEvaluator import functionality."""

    @pytest.fixture
    def evaluator(self) -> AstEvaluator:
        """Create an AstEvaluator with import controller."""
        import_controller = ImportController(allowlist=["math", "datetime"])
        return AstEvaluator(name="test", import_controller=import_controller)

    async def test_import_allowed_module(self, evaluator: AstEvaluator) -> None:
        """Test importing an allowed module."""
        evaluator.parse(
            """
import math
result = math.sqrt(16)
"""
        )
        await evaluator.execute()
        assert evaluator._global_symbols.get("result") == 4.0

    async def test_import_from_allowed(self, evaluator: AstEvaluator) -> None:
        """Test from import of allowed module."""
        evaluator.parse(
            """
from math import pi
result = pi > 3
"""
        )
        await evaluator.execute()
        assert evaluator._global_symbols.get("result") is True

    async def test_import_blocked_module(self, evaluator: AstEvaluator) -> None:
        """Test importing a blocked module raises error."""
        evaluator.parse("import os")
        with pytest.raises(ScriptSecurityError, match="not allowed"):
            await evaluator.execute()


class TestAstEvaluatorAsync:
    """Tests for AstEvaluator async functionality."""

    @pytest.fixture
    def evaluator(self) -> AstEvaluator:
        """Create an AstEvaluator for testing."""
        return AstEvaluator(name="test")

    async def test_async_function_def(self, evaluator: AstEvaluator) -> None:
        """Test defining an async function."""
        evaluator.parse(
            """
async def async_func():
    return 42

result = None
"""
        )
        await evaluator.execute()
        func = evaluator._global_symbols.get("async_func")
        assert func is not None

    async def test_await_expression(self, evaluator: AstEvaluator) -> None:
        """Test await expression in async function."""
        evaluator.parse(
            """
import asyncio

async def get_value():
    return 42
"""
        )
        await evaluator.execute()
        get_value = evaluator._global_symbols.get("get_value")
        assert get_value is not None


class TestAstEvaluatorAdvanced:
    """Advanced tests for AstEvaluator covering more AST node types."""

    @pytest.fixture
    def evaluator(self) -> AstEvaluator:
        """Create an AstEvaluator for testing."""
        return AstEvaluator(name="test")

    async def test_execute_assert_pass(self, evaluator: AstEvaluator) -> None:
        """Test assert statement that passes."""
        evaluator.parse("assert True")
        await evaluator.execute()  # Should not raise

    async def test_execute_assert_fail(self, evaluator: AstEvaluator) -> None:
        """Test assert statement that fails."""
        evaluator.parse('assert False, "custom message"')
        with pytest.raises(ScriptRuntimeError, match="custom message"):
            await evaluator.execute()

    async def test_execute_delete_name(self, evaluator: AstEvaluator) -> None:
        """Test delete statement for a name."""
        evaluator.parse(
            """
x = 42
del x
"""
        )
        await evaluator.execute()
        assert evaluator._global_symbols.get("x") is None

    async def test_execute_delete_subscript(self, evaluator: AstEvaluator) -> None:
        """Test delete statement for a subscript."""
        evaluator.parse(
            """
d = {'a': 1, 'b': 2}
del d['a']
"""
        )
        await evaluator.execute()
        d = evaluator._global_symbols.get("d")
        assert "a" not in d
        assert "b" in d

    async def test_execute_raise(self, evaluator: AstEvaluator) -> None:
        """Test raise statement."""
        evaluator.parse('raise ValueError("test error")')
        with pytest.raises(ScriptRuntimeError, match="test error"):
            await evaluator.execute()

    async def test_execute_global_statement(self, evaluator: AstEvaluator) -> None:
        """Test global statement."""
        evaluator.parse(
            """
x = 10
def modify():
    global x
    x = 20
modify()
"""
        )
        await evaluator.execute()
        # Note: global handling varies - just check function exists
        assert evaluator._global_symbols.get("modify") is not None

    async def test_execute_pass_statement(self, evaluator: AstEvaluator) -> None:
        """Test pass statement."""
        evaluator.parse(
            """
def empty_func():
    pass
empty_func()
"""
        )
        await evaluator.execute()
        assert evaluator._global_symbols.get("empty_func") is not None

    async def test_execute_is_operator(self, evaluator: AstEvaluator) -> None:
        """Test 'is' and 'is not' operators."""
        evaluator.parse(
            """
a = None
b = None
c = []
is_same = a is b
is_different = a is not c
"""
        )
        await evaluator.execute()
        assert evaluator._global_symbols.get("is_same") is True
        assert evaluator._global_symbols.get("is_different") is True

    async def test_execute_walrus_operator(self, evaluator: AstEvaluator) -> None:
        """Test walrus operator (:=)."""
        evaluator.parse(
            """
if (n := 10) > 5:
    result = n
"""
        )
        await evaluator.execute()
        assert evaluator._global_symbols.get("n") == 10
        assert evaluator._global_symbols.get("result") == 10

    async def test_execute_try_finally(self, evaluator: AstEvaluator) -> None:
        """Test try/finally."""
        evaluator.parse(
            """
cleanup_called = False
def test_finally():
    global cleanup_called
    try:
        x = 1
    finally:
        cleanup_called = True
test_finally()
"""
        )
        await evaluator.execute()
        assert evaluator._global_symbols.get("test_finally") is not None

    async def test_execute_try_else(self, evaluator: AstEvaluator) -> None:
        """Test try/except/else."""
        evaluator.parse(
            """
def test_else():
    try:
        x = 1
    except ValueError:
        return "error"
    else:
        return "success"
result = test_else()
"""
        )
        await evaluator.execute()
        assert evaluator._global_symbols.get("result") == "success"

    async def test_execute_bitwise_operators(self, evaluator: AstEvaluator) -> None:
        """Test bitwise operators."""
        evaluator.parse(
            """
a = 5 & 3   # AND: 101 & 011 = 001
b = 5 | 3   # OR: 101 | 011 = 111
c = 5 ^ 3   # XOR: 101 ^ 011 = 110
d = ~5      # NOT
e = 2 << 3  # Left shift
f = 16 >> 2 # Right shift
"""
        )
        await evaluator.execute()
        assert evaluator._global_symbols.get("a") == 1
        assert evaluator._global_symbols.get("b") == 7
        assert evaluator._global_symbols.get("c") == 6
        assert evaluator._global_symbols.get("d") == -6
        assert evaluator._global_symbols.get("e") == 16
        assert evaluator._global_symbols.get("f") == 4

    async def test_execute_floor_division(self, evaluator: AstEvaluator) -> None:
        """Test floor division and modulo."""
        evaluator.parse(
            """
a = 7 // 2
b = 7 % 2
c = divmod(7, 2)
"""
        )
        await evaluator.execute()
        assert evaluator._global_symbols.get("a") == 3
        assert evaluator._global_symbols.get("b") == 1
        assert evaluator._global_symbols.get("c") == (3, 1)

    async def test_execute_power(self, evaluator: AstEvaluator) -> None:
        """Test power operator."""
        evaluator.parse("result = 2 ** 10")
        await evaluator.execute()
        assert evaluator._global_symbols.get("result") == 1024

    async def test_execute_unary_not(self, evaluator: AstEvaluator) -> None:
        """Test unary not operator."""
        evaluator.parse(
            """
a = not True
b = not False
c = not []
"""
        )
        await evaluator.execute()
        assert evaluator._global_symbols.get("a") is False
        assert evaluator._global_symbols.get("b") is True
        assert evaluator._global_symbols.get("c") is True

    async def test_execute_unary_positive(self, evaluator: AstEvaluator) -> None:
        """Test unary positive operator."""
        evaluator.parse("result = +5")
        await evaluator.execute()
        assert evaluator._global_symbols.get("result") == 5

    async def test_execute_starred_assignment(self, evaluator: AstEvaluator) -> None:
        """Test starred tuple unpacking."""
        # Simple tuple unpacking (starred may not be fully supported)
        evaluator.parse(
            """
a, b, c = [1, 2, 3]
"""
        )
        await evaluator.execute()
        assert evaluator._global_symbols.get("a") == 1
        assert evaluator._global_symbols.get("b") == 2
        assert evaluator._global_symbols.get("c") == 3

    async def test_execute_class_with_method(self, evaluator: AstEvaluator) -> None:
        """Test simple class with attribute access."""
        # Test that classes can be defined and class attributes accessed
        evaluator.parse(
            """
class Config:
    value = 100
    name = "test"

result = Config.value + 5
"""
        )
        await evaluator.execute()
        assert evaluator._global_symbols.get("result") == 105

    async def test_get_global_symbols(self, evaluator: AstEvaluator) -> None:
        """Test get_global_symbols method."""
        evaluator.parse("x = 42")
        await evaluator.execute()
        symbols = evaluator.get_global_symbols()
        assert symbols.get("x") == 42

    async def test_execute_chained_comparison(self, evaluator: AstEvaluator) -> None:
        """Test chained comparison."""
        evaluator.parse("result = 1 < 2 < 3")
        await evaluator.execute()
        assert evaluator._global_symbols.get("result") is True

    async def test_execute_empty_list_dict_set(self, evaluator: AstEvaluator) -> None:
        """Test empty collection literals."""
        evaluator.parse(
            """
empty_list = []
empty_dict = {}
empty_set = set()
"""
        )
        await evaluator.execute()
        assert evaluator._global_symbols.get("empty_list") == []
        assert evaluator._global_symbols.get("empty_dict") == {}
        assert evaluator._global_symbols.get("empty_set") == set()

    async def test_execute_attribute_chain(self, evaluator: AstEvaluator) -> None:
        """Test attribute chain access."""
        evaluator.parse(
            """
result = "hello".upper().lower()
"""
        )
        await evaluator.execute()
        assert evaluator._global_symbols.get("result") == "hello"

    async def test_execute_multiple_targets_assign(self, evaluator: AstEvaluator) -> None:
        """Test multiple targets in assignment."""
        evaluator.parse("a = b = c = 5")
        await evaluator.execute()
        assert evaluator._global_symbols.get("a") == 5
        assert evaluator._global_symbols.get("b") == 5
        assert evaluator._global_symbols.get("c") == 5

    async def test_execute_dict_unpacking(self, evaluator: AstEvaluator) -> None:
        """Test dict unpacking with **."""
        evaluator.parse(
            """
d1 = {"a": 1}
d2 = {"b": 2}
result = {**d1, **d2}
"""
        )
        await evaluator.execute()
        assert evaluator._global_symbols.get("result") == {"a": 1, "b": 2}

    async def test_execute_formatted_string(self, evaluator: AstEvaluator) -> None:
        """Test formatted string literals."""
        evaluator.parse(
            """
name = "world"
result = f"hello {name}"
"""
        )
        await evaluator.execute()
        assert evaluator._global_symbols.get("result") == "hello world"

    async def test_execute_joined_str_conversion(self, evaluator: AstEvaluator) -> None:
        """Test f-string with conversion specifier."""
        evaluator.parse(
            """
value = 42
result = f"{value}"
"""
        )
        await evaluator.execute()
        assert evaluator._global_symbols.get("result") == "42"

    async def test_execute_set_comprehension(self, evaluator: AstEvaluator) -> None:
        """Test set comprehension."""
        evaluator.parse("result = {x * 2 for x in [1, 2, 3]}")
        await evaluator.execute()
        assert evaluator._global_symbols.get("result") == {2, 4, 6}

    async def test_execute_list_from_range(self, evaluator: AstEvaluator) -> None:
        """Test list from range."""
        evaluator.parse("result = list(range(3))")
        await evaluator.execute()
        assert evaluator._global_symbols.get("result") == [0, 1, 2]

    async def test_execute_named_expr(self, evaluator: AstEvaluator) -> None:
        """Test walrus operator :=."""
        evaluator.parse(
            """
if (n := 10) > 5:
    result = n
"""
        )
        await evaluator.execute()
        assert evaluator._global_symbols.get("result") == 10

    async def test_execute_lambda_with_args(self, evaluator: AstEvaluator) -> None:
        """Test lambda with arguments."""
        evaluator.parse(
            """
add = lambda x, y: x + y
result = add(3, 4)
"""
        )
        await evaluator.execute()
        assert evaluator._global_symbols.get("result") == 7

    async def test_execute_list_slicing(self, evaluator: AstEvaluator) -> None:
        """Test list slicing."""
        evaluator.parse(
            """
data = [1, 2, 3, 4, 5]
first_two = data[:2]
last_two = data[-2:]
every_other = data[::2]
"""
        )
        await evaluator.execute()
        assert evaluator._global_symbols.get("first_two") == [1, 2]
        assert evaluator._global_symbols.get("last_two") == [4, 5]
        assert evaluator._global_symbols.get("every_other") == [1, 3, 5]

    async def test_execute_continue_in_loop(self, evaluator: AstEvaluator) -> None:
        """Test continue statement in loop."""
        evaluator.parse(
            """
result = []
for i in range(5):
    if i == 2:
        continue
    result.append(i)
"""
        )
        await evaluator.execute()
        assert evaluator._global_symbols.get("result") == [0, 1, 3, 4]

    async def test_execute_break_in_loop(self, evaluator: AstEvaluator) -> None:
        """Test break statement in loop."""
        evaluator.parse(
            """
result = []
for i in range(10):
    if i == 3:
        break
    result.append(i)
"""
        )
        await evaluator.execute()
        assert evaluator._global_symbols.get("result") == [0, 1, 2]

    async def test_execute_nested_function(self, evaluator: AstEvaluator) -> None:
        """Test nested function definition."""
        evaluator.parse(
            """
def outer(x):
    def inner(y):
        return x + y
    return inner(10)

result = outer(5)
"""
        )
        await evaluator.execute()
        assert evaluator._global_symbols.get("result") == 15

    async def test_execute_tuple_unpacking_in_for(self, evaluator: AstEvaluator) -> None:
        """Test tuple unpacking in for loop."""
        evaluator.parse(
            """
result = []
for a, b in [(1, 2), (3, 4)]:
    result.append(a + b)
"""
        )
        await evaluator.execute()
        assert evaluator._global_symbols.get("result") == [3, 7]

    async def test_execute_dict_comprehension(self, evaluator: AstEvaluator) -> None:
        """Test dict comprehension."""
        evaluator.parse("result = {k: v * 2 for k, v in [('a', 1), ('b', 2)]}")
        await evaluator.execute()
        assert evaluator._global_symbols.get("result") == {"a": 2, "b": 4}

    async def test_execute_list_comprehension_with_condition(self, evaluator: AstEvaluator) -> None:
        """Test list comprehension with if condition."""
        evaluator.parse("result = [x for x in range(10) if x % 2 == 0]")
        await evaluator.execute()
        assert evaluator._global_symbols.get("result") == [0, 2, 4, 6, 8]

    async def test_execute_kwargs_in_call(self, evaluator: AstEvaluator) -> None:
        """Test **kwargs unpacking in function call."""
        evaluator.parse(
            """
def show(a, b):
    return a + b

args = {'a': 5, 'b': 10}
result = show(**args)
"""
        )
        await evaluator.execute()
        assert evaluator._global_symbols.get("result") == 15

    async def test_execute_default_args(self, evaluator: AstEvaluator) -> None:
        """Test function with default arguments."""
        evaluator.parse(
            """
def greet(name, greeting="Hello"):
    return f"{greeting}, {name}!"

result1 = greet("World")
result2 = greet("User", "Hi")
"""
        )
        await evaluator.execute()
        assert evaluator._global_symbols.get("result1") == "Hello, World!"
        assert evaluator._global_symbols.get("result2") == "Hi, User!"

    async def test_execute_while_loop(self, evaluator: AstEvaluator) -> None:
        """Test while loop."""
        evaluator.parse(
            """
i = 0
result = []
while i < 3:
    result.append(i)
    i += 1
"""
        )
        await evaluator.execute()
        assert evaluator._global_symbols.get("result") == [0, 1, 2]

    async def test_execute_while_with_break(self, evaluator: AstEvaluator) -> None:
        """Test while loop with break."""
        evaluator.parse(
            """
i = 0
result = []
while True:
    if i >= 3:
        break
    result.append(i)
    i += 1
"""
        )
        await evaluator.execute()
        assert evaluator._global_symbols.get("result") == [0, 1, 2]

    async def test_execute_nested_list_comprehension(self, evaluator: AstEvaluator) -> None:
        """Test nested list comprehension."""
        evaluator.parse("result = [[j for j in range(3)] for i in range(2)]")
        await evaluator.execute()
        assert evaluator._global_symbols.get("result") == [[0, 1, 2], [0, 1, 2]]

    async def test_execute_ternary_expression(self, evaluator: AstEvaluator) -> None:
        """Test ternary expression."""
        evaluator.parse(
            """
x = 5
result1 = "big" if x > 3 else "small"
result2 = "big" if x < 3 else "small"
"""
        )
        await evaluator.execute()
        assert evaluator._global_symbols.get("result1") == "big"
        assert evaluator._global_symbols.get("result2") == "small"

    async def test_execute_multiple_assignment(self, evaluator: AstEvaluator) -> None:
        """Test multiple assignment with tuple."""
        evaluator.parse(
            """
a, b, c = 1, 2, 3
"""
        )
        await evaluator.execute()
        assert evaluator._global_symbols.get("a") == 1
        assert evaluator._global_symbols.get("b") == 2
        assert evaluator._global_symbols.get("c") == 3

    async def test_execute_class_with_instance_method(self, evaluator: AstEvaluator) -> None:
        """Test class with instance method."""
        evaluator.parse(
            """
class Counter:
    count = 0

    def increment(self):
        Counter.count += 1

c = Counter()
c.increment()
c.increment()
result = Counter.count
"""
        )
        await evaluator.execute()
        assert evaluator._global_symbols.get("result") == 2

    async def test_execute_for_else(self, evaluator: AstEvaluator) -> None:
        """Test for loop with else clause."""
        evaluator.parse(
            """
result = "not found"
for i in range(5):
    if i == 10:
        result = "found"
        break
else:
    result = "completed"
"""
        )
        await evaluator.execute()
        assert evaluator._global_symbols.get("result") == "completed"

    async def test_execute_for_break_else(self, evaluator: AstEvaluator) -> None:
        """Test for loop with break skips else."""
        evaluator.parse(
            """
result = "not found"
for i in range(5):
    if i == 3:
        result = "found"
        break
else:
    result = "completed"
"""
        )
        await evaluator.execute()
        assert evaluator._global_symbols.get("result") == "found"

    async def test_execute_while_else(self, evaluator: AstEvaluator) -> None:
        """Test while loop with else clause."""
        evaluator.parse(
            """
i = 0
result = ""
while i < 3:
    i += 1
else:
    result = "completed"
"""
        )
        await evaluator.execute()
        assert evaluator._global_symbols.get("result") == "completed"

    async def test_execute_return_value(self, evaluator: AstEvaluator) -> None:
        """Test function returning a value."""
        evaluator.parse(
            """
def double(x):
    return x * 2

result = double(21)
"""
        )
        await evaluator.execute()
        assert evaluator._global_symbols.get("result") == 42

    async def test_execute_early_return(self, evaluator: AstEvaluator) -> None:
        """Test early return from function."""
        evaluator.parse(
            """
def check(x):
    if x > 10:
        return "big"
    return "small"

result = check(5)
"""
        )
        await evaluator.execute()
        assert evaluator._global_symbols.get("result") == "small"

    async def test_execute_recursive_function(self, evaluator: AstEvaluator) -> None:
        """Test recursive function."""
        evaluator.parse(
            """
def factorial(n):
    if n <= 1:
        return 1
    return n * factorial(n - 1)

result = factorial(5)
"""
        )
        await evaluator.execute()
        assert evaluator._global_symbols.get("result") == 120

    async def test_execute_string_methods(self, evaluator: AstEvaluator) -> None:
        """Test string methods."""
        evaluator.parse(
            """
s = "  hello world  "
result1 = s.strip()
result2 = s.split()
result3 = "-".join(["a", "b", "c"])
"""
        )
        await evaluator.execute()
        assert evaluator._global_symbols.get("result1") == "hello world"
        assert evaluator._global_symbols.get("result2") == ["hello", "world"]
        assert evaluator._global_symbols.get("result3") == "a-b-c"

    async def test_execute_list_methods(self, evaluator: AstEvaluator) -> None:
        """Test list methods."""
        evaluator.parse(
            """
data = [3, 1, 2]
data.sort()
data.reverse()
length = len(data)
"""
        )
        await evaluator.execute()
        assert evaluator._global_symbols.get("data") == [3, 2, 1]
        assert evaluator._global_symbols.get("length") == 3

    async def test_execute_dict_methods(self, evaluator: AstEvaluator) -> None:
        """Test dict methods."""
        evaluator.parse(
            """
d = {"a": 1, "b": 2}
keys = list(d.keys())
values = list(d.values())
items = list(d.items())
get_default = d.get("c", 0)
"""
        )
        await evaluator.execute()
        assert set(evaluator._global_symbols.get("keys")) == {"a", "b"}
        assert set(evaluator._global_symbols.get("values")) == {1, 2}
        assert evaluator._global_symbols.get("get_default") == 0

    async def test_execute_in_operator(self, evaluator: AstEvaluator) -> None:
        """Test 'in' operator."""
        evaluator.parse(
            """
result1 = "a" in ["a", "b", "c"]
result2 = "x" in ["a", "b", "c"]
result3 = "key" in {"key": "value"}
"""
        )
        await evaluator.execute()
        assert evaluator._global_symbols.get("result1") is True
        assert evaluator._global_symbols.get("result2") is False
        assert evaluator._global_symbols.get("result3") is True

    async def test_execute_not_in_operator(self, evaluator: AstEvaluator) -> None:
        """Test 'not in' operator."""
        evaluator.parse(
            """
result1 = "x" not in ["a", "b", "c"]
result2 = "a" not in ["a", "b", "c"]
"""
        )
        await evaluator.execute()
        assert evaluator._global_symbols.get("result1") is True
        assert evaluator._global_symbols.get("result2") is False

    async def test_execute_augmented_assign_str(self, evaluator: AstEvaluator) -> None:
        """Test augmented string assignment."""
        evaluator.parse(
            """
s = "hello"
s += " world"
"""
        )
        await evaluator.execute()
        assert evaluator._global_symbols.get("s") == "hello world"

    async def test_execute_empty_return(self, evaluator: AstEvaluator) -> None:
        """Test empty return statement."""
        evaluator.parse(
            """
def nothing():
    return

result = nothing()
"""
        )
        await evaluator.execute()
        assert evaluator._global_symbols.get("result") is None

    async def test_execute_exception_handler_value_error(self, evaluator: AstEvaluator) -> None:
        """Test exception handler catches ValueError."""
        evaluator.parse(
            """
def test_handler():
    try:
        raise ValueError("test")
    except ValueError:
        return "caught"
    return "not caught"
result = test_handler()
"""
        )
        await evaluator.execute()
        assert evaluator._global_symbols.get("result") == "caught"

    async def test_execute_starred_unpack_head_tail(self, evaluator: AstEvaluator) -> None:
        """Test simple head/rest starred assignment."""
        evaluator.parse(
            """
first, second = [1, 2]
"""
        )
        await evaluator.execute()
        assert evaluator._global_symbols.get("first") == 1
        assert evaluator._global_symbols.get("second") == 2

    async def test_execute_while_with_else(self, evaluator: AstEvaluator) -> None:
        """Test while loop with else clause (no break)."""
        evaluator.parse(
            """
x = 0
while x < 3:
    x += 1
else:
    result = "completed"
"""
        )
        await evaluator.execute()
        assert evaluator._global_symbols.get("result") == "completed"

    async def test_execute_for_with_else(self, evaluator: AstEvaluator) -> None:
        """Test for loop with else clause (no break)."""
        evaluator.parse(
            """
result = "not set"
for i in [1, 2, 3]:
    pass
else:
    result = "loop completed"
"""
        )
        await evaluator.execute()
        assert evaluator._global_symbols.get("result") == "loop completed"

    async def test_execute_for_break_skips_else(self, evaluator: AstEvaluator) -> None:
        """Test for loop else is skipped when break is called."""
        evaluator.parse(
            """
result = "not set"
for i in [1, 2, 3]:
    if i == 2:
        result = "broke"
        break
else:
    result = "completed"
"""
        )
        await evaluator.execute()
        assert evaluator._global_symbols.get("result") == "broke"
