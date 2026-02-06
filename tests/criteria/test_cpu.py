"""Tests for CPU criterion."""

from __future__ import annotations

import pytest

from waste.config import CriterionConfig
from waste.criteria.cpu import LowCPUCriterion


class TestLowCPUCriterion:
    def test_idle_below_threshold(self):
        criterion = LowCPUCriterion(threshold_percent=5.0)
        result = criterion.evaluate(None, {"cpu_utilization_percent": 2.0})
        assert result.is_idle is True
        assert "2.0%" in result.reason
        assert result.metrics["cpu_utilization_percent"] == 2.0

    def test_not_idle_above_threshold(self):
        criterion = LowCPUCriterion(threshold_percent=5.0)
        result = criterion.evaluate(None, {"cpu_utilization_percent": 10.0})
        assert result.is_idle is False

    def test_not_idle_at_threshold(self):
        criterion = LowCPUCriterion(threshold_percent=5.0)
        result = criterion.evaluate(None, {"cpu_utilization_percent": 5.0})
        assert result.is_idle is False

    def test_no_data_not_idle(self):
        criterion = LowCPUCriterion(threshold_percent=5.0)
        result = criterion.evaluate(None, {})
        assert result.is_idle is False
        assert "unavailable" in result.reason

    def test_from_config(self):
        config = CriterionConfig(type="low_cpu", threshold_percent=10.0)
        criterion = LowCPUCriterion.from_config(config)
        assert criterion.threshold_percent == 10.0

    def test_from_config_default(self):
        config = CriterionConfig(type="low_cpu")
        criterion = LowCPUCriterion.from_config(config)
        assert criterion.threshold_percent == 5.0

    def test_criterion_name(self):
        criterion = LowCPUCriterion()
        result = criterion.evaluate(None, {"cpu_utilization_percent": 1.0})
        assert result.criterion_name == "low_cpu"
