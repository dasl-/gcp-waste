"""Base checker interface."""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

from waste.config import WasteConfig
from waste.criteria.base import CriteriaGroup
from waste.models import IdleResource, ResourceType
from waste.monitoring import MonitoringClient
from waste.pricing import PricingBackend

logger = logging.getLogger(__name__)


class BaseChecker(ABC):
    """Abstract base class for resource checkers."""

    resource_type: ResourceType
    resource_type_key: str  # Key in config, e.g. "compute", "bigtable"

    def __init__(
        self,
        project: str,
        config: WasteConfig,
        monitoring: MonitoringClient,
        pricing: PricingBackend,
        criteria_group: CriteriaGroup,
        idle_days: int = 7,
        min_age_days: int | None = None,
        max_workers: int = 4,
        credentials=None,
    ):
        self.project = project
        self.config = config
        self.monitoring = monitoring
        self.pricing = pricing
        self.criteria_group = criteria_group
        self.idle_days = idle_days
        self.min_age_days = min_age_days
        self.max_workers = max_workers
        self.credentials = credentials

    @abstractmethod
    def list_resources(self) -> list[dict]:
        """List all resources of this type in the project.

        Returns:
            List of resource dicts with at minimum 'name' and 'location' keys.
        """

    @abstractmethod
    def get_metrics(self, resource: dict) -> dict:
        """Fetch metrics for a specific resource from Cloud Monitoring.

        Args:
            resource: Resource dict from list_resources().

        Returns:
            Dict of metric_key -> value for criterion evaluation.
        """

    @abstractmethod
    def to_idle_resource(
        self, resource: dict, criterion_results: list
    ) -> IdleResource:
        """Convert a resource dict to an IdleResource model.

        Args:
            resource: Resource dict from list_resources().
            criterion_results: List of CriterionResult from evaluation.

        Returns:
            IdleResource with all fields populated.
        """

    def is_too_young(self, creation_time: datetime | None) -> bool:
        """Check if a resource is too young to be considered idle."""
        if creation_time is None or self.min_age_days is None:
            return False
        age = datetime.now(timezone.utc) - creation_time
        return age.days < self.min_age_days

    def has_criterion(self, name: str) -> bool:
        """Check if a criterion is active in this checker's criteria group."""
        return name in self.criteria_group.criterion_names

    def is_blocklisted(self, resource_name: str) -> bool:
        """Check if a resource is in the blocklist."""
        return self.config.is_blocklisted(
            self.project, self.resource_type_key, resource_name
        )

    def _post_metrics_filter(self, resource: dict, metrics: dict) -> bool:
        """Hook for subclasses to filter resources after metrics are fetched.

        Returns True to keep the resource, False to skip it.
        """
        return True

    def _process_resource(self, resource: dict) -> IdleResource | None:
        """Process a single resource: filter, fetch metrics, evaluate."""
        name = resource.get("name", "")

        if self.is_blocklisted(name):
            logger.info("[%s] Skipping %s (blocklisted)", self.project, name)
            return None

        creation_time = resource.get("creation_time")
        if self.is_too_young(creation_time):
            logger.info(
                "[%s] Skipping %s (younger than %d days)",
                self.project, name, self.min_age_days,
            )
            return None

        logger.info("[%s] Fetching metrics for %s...", self.project, name)
        metrics = self.get_metrics(resource)
        logger.info("[%s] Metrics for %s: %s", self.project, name, metrics)

        if not self._post_metrics_filter(resource, metrics):
            return None

        is_idle, results = self.criteria_group.evaluate(resource, metrics)

        for r in results:
            logger.info(
                "[%s] %s -> %s: %s",
                self.project, name, r.criterion_name,
                "IDLE" if r.is_idle else "active",
            )

        if is_idle:
            idle = self.to_idle_resource(resource, results)
            idle.estimated_yearly_cost = self.pricing.estimate_yearly_cost(idle)
            cost = idle.estimated_yearly_cost
            if cost is not None:
                logger.info(
                    "[%s] %s is IDLE (est. $%.2f/yr)",
                    self.project, name, cost,
                )
            else:
                logger.info("[%s] %s is IDLE", self.project, name)
            return idle

        logger.info("[%s] %s is not idle", self.project, name)
        return None

    def check(self) -> list[IdleResource]:
        """Run the full check: list resources, fetch metrics in parallel, return idle ones."""
        logger.info(
            "[%s] Listing %s resources...", self.project, self.resource_type_key
        )
        resources = self.list_resources()
        logger.info(
            "[%s] Found %d %s resource(s) to evaluate",
            self.project, len(resources), self.resource_type_key,
        )

        if not resources:
            return []

        workers = min(self.max_workers, len(resources))
        if workers <= 1:
            results = [self._process_resource(r) for r in resources]
        else:
            logger.info(
                "[%s] Processing %s resources with %d workers",
                self.project, self.resource_type_key, workers,
            )
            with ThreadPoolExecutor(max_workers=workers) as executor:
                results = list(executor.map(self._process_resource, resources))

        return [r for r in results if r is not None]
