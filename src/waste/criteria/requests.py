"""Read bytes throughput criterion for Bigtable and similar resources."""

from __future__ import annotations

from typing import Any, TYPE_CHECKING

from waste.criteria.base import Criterion
from waste.models import CriterionResult

if TYPE_CHECKING:
    from waste.config import CriterionConfig


class LowReadBytesCriterion(Criterion):
    """Identifies resources with low read throughput (bytes sent to clients)."""

    name = "low_read_bytes"
    METRIC_KEY = "read_bytes_per_second"

    def __init__(self, threshold_bytes_per_second: float = 1000.0):
        self.threshold_bytes_per_second = threshold_bytes_per_second

    def evaluate(self, resource: Any, metrics: dict[str, Any]) -> CriterionResult:
        bps = metrics.get(self.METRIC_KEY)

        if bps is None:
            return CriterionResult(
                criterion_name=self.name,
                is_idle=True,
                reason="No read data (zero bytes sent to clients)",
                metrics={},
            )

        is_idle = bps < self.threshold_bytes_per_second
        return CriterionResult(
            criterion_name=self.name,
            is_idle=is_idle,
            reason=(
                f"Read throughput {bps:.0f} B/s < {self.threshold_bytes_per_second:.0f} B/s threshold"
                if is_idle
                else f"Read throughput {bps:.0f} B/s >= {self.threshold_bytes_per_second:.0f} B/s threshold"
            ),
            metrics={self.METRIC_KEY: bps},
        )

    @classmethod
    def from_config(cls, config: CriterionConfig) -> LowReadBytesCriterion:
        return cls(threshold_bytes_per_second=config.threshold_bytes_per_second or 1000.0)
