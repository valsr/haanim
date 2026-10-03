"""Tests for load-time validation of automation source code."""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Any

import pytest

from haanim import PUBLIC_ERRORS
from haanim.engine.ast_evaluator import AstEvaluator
from haanim.engine.errors import AutomationSyntaxError, HAAnimError
from haanim.engine.import_controller import ImportController
from haanim.engine.validation import (
    Problem,
    check_source,
    find_unsupported,
    validate_files,
    validate_source,
)
from haanim.testing import FakeFileSystem
from tests.engine.helpers import automation_file, make_context

# Each unsupported construct of the design's "Supported Python" section:
# (source, line of the construct, text expected in the message).
UNSUPPORTED: dict[str, tuple[str, int, str]] = {
    "yield": ("x = 1\ndef gen():\n    yield 1\n", 3, "'yield' is not supported"),
    "bare yield": ("def gen():\n    yield\n", 2, "'yield' is not supported"),
    "yield in lambda": ("f = lambda: (yield)\n", 1, "'yield' is not supported"),
    "yield from": ("def gen():\n\n    yield from [1, 2]\n", 3, "'yield from' is not supported"),
    "generator expression": ("\n\ntotal = sum(x for x in [1, 2])\n", 3, "generator expressions"),
    "async for": ("async def f(items):\n    async for item in items:\n        pass\n", 2, "'async for'"),
    "async list comprehension": (
        "async def f(items):\n    return [x async for x in items]\n",
        2,
        "async comprehensions",
    ),
    "async set comprehension": (
        "async def f(items):\n    return {x async for x in items}\n",
        2,
        "async comprehensions",
    ),
    "async dict comprehension": (
        "async def f(items):\n    return {x: 1 async for x in items}\n",
        2,
        "async comprehensions",
    ),
    "async inner comprehension clause": (
        "async def f(rows):\n    return [x for row in rows async for x in row]\n",
        2,
        "async comprehensions",
    ),
    "match": ("value = 1\nmatch value:\n    case 1:\n        pass\n", 2, "'match' statements"),
    "except*": ("try:\n    pass\nexcept* ValueError:\n    pass\n", 1, "'except*'"),
}

# Supported Python: (source, expected result). See run() for what the result is.
SUPPORTED: dict[str, tuple[str, Any]] = {
    "class with attributes": ("class A:\n    x = 1\n    y = x + 1\nr = (A.x, A().y)", (1, 2)),
    "lambda": ("f = lambda a, b: a + b\nr = f(1, 2)", 3),
    "lambda closing over a loop variable": (
        "fs = [lambda i=i: i for i in range(3)]\nr = [f() for f in fs]",
        [0, 1, 2],
    ),
    "list comprehension": ("r = [x * 2 for x in range(3) if x]", [2, 4]),
    "set comprehension": ("r = {x for x in [1, 1, 2]}", {1, 2}),
    "dict comprehension": ("r = {k: v for k, v in [(1, 2)]}", {1: 2}),
    "nested comprehension": (
        "r = [(x, y) for x in range(2) for y in range(2)]",
        [(0, 0), (0, 1), (1, 0), (1, 1)],
    ),
    "await inside a comprehension": (
        "async def g(x):\n    return x\nasync def f():\n    return [await g(x) for x in range(2)]\nasync def main():\n    return await f()",
        [0, 1],
    ),
    "with": ("from contextlib import nullcontext\nwith nullcontext(5) as v:\n    r = v", 5),
    "try and except in a function": (
        "def f():\n    try:\n        raise ValueError('x')\n    except ValueError as e:\n        return str(e)\nr = f()",
        "x",
    ),
    "try, except, else and finally": (
        "log = []\ntry:\n    log.append(1)\nexcept ValueError:\n    log.append(0)\nelse:\n    log.append(2)\nfinally:\n    log.append(3)\nr = log",
        [1, 2, 3],
    ),
    "walrus": ("if (n := 3) > 2:\n    r = n", 3),
    "f-string": ("x = 3.14159\nr = f'{x:.2f}|{x!r}|{\"a\"}'", "3.14|3.14159|a"),
    "dict unpacking": ("r = {**{'a': 1}, 'b': 2}", {"a": 1, "b": 2}),
    "keyword-only argument": ("def f(a, *, b=1):\n    return a + b\nr = f(1, b=2)", 3),
    "default argument": ("def f(a, b=2):\n    return a + b\nr = f(1)", 3),
    "while with else": ("i = 0\nwhile i < 3:\n    i += 1\nelse:\n    r = i", 3),
    "for with break and continue": (
        "for i in range(5):\n    if i == 1:\n        continue\n    if i == 2:\n        break\nr = i",
        2,
    ),
    "conditional expression": ("r = 1 if True else 2", 1),
    "chained comparison": ("r = 1 < 2 < 3", True),
    "slice": ("r = [1, 2, 3, 4][1:3]", [2, 3]),
    "subscript assignment": ("d = {}\nd['a'] = 1\nr = d", {"a": 1}),
    "augmented assignment": ("x = 1\nx += 2\nr = x", 3),
    "annotated assignment": ("x: int = 4\nr = x", 4),
    "tuple unpacking": ("a, (b, c) = 1, (2, 3)\nr = a + b + c", 6),
    "assert": ("assert True, 'm'\nr = 1", 1),
    "async def and await": ("async def f():\n    return 7\nasync def main():\n    return await f()", 7),
    "import": ("import math\nfrom json import dumps as d\nr = (math.floor(1.5), d([1]))", (1, "[1]")),
    "constants": ("r = (b'a', ..., None, 1j)", (b"a", ..., None, 1j)),
    "generic function": ("def f[T](a: T) -> T:\n    return a\nr = f(1)", 1),
    "operators": (
        "r = (7 // 2, 7 % 2, 2 ** 3, 1 << 2, 5 & 3, 5 | 3, 5 ^ 3, ~1, -1, not 1)",
        (3, 1, 8, 4, 1, 7, 6, -2, -1, False),
    ),
    "identity and membership": (
        "r = (None is None, 1 in [1], 2 not in [1], 1 is not None)",
        (True, True, True, True),
    ),
    "docstrings": ("'''doc'''\ndef f():\n    '''doc'''\n    return 1\nr = f()", 1),
    "method using self": ("class A:\n    x = 1\n    def m(self):\n        return self.x + 1\nr = A().m()", 2),
    "super()": (
        "class A:\n    def m(self):\n        return 1\nclass B(A):\n    def m(self):\n        return super().m() + 1\nr = B().m()",
        2,
    ),
    "property": ("class A:\n    @property\n    def p(self):\n        return 2\nr = A().p", 2),
    "lambda default": ("f = lambda a, b=2: a + b\nr = f(1)", 3),
    "context manager class": (
        "class C:\n    def __enter__(self):\n        return 5\n    def __exit__(self, *a):\n        return False\n"
        "with C() as v:\n    r = v",
        5,
    ),
    "async context manager class": (
        "class C:\n    async def __aenter__(self):\n        return 5\n    async def __aexit__(self, *a):\n"
        "        return False\nasync def f():\n    async with C() as v:\n        return v\nasync def main():\n    return await f()",
        5,
    ),
    "with suppressing an exception": (
        "from contextlib import suppress\nwith suppress(ValueError):\n    raise ValueError('x')\nr = 1",
        1,
    ),
    "assignment inside except": (
        "try:\n    raise ValueError('x')\nexcept ValueError as e:\n    r = str(e)",
        "x",
    ),
    "starred call argument": ("def f(a, b):\n    return a + b\nr = f(*[1, 2])", 3),
    "variadic parameters": ("def f(*a, **k):\n    return (a, k)\nr = f(1, z=3)", ((1,), {"z": 3})),
    "starred assignment": ("a, *b = [1, 2, 3]\nr = b", [2, 3]),
    "starred list display": ("r = [*[1, 2], 3]", [1, 2, 3]),
    "positional-only parameter": ("def f(a, /, b):\n    return a + b\nr = f(1, 2)", 3),
    "nonlocal": (
        "def mk():\n    c = 0\n    def inc():\n        nonlocal c\n        c += 1\n        return c\n    return inc\n"
        "i = mk()\ni()\nr = i()",
        2,
    ),
    "global": ("g = 0\ndef f():\n    global g\n    g = 5\nf()\nr = g", 5),
    "decorator defined in the automation": (
        "def d(f):\n    def w():\n        return f() + 1\n    return w\n@d\ndef f():\n    return 1\nr = f()",
        2,
    ),
    "function passed to a builtin": ("r = sorted([3, 1, 2], key=lambda v: -v)", [3, 2, 1]),
    "type alias": ("type X = int\nr = 1", 1),
}


async def run(source: str) -> Any:
    """Run a source in the interpreter and return its result.

    The result is the value of ``r``, or what ``main()`` returns if the source
    defines it (for sources that have to await).
    """
    evaluator = AstEvaluator(name="test", import_controller=ImportController(allow_all=True))
    evaluator.parse(source)
    symbols = await evaluator.execute()
    if "main" in symbols:
        return await symbols["main"]()
    return symbols.get("r")


class TestUnsupportedConstructs:
    """Every construct in the design's list is rejected with a line number."""

    @pytest.mark.parametrize("case", UNSUPPORTED)
    def test_rejected_with_file_and_line(self, case: str) -> None:
        """The error names the file, the line and the construct."""
        source, lineno, text = UNSUPPORTED[case]

        with pytest.raises(AutomationSyntaxError) as raised:
            validate_source(source, filename="main.py")

        error = raised.value
        assert error.lineno == lineno
        assert error.filename == "main.py"
        assert str(error).startswith(f"main.py:{lineno}: ")
        assert text in str(error)

    @pytest.mark.parametrize("case", UNSUPPORTED)
    def test_rejected_by_the_interpreter_before_running(self, case: str) -> None:
        """The interpreter refuses the source when parsing it."""
        source, lineno, _ = UNSUPPORTED[case]
        evaluator = AstEvaluator(name="test")

        with pytest.raises(AutomationSyntaxError) as raised:
            evaluator.parse(source, filename="main.py")

        assert raised.value.lineno == lineno

    def test_design_list_is_covered(self) -> None:
        """Each node type the validator rejects has a test case."""
        rejected = {
            type(node) for source, _, _ in UNSUPPORTED.values() for node in ast.walk(ast.parse(source))
        }

        assert {ast.Yield, ast.YieldFrom, ast.GeneratorExp, ast.AsyncFor, ast.Match, ast.TryStar} <= rejected

    def test_generator_expression_suggests_a_list_comprehension(self) -> None:
        """The message tells the author what to use instead."""
        with pytest.raises(AutomationSyntaxError, match="use a list comprehension"):
            validate_source("r = any(x for x in [1])")

    def test_is_the_public_error(self) -> None:
        """The error is the one automations and tools import from haanim."""
        assert AutomationSyntaxError in PUBLIC_ERRORS
        assert issubclass(AutomationSyntaxError, HAAnimError)


class TestSyntaxErrors:
    """Invalid Python is reported the same way as unsupported Python."""

    def test_syntax_error_has_file_and_line(self) -> None:
        """A syntax error carries the file, line and column."""
        with pytest.raises(AutomationSyntaxError) as raised:
            validate_source("x = 1\ndef broken(:\n    pass\n", filename="main.py")

        error = raised.value
        assert error.lineno == 2
        assert error.col_offset == 11
        assert error.filename == "main.py"
        assert str(error).startswith("main.py:2: invalid syntax: ")

    def test_indentation_error(self) -> None:
        """An indentation error is a syntax error."""
        with pytest.raises(AutomationSyntaxError, match=r"main.py:2: invalid syntax"):
            validate_source("def f():\npass\n", filename="main.py")

    def test_null_byte(self) -> None:
        """A source that cannot be parsed at all is reported without a line."""
        with pytest.raises(AutomationSyntaxError) as raised:
            validate_source("x = 1\x00", filename="main.py")

        assert raised.value.lineno is None
        assert str(raised.value).startswith("main.py: invalid ")

    def test_default_filename(self) -> None:
        """Without a filename the problem is reported against a placeholder."""
        with pytest.raises(AutomationSyntaxError, match=r"^<automation>:1: "):
            validate_source("def broken(:")


class TestProblems:
    """All problems of a source are found and reported together."""

    def test_valid_source_returns_the_module(self) -> None:
        """A supported source is returned parsed."""
        tree = validate_source("x = 1\n")

        assert isinstance(tree, ast.Module)
        assert len(tree.body) == 1

    def test_empty_source_is_valid(self) -> None:
        """An empty file has nothing wrong with it."""
        assert validate_source("").body == []

    def test_all_problems_are_listed_in_source_order(self) -> None:
        """One error lists every problem, first one first."""
        source = "match 1:\n    case _:\n        pass\ndef gen():\n    yield 1\nr = sum(x for x in [])\n"

        with pytest.raises(AutomationSyntaxError) as raised:
            validate_source(source, filename="main.py")

        error = raised.value
        assert [problem.lineno for problem in error.problems] == [1, 5, 6]
        assert error.lineno == 1
        assert str(error).splitlines() == [str(problem) for problem in error.problems]

    def test_problems_on_one_line_are_ordered_by_column(self) -> None:
        """Two problems on a line are reported left to right."""
        problems = find_unsupported(ast.parse("r = [sum(a for a in []), sum(b for b in [])]"), "main.py")

        assert [problem.col_offset for problem in problems] == sorted(
            problem.col_offset for problem in problems
        )
        assert len(problems) == 2

    def test_nested_function_is_checked(self) -> None:
        """Code in function and class bodies is checked although it does not run at load."""
        source = "class A:\n    def m(self):\n        def inner():\n            yield 1\n"

        _, problems = check_source(source, "main.py")

        assert [problem.lineno for problem in problems] == [4]

    def test_check_source_does_not_raise(self) -> None:
        """Problems can be collected without an exception."""
        tree, problems = check_source("def broken(:", "main.py")

        assert tree is None
        assert len(problems) == 1

    def test_problem_without_line(self) -> None:
        """A problem with no line is shown with the file only."""
        assert str(Problem("main.py", None, None, "bad")) == "main.py: bad"

    def test_nothing_is_executed(self) -> None:
        """Validating does not run the source."""
        validate_source("raise SystemExit('ran')\nimport os\nos.abort()\n")


class TestValidateFiles:
    """Every source file of an automation is checked."""

    async def test_returns_a_module_per_file(self) -> None:
        """Valid files are returned parsed."""
        files = FakeFileSystem()
        files.write(Path("/a/main.py"), "import helper\n")
        files.write(Path("/a/helper.py"), "x = 1\n")

        trees = await validate_files(files, [Path("/a/main.py"), Path("/a/helper.py")])

        assert set(trees) == {Path("/a/main.py"), Path("/a/helper.py")}

    async def test_problem_in_a_helper_file_is_reported(self) -> None:
        """A file other than the main one is checked too."""
        files = FakeFileSystem()
        files.write(Path("/a/main.py"), "import helper\n")
        files.write(Path("/a/helper.py"), "\ndef gen():\n    yield 1\n")

        with pytest.raises(AutomationSyntaxError, match=r"^helper.py:3: 'yield'") as raised:
            await validate_files(files, [Path("/a/main.py"), Path("/a/helper.py")])

        assert raised.value.filename == "helper.py"

    async def test_problems_of_all_files_are_reported_together(self) -> None:
        """One error covers the whole automation."""
        files = FakeFileSystem()
        files.write(Path("/a/main.py"), "def broken(:\n")
        files.write(Path("/a/helper.py"), "r = sum(x for x in [])\n")

        with pytest.raises(AutomationSyntaxError) as raised:
            await validate_files(files, [Path("/a/main.py"), Path("/a/helper.py")])

        assert [problem.filename for problem in raised.value.problems] == ["main.py", "helper.py"]

    async def test_no_files(self) -> None:
        """An automation without files has no problems."""
        assert await validate_files(FakeFileSystem(), []) == {}

    async def test_unreadable_file(self) -> None:
        """A file that cannot be read is not a syntax error."""
        with pytest.raises(OSError):
            await validate_files(FakeFileSystem(), [Path("/a/missing.py")])


class TestLoad:
    """An automation is checked completely before any of it runs."""

    @pytest.mark.parametrize("case", UNSUPPORTED)
    async def test_load_rejects_unsupported_construct(self, case: str, tmp_path: Path) -> None:
        """Loading fails with the file and line, and the automation is not loaded."""
        source, lineno, _ = UNSUPPORTED[case]
        path = automation_file(tmp_path, "lights")
        path.write_text(source)
        context = make_context(str(path))

        with pytest.raises(AutomationSyntaxError, match=rf"^main.py:{lineno}: "):
            await context.load()

        assert not context.is_loaded

    async def test_nothing_runs_when_a_later_line_is_unsupported(self, tmp_path: Path) -> None:
        """Code before the unsupported construct is not executed."""
        marker = tmp_path / "ran"
        path = automation_file(tmp_path, "lights")
        path.write_text(f"open({str(marker)!r}, 'w').close()\nran = True\n\ndef gen():\n    yield 1\n")
        context = make_context(str(path), allow_all_imports=True)

        with pytest.raises(AutomationSyntaxError, match=r"^main.py:5: "):
            await context.load()

        assert not marker.exists()
        assert context.get_symbol("ran") is None

    async def test_syntax_error_at_load(self, tmp_path: Path) -> None:
        """A syntax error is reported with the file and line."""
        path = automation_file(tmp_path, "lights")
        path.write_text("x = 1\n\ndef broken(:\n")
        context = make_context(str(path))

        with pytest.raises(AutomationSyntaxError, match=r"^main.py:3: invalid syntax"):
            await context.load()


class TestSupportedConstructs:
    """Everything the design counts as supported Python gives the result Python gives."""

    @pytest.mark.parametrize("case", SUPPORTED)
    async def test_runs(self, case: str) -> None:
        """The construct passes validation and gives the result Python gives."""
        source, expected = SUPPORTED[case]

        assert await run(source) == expected
