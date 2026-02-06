"""Tests for Compute Engine VM checker."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from waste.checkers.compute import ComputeChecker
from waste.config import WasteConfig
from waste.criteria import build_criteria_group
from waste.models import ResourceType


def _make_instance(name, status="RUNNING", machine_type="e2-standard-2",
                   creation_timestamp="2024-01-01T00:00:00Z",
                   last_start_timestamp="2024-06-01T00:00:00Z",
                   instance_id=12345):
    instance = MagicMock()
    instance.name = name
    instance.status = status
    instance.id = instance_id
    instance.machine_type = machine_type
    instance.creation_timestamp = creation_timestamp
    instance.last_start_timestamp = last_start_timestamp
    return instance


class TestComputeChecker:
    @pytest.fixture
    def checker(self, sample_config, mock_monitoring_client, mock_pricing_client):
        criteria_group = build_criteria_group(
            sample_config.thresholds.compute.criteria,
            mode=sample_config.thresholds.compute.criteria_mode,
        )
        with patch("waste.checkers.compute.compute_v1.InstancesClient"):
            return ComputeChecker(
                project="test-project",
                config=sample_config,
                monitoring=mock_monitoring_client,
                pricing=mock_pricing_client,
                criteria_group=criteria_group,
                idle_days=7,
                min_age_days=7,
            )

    def _set_instances(self, checker, instances, zone="zones/us-east1-b"):
        scoped = MagicMock()
        scoped.instances = instances
        checker._compute_client.aggregated_list.return_value = [(zone, scoped)]

    def test_list_resources_filters_running(self, checker):
        running = _make_instance("running-vm", status="RUNNING",
                                 machine_type="zones/us-east1-b/machineTypes/e2-standard-2")
        stopped = _make_instance("stopped-vm", status="TERMINATED")

        self._set_instances(checker, [running, stopped])

        resources = checker.list_resources()
        assert len(resources) == 1
        assert resources[0]["name"] == "running-vm"
        assert resources[0]["location"] == "us-east1-b"
        assert resources[0]["machine_type"] == "e2-standard-2"

    def test_check_idle_vm(self, checker, mock_monitoring_client):
        instance = _make_instance("idle-vm")
        self._set_instances(checker, [instance])

        # Return low metrics
        mock_monitoring_client.query_mean.return_value = 0.02  # 2% CPU
        mock_monitoring_client.query_sum.return_value = 100.0  # 100 bytes total

        idle = checker.check()
        assert len(idle) == 1
        assert idle[0].resource_type == ResourceType.COMPUTE_VM
        assert idle[0].name == "idle-vm"
        assert idle[0].estimated_yearly_cost is not None

    def test_check_active_vm_not_idle(self, checker, mock_monitoring_client):
        instance = _make_instance("active-vm")
        self._set_instances(checker, [instance])

        # Return high metrics
        mock_monitoring_client.query_mean.return_value = 0.50  # 50% CPU
        mock_monitoring_client.query_sum.return_value = 1_000_000_000.0  # lots of bytes

        idle = checker.check()
        assert len(idle) == 0

    def test_blocklisted_vm_skipped(self, mock_monitoring_client, mock_pricing_client):
        config = WasteConfig(
            blocklist={"test-project": {"compute": ["skip-me-*"]}}
        )
        criteria_group = build_criteria_group(
            config.thresholds.compute.criteria,
            mode=config.thresholds.compute.criteria_mode,
        )
        with patch("waste.checkers.compute.compute_v1.InstancesClient"):
            checker = ComputeChecker(
                project="test-project",
                config=config,
                monitoring=mock_monitoring_client,
                pricing=mock_pricing_client,
                criteria_group=criteria_group,
                idle_days=7,
            )

        instance = _make_instance("skip-me-123")
        self._set_instances(checker, [instance])

        mock_monitoring_client.query_mean.return_value = 0.01
        mock_monitoring_client.query_sum.return_value = 0.0

        idle = checker.check()
        assert len(idle) == 0
