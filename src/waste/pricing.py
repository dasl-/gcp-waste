"""Cost estimation using lookup tables with per-vCPU fallback.

Known machine types are mapped to their hourly on-demand prices (Iowa,
us-central1).  Unknown types fall back to a rough per-vCPU estimate.
"""

from __future__ import annotations

import logging

from waste.models import IdleResource, ResourceType

logger = logging.getLogger(__name__)

# Hours per month (365.25 / 12 * 24)
HOURS_PER_MONTH = 730

# ---- VM pricing: per-instance hourly rates (Iowa us-central1, on-demand) ----
# Source: https://cloud.google.com/compute/vm-instance-pricing

VM_HOURLY: dict[str, float] = {
    # E2 shared-core
    "e2-micro": 0.00838,
    "e2-small": 0.01675,
    "e2-medium": 0.03351,
    # E2 standard
    "e2-standard-2": 0.06701,
    "e2-standard-4": 0.13402,
    "e2-standard-8": 0.26805,
    "e2-standard-16": 0.53609,
    # N1 standard
    "n1-standard-1": 0.04749,
    "n1-standard-2": 0.09498,
    "n1-standard-4": 0.18995,
    "n1-standard-8": 0.37990,
    "n1-standard-16": 0.75981,
    # N2 standard
    "n2-standard-2": 0.09712,
    "n2-standard-4": 0.19424,
    "n2-standard-8": 0.38848,
    "n2-standard-16": 0.77696,
    # N2D standard
    "n2d-standard-2": 0.08448,
    "n2d-standard-4": 0.16896,
    "n2d-standard-8": 0.33791,
    # F1/G1 shared-core
    "f1-micro": 0.0076,
    "g1-small": 0.0257,
}

# Rough per-vCPU rate for unknown machine types (~E2 standard pricing)
_FALLBACK_PER_VCPU = 0.033

# ---- Bigtable pricing ----

BIGTABLE_NODE_HOURLY = 0.65

# ---- Storage pricing ----

STORAGE_MONTHLY_PER_GB: dict[str, float] = {
    "STANDARD": 0.020,
    "NEARLINE": 0.010,
    "COLDLINE": 0.004,
    "ARCHIVE": 0.0012,
    "MULTI_REGIONAL": 0.026,
    "REGIONAL": 0.020,
}


class PricingClient:
    """Estimate GCP resource costs from pricing lookup tables."""

    def get_vm_hourly_cost(self, machine_type: str, zone: str) -> float:
        """Get hourly cost for a VM machine type.

        Args:
            machine_type: e.g. "e2-standard-2", "n2-highmem-8".
            zone: e.g. "us-central1-a" (currently unused; prices are Iowa-based).

        Returns:
            Estimated hourly cost in USD.
        """
        cost = VM_HOURLY.get(machine_type)
        if cost is not None:
            return cost

        # For unknown types, estimate based on vCPU count from name
        parts = machine_type.rsplit("-", 1)
        if len(parts) == 2 and parts[1].isdigit():
            vcpus = int(parts[1])
            return vcpus * _FALLBACK_PER_VCPU
        return 0.10  # Default fallback

    def get_bigtable_node_hourly_cost(self, region: str) -> float:
        """Get hourly cost per Bigtable node."""
        return BIGTABLE_NODE_HOURLY

    def get_storage_monthly_cost_per_gb(
        self, storage_class: str, region: str
    ) -> float:
        """Get monthly cost per GB for a storage class."""
        return STORAGE_MONTHLY_PER_GB.get(storage_class, 0.020)

    def estimate_yearly_cost(self, resource: IdleResource) -> float:
        """Calculate estimated yearly cost for a resource."""
        if resource.resource_type == ResourceType.COMPUTE_VM:
            machine_type = resource.metadata.get("machine_type", "")
            zone = resource.location
            hourly = self.get_vm_hourly_cost(machine_type, zone)
            return hourly * HOURS_PER_MONTH * 12

        elif resource.resource_type == ResourceType.BIGTABLE:
            node_count = int(resource.metadata.get("node_count", "1"))
            region = resource.location
            hourly = self.get_bigtable_node_hourly_cost(region)
            return node_count * hourly * HOURS_PER_MONTH * 12

        elif resource.resource_type == ResourceType.STORAGE:
            storage_gb = float(resource.metadata.get("size_gb", "0"))
            storage_class = resource.metadata.get("storage_class", "STANDARD")
            region = resource.location
            per_gb = self.get_storage_monthly_cost_per_gb(storage_class, region)
            return storage_gb * per_gb * 12

        return 0.0
