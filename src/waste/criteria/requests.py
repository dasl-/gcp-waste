"""Request rate criterion for Bigtable and similar resources."""

from __future__ import annotations

from typing import Any, TYPE_CHECKING

from waste.criteria.base import Criterion
from waste.models import CriterionResult

if TYPE_CHECKING:
    from waste.config import CriterionConfig


class LowRequestsCriterion(Criterion):
    """Identifies resources with low request rates."""

    name = "low_requests"
    METRIC_KEY = "requests_per_second"

    def __init__(self, threshold_per_second: float = 1.0):
        self.threshold_per_second = threshold_per_second

    def evaluate(self, resource: Any, metrics: dict[str, Any]) -> CriterionResult:
        rps = metrics.get(self.METRIC_KEY)

        if rps is None:
            return CriterionResult(
                criterion_name=self.name,
                is_idle=False,
                reason="Request rate data unavailable",
                metrics={},
            )

        is_idle = rps < self.threshold_per_second
        return CriterionResult(
            criterion_name=self.name,
            is_idle=is_idle,
            reason=(
                f"Request rate {rps:.2f}/s < {self.threshold_per_second:.1f}/s threshold"
                if is_idle
                else f"Request rate {rps:.2f}/s >= {self.threshold_per_second:.1f}/s threshold"
            ),
            metrics={self.METRIC_KEY: rps},
        )

    @classmethod
    def from_config(cls, config: CriterionConfig) -> LowRequestsCriterion:
        return cls(threshold_per_second=config.threshold_per_second or 1.0)
