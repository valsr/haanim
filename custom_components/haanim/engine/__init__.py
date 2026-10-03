"""AST-based Python script execution engine for HAAnim.

This package provides a restricted Python execution environment using
AST (Abstract Syntax Tree) evaluation instead of exec/eval.
"""

from __future__ import annotations

from custom_components.haanim.engine.ast_evaluator import AstEvaluator
from custom_components.haanim.engine.errors import (
    ScriptError,
    ScriptRuntimeError,
    ScriptSecurityError,
    ScriptSyntaxError,
)
from custom_components.haanim.engine.eval_function import EvalFunction, ReturnValue
from custom_components.haanim.engine.import_controller import ImportController
from custom_components.haanim.engine.safe_builtins import SafeBuiltins
from custom_components.haanim.engine.symbol_table import SymbolTable

__all__ = [
    # Error types
    "ScriptError",
    "ScriptRuntimeError",
    "ScriptSecurityError",
    "ScriptSyntaxError",
    # Core components
    "AstEvaluator",
    "EvalFunction",
    "ImportController",
    "ReturnValue",
    "SafeBuiltins",
    "SymbolTable",
]
