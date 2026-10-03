"""Load-time validation of automation source code.

The interpreter supports Python with a few exceptions (see "Supported Python" in
the design). This module finds those exceptions by inspecting the parsed source,
so that an automation is rejected before any of its code runs.
"""

from __future__ import annotations

import ast
import warnings
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from haanim.engine.errors import AutomationSyntaxError
from haanim.interfaces import FileSystem

_GENERATOR_HINT = "use a list comprehension"

# Node types that are unsupported wherever they appear.
_UNSUPPORTED_NODES: dict[type[ast.AST], str] = {
    ast.Yield: "'yield' is not supported: automations cannot define generators",
    ast.YieldFrom: "'yield from' is not supported: automations cannot define generators",
    ast.GeneratorExp: f"generator expressions are not supported: {_GENERATOR_HINT}",
    ast.AsyncFor: "'async for' is not supported",
    ast.Match: "'match' statements are not supported",
    ast.TryStar: "'except*' is not supported",
}

_COMPREHENSIONS = (ast.ListComp, ast.SetComp, ast.DictComp)


@dataclass(frozen=True)
class SyntaxProblem:
    """One reason an automation's source cannot be loaded.

    Args:
        filename: The file the problem is in.
        lineno: Line of the problem, starting at 1. None if unknown.
        col_offset: Column of the problem, starting at 0. None if unknown.
        message: What is wrong.
    """

    filename: str
    lineno: int | None
    col_offset: int | None
    message: str

    def __str__(self) -> str:
        """Return the problem as ``file:line: message``."""
        location = self.filename if self.lineno is None else f"{self.filename}:{self.lineno}"
        return f"{location}: {self.message}"


def _position(problem: SyntaxProblem) -> tuple[int, int]:
    """Sort key that puts problems in source order."""
    return (problem.lineno or 0, problem.col_offset or 0)


def _syntax_problem(err: SyntaxError, filename: str) -> SyntaxProblem:
    """Describe a Python syntax error as a problem."""
    column = None if err.offset is None else max(err.offset - 1, 0)
    return SyntaxProblem(filename, err.lineno, column, f"invalid syntax: {err.msg}")


def find_unsupported(tree: ast.AST, filename: str) -> list[SyntaxProblem]:
    """Find every construct in a parsed source that the interpreter does not support.

    Args:
        tree: The parsed source.
        filename: Filename to report the problems against.

    Returns:
        The problems in source order. Empty if the source is supported.
    """
    problems: list[SyntaxProblem] = []

    for node in ast.walk(tree):
        message = _UNSUPPORTED_NODES.get(type(node))
        if message is None and isinstance(node, _COMPREHENSIONS):
            if any(generator.is_async for generator in node.generators):
                message = "async comprehensions are not supported"
        if message is not None:
            problems.append(
                SyntaxProblem(
                    filename=filename,
                    lineno=getattr(node, "lineno", None),
                    col_offset=getattr(node, "col_offset", None),
                    message=message,
                )
            )

    problems.sort(key=_position)
    return problems


def check_source(source: str, filename: str) -> tuple[ast.Module | None, list[SyntaxProblem]]:
    """Parse a source and collect its problems without raising.

    Args:
        source: Python source code.
        filename: Filename to report the problems against.

    Returns:
        The parsed module and its problems. The module is None if the source
        does not parse, in which case the only problem is the syntax error.
    """
    try:
        tree = ast.parse(source, filename=filename, mode="exec")
    except SyntaxError as err:
        return None, [_syntax_problem(err, filename)]

    problems = find_unsupported(tree, filename)

    # The compiler rejects what the parser lets through: 'await' outside an
    # async function, 'return' outside a function and the like. Nothing runs.
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", SyntaxWarning)
            compile(source, filename, "exec", dont_inherit=True)
    except SyntaxError as err:
        problems.append(_syntax_problem(err, filename))
        problems.sort(key=_position)

    return tree, problems


def _raise_for(problems: list[SyntaxProblem]) -> None:
    """Raise an AutomationSyntaxError describing the problems, if there are any."""
    if not problems:
        return

    first = problems[0]
    message = str(first)
    if len(problems) > 1:
        message += "".join(f"\n{problem}" for problem in problems[1:])
    raise AutomationSyntaxError(
        message,
        lineno=first.lineno,
        col_offset=first.col_offset,
        filename=first.filename,
        problems=problems,
    )


def validate_source(source: str, filename: str = "<automation>") -> ast.Module:
    """Parse a source and check that the interpreter supports all of it.

    Nothing in the source is executed.

    Args:
        source: Python source code.
        filename: Filename to report the problems against.

    Returns:
        The parsed module.

    Raises:
        AutomationSyntaxError: If the source does not parse or uses an
            unsupported construct. The error lists every problem found.
    """
    tree, problems = check_source(source, filename)
    _raise_for(problems)
    assert tree is not None
    return tree


async def validate_files(files: FileSystem, paths: Iterable[Path]) -> dict[Path, ast.Module]:
    """Check every source file of an automation.

    All files are checked before anything is reported, so one error lists the
    problems of the whole automation. Nothing in the files is executed.

    Args:
        files: The file system to read from.
        paths: The source files to check.

    Returns:
        The parsed module of each file.

    Raises:
        AutomationSyntaxError: If any file does not parse or uses an
            unsupported construct.
        OSError: If a file cannot be read.
    """
    trees: dict[Path, ast.Module] = {}
    problems: list[SyntaxProblem] = []

    for path in paths:
        tree, found = check_source(await files.read_text(path), path.name)
        problems.extend(found)
        if tree is not None:
            trees[path] = tree

    _raise_for(problems)
    return trees
