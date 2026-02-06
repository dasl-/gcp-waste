"""Composable idleness criteria."""

from __future__ import annotations

from typing import TYPE_CHECKING

from waste.criteria.access import NoRecentAccessCriterion
from waste.criteria.base import Criterion, CriteriaGroup, parse_criteria_mode
from waste.criteria.cpu import LowCPUCriterion
from waste.criteria.memory import LowMemoryCriterion
from waste.criteria.network import LowNetworkCriterion
from waste.criteria.requests import LowRequestsCriterion

if TYPE_CHECKING:
    from waste.config import CriterionConfig

CRITERION_REGISTRY: dict[str, type[Criterion]] = {
    "low_cpu": LowCPUCriterion,
    "low_network": LowNetworkCriterion,
    "low_memory": LowMemoryCriterion,
    "low_requests": LowRequestsCriterion,
    "no_recent_access": NoRecentAccessCriterion,
}


def build_criteria_group(
    criteria_configs: list[CriterionConfig],
    mode: str = "all",
) -> CriteriaGroup:
    """Build a CriteriaGroup from configuration.

    The mode string supports:
      "all"                        - all criteria must match (AND)
      "any"                        - any criterion can match (OR)
      "all(low_cpu, low_network)"  - only listed criteria must ALL match
      "any(low_cpu, low_network)"  - any of the listed criteria can match
    """
    parsed_mode, required_criteria = parse_criteria_mode(mode)

    criteria = []
    for config in criteria_configs:
        cls = CRITERION_REGISTRY.get(config.type)
        if cls is None:
            raise ValueError(f"Unknown criterion type: {config.type}")
        criteria.append(cls.from_config(config))

    if required_criteria is not None:
        defined = {config.type for config in criteria_configs}
        unknown = required_criteria - defined
        if unknown:
            raise ValueError(
                f"criteria_mode references unknown criteria: {', '.join(sorted(unknown))}. "
                f"Defined criteria: {', '.join(sorted(defined))}"
            )

    return CriteriaGroup(
        criteria=criteria, mode=parsed_mode, required_criteria=required_criteria
    )


__all__ = [
    "CRITERION_REGISTRY",
    "Criterion",
    "CriteriaGroup",
    "LowCPUCriterion",
    "LowNetworkCriterion",
    "LowMemoryCriterion",
    "LowRequestsCriterion",
    "NoRecentAccessCriterion",
    "build_criteria_group",
]
