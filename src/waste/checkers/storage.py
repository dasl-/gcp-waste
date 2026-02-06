"""Cloud Storage bucket checker."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from google.cloud import storage

from waste.checkers.base import BaseChecker
from waste.criteria.access import NoRecentAccessCriterion
from waste.models import CriterionResult, IdleResource, ResourceType

logger = logging.getLogger(__name__)


class StorageChecker(BaseChecker):
    """Check Cloud Storage buckets for idleness."""

    resource_type = ResourceType.STORAGE
    resource_type_key = "storage"

    def __init__(self, *args, min_size_gb: float | None = None, **kwargs):
        super().__init__(*args, **kwargs)
        self.min_size_gb = min_size_gb
        self._storage_client = storage.Client(project=self.project, credentials=self.credentials)

    def list_resources(self) -> list[dict]:
        """List all GCS buckets in the project."""
        resources = []

        for bucket in self._storage_client.list_buckets():
            creation_time = bucket.time_created
            if creation_time and creation_time.tzinfo is None:
                creation_time = creation_time.replace(tzinfo=timezone.utc)

            resources.append({
                "name": bucket.name,
                "location": bucket.location or "unknown",
                "storage_class": bucket.storage_class or "STANDARD",
                "creation_time": creation_time,
            })

        return resources

    def get_metrics(self, resource: dict) -> dict:
        """Fetch access and size metrics for a bucket."""
        bucket_name = resource["name"]
        resource_filter = f'resource.labels.bucket_name = "{bucket_name}"'

        metrics = {}

        # Access criterion uses configurable days from the criterion itself
        access_days = self.idle_days
        for criterion in self.criteria_group.criteria:
            if isinstance(criterion, NoRecentAccessCriterion):
                access_days = criterion.days
                break

        request_count = self.monitoring.query_sum(
            metric_type="storage.googleapis.com/api/request_count",
            resource_filter=resource_filter,
            days=access_days,
        )
        if request_count is not None:
            metrics[NoRecentAccessCriterion.METRIC_KEY] = request_count

        # Get bucket size
        size_bytes = self.monitoring.query_mean(
            metric_type="storage.googleapis.com/storage/total_bytes",
            resource_filter=resource_filter,
            days=1,
        )
        if size_bytes is not None:
            metrics["size_gb"] = size_bytes / (1024**3)
            resource["size_gb"] = metrics["size_gb"]

        return metrics

    def _post_metrics_filter(self, resource: dict, metrics: dict) -> bool:
        """Filter out buckets smaller than min_size_gb."""
        if self.min_size_gb is not None:
            size_gb = metrics.get("size_gb", 0)
            if size_gb < self.min_size_gb:
                name = resource.get("name", "")
                logger.info(
                    "[%s] Skipping bucket %s (%.2f GB < %.2f GB min)",
                    self.project, name, size_gb, self.min_size_gb,
                )
                return False
        return True

    def to_idle_resource(
        self, resource: dict, criterion_results: list[CriterionResult]
    ) -> IdleResource:
        return IdleResource(
            resource_type=self.resource_type,
            name=resource["name"],
            project=self.project,
            location=resource["location"],
            creation_time=resource.get("creation_time"),
            criterion_results=criterion_results,
            metadata={
                "storage_class": resource.get("storage_class", "STANDARD"),
                "size_gb": str(resource.get("size_gb", 0)),
            },
        )
