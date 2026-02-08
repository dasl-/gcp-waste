"""Egress (sent bytes) utilization criterion."""

from __future__ import annotations

from typing import Any, TYPE_CHECKING

from waste.criteria.base import Criterion
from waste.models import CriterionResult

if TYPE_CHECKING:
    from waste.config import CriterionConfig


class LowEgressCriterion(Criterion):
    """Identifies resources with low egress (outbound) network throughput."""

    name = "low_egress"
    METRIC_KEY = "egress_bytes_per_second"

    def __init__(self, threshold_bytes_per_second: float = 1000.0):
        self.threshold_bytes_per_second = threshold_bytes_per_second

    def evaluate(self, resource: Any, metrics: dict[str, Any]) -> CriterionResult:
        egress_bps = metrics.get(self.METRIC_KEY)

        if egress_bps is None:
            return CriterionResult(
                criterion_name=self.name,
                is_idle=False,
                reason="Egress throughput data unavailable",
                metrics={},
            )

        is_idle = egress_bps < self.threshold_bytes_per_second
        return CriterionResult(
            criterion_name=self.name,
            is_idle=is_idle,
            reason=(
                f"Egress {egress_bps:.0f} B/s < {self.threshold_bytes_per_second:.0f} B/s threshold"
                if is_idle
                else f"Egress {egress_bps:.0f} B/s >= {self.threshold_bytes_per_second:.0f} B/s threshold"
            ),
            metrics={self.METRIC_KEY: egress_bps},
        )

    @classmethod
    def from_config(cls, config: CriterionConfig) -> LowEgressCriterion:
        return cls(threshold_bytes_per_second=config.threshold_bytes_per_second or 1000.0)
