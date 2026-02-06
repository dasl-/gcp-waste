"""Tests for Persistent Disk checker."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from waste.checkers.persistent_disk import PersistentDiskChecker
from waste.config import WasteConfig
from waste.criteria import build_criteria_group
from waste.models import ResourceType


def _make_disk(name, status="READY", disk_type="pd-ssd", size_gb=100,
               creation_timestamp="2024-01-01T00:00:00Z",
               users=None, provisioned_iops=0, provisioned_throughput=0):
    disk = MagicMock()
    disk.name = name
    disk.status = status
    disk.type_ = disk_type
    disk.size_gb = size_gb
    disk.creation_timestamp = creation_timestamp
    disk.users = users or []
    disk.provisioned_iops = provisioned_iops
    disk.provisioned_throughput = provisioned_throughput
    return disk


class TestPersistentDiskChecker:
    @pytest.fixture
    def checker(self, sample_config, mock_monitoring_client, mock_pricing_client):
        criteria_group = build_criteria_group(
            sample_config.thresholds.persistent_disk.criteria,
            mode=sample_config.thresholds.persistent_disk.criteria_mode,
        )
        with patch("waste.checkers.persistent_disk.compute_v1.DisksClient"):
            return PersistentDiskChecker(
                project="test-project",
                config=sample_config,
                monitoring=mock_monitoring_client,
                pricing=mock_pricing_client,
                criteria_group=criteria_group,
                idle_days=7,
                min_age_days=7,
            )

    def _set_disks(self, checker, disks, zone="zones/us-central1-a"):
        scoped = MagicMock()
        scoped.disks = disks
        checker._disks_client.aggregated_list.return_value = [(zone, scoped)]

    def test_list_resources_filters_ready(self, checker):
        ready = _make_disk("ready-disk", status="READY",
                           disk_type="zones/us-central1-a/diskTypes/pd-ssd")
        creating = _make_disk("creating-disk", status="CREATING")

        self._set_disks(checker, [ready, creating])

        resources = checker.list_resources()
        assert len(resources) == 1
        assert resources[0]["name"] == "ready-disk"
        assert resources[0]["location"] == "us-central1-a"
        assert resources[0]["disk_type"] == "pd-ssd"

    def test_check_idle_disk_no_reads(self, checker, mock_monitoring_client):
        """Disk with no read data should be idle."""
        disk = _make_disk("idle-disk")
        self._set_disks(checker, [disk])

        # No data returned → idle
        mock_monitoring_client.query_sum.return_value = None

        idle = checker.check()
        assert len(idle) == 1
        assert idle[0].resource_type == ResourceType.PERSISTENT_DISK
        assert idle[0].name == "idle-disk"
        assert idle[0].estimated_yearly_cost is not None

    def test_check_idle_disk_low_reads(self, checker, mock_monitoring_client):
        """Disk with low read throughput should be idle."""
        disk = _make_disk("low-read-disk")
        self._set_disks(checker, [disk])

        # Return low bytes (100 bytes over 7 days = ~0.00017 B/s)
        mock_monitoring_client.query_sum.return_value = 100.0

        idle = checker.check()
        assert len(idle) == 1
        assert idle[0].name == "low-read-disk"

    def test_check_active_disk_not_idle(self, checker, mock_monitoring_client):
        """Disk with high read throughput should not be idle."""
        disk = _make_disk("active-disk")
        self._set_disks(checker, [disk])

        # Return high bytes (10GB over 7 days = ~16.5 KB/s)
        mock_monitoring_client.query_sum.return_value = 10_000_000_000.0

        idle = checker.check()
        assert len(idle) == 0

    def test_blocklisted_disk_skipped(self, mock_monitoring_client, mock_pricing_client):
        config = WasteConfig(
            blocklist={"test-project": {"persistent_disk": ["skip-me-*"]}}
        )
        criteria_group = build_criteria_group(
            config.thresholds.persistent_disk.criteria,
            mode=config.thresholds.persistent_disk.criteria_mode,
        )
        with patch("waste.checkers.persistent_disk.compute_v1.DisksClient"):
            checker = PersistentDiskChecker(
                project="test-project",
                config=config,
                monitoring=mock_monitoring_client,
                pricing=mock_pricing_client,
                criteria_group=criteria_group,
                idle_days=7,
            )

        disk = _make_disk("skip-me-123")
        self._set_disks(checker, [disk])

        mock_monitoring_client.query_sum.return_value = None

        idle = checker.check()
        assert len(idle) == 0

    def test_metadata_includes_disk_info(self, checker, mock_monitoring_client):
        """Metadata should include disk type, size, users, and provisioned resources."""
        disk = _make_disk(
            "info-disk",
            disk_type="pd-extreme",
            size_gb=500,
            users=["projects/p/zones/z/instances/vm-1"],
            provisioned_iops=15000,
            provisioned_throughput=0,
        )
        self._set_disks(checker, [disk])
        mock_monitoring_client.query_sum.return_value = None

        idle = checker.check()
        assert len(idle) == 1
        assert idle[0].metadata["disk_type"] == "pd-extreme"
        assert idle[0].metadata["size_gb"] == "500"
        assert idle[0].metadata["users"] == "1"
        assert idle[0].metadata["provisioned_iops"] == "15000"
        assert idle[0].metadata["provisioned_throughput"] == "0"
