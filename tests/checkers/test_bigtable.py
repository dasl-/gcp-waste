"""Tests for Bigtable cluster checker."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from waste.checkers.bigtable import BigtableChecker
from waste.criteria import build_criteria_group
from waste.models import ResourceType


class TestBigtableChecker:
    @pytest.fixture
    def checker(self, sample_config, mock_monitoring_client, mock_pricing_client):
        criteria_group = build_criteria_group(
            sample_config.thresholds.bigtable.criteria,
            mode=sample_config.thresholds.bigtable.criteria_mode,
        )
        with patch("waste.checkers.bigtable.bigtable.Client"):
            return BigtableChecker(
                project="test-project",
                config=sample_config,
                monitoring=mock_monitoring_client,
                pricing=mock_pricing_client,
                criteria_group=criteria_group,
                idle_days=7,
            )

    def test_list_resources(self, checker):
        cluster = MagicMock()
        cluster.cluster_id = "cluster-0"
        cluster.location = "projects/test/locations/us-central1-b"
        cluster.serve_nodes = 3

        instance = MagicMock()
        instance.instance_id = "my-instance"
        instance.list_clusters.return_value = ([cluster], [])

        checker._bigtable_client.list_instances.return_value = ([instance], [])

        resources = checker.list_resources()
        assert len(resources) == 1
        assert resources[0]["name"] == "my-instance/cluster-0"
        assert resources[0]["node_count"] == 3
        assert resources[0]["location"] == "us-central1-b"

    def test_check_idle_cluster(self, checker, mock_monitoring_client):
        cluster = MagicMock()
        cluster.cluster_id = "cluster-0"
        cluster.location = "us-central1-b"
        cluster.serve_nodes = 3

        instance = MagicMock()
        instance.instance_id = "idle-instance"
        instance.list_clusters.return_value = ([cluster], [])

        checker._bigtable_client.list_instances.return_value = ([instance], [])

        mock_monitoring_client.query_rate.return_value = 0.1  # Very low RPS

        idle = checker.check()
        assert len(idle) == 1
        assert idle[0].resource_type == ResourceType.BIGTABLE
        assert idle[0].name == "idle-instance/cluster-0"
        assert idle[0].estimated_yearly_cost is not None

    def test_check_active_cluster_not_idle(self, checker, mock_monitoring_client):
        cluster = MagicMock()
        cluster.cluster_id = "cluster-0"
        cluster.location = "us-central1-b"
        cluster.serve_nodes = 3

        instance = MagicMock()
        instance.instance_id = "active-instance"
        instance.list_clusters.return_value = ([cluster], [])

        checker._bigtable_client.list_instances.return_value = ([instance], [])

        mock_monitoring_client.query_rate.return_value = 100.0  # High RPS

        idle = checker.check()
        assert len(idle) == 0
