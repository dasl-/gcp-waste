"""Access-based criterion for storage resources."""

from __future__ import annotations

from typing import Any, TYPE_CHECKING

from waste.criteria.base import Criterion
from waste.models import CriterionResult

if TYPE_CHECKING:
    from waste.config import CriterionConfig


class NoRecentAccessCriterion(Criterion):
    """Identifies resources with no recent access."""

    name = "no_recent_access"
    METRIC_KEY = "request_count"

    def __init__(self, days: int = 90):
        self.days = days

    def evaluate(self, resource: Any, metrics: dict[str, Any]) -> CriterionResult:
        request_count = metrics.get(self.METRIC_KEY)

        if request_count is None:
            return CriterionResult(
                criterion_name=self.name,
                is_idle=False,
                reason="Access data unavailable",
                metrics={},
            )

        is_idle = request_count == 0
        return CriterionResult(
            criterion_name=self.name,
            is_idle=is_idle,
            reason=(
                f"No requests in the last {self.days} days"
                if is_idle
                else f"{request_count:.0f} requests in the last {self.days} days"
            ),
            metrics={self.METRIC_KEY: request_count},
        )

    @classmethod
    def from_config(cls, config: CriterionConfig) -> NoRecentAccessCriterion:
        return cls(days=config.days or 90)
