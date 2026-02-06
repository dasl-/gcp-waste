"""Shared test fixtures."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

from waste.config import WasteConfig, load_config
from waste.criteria import build_criteria_group
from waste.criteria.base import CriteriaGroup
from waste.models import IdleResource, ResourceType
from waste.monitoring import MonitoringClient
from waste.pricing import PricingClient


@pytest.fixture
def sample_config() -> WasteConfig:
    """Sample configuration for tests."""
    return WasteConfig()


@pytest.fixture
def mock_monitoring_client() -> MagicMock:
    """Mock Cloud Monitoring client with configurable responses."""
    client = MagicMock(spec=MonitoringClient)
    client.project = "test-project"
    client.query_mean.return_value = None
    client.query_sum.return_value = None
    client.query_rate.return_value = None
    return client


@pytest.fixture
def mock_pricing_client() -> PricingClient:
    """Pricing client using hardcoded rates (no API calls)."""
    return PricingClient()


@pytest.fixture
def sample_vm_resource() -> IdleResource:
    """Sample idle VM resource."""
    return IdleResource(
        resource_type=ResourceType.COMPUTE_VM,
        name="dev-server-1",
        project="test-project",
        location="us-east1-b",
        creation_time=datetime(2024, 1, 1, tzinfo=timezone.utc),
        metadata={"machine_type": "e2-standard-2", "instance_id": "12345"},
    )


@pytest.fixture
def sample_bigtable_resource() -> IdleResource:
    """Sample idle Bigtable resource."""
    return IdleResource(
        resource_type=ResourceType.BIGTABLE,
        name="test-instance/cluster-1",
        project="test-project",
        location="us-central1-b",
        metadata={"node_count": "3", "instance_id": "test-instance", "cluster_id": "cluster-1"},
    )


@pytest.fixture
def sample_storage_resource() -> IdleResource:
    """Sample idle storage resource."""
    return IdleResource(
        resource_type=ResourceType.STORAGE,
        name="old-logs-bucket",
        project="test-project",
        location="US",
        metadata={"storage_class": "STANDARD", "size_gb": "500"},
    )


@pytest.fixture
def compute_criteria_group(sample_config) -> CriteriaGroup:
    """Criteria group for compute VMs."""
    return build_criteria_group(
        sample_config.thresholds.compute.criteria,
        mode=sample_config.thresholds.compute.criteria_mode,
    )


@pytest.fixture
def bigtable_criteria_group(sample_config) -> CriteriaGroup:
    """Criteria group for Bigtable."""
    return build_criteria_group(
        sample_config.thresholds.bigtable.criteria,
        mode=sample_config.thresholds.bigtable.criteria_mode,
    )


@pytest.fixture
def storage_criteria_group(sample_config) -> CriteriaGroup:
    """Criteria group for storage."""
    return build_criteria_group(
        sample_config.thresholds.storage.criteria,
        mode=sample_config.thresholds.storage.criteria_mode,
    )
