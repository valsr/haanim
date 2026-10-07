"""AST-based Python automation execution engine for HAAnim.

This package provides a restricted Python execution environment using
AST (Abstract Syntax Tree) evaluation instead of exec/eval.
"""

from __future__ import annotations

from haanim.engine.ast_evaluator import AstEvaluator
from haanim.engine.errors import (
    HAAnimError,
    AutomationRuntimeError,
    AutomationSecurityError,
    AutomationSyntaxError,
)
from haanim.engine.eval_function import EvalFunction, ReturnValue
from haanim.engine.import_controller import ImportController
from haanim.engine.safe_builtins import SafeBuiltins
from haanim.engine.symbol_table import SymbolTable

__all__ = [
    # Error types
    "HAAnimError",
    "AutomationRuntimeError",
    "AutomationSecurityError",
    "AutomationSyntaxError",
    # Core components
    "AstEvaluator",
    "EvalFunction",
    "ImportController",
    "ReturnValue",
    "SafeBuiltins",
    "SymbolTable",
]
