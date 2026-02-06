"""Bigtable cluster checker."""

from __future__ import annotations

from datetime import datetime, timezone

from google.cloud import bigtable

from waste.checkers.base import BaseChecker
from waste.criteria.requests import LowRequestsCriterion
from waste.models import CriterionResult, IdleResource, ResourceType


class BigtableChecker(BaseChecker):
    """Check Bigtable clusters for idleness."""

    resource_type = ResourceType.BIGTABLE
    resource_type_key = "bigtable"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._bigtable_client = bigtable.Client(project=self.project, admin=True, credentials=self.credentials)

    def list_resources(self) -> list[dict]:
        """List all Bigtable instances and their clusters."""
        resources = []

        for instance in self._bigtable_client.list_instances()[0]:
            clusters = instance.list_clusters()[0]
            for cluster in clusters:
                # Extract location from cluster location string
                location = cluster.location
                if "/" in location:
                    location = location.split("/")[-1]

                resources.append({
                    "name": f"{instance.instance_id}/{cluster.cluster_id}",
                    "instance_id": instance.instance_id,
                    "cluster_id": cluster.cluster_id,
                    "location": location,
                    "node_count": cluster.serve_nodes,
                    "creation_time": None,  # Bigtable API doesn't expose creation time
                })

        return resources

    def get_metrics(self, resource: dict) -> dict:
        """Fetch request rate metrics for a Bigtable cluster."""
        instance_id = resource["instance_id"]
        cluster_id = resource["cluster_id"]
        resource_filter = (
            f'resource.labels.instance = "{instance_id}" '
            f'AND resource.labels.cluster = "{cluster_id}"'
        )

        metrics = {}

        rps = self.monitoring.query_rate(
            metric_type="bigtable.googleapis.com/server/request_count",
            resource_filter=resource_filter,
            days=self.idle_days,
        )
        if rps is not None:
            metrics[LowRequestsCriterion.METRIC_KEY] = rps

        return metrics

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
                "node_count": str(resource.get("node_count", 1)),
                "instance_id": resource["instance_id"],
                "cluster_id": resource["cluster_id"],
            },
        )
