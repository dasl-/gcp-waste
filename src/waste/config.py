"""Configuration loading and validation."""

from __future__ import annotations

import fnmatch
import logging
from pathlib import Path

import yaml
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class CriterionConfig(BaseModel):
    """Configuration for a single idleness criterion."""

    type: str
    # Generic threshold fields - each criterion uses what it needs
    threshold_percent: float | None = None
    threshold_bytes_per_second: float | None = None
    threshold_per_second: float | None = None
    days: int | None = None


class ResourceTypeConfig(BaseModel):
    """Configuration for a resource type's idleness detection."""

    criteria_mode: str = "all"
    min_age_days: int = 7
    criteria: list[CriterionConfig] = Field(default_factory=list)
    # Storage-specific
    min_size_gb: float | None = None


class ThresholdsConfig(BaseModel):
    """Thresholds configuration for all resource types."""

    compute: ResourceTypeConfig = Field(default_factory=lambda: ResourceTypeConfig(
        criteria=[
            CriterionConfig(type="low_cpu", threshold_percent=5.0),
            CriterionConfig(type="low_network", threshold_bytes_per_second=1000),
        ]
    ))
    bigtable: ResourceTypeConfig = Field(default_factory=lambda: ResourceTypeConfig(
        criteria=[
            CriterionConfig(type="low_read_bytes", threshold_bytes_per_second=1000),
        ]
    ))
    storage: ResourceTypeConfig = Field(default_factory=lambda: ResourceTypeConfig(
        criteria_mode="any",
        min_size_gb=1.0,
        criteria=[
            CriterionConfig(type="low_read_bytes", threshold_bytes_per_second=1000),
        ]
    ))
    persistent_disk: ResourceTypeConfig = Field(default_factory=lambda: ResourceTypeConfig(
        criteria=[
            CriterionConfig(type="low_disk_read", threshold_bytes_per_second=1000),
        ]
    ))


class WasteConfig(BaseModel):
    """Top-level configuration."""

    thresholds: ThresholdsConfig = Field(default_factory=ThresholdsConfig)
    blocklist: dict[str, dict[str, list[str]]] = Field(default_factory=dict)
    min_yearly_cost: float | None = None
    exclude_projects: list[str] = Field(default_factory=list)

    def is_blocklisted(self, project: str, resource_type: str, resource_name: str) -> bool:
        """Check if a resource matches any blocklist pattern."""
        project_blocklist = self.blocklist.get(project, {})
        patterns = project_blocklist.get(resource_type, [])
        return any(fnmatch.fnmatch(resource_name, pattern) for pattern in patterns)


def _log_criterion(criterion: CriterionConfig) -> str:
    """Format a single criterion for logging."""
    parts = [criterion.type]
    if criterion.threshold_percent is not None:
        parts.append(f"threshold={criterion.threshold_percent}%")
    if criterion.threshold_bytes_per_second is not None:
        parts.append(f"threshold={criterion.threshold_bytes_per_second} B/s")
    if criterion.threshold_per_second is not None:
        parts.append(f"threshold={criterion.threshold_per_second}/s")
    if criterion.days is not None:
        parts.append(f"days={criterion.days}")
    return ", ".join(parts)


def _log_config(config: WasteConfig, source: str) -> None:
    """Log the parsed configuration at INFO level."""
    logger.info("Configuration loaded from %s", source)

    for rtype in ("compute", "bigtable", "storage", "persistent_disk"):
        type_config: ResourceTypeConfig = getattr(config.thresholds, rtype)
        logger.info(
            "  %s: criteria_mode=%s, min_age_days=%d",
            rtype, type_config.criteria_mode, type_config.min_age_days,
        )
        if rtype == "storage" and type_config.min_size_gb is not None:
            logger.info("  %s: min_size_gb=%.1f", rtype, type_config.min_size_gb)
        for criterion in type_config.criteria:
            logger.info("  %s: criterion: %s", rtype, _log_criterion(criterion))

    if config.min_yearly_cost is not None:
        logger.info("  min_yearly_cost: $%.2f", config.min_yearly_cost)

    if config.exclude_projects:
        logger.info("  exclude_projects: %s", ", ".join(config.exclude_projects))

    if config.blocklist:
        for project, types in config.blocklist.items():
            for btype, patterns in types.items():
                logger.info(
                    "  blocklist: %s/%s: %s",
                    project, btype, ", ".join(patterns),
                )
    else:
        logger.info("  blocklist: (empty)")


_AUTO_DISCOVER_PATHS = [
    "config.yaml",
    "config.yml",
    "gcp-waste.yaml",
    "gcp-waste.yml",
]


def load_config(path: Path | None = None) -> WasteConfig:
    """Load configuration from YAML file, or return defaults.

    If no path is given, looks for config.yaml, config.yml, gcp-waste.yaml,
    or gcp-waste.yml in the current directory. Falls back to built-in defaults.
    """
    if path is None:
        for candidate in _AUTO_DISCOVER_PATHS:
            candidate_path = Path(candidate)
            if candidate_path.is_file():
                logger.info("Auto-discovered config file: %s", candidate_path)
                path = candidate_path
                break

    if path is None:
        config = WasteConfig()
        _log_config(config, "built-in defaults (no config file found)")
        return config

    logger.info("Reading config file: %s", path)
    with open(path) as f:
        raw = yaml.safe_load(f)

    if raw is None:
        config = WasteConfig()
        _log_config(config, f"{path} (empty file, using defaults)")
        return config

    config = WasteConfig.model_validate(raw)
    _log_config(config, str(path))
    return config
