"""Tests for network criterion."""

from __future__ import annotations

import pytest

from waste.config import CriterionConfig
from waste.criteria.network import LowNetworkCriterion


class TestLowNetworkCriterion:
    def test_idle_below_threshold(self):
        criterion = LowNetworkCriterion(threshold_bytes_per_second=1000.0)
        result = criterion.evaluate(None, {"network_bytes_per_second": 100.0})
        assert result.is_idle is True
        assert "100 B/s" in result.reason

    def test_not_idle_above_threshold(self):
        criterion = LowNetworkCriterion(threshold_bytes_per_second=1000.0)
        result = criterion.evaluate(None, {"network_bytes_per_second": 5000.0})
        assert result.is_idle is False

    def test_no_data_not_idle(self):
        criterion = LowNetworkCriterion(threshold_bytes_per_second=1000.0)
        result = criterion.evaluate(None, {})
        assert result.is_idle is False
        assert "unavailable" in result.reason

    def test_from_config(self):
        config = CriterionConfig(type="low_network", threshold_bytes_per_second=500.0)
        criterion = LowNetworkCriterion.from_config(config)
        assert criterion.threshold_bytes_per_second == 500.0

    def test_zero_traffic_is_idle(self):
        criterion = LowNetworkCriterion(threshold_bytes_per_second=1000.0)
        result = criterion.evaluate(None, {"network_bytes_per_second": 0.0})
        assert result.is_idle is True
