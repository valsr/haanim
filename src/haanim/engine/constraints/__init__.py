"""Constraint decorators and checker for HAAnim triggers.

This module provides decorators that add constraints to trigger functions, controlling
when they can execute based on state and time conditions. It also provides the
ConstraintChecker class for centralized constraint evaluation.
"""

from haanim.engine.constraints.checker import ConstraintChecker
from haanim.engine.constraints.state_constraint import state_active
from haanim.engine.constraints.time_constraint import time_active

__all__ = [
    "ConstraintChecker",
    "state_active",
    "time_active",
]
