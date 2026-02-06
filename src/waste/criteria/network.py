"""Network utilization criterion."""

from __future__ import annotations

from typing import Any, TYPE_CHECKING

from waste.criteria.base import Criterion
from waste.models import CriterionResult

if TYPE_CHECKING:
    from waste.config import CriterionConfig


class LowNetworkCriterion(Criterion):
    """Identifies resources with low network throughput."""

    name = "low_network"
    METRIC_KEY = "network_bytes_per_second"

    def __init__(self, threshold_bytes_per_second: float = 1000.0):
        self.threshold_bytes_per_second = threshold_bytes_per_second

    def evaluate(self, resource: Any, metrics: dict[str, Any]) -> CriterionResult:
        network_bps = metrics.get(self.METRIC_KEY)

        if network_bps is None:
            return CriterionResult(
                criterion_name=self.name,
                is_idle=False,
                reason="Network throughput data unavailable",
                metrics={},
            )

        is_idle = network_bps < self.threshold_bytes_per_second
        return CriterionResult(
            criterion_name=self.name,
            is_idle=is_idle,
            reason=(
                f"Network {network_bps:.0f} B/s < {self.threshold_bytes_per_second:.0f} B/s threshold"
                if is_idle
                else f"Network {network_bps:.0f} B/s >= {self.threshold_bytes_per_second:.0f} B/s threshold"
            ),
            metrics={self.METRIC_KEY: network_bps},
        )

    @classmethod
    def from_config(cls, config: CriterionConfig) -> LowNetworkCriterion:
        return cls(threshold_bytes_per_second=config.threshold_bytes_per_second or 1000.0)
