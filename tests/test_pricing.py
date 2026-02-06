"""Tests for pricing module."""

from __future__ import annotations

import pytest

from waste.models import IdleResource, ResourceType
from waste.pricing import (
    BIGTABLE_NODE_HOURLY,
    HOURS_PER_MONTH,
    STORAGE_MONTHLY_PER_GB,
    VM_HOURLY,
    PricingClient,
)


class TestPricingClientVM:
    @pytest.fixture
    def client(self):
        return PricingClient()

    def test_shared_core_e2_micro(self, client):
        cost = client.get_vm_hourly_cost("e2-micro", "us-central1-a")
        assert cost == pytest.approx(0.00838)

    def test_shared_core_e2_small(self, client):
        cost = client.get_vm_hourly_cost("e2-small", "us-central1-a")
        assert cost == pytest.approx(0.01675)

    def test_shared_core_e2_medium(self, client):
        cost = client.get_vm_hourly_cost("e2-medium", "us-central1-a")
        assert cost == pytest.approx(0.03351)

    def test_e2_standard_2(self, client):
        cost = client.get_vm_hourly_cost("e2-standard-2", "us-central1-a")
        assert cost == pytest.approx(0.06701)

    def test_n1_standard_8(self, client):
        cost = client.get_vm_hourly_cost("n1-standard-8", "us-central1-a")
        assert cost == pytest.approx(0.37990)

    def test_n2_standard_2(self, client):
        cost = client.get_vm_hourly_cost("n2-standard-2", "us-central1-a")
        assert cost == pytest.approx(0.09712)

    def test_n2_standard_16(self, client):
        cost = client.get_vm_hourly_cost("n2-standard-16", "us-central1-a")
        assert cost == pytest.approx(0.77696)

    def test_n2d_standard_8(self, client):
        cost = client.get_vm_hourly_cost("n2d-standard-8", "us-central1-a")
        assert cost == pytest.approx(0.33791)

    def test_known_types_match_table(self, client):
        """Every entry in VM_HOURLY should be returned exactly."""
        for machine_type, expected in VM_HOURLY.items():
            cost = client.get_vm_hourly_cost(machine_type, "us-central1-a")
            assert cost == pytest.approx(expected), f"Mismatch for {machine_type}"

    def test_unknown_type_uses_vcpu_fallback(self, client):
        cost = client.get_vm_hourly_cost("n2-highmem-8", "us-central1-a")
        assert cost == pytest.approx(8 * 0.033)

    def test_unknown_family_uses_vcpu_fallback(self, client):
        cost = client.get_vm_hourly_cost("z99-standard-4", "us-central1-a")
        assert cost == pytest.approx(4 * 0.033)

    def test_completely_unknown_type(self, client):
        cost = client.get_vm_hourly_cost("custom-machine", "us-central1-a")
        assert cost == pytest.approx(0.10)


class TestPricingClientBigtable:
    def test_node_cost(self):
        client = PricingClient()
        cost = client.get_bigtable_node_hourly_cost("us-central1")
        assert cost == BIGTABLE_NODE_HOURLY


class TestPricingClientStorage:
    @pytest.fixture
    def client(self):
        return PricingClient()

    def test_standard(self, client):
        cost = client.get_storage_monthly_cost_per_gb("STANDARD", "US")
        assert cost == STORAGE_MONTHLY_PER_GB["STANDARD"]

    def test_nearline(self, client):
        cost = client.get_storage_monthly_cost_per_gb("NEARLINE", "US")
        assert cost == STORAGE_MONTHLY_PER_GB["NEARLINE"]

    def test_coldline(self, client):
        cost = client.get_storage_monthly_cost_per_gb("COLDLINE", "US")
        assert cost == STORAGE_MONTHLY_PER_GB["COLDLINE"]

    def test_archive(self, client):
        cost = client.get_storage_monthly_cost_per_gb("ARCHIVE", "US")
        assert cost == STORAGE_MONTHLY_PER_GB["ARCHIVE"]

    def test_unknown_class_defaults(self, client):
        cost = client.get_storage_monthly_cost_per_gb("UNKNOWN", "US")
        assert cost == 0.020


class TestEstimateYearlyCost:
    @pytest.fixture
    def client(self):
        return PricingClient()

    def test_compute_vm(self, client):
        resource = IdleResource(
            resource_type=ResourceType.COMPUTE_VM,
            name="test-vm",
            project="test",
            location="us-central1-a",
            metadata={"machine_type": "e2-standard-2", "instance_id": "123"},
        )
        cost = client.estimate_yearly_cost(resource)
        assert cost == pytest.approx(0.06701 * HOURS_PER_MONTH * 12)

    def test_bigtable(self, client):
        resource = IdleResource(
            resource_type=ResourceType.BIGTABLE,
            name="instance/cluster",
            project="test",
            location="us-central1-b",
            metadata={"node_count": "3", "instance_id": "i", "cluster_id": "c"},
        )
        cost = client.estimate_yearly_cost(resource)
        assert cost == pytest.approx(3 * BIGTABLE_NODE_HOURLY * HOURS_PER_MONTH * 12)

    def test_storage(self, client):
        resource = IdleResource(
            resource_type=ResourceType.STORAGE,
            name="bucket",
            project="test",
            location="US",
            metadata={"storage_class": "STANDARD", "size_gb": "100"},
        )
        cost = client.estimate_yearly_cost(resource)
        assert cost == pytest.approx(100 * STORAGE_MONTHLY_PER_GB["STANDARD"] * 12)
