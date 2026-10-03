"""The Python operators as functions, keyed by their AST node type."""

from __future__ import annotations

import ast
import operator
from collections.abc import Callable
from typing import Any

BINARY: dict[type[ast.operator], Callable[[Any, Any], Any]] = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
    ast.LShift: operator.lshift,
    ast.RShift: operator.rshift,
    ast.BitOr: operator.or_,
    ast.BitXor: operator.xor,
    ast.BitAnd: operator.and_,
    ast.MatMult: operator.matmul,
}

# Augmented assignment: these update the left operand in place where its type supports it.
IN_PLACE: dict[type[ast.operator], Callable[[Any, Any], Any]] = {
    ast.Add: operator.iadd,
    ast.Sub: operator.isub,
    ast.Mult: operator.imul,
    ast.Div: operator.itruediv,
    ast.FloorDiv: operator.ifloordiv,
    ast.Mod: operator.imod,
    ast.Pow: operator.ipow,
    ast.LShift: operator.ilshift,
    ast.RShift: operator.irshift,
    ast.BitOr: operator.ior,
    ast.BitXor: operator.ixor,
    ast.BitAnd: operator.iand,
    ast.MatMult: operator.imatmul,
}

UNARY: dict[type[ast.unaryop], Callable[[Any], Any]] = {
    ast.UAdd: operator.pos,
    ast.USub: operator.neg,
    ast.Not: operator.not_,
    ast.Invert: operator.invert,
}
