"""Tests for Cloud Storage bucket checker."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from waste.checkers.storage import StorageChecker
from waste.criteria import build_criteria_group
from waste.models import ResourceType


def _make_bucket(name, location="US", storage_class="STANDARD",
                 time_created=None):
    bucket = MagicMock()
    bucket.name = name
    bucket.location = location
    bucket.storage_class = storage_class
    bucket.time_created = time_created or datetime(2024, 1, 1, tzinfo=timezone.utc)
    return bucket


class TestStorageChecker:
    @pytest.fixture
    def checker(self, sample_config, mock_monitoring_client, mock_pricing_client):
        criteria_group = build_criteria_group(
            sample_config.thresholds.storage.criteria,
            mode=sample_config.thresholds.storage.criteria_mode,
        )
        with patch("waste.checkers.storage.storage.Client"):
            return StorageChecker(
                project="test-project",
                config=sample_config,
                monitoring=mock_monitoring_client,
                pricing=mock_pricing_client,
                criteria_group=criteria_group,
                idle_days=7,
                min_size_gb=sample_config.thresholds.storage.min_size_gb,
            )

    def test_list_resources(self, checker):
        bucket = _make_bucket("my-bucket")
        checker._storage_client.list_buckets.return_value = [bucket]

        resources = checker.list_resources()
        assert len(resources) == 1
        assert resources[0]["name"] == "my-bucket"
        assert resources[0]["location"] == "US"
        assert resources[0]["storage_class"] == "STANDARD"

    def test_check_idle_bucket(self, checker, mock_monitoring_client):
        bucket = _make_bucket("idle-bucket")
        checker._storage_client.list_buckets.return_value = [bucket]

        # Low egress and large bucket
        mock_monitoring_client.query_rate.return_value = 0.1  # Very low egress (B/s)
        mock_monitoring_client.query_mean.return_value = 10 * 1024**3  # 10 GB

        idle = checker.check()
        assert len(idle) == 1
        assert idle[0].resource_type == ResourceType.STORAGE
        assert idle[0].name == "idle-bucket"

    def test_check_active_bucket_not_idle(self, checker, mock_monitoring_client):
        bucket = _make_bucket("active-bucket")
        checker._storage_client.list_buckets.return_value = [bucket]

        # High egress
        mock_monitoring_client.query_rate.return_value = 50000.0  # High egress (B/s)
        mock_monitoring_client.query_mean.return_value = 10 * 1024**3

        idle = checker.check()
        assert len(idle) == 0

    def test_small_bucket_skipped(self, checker, mock_monitoring_client):
        bucket = _make_bucket("tiny-bucket")
        checker._storage_client.list_buckets.return_value = [bucket]

        # Low egress but small bucket
        mock_monitoring_client.query_rate.return_value = 0.0
        mock_monitoring_client.query_mean.return_value = 0.5 * 1024**3  # 0.5 GB < 1.0 threshold

        idle = checker.check()
        assert len(idle) == 0
