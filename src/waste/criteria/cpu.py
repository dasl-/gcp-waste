"""CPU utilization criterion."""

from __future__ import annotations

from typing import Any, TYPE_CHECKING

from waste.criteria.base import Criterion
from waste.models import CriterionResult

if TYPE_CHECKING:
    from waste.config import CriterionConfig


class LowCPUCriterion(Criterion):
    """Identifies resources with low CPU utilization."""

    name = "low_cpu"
    METRIC_KEY = "cpu_utilization_percent"

    def __init__(self, threshold_percent: float = 5.0):
        self.threshold_percent = threshold_percent

    def evaluate(self, resource: Any, metrics: dict[str, Any]) -> CriterionResult:
        cpu_percent = metrics.get(self.METRIC_KEY)

        if cpu_percent is None:
            return CriterionResult(
                criterion_name=self.name,
                is_idle=False,
                reason="CPU utilization data unavailable",
                metrics={},
            )

        is_idle = cpu_percent < self.threshold_percent
        return CriterionResult(
            criterion_name=self.name,
            is_idle=is_idle,
            reason=(
                f"CPU utilization {cpu_percent:.1f}% < {self.threshold_percent}% threshold"
                if is_idle
                else f"CPU utilization {cpu_percent:.1f}% >= {self.threshold_percent}% threshold"
            ),
            metrics={self.METRIC_KEY: cpu_percent},
        )

    @classmethod
    def from_config(cls, config: CriterionConfig) -> LowCPUCriterion:
        return cls(threshold_percent=config.threshold_percent or 5.0)
