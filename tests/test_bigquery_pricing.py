"""Tests for BigQuery pricing backend."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from waste.models import IdleResource, ResourceType
from waste.pricing import PricingBackend


class TestBigQueryPricingBackend:
    @pytest.fixture
    def backend(self):
        with patch("waste.bigquery_pricing.bigquery") as mock_bq:
            mock_bq.Client.return_value = MagicMock()
            mock_bq.QueryJobConfig = MagicMock()
            mock_bq.ArrayQueryParameter = MagicMock()
            from waste.bigquery_pricing import BigQueryPricingBackend

            return BigQueryPricingBackend(
                table="test-project.billing.gcp_billing_export_resource_v1_AAAAAA_BBBBBB_CCCCCC"
            )

    def test_is_pricing_backend(self):
        with patch("waste.bigquery_pricing.bigquery"):
            from waste.bigquery_pricing import BigQueryPricingBackend

            assert issubclass(BigQueryPricingBackend, PricingBackend)

    def test_estimate_yearly_cost_returns_none(self, backend):
        resource = IdleResource(
            resource_type=ResourceType.COMPUTE_VM,
            name="vm-1",
            project="test",
            location="us-central1-a",
            metadata={"machine_type": "e2-standard-2", "instance_id": "123"},
        )
        assert backend.estimate_yearly_cost(resource) is None

    def test_enrich_empty_list(self, backend):
        backend.enrich([])
        backend._bq_client.query.assert_not_called()

    def test_match_disk_by_name(self, backend):
        cost_by_global: dict[tuple[str, str], float] = {}
        cost_by_name = {("proj", "my-disk"): 100.0}
        resource = IdleResource(
            resource_type=ResourceType.PERSISTENT_DISK,
            name="my-disk",
            project="proj",
            location="us-central1-a",
            metadata={"disk_type": "pd-standard", "size_gb": "100"},
        )
        result = backend._match_cost(resource, cost_by_global, cost_by_name)
        assert result == 100.0

    def test_match_vm_by_global_name(self, backend):
        cost_by_global = {
            ("proj", "//compute.googleapis.com/projects/123/zones/us-central1-a/instances/12345"): 500.0,
        }
        cost_by_name: dict[tuple[str, str], float] = {}
        resource = IdleResource(
            resource_type=ResourceType.COMPUTE_VM,
            name="my-vm",
            project="proj",
            location="us-central1-a",
            metadata={"machine_type": "n2-highmem-48", "instance_id": "12345"},
        )
        result = backend._match_cost(resource, cost_by_global, cost_by_name)
        assert result == 500.0

    def test_match_bigtable_by_global_name(self, backend):
        cost_by_global = {
            ("proj", "//bigtable.googleapis.com/projects/proj/instances/my-bt"): 300.0,
        }
        cost_by_name: dict[tuple[str, str], float] = {}
        resource = IdleResource(
            resource_type=ResourceType.BIGTABLE,
            name="my-bt/cluster-1",
            project="proj",
            location="us-central1-b",
            metadata={"node_count": "3", "instance_id": "my-bt", "cluster_id": "cluster-1"},
        )
        result = backend._match_cost(resource, cost_by_global, cost_by_name)
        assert result == 300.0

    def test_match_cost_no_match(self, backend):
        cost_by_global: dict[tuple[str, str], float] = {}
        cost_by_name: dict[tuple[str, str], float] = {}
        resource = IdleResource(
            resource_type=ResourceType.COMPUTE_VM,
            name="vm-1",
            project="proj",
            location="us-central1-a",
            metadata={"machine_type": "e2-standard-2", "instance_id": "123"},
        )
        result = backend._match_cost(resource, cost_by_global, cost_by_name)
        assert result is None

    def test_enrich_with_results(self, backend):
        """Test that enrich() updates resources with BQ results."""
        mock_row = MagicMock()
        mock_row.project_id = "proj"
        mock_row.name = "my-bucket"
        mock_row.global_name = "//storage.googleapis.com/projects/_/buckets/my-bucket"
        mock_row.yearly_cost = 50.0

        mock_result = MagicMock()
        mock_result.__iter__ = lambda self: iter([mock_row])
        mock_result.total_rows = 1
        backend._bq_client.query.return_value.result.return_value = mock_result

        resources = [
            IdleResource(
                resource_type=ResourceType.STORAGE,
                name="my-bucket",
                project="proj",
                location="US",
                metadata={"storage_class": "STANDARD", "size_gb": "100"},
            ),
        ]

        backend.enrich(resources)

        assert resources[0].estimated_yearly_cost == 50.0

    def test_enrich_unmatched_uses_lookup_fallback(self, backend):
        """When BQ has no match, falls back to lookup pricing."""
        mock_result = MagicMock()
        mock_result.__iter__ = lambda self: iter([])
        mock_result.total_rows = 0
        backend._bq_client.query.return_value.result.return_value = mock_result

        resources = [
            IdleResource(
                resource_type=ResourceType.PERSISTENT_DISK,
                name="unmatched-disk",
                project="proj",
                location="us-central1-a",
                metadata={
                    "disk_type": "pd-ssd",
                    "size_gb": "100",
                    "provisioned_iops": "0",
                    "provisioned_throughput": "0",
                },
            ),
        ]

        backend.enrich(resources)

        assert resources[0].estimated_yearly_cost is not None
        assert resources[0].estimated_yearly_cost > 0

    def test_enrich_sums_multiple_global_names_for_same_name(self, backend):
        """Disk with multiple SKUs (different global_names) should sum costs."""
        row1 = MagicMock()
        row1.project_id = "proj"
        row1.name = "my-disk"
        row1.global_name = "//compute.googleapis.com/projects/123/zones/us-central1-a/disk/456"
        row1.yearly_cost = 100.0

        row2 = MagicMock()
        row2.project_id = "proj"
        row2.name = "my-disk"
        row2.global_name = "//compute.googleapis.com/projects/123/zones/us-central1-a/disk/456-iops"
        row2.yearly_cost = 50.0

        mock_result = MagicMock()
        mock_result.__iter__ = lambda self: iter([row1, row2])
        mock_result.total_rows = 2
        backend._bq_client.query.return_value.result.return_value = mock_result

        resources = [
            IdleResource(
                resource_type=ResourceType.PERSISTENT_DISK,
                name="my-disk",
                project="proj",
                location="us-central1-a",
                metadata={"disk_type": "pd-extreme", "size_gb": "500"},
            ),
        ]

        backend.enrich(resources)

        assert resources[0].estimated_yearly_cost == 150.0
