"""Centralized constraint checking for HAAnim triggers.

This module provides the ConstraintChecker class that evaluates state and time constraints
for trigger execution. It is used by TriggerManager to determine if a trigger should execute.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from haanim.const import (
    DECORATOR_STATE_ACTIVE,
    DECORATOR_TIME_ACTIVE,
)

if TYPE_CHECKING:
    from custom_components.haanim.ha.state import StateManager

_LOGGER = logging.getLogger(__name__)


class ConstraintChecker:
    """Evaluates constraints for trigger execution.

    Provides centralized constraint evaluation logic for state and time constraints.
    This class is used by TriggerManager to determine if a trigger's constraints
    are satisfied before execution.
    """

    def __init__(self, state_manager: StateManager) -> None:
        """Initialize the constraint checker.

        Args:
            state_manager: State manager for accessing entity states.
        """
        self.state_manager = state_manager

    async def check_constraints(self, constraints: list[dict[str, Any]]) -> bool:
        """Check if all constraints are satisfied.

        Args:
            constraints: List of constraint dictionaries.

        Returns:
            True if all constraints are satisfied, False otherwise.
        """
        for constraint in constraints:
            constraint_type = constraint.get("type")

            if constraint_type == DECORATOR_STATE_ACTIVE:
                if not self.check_state_constraint(constraint):
                    return False

            elif constraint_type == DECORATOR_TIME_ACTIVE:
                if not self.check_time_constraint(constraint):
                    return False

        return True

    def check_state_constraint(self, constraint: dict[str, Any]) -> bool:
        """Check if state constraint is satisfied.

        Args:
            constraint: State constraint configuration.

        Returns:
            True if constraint is satisfied.
        """
        exprs = constraint.get("exprs", [])
        return all(self._evaluate_state_expr(expr) for expr in exprs)

    def check_time_constraint(self, constraint: dict[str, Any]) -> bool:
        """Check if time constraint is satisfied.

        Args:
            constraint: Time constraint configuration.

        Returns:
            True if constraint is satisfied.
        """
        # TODO: Implement time constraint checking - move it to the time_constraints.py file
        # This should evaluate time range specifications like:
        # - "range(08:00, 17:00)" - specific time ranges
        # - "range(sunset, sunrise)" - dynamic sun-based ranges
        # - Handle overnight ranges that cross midnight
        return True

    def _evaluate_state_expr(self, expr: str) -> bool:
        """Evaluate a state expression.

        Args:
            expr: State expression (e.g., "sensor.temp > 25").

        Returns:
            True if expression evaluates to True.
        """
        try:
            # Parse expression - format: "entity_id operator value"
            parts = expr.split()
            if len(parts) != 3:
                _LOGGER.error("Invalid state expression format: %s", expr)
                return False

            entity_id, operator, expected_value = parts

            # Get current state
            state_val = self.state_manager.get(entity_id)
            if state_val is None:
                _LOGGER.warning("Entity not found for constraint: %s", entity_id)
                return False

            current_value = state_val.state
            if current_value is None:
                _LOGGER.warning("Entity %s has None state", entity_id)
                return False

            # Evaluate based on operator
            if operator == "==":
                return str(current_value) == expected_value.strip("'\"")
            elif operator == "!=":
                return str(current_value) != expected_value.strip("'\"")
            elif operator == ">":
                return float(str(current_value)) > float(expected_value)
            elif operator == ">=":
                return float(str(current_value)) >= float(expected_value)
            elif operator == "<":
                return float(str(current_value)) < float(expected_value)
            elif operator == "<=":
                return float(str(current_value)) <= float(expected_value)
            else:
                _LOGGER.error("Unsupported operator in state expression: %s", operator)
                return False

        except (ValueError, TypeError) as err:
            _LOGGER.error("Error evaluating state expression '%s': %s", expr, err)
            return False
