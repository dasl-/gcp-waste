"""Tests for pricing module."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from waste.models import IdleResource, ResourceType
from waste.pricing import (
    BIGTABLE_NODE_HOURLY,
    DISK_IOPS_MONTHLY,
    DISK_MONTHLY_PER_GB,
    DISK_THROUGHPUT_MONTHLY,
    HOURS_PER_MONTH,
    STORAGE_MONTHLY_PER_GB,
    VM_HOURLY,
    LookupPricingBackend,
    PricingBackend,
    PricingClient,
    create_pricing_backend,
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


class TestPricingClientDisk:
    @pytest.fixture
    def client(self):
        return PricingClient()

    def test_pd_standard(self, client):
        cost = client.get_disk_monthly_cost("pd-standard", 100)
        assert cost == pytest.approx(100 * 0.04)

    def test_pd_ssd(self, client):
        cost = client.get_disk_monthly_cost("pd-ssd", 200)
        assert cost == pytest.approx(200 * 0.17)

    def test_pd_extreme_with_iops(self, client):
        cost = client.get_disk_monthly_cost("pd-extreme", 500, provisioned_iops=10000)
        assert cost == pytest.approx(500 * 0.125 + 10000 * 0.01)

    def test_hyperdisk_balanced_full(self, client):
        cost = client.get_disk_monthly_cost(
            "hyperdisk-balanced", 100, provisioned_iops=3000, provisioned_throughput=140,
        )
        assert cost == pytest.approx(100 * 0.10 + 3000 * 0.006 + 140 * 0.06)

    def test_hyperdisk_throughput(self, client):
        cost = client.get_disk_monthly_cost(
            "hyperdisk-throughput", 2048, provisioned_throughput=250,
        )
        assert cost == pytest.approx(2048 * 0.06 + 250 * 0.048)

    def test_unknown_type_defaults(self, client):
        cost = client.get_disk_monthly_cost("unknown-type", 100)
        assert cost == pytest.approx(100 * 0.04)


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

    def test_persistent_disk_standard(self, client):
        resource = IdleResource(
            resource_type=ResourceType.PERSISTENT_DISK,
            name="disk-1",
            project="test",
            location="us-central1-a",
            metadata={
                "disk_type": "pd-standard",
                "size_gb": "500",
                "provisioned_iops": "0",
                "provisioned_throughput": "0",
            },
        )
        cost = client.estimate_yearly_cost(resource)
        assert cost == pytest.approx(500 * DISK_MONTHLY_PER_GB["pd-standard"] * 12)

    def test_persistent_disk_with_iops(self, client):
        resource = IdleResource(
            resource_type=ResourceType.PERSISTENT_DISK,
            name="disk-2",
            project="test",
            location="us-central1-a",
            metadata={
                "disk_type": "pd-extreme",
                "size_gb": "1000",
                "provisioned_iops": "15000",
                "provisioned_throughput": "0",
            },
        )
        cost = client.estimate_yearly_cost(resource)
        expected_monthly = (
            1000 * DISK_MONTHLY_PER_GB["pd-extreme"]
            + 15000 * DISK_IOPS_MONTHLY["pd-extreme"]
        )
        assert cost == pytest.approx(expected_monthly * 12)

    def test_persistent_disk_with_throughput(self, client):
        resource = IdleResource(
            resource_type=ResourceType.PERSISTENT_DISK,
            name="disk-3",
            project="test",
            location="us-central1-a",
            metadata={
                "disk_type": "hyperdisk-throughput",
                "size_gb": "2048",
                "provisioned_iops": "0",
                "provisioned_throughput": "140",
            },
        )
        cost = client.estimate_yearly_cost(resource)
        expected_monthly = (
            2048 * DISK_MONTHLY_PER_GB["hyperdisk-throughput"]
            + 140 * DISK_THROUGHPUT_MONTHLY["hyperdisk-throughput"]
        )
        assert cost == pytest.approx(expected_monthly * 12)

    def test_persistent_disk_with_iops_and_throughput(self, client):
        resource = IdleResource(
            resource_type=ResourceType.PERSISTENT_DISK,
            name="disk-4",
            project="test",
            location="us-central1-a",
            metadata={
                "disk_type": "hyperdisk-balanced",
                "size_gb": "100",
                "provisioned_iops": "3000",
                "provisioned_throughput": "140",
            },
        )
        cost = client.estimate_yearly_cost(resource)
        expected_monthly = (
            100 * DISK_MONTHLY_PER_GB["hyperdisk-balanced"]
            + 3000 * DISK_IOPS_MONTHLY["hyperdisk-balanced"]
            + 140 * DISK_THROUGHPUT_MONTHLY["hyperdisk-balanced"]
        )
        assert cost == pytest.approx(expected_monthly * 12)


class TestPricingBackend:
    def test_lookup_is_pricing_backend_subclass(self):
        assert issubclass(LookupPricingBackend, PricingBackend)

    def test_pricing_client_alias(self):
        assert PricingClient is LookupPricingBackend

    def test_default_enrich_calls_estimate_per_resource(self):
        backend = LookupPricingBackend()
        resources = [
            IdleResource(
                resource_type=ResourceType.COMPUTE_VM,
                name="vm-1",
                project="test",
                location="us-central1-a",
                metadata={"machine_type": "e2-standard-2", "instance_id": "123"},
            ),
            IdleResource(
                resource_type=ResourceType.STORAGE,
                name="bucket-1",
                project="test",
                location="US",
                metadata={"storage_class": "STANDARD", "size_gb": "100"},
            ),
        ]
        for r in resources:
            r.estimated_yearly_cost = None

        backend.enrich(resources)

        assert resources[0].estimated_yearly_cost == pytest.approx(
            0.06701 * HOURS_PER_MONTH * 12
        )
        assert resources[1].estimated_yearly_cost == pytest.approx(
            100 * STORAGE_MONTHLY_PER_GB["STANDARD"] * 12
        )


class TestCreatePricingBackend:
    def test_lookup(self):
        backend = create_pricing_backend("lookup")
        assert isinstance(backend, LookupPricingBackend)

    def test_invalid_name_raises(self):
        with pytest.raises(ValueError, match="Invalid pricing backend"):
            create_pricing_backend("nonexistent")

    def test_dotted_path_with_mock_backend(self):
        backend = create_pricing_backend("waste.pricing.LookupPricingBackend")
        assert isinstance(backend, LookupPricingBackend)

    def test_dotted_path_missing_module(self):
        with pytest.raises(ValueError, match="Cannot import module"):
            create_pricing_backend("nonexistent.module.Backend")

    def test_dotted_path_missing_class(self):
        with pytest.raises(ValueError, match="has no attribute"):
            create_pricing_backend("waste.pricing.NoSuchClass")

    def test_dotted_path_not_subclass(self):
        with pytest.raises(ValueError, match="not a PricingBackend subclass"):
            create_pricing_backend("waste.pricing.HOURS_PER_MONTH")

    def test_bigquery_requires_table(self):
        with pytest.raises(ValueError, match="requires a billing table"):
            create_pricing_backend("bigquery")

    def test_bigquery_with_table(self):
        with patch("waste.bigquery_pricing.bigquery") as mock_bq:
            mock_bq.Client.return_value = MagicMock()
            backend = create_pricing_backend(
                "bigquery",
                bigquery_billing_table="my-project.my_dataset.gcp_billing_export_resource_v1_AAAAAA_BBBBBB_CCCCCC",
            )
            assert isinstance(backend, PricingBackend)
