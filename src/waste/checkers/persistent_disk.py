"""Persistent Disk checker."""

from __future__ import annotations

from datetime import datetime, timezone

from google.cloud import compute_v1

from waste.checkers.base import BaseChecker
from waste.criteria.disk import LowDiskReadCriterion
from waste.models import CriterionResult, IdleResource, ResourceType


class PersistentDiskChecker(BaseChecker):
    """Check Persistent Disks for idleness based on read throughput."""

    resource_type = ResourceType.PERSISTENT_DISK
    resource_type_key = "persistent_disk"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._disks_client = compute_v1.DisksClient(credentials=self.credentials)
        self._instances_client = compute_v1.InstancesClient(credentials=self.credentials)

    def _build_instance_status_map(self) -> dict[str, str]:
        """Build a map of instance resource URL → status (RUNNING, TERMINATED, etc.)."""
        request = compute_v1.AggregatedListInstancesRequest(project=self.project)
        status_map: dict[str, str] = {}
        for zone, scoped_list in self._instances_client.aggregated_list(request=request):
            if scoped_list.instances:
                for instance in scoped_list.instances:
                    zone_name = zone.split("/")[-1] if "/" in zone else zone
                    if zone_name.startswith("zones/"):
                        zone_name = zone_name[6:]
                    key = f"projects/{self.project}/zones/{zone_name}/instances/{instance.name}"
                    status_map[key] = instance.status
        return status_map

    def list_resources(self) -> list[dict]:
        """List all READY persistent disks in the project."""
        instance_status_map = self._build_instance_status_map()
        request = compute_v1.AggregatedListDisksRequest(project=self.project)

        resources = []
        for zone, disks_scoped_list in self._disks_client.aggregated_list(request=request):
            if disks_scoped_list.disks:
                for disk in disks_scoped_list.disks:
                    if disk.status != "READY":
                        continue

                    creation_time = None
                    if disk.creation_timestamp:
                        creation_time = datetime.fromisoformat(
                            disk.creation_timestamp
                        )
                        if creation_time.tzinfo is None:
                            creation_time = creation_time.replace(tzinfo=timezone.utc)

                    # Extract zone name from full zone URL
                    zone_name = zone.split("/")[-1] if "/" in zone else zone
                    if zone_name.startswith("zones/"):
                        zone_name = zone_name[6:]

                    # Extract disk type name from full URL
                    disk_type = disk.type_ if hasattr(disk, "type_") else ""
                    if "/" in disk_type:
                        disk_type = disk_type.split("/")[-1]

                    # Resolve attached instance names and statuses
                    user_urls = list(disk.users) if disk.users else []
                    attached_instances = []
                    for url in user_urls:
                        name = url.split("/")[-1]
                        # Normalize: disk.users contains full API URLs
                        # (https://www.googleapis.com/compute/v1/projects/...)
                        # while our map keys start at "projects/..."
                        idx = url.find("projects/")
                        lookup_key = url[idx:] if idx >= 0 else url
                        status = instance_status_map.get(lookup_key, "UNKNOWN")
                        attached_instances.append(f"{name} ({status})")

                    resources.append({
                        "name": disk.name,
                        "location": zone_name,
                        "creation_time": creation_time,
                        "disk_type": disk_type,
                        "size_gb": disk.size_gb,
                        "users": user_urls,
                        "attached_instances": attached_instances,
                        "provisioned_iops": getattr(disk, "provisioned_iops", 0) or 0,
                        "provisioned_throughput": getattr(disk, "provisioned_throughput", 0) or 0,
                    })

        return resources

    def get_metrics(self, resource: dict) -> dict:
        """Fetch disk read metrics."""
        disk_name = resource["name"]
        resource_filter = (
            f'metric.labels.device_name = "{disk_name}"'
        )

        metrics = {}

        # Disk read bytes: sum over the window, convert to per-second rate
        read_bytes = self.monitoring.query_sum(
            metric_type="compute.googleapis.com/instance/disk/read_bytes_count",
            resource_filter=resource_filter,
            days=self.idle_days,
        )
        if read_bytes is not None:
            seconds = self.idle_days * 86400
            metrics[LowDiskReadCriterion.METRIC_KEY] = read_bytes / seconds

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
                "disk_type": resource["disk_type"],
                "size_gb": str(resource["size_gb"]),
                "users": str(len(resource["users"])),
                "attached_instances": ", ".join(resource["attached_instances"]) if resource["attached_instances"] else "unattached",
                "provisioned_iops": str(resource["provisioned_iops"]),
                "provisioned_throughput": str(resource["provisioned_throughput"]),
            },
        )
