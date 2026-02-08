"""Compute Engine VM checker."""

from __future__ import annotations

from datetime import datetime, timezone

from google.cloud import compute_v1

from waste.checkers.base import BaseChecker
from waste.criteria.cpu import LowCPUCriterion
from waste.criteria.egress import LowEgressCriterion
from waste.criteria.network import LowNetworkCriterion
from waste.models import CriterionResult, IdleResource, ResourceType


class ComputeChecker(BaseChecker):
    """Check Compute Engine VMs for idleness."""

    resource_type = ResourceType.COMPUTE_VM
    resource_type_key = "compute"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._compute_client = compute_v1.InstancesClient(credentials=self.credentials)

    def list_resources(self) -> list[dict]:
        """List all running VMs in the project."""
        request = compute_v1.AggregatedListInstancesRequest(project=self.project)

        resources = []
        for zone, instances_scoped_list in self._compute_client.aggregated_list(request=request):
            if instances_scoped_list.instances:
                for instance in instances_scoped_list.instances:
                    if instance.status != "RUNNING":
                        continue

                    creation_time = None
                    if instance.creation_timestamp:
                        creation_time = datetime.fromisoformat(
                            instance.creation_timestamp
                        )
                        if creation_time.tzinfo is None:
                            creation_time = creation_time.replace(tzinfo=timezone.utc)

                    # Extract zone name from full zone URL
                    zone_name = zone.split("/")[-1] if "/" in zone else zone
                    # Remove "zones/" prefix if present
                    if zone_name.startswith("zones/"):
                        zone_name = zone_name[6:]

                    # Extract machine type name from full URL
                    machine_type = instance.machine_type
                    if "/" in machine_type:
                        machine_type = machine_type.split("/")[-1]

                    last_start_time = None
                    if instance.last_start_timestamp:
                        last_start_time = datetime.fromisoformat(
                            instance.last_start_timestamp
                        )
                        if last_start_time.tzinfo is None:
                            last_start_time = last_start_time.replace(tzinfo=timezone.utc)

                    # Extract GPU info from guest accelerators
                    gpu_count = 0
                    gpu_type = ""
                    if instance.guest_accelerators:
                        acc = instance.guest_accelerators[0]
                        gpu_count = acc.accelerator_count
                        gpu_type = acc.accelerator_type
                        if "/" in gpu_type:
                            gpu_type = gpu_type.split("/")[-1]

                    resources.append({
                        "name": instance.name,
                        "location": zone_name,
                        "instance_id": str(instance.id),
                        "machine_type": machine_type,
                        "creation_time": creation_time,
                        "last_start_time": last_start_time,
                        "gpu_count": gpu_count,
                        "gpu_type": gpu_type,
                    })

        return resources

    def get_metrics(self, resource: dict) -> dict:
        """Fetch CPU and network metrics for a VM."""
        instance_id = resource["instance_id"]
        resource_filter = (
            f'resource.labels.instance_id = "{instance_id}"'
        )

        metrics = {}

        # CPU utilization (returns 0-1, convert to percent)
        cpu = self.monitoring.query_mean(
            metric_type="compute.googleapis.com/instance/cpu/utilization",
            resource_filter=resource_filter,
            days=self.idle_days,
        )
        if cpu is not None:
            metrics[LowCPUCriterion.METRIC_KEY] = cpu * 100.0

        # Network: sum of sent and received bytes, convert to per-second
        sent = self.monitoring.query_sum(
            metric_type="compute.googleapis.com/instance/network/sent_bytes_count",
            resource_filter=resource_filter,
            days=self.idle_days,
        )
        received = self.monitoring.query_sum(
            metric_type="compute.googleapis.com/instance/network/received_bytes_count",
            resource_filter=resource_filter,
            days=self.idle_days,
        )
        seconds = self.idle_days * 86400
        if sent is not None:
            metrics[LowEgressCriterion.METRIC_KEY] = sent / seconds
        if sent is not None and received is not None:
            total_bytes = sent + received
            metrics[LowNetworkCriterion.METRIC_KEY] = total_bytes / seconds

        # Memory (from ops agent, may not be available)
        memory = self.monitoring.query_mean(
            metric_type="agent.googleapis.com/memory/percent_used",
            resource_filter=resource_filter,
            days=self.idle_days,
        )
        if memory is not None:
            from waste.criteria.memory import LowMemoryCriterion
            metrics[LowMemoryCriterion.METRIC_KEY] = memory

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
                "machine_type": resource["machine_type"],
                "instance_id": resource["instance_id"],
                **({"last_start_time": resource["last_start_time"].isoformat()}
                   if resource.get("last_start_time") else {}),
                **({"gpu_count": str(resource["gpu_count"]),
                    "gpu_type": resource["gpu_type"]}
                   if resource.get("gpu_count") else {}),
            },
        )
