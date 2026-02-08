"""Composable idleness criteria."""

from __future__ import annotations

from typing import TYPE_CHECKING

from waste.criteria.access import NoRecentAccessCriterion
from waste.criteria.base import Criterion, CriteriaGroup, parse_criteria_mode
from waste.criteria.cpu import LowCPUCriterion
from waste.criteria.disk import LowDiskReadCriterion
from waste.criteria.egress import LowEgressCriterion
from waste.criteria.memory import LowMemoryCriterion
from waste.criteria.network import LowNetworkCriterion
from waste.criteria.requests import LowReadBytesCriterion

if TYPE_CHECKING:
    from waste.config import CriterionConfig

CRITERION_REGISTRY: dict[str, type[Criterion]] = {
    "low_cpu": LowCPUCriterion,
    "low_egress": LowEgressCriterion,
    "low_network": LowNetworkCriterion,
    "low_memory": LowMemoryCriterion,
    "low_read_bytes": LowReadBytesCriterion,
    "low_disk_read": LowDiskReadCriterion,
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

    if required_criteria is not None:
        defined = {config.type for config in criteria_configs}
        unknown = required_criteria - defined
        if unknown:
            raise ValueError(
                f"criteria_mode references unknown criteria: {', '.join(sorted(unknown))}. "
                f"Defined criteria: {', '.join(sorted(defined))}"
            )

    criteria = []
    for config in criteria_configs:
        if required_criteria is not None and config.type not in required_criteria:
            continue
        cls = CRITERION_REGISTRY.get(config.type)
        if cls is None:
            raise ValueError(f"Unknown criterion type: {config.type}")
        criteria.append(cls.from_config(config))

    return CriteriaGroup(criteria=criteria, mode=parsed_mode)


__all__ = [
    "CRITERION_REGISTRY",
    "Criterion",
    "CriteriaGroup",
    "LowCPUCriterion",
    "LowEgressCriterion",
    "LowNetworkCriterion",
    "LowMemoryCriterion",
    "LowReadBytesCriterion",
    "LowDiskReadCriterion",
    "NoRecentAccessCriterion",
    "build_criteria_group",
]
