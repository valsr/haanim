"""Load-time validation of automation source code.

The interpreter supports Python with a few exceptions (see "Supported Python" in
the design), and automations may only use allowed imports and builtins (see
"Imports"). This module finds violations of both by inspecting the parsed
source, so that an automation is rejected before any of its code runs.
"""

from __future__ import annotations

import ast
import warnings
from collections.abc import Collection, Iterable
from dataclasses import dataclass
from pathlib import Path

from haanim.engine.errors import AutomationSecurityError, AutomationSyntaxError
from haanim.engine.import_controller import ImportController
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
class Problem:
    """One reason an automation's source cannot be loaded.

    Args:
        filename: The file the problem is in.
        lineno: Line of the problem, starting at 1. None if unknown.
        col_offset: Column of the problem, starting at 0. None if unknown.
        message: What is wrong.
        security: Whether this is a disallowed import or builtin rather than
            unsupported or invalid Python.
    """

    filename: str
    lineno: int | None
    col_offset: int | None
    message: str
    security: bool = False

    def __str__(self) -> str:
        """Return the problem as ``file:line: message``."""
        location = self.filename if self.lineno is None else f"{self.filename}:{self.lineno}"
        return f"{location}: {self.message}"


def _position(problem: Problem) -> tuple[int, int]:
    """Sort key that puts problems in source order."""
    return (problem.lineno or 0, problem.col_offset or 0)


def _syntax_problem(err: SyntaxError, filename: str) -> Problem:
    """Describe a Python syntax error as a problem."""
    column = None if err.offset is None else max(err.offset - 1, 0)
    return Problem(filename, err.lineno, column, f"invalid syntax: {err.msg}")


def find_unsupported(tree: ast.AST, filename: str) -> list[Problem]:
    """Find every construct in a parsed source that the interpreter does not support.

    Args:
        tree: The parsed source.
        filename: Filename to report the problems against.

    Returns:
        The problems in source order. Empty if the source is supported.
    """
    problems: list[Problem] = []

    for node in ast.walk(tree):
        message = _UNSUPPORTED_NODES.get(type(node))
        if message is None and isinstance(node, _COMPREHENSIONS):
            if any(generator.is_async for generator in node.generators):
                message = "async comprehensions are not supported"
        if message is not None:
            problems.append(
                Problem(
                    filename=filename,
                    lineno=getattr(node, "lineno", None),
                    col_offset=getattr(node, "col_offset", None),
                    message=message,
                )
            )

    problems.sort(key=_position)
    return problems


def _bound_names(tree: ast.AST) -> set[str]:
    """Return every name the source itself defines, in any scope."""
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and not isinstance(node.ctx, ast.Load):
            names.add(node.id)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, ast.arg):
            names.add(node.arg)
        elif isinstance(node, ast.alias):
            names.add((node.asname or node.name).split(".")[0])
        elif isinstance(node, ast.ExceptHandler) and node.name:
            names.add(node.name)
    return names


def find_disallowed(
    tree: ast.AST,
    filename: str,
    imports: ImportController | None = None,
    restricted_builtins: Collection[str] = (),
) -> list[Problem]:
    """Find every import and builtin in a parsed source that automations may not use.

    A restricted builtin name that the source defines itself (``def open(): ...``)
    is not a use of the builtin and is not reported.

    Args:
        tree: The parsed source.
        filename: Filename to report the problems against.
        imports: The import rules. Imports are not checked if omitted.
        restricted_builtins: Names of the builtins that are disabled.

    Returns:
        The problems in source order. Empty if nothing is disallowed.
    """
    problems: list[Problem] = []
    own_names = _bound_names(tree) if restricted_builtins else set()

    def report(node: ast.AST, message: str) -> None:
        lineno, col_offset = getattr(node, "lineno", None), getattr(node, "col_offset", None)
        problems.append(Problem(filename, lineno, col_offset, message, security=True))

    for node in ast.walk(tree):
        modules: list[str] = []
        if isinstance(node, ast.Import):
            modules = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            if any(alias.name == "*" for alias in node.names):
                report(node, "wildcard imports are not allowed")
            # Relative imports stay within the automation and are always allowed.
            modules = [node.module] if node.level == 0 and node.module else []
        elif isinstance(node, ast.Name) and node.id in restricted_builtins and node.id not in own_names:
            report(node, f"builtin '{node.id}' is not available in automations")

        if imports is not None:
            for module in modules:
                if not imports.is_allowed(module):
                    report(node, f"import of module '{module}' is not allowed")

    problems.sort(key=_position)
    return problems


def check_source(
    source: str,
    filename: str,
    imports: ImportController | None = None,
    restricted_builtins: Collection[str] = (),
) -> tuple[ast.Module | None, list[Problem]]:
    """Parse a source and collect its problems without raising.

    Args:
        source: Python source code.
        filename: Filename to report the problems against.
        imports: The import rules. Imports are not checked if omitted.
        restricted_builtins: Names of the builtins that are disabled.

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

    problems.extend(find_disallowed(tree, filename, imports, restricted_builtins))
    problems.sort(key=_position)
    return tree, problems


def _raise_for(problems: list[Problem]) -> None:
    """Raise the error describing the problems, if there are any.

    Invalid or unsupported Python is reported first, as AutomationSyntaxError.
    A source that is valid but uses something disallowed is reported as
    AutomationSecurityError.
    """
    if not problems:
        return

    syntax = [problem for problem in problems if not problem.security]
    reported = syntax or problems
    error = AutomationSyntaxError if syntax else AutomationSecurityError
    first = reported[0]
    raise error(
        "\n".join(str(problem) for problem in reported),
        lineno=first.lineno,
        col_offset=first.col_offset,
        filename=first.filename,
        problems=reported,
    )


def validate_source(
    source: str,
    filename: str = "<automation>",
    *,
    imports: ImportController | None = None,
    restricted_builtins: Collection[str] = (),
) -> ast.Module:
    """Parse a source and check that an automation may contain all of it.

    Nothing in the source is executed.

    Args:
        source: Python source code.
        filename: Filename to report the problems against.
        imports: The import rules. Imports are not checked if omitted.
        restricted_builtins: Names of the builtins that are disabled.

    Returns:
        The parsed module.

    Raises:
        AutomationSyntaxError: If the source does not parse or uses an
            unsupported construct. The error lists every such problem.
        AutomationSecurityError: If the source is supported Python but uses a
            disallowed import or builtin. The error lists every such problem.
    """
    tree, problems = check_source(source, filename, imports, restricted_builtins)
    _raise_for(problems)
    assert tree is not None
    return tree


async def validate_files(
    files: FileSystem,
    paths: Iterable[Path],
    *,
    imports: ImportController | None = None,
    restricted_builtins: Collection[str] = (),
    relative_to: Path | None = None,
) -> dict[Path, ast.Module]:
    """Check every source file of an automation.

    All files are checked before anything is reported, so one error lists the
    problems of the whole automation. Nothing in the files is executed.

    Args:
        files: The file system to read from.
        paths: The source files to check.
        imports: The import rules. Imports are not checked if omitted.
        restricted_builtins: Names of the builtins that are disabled.
        relative_to: The automation's folder. Problems are reported with the
            file's path within it; with the bare file name if omitted.

    Returns:
        The parsed module of each file.

    Raises:
        AutomationSyntaxError: If any file does not parse or uses an
            unsupported construct.
        AutomationSecurityError: If the files are supported Python but one uses
            a disallowed import or builtin.
        OSError: If a file cannot be read.
    """
    trees: dict[Path, ast.Module] = {}
    problems: list[Problem] = []

    for path in paths:
        name = path.name if relative_to is None else path.relative_to(relative_to).as_posix()
        tree, found = check_source(await files.read_text(path), name, imports, restricted_builtins)
        problems.extend(found)
        if tree is not None:
            trees[path] = tree

    _raise_for(problems)
    return trees
