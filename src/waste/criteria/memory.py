"""Memory utilization criterion."""

from __future__ import annotations

from typing import Any, TYPE_CHECKING

from waste.criteria.base import Criterion
from waste.models import CriterionResult

if TYPE_CHECKING:
    from waste.config import CriterionConfig


class LowMemoryCriterion(Criterion):
    """Identifies resources with low memory utilization."""

    name = "low_memory"
    METRIC_KEY = "memory_utilization_percent"

    def __init__(self, threshold_percent: float = 10.0):
        self.threshold_percent = threshold_percent

    def evaluate(self, resource: Any, metrics: dict[str, Any]) -> CriterionResult:
        mem_percent = metrics.get(self.METRIC_KEY)

        if mem_percent is None:
            return CriterionResult(
                criterion_name=self.name,
                is_idle=False,
                reason="Memory utilization data unavailable",
                metrics={},
            )

        is_idle = mem_percent < self.threshold_percent
        return CriterionResult(
            criterion_name=self.name,
            is_idle=is_idle,
            reason=(
                f"Memory utilization {mem_percent:.1f}% < {self.threshold_percent}% threshold"
                if is_idle
                else f"Memory utilization {mem_percent:.1f}% >= {self.threshold_percent}% threshold"
            ),
            metrics={self.METRIC_KEY: mem_percent},
        )

    @classmethod
    def from_config(cls, config: CriterionConfig) -> LowMemoryCriterion:
        return cls(threshold_percent=config.threshold_percent or 10.0)
