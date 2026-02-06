"""Core data models for idle resource detection."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


class ResourceType(str, Enum):
    COMPUTE_VM = "compute_vm"
    BIGTABLE = "bigtable"
    STORAGE = "storage"
    PERSISTENT_DISK = "persistent_disk"


@dataclass
class CriterionResult:
    """Result of evaluating a single idleness criterion."""

    criterion_name: str
    is_idle: bool
    reason: str
    metrics: dict[str, float] = field(default_factory=dict)


@dataclass
class IdleResource:
    """A resource identified as idle/underutilized."""

    resource_type: ResourceType
    name: str
    project: str
    location: str
    creation_time: datetime | None = None
    criterion_results: list[CriterionResult] = field(default_factory=list)
    estimated_yearly_cost: float | None = None
    metadata: dict[str, str] = field(default_factory=dict)

    @property
    def idle_reasons(self) -> list[str]:
        return [r.reason for r in self.criterion_results if r.is_idle]

    @property
    def idle_criterion_names(self) -> list[str]:
        return [r.criterion_name for r in self.criterion_results if r.is_idle]


@dataclass
class ScanResult:
    """Result of scanning one or more projects for idle resources."""

    project: str
    idle_resources: list[IdleResource] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    skipped_types: list[str] = field(default_factory=list)

    @property
    def total_estimated_savings(self) -> float:
        return sum(
            r.estimated_yearly_cost
            for r in self.idle_resources
            if r.estimated_yearly_cost is not None
        )

    def merge(self, other: ScanResult) -> None:
        """Merge another ScanResult into this one."""
        self.idle_resources.extend(other.idle_resources)
        self.errors.extend(other.errors)
        self.skipped_types.extend(other.skipped_types)
