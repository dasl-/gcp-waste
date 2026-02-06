"""Disk read throughput criterion for persistent disks."""

from __future__ import annotations

from typing import Any, TYPE_CHECKING

from waste.criteria.base import Criterion
from waste.models import CriterionResult

if TYPE_CHECKING:
    from waste.config import CriterionConfig


class LowDiskReadCriterion(Criterion):
    """Identifies disks with low read throughput."""

    name = "low_disk_read"
    METRIC_KEY = "disk_read_bytes_per_second"

    def __init__(self, threshold_bytes_per_second: float = 1000.0):
        self.threshold_bytes_per_second = threshold_bytes_per_second

    def evaluate(self, resource: Any, metrics: dict[str, Any]) -> CriterionResult:
        read_bps = metrics.get(self.METRIC_KEY)

        # No data means the disk has zero reads (e.g. unattached disk) → idle
        if read_bps is None:
            return CriterionResult(
                criterion_name=self.name,
                is_idle=True,
                reason="No disk read data (disk has zero reads)",
                metrics={},
            )

        is_idle = read_bps < self.threshold_bytes_per_second
        return CriterionResult(
            criterion_name=self.name,
            is_idle=is_idle,
            reason=(
                f"Disk read {read_bps:.0f} B/s < {self.threshold_bytes_per_second:.0f} B/s threshold"
                if is_idle
                else f"Disk read {read_bps:.0f} B/s >= {self.threshold_bytes_per_second:.0f} B/s threshold"
            ),
            metrics={self.METRIC_KEY: read_bps},
        )

    @classmethod
    def from_config(cls, config: CriterionConfig) -> LowDiskReadCriterion:
        return cls(threshold_bytes_per_second=config.threshold_bytes_per_second or 1000.0)
