"""Base classes for idleness criteria."""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from typing import Any, Literal, TYPE_CHECKING

from waste.models import CriterionResult

if TYPE_CHECKING:
    from waste.config import CriterionConfig


class Criterion(ABC):
    """Single idleness criterion."""

    name: str = "unknown"

    @abstractmethod
    def evaluate(self, resource: Any, metrics: dict[str, Any]) -> CriterionResult:
        """Evaluate whether a resource meets this idleness criterion.

        Args:
            resource: The resource being evaluated (type depends on checker).
            metrics: Dict of metric name -> value from Cloud Monitoring.

        Returns:
            CriterionResult with is_idle, reason, and relevant metrics.
        """

    @classmethod
    @abstractmethod
    def from_config(cls, config: CriterionConfig) -> Criterion:
        """Create a criterion instance from configuration."""


def parse_criteria_mode(mode_str: str) -> tuple[str, set[str] | None]:
    """Parse a criteria_mode string into (mode, required_criteria).

    Formats:
      "all"                        → ("all", None)       — all criteria must match
      "any"                        → ("any", None)       — any criterion can match
      "all(low_cpu, low_network)"  → ("all", {"low_cpu", "low_network"})
      "any(low_cpu, low_network)"  → ("any", {"low_cpu", "low_network"})

    When required_criteria is not None, only those criteria are included
    in the group. Unlisted criteria are not evaluated.

    Returns:
        Tuple of (mode, required_criteria). mode is "all" or "any".
        required_criteria is None (use all) or a set of criterion names.
    """
    mode_str = mode_str.strip()

    if mode_str in ("all", "any"):
        return mode_str, None

    match = re.fullmatch(r"(all|any)\(([^)]+)\)", mode_str)
    if not match:
        raise ValueError(
            f"Invalid criteria_mode: {mode_str!r}. "
            f"Expected 'all', 'any', 'all(criterion1, criterion2, ...)', "
            f"or 'any(criterion1, criterion2, ...)'."
        )

    mode = match.group(1)
    names = {n.strip() for n in match.group(2).split(",")}
    if not names:
        raise ValueError(f"Empty criteria list in criteria_mode: {mode_str!r}")
    return mode, names


class CriteriaGroup:
    """Combine criteria with AND/OR logic."""

    def __init__(
        self,
        criteria: list[Criterion],
        mode: Literal["all", "any"] = "all",
    ):
        self.criteria = criteria
        self.mode = mode

    @property
    def criterion_names(self) -> set[str]:
        """Return the set of criterion names in this group."""
        return {c.name for c in self.criteria}

    def evaluate(
        self, resource: Any, metrics: dict[str, Any]
    ) -> tuple[bool, list[CriterionResult]]:
        """Evaluate all criteria and combine results.

        Args:
            resource: The resource being evaluated.
            metrics: Dict of metric name -> value from Cloud Monitoring.

        Returns:
            Tuple of (is_idle, list of individual criterion results).
        """
        results = [c.evaluate(resource, metrics) for c in self.criteria]

        if not results:
            return False, []

        if self.mode == "all":
            is_idle = all(r.is_idle for r in results)
        else:
            is_idle = any(r.is_idle for r in results)

        return is_idle, results
