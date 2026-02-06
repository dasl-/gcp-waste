"""Tests for criteria composition (AND/OR logic)."""

from __future__ import annotations

import pytest

from waste.criteria.base import CriteriaGroup, parse_criteria_mode
from waste.criteria.cpu import LowCPUCriterion
from waste.criteria.network import LowNetworkCriterion
from waste.criteria import build_criteria_group
from waste.config import CriterionConfig


class TestCriteriaGroup:
    def test_all_mode_requires_all_idle(self):
        group = CriteriaGroup(
            criteria=[
                LowCPUCriterion(threshold_percent=5.0),
                LowNetworkCriterion(threshold_bytes_per_second=1000.0),
            ],
            mode="all",
        )
        metrics = {
            "cpu_utilization_percent": 2.0,
            "network_bytes_per_second": 100.0,
        }
        is_idle, results = group.evaluate(None, metrics)
        assert is_idle is True
        assert len(results) == 2
        assert all(r.is_idle for r in results)

    def test_all_mode_not_idle_if_one_active(self):
        group = CriteriaGroup(
            criteria=[
                LowCPUCriterion(threshold_percent=5.0),
                LowNetworkCriterion(threshold_bytes_per_second=1000.0),
            ],
            mode="all",
        )
        metrics = {
            "cpu_utilization_percent": 2.0,
            "network_bytes_per_second": 5000.0,  # Above threshold
        }
        is_idle, results = group.evaluate(None, metrics)
        assert is_idle is False

    def test_any_mode_idle_if_one_matches(self):
        group = CriteriaGroup(
            criteria=[
                LowCPUCriterion(threshold_percent=5.0),
                LowNetworkCriterion(threshold_bytes_per_second=1000.0),
            ],
            mode="any",
        )
        metrics = {
            "cpu_utilization_percent": 2.0,   # Below threshold
            "network_bytes_per_second": 5000.0,  # Above threshold
        }
        is_idle, results = group.evaluate(None, metrics)
        assert is_idle is True

    def test_any_mode_not_idle_if_none_match(self):
        group = CriteriaGroup(
            criteria=[
                LowCPUCriterion(threshold_percent=5.0),
                LowNetworkCriterion(threshold_bytes_per_second=1000.0),
            ],
            mode="any",
        )
        metrics = {
            "cpu_utilization_percent": 50.0,
            "network_bytes_per_second": 5000.0,
        }
        is_idle, results = group.evaluate(None, metrics)
        assert is_idle is False

    def test_empty_criteria_not_idle(self):
        group = CriteriaGroup(criteria=[], mode="all")
        is_idle, results = group.evaluate(None, {})
        assert is_idle is False
        assert results == []


class TestRequiredCriteria:
    """Tests for criteria_mode with explicit criterion lists."""

    def test_all_with_required_subset(self):
        """all(low_cpu) — only CPU must be idle, network is informational."""
        group = CriteriaGroup(
            criteria=[
                LowCPUCriterion(threshold_percent=5.0),
                LowNetworkCriterion(threshold_bytes_per_second=1000.0),
            ],
            mode="all",
            required_criteria={"low_cpu"},
        )
        metrics = {
            "cpu_utilization_percent": 2.0,       # idle
            "network_bytes_per_second": 5000.0,   # active — but not required
        }
        is_idle, results = group.evaluate(None, metrics)
        assert is_idle is True
        assert len(results) == 2  # both criteria still evaluated

    def test_all_with_required_subset_not_idle(self):
        """all(low_cpu) — required criterion is not met."""
        group = CriteriaGroup(
            criteria=[
                LowCPUCriterion(threshold_percent=5.0),
                LowNetworkCriterion(threshold_bytes_per_second=1000.0),
            ],
            mode="all",
            required_criteria={"low_cpu"},
        )
        metrics = {
            "cpu_utilization_percent": 50.0,      # active — required
            "network_bytes_per_second": 100.0,    # idle — but not required
        }
        is_idle, results = group.evaluate(None, metrics)
        assert is_idle is False

    def test_any_with_required_subset(self):
        """any(low_cpu, low_network) — either of the two must match."""
        group = CriteriaGroup(
            criteria=[
                LowCPUCriterion(threshold_percent=5.0),
                LowNetworkCriterion(threshold_bytes_per_second=1000.0),
            ],
            mode="any",
            required_criteria={"low_cpu", "low_network"},
        )
        metrics = {
            "cpu_utilization_percent": 2.0,       # idle
            "network_bytes_per_second": 5000.0,   # active
        }
        is_idle, results = group.evaluate(None, metrics)
        assert is_idle is True

    def test_required_criteria_no_match_returns_not_idle(self):
        """If no required criteria names match any evaluated criterion, not idle."""
        group = CriteriaGroup(
            criteria=[
                LowCPUCriterion(threshold_percent=5.0),
            ],
            mode="all",
            required_criteria={"nonexistent"},
        )
        metrics = {"cpu_utilization_percent": 2.0}
        is_idle, results = group.evaluate(None, metrics)
        assert is_idle is False
        assert len(results) == 1  # CPU still evaluated

    def test_all_required_must_all_match(self):
        """all(low_cpu, low_network) — both required criteria must be idle."""
        group = CriteriaGroup(
            criteria=[
                LowCPUCriterion(threshold_percent=5.0),
                LowNetworkCriterion(threshold_bytes_per_second=1000.0),
            ],
            mode="all",
            required_criteria={"low_cpu", "low_network"},
        )
        metrics = {
            "cpu_utilization_percent": 2.0,       # idle
            "network_bytes_per_second": 5000.0,   # active
        }
        is_idle, results = group.evaluate(None, metrics)
        assert is_idle is False


class TestParseCriteriaMode:
    def test_all(self):
        mode, required = parse_criteria_mode("all")
        assert mode == "all"
        assert required is None

    def test_any(self):
        mode, required = parse_criteria_mode("any")
        assert mode == "any"
        assert required is None

    def test_all_with_list(self):
        mode, required = parse_criteria_mode("all(low_cpu, low_network)")
        assert mode == "all"
        assert required == {"low_cpu", "low_network"}

    def test_any_with_list(self):
        mode, required = parse_criteria_mode("any(low_cpu, low_network)")
        assert mode == "any"
        assert required == {"low_cpu", "low_network"}

    def test_whitespace_tolerance(self):
        mode, required = parse_criteria_mode("  all( low_cpu , low_network )  ")
        assert mode == "all"
        assert required == {"low_cpu", "low_network"}

    def test_single_criterion(self):
        mode, required = parse_criteria_mode("all(low_cpu)")
        assert mode == "all"
        assert required == {"low_cpu"}

    def test_invalid_mode_raises(self):
        with pytest.raises(ValueError, match="Invalid criteria_mode"):
            parse_criteria_mode("invalid")

    def test_invalid_syntax_raises(self):
        with pytest.raises(ValueError, match="Invalid criteria_mode"):
            parse_criteria_mode("all[low_cpu]")


class TestBuildCriteriaGroup:
    def test_build_from_config(self):
        configs = [
            CriterionConfig(type="low_cpu", threshold_percent=10.0),
            CriterionConfig(type="low_network", threshold_bytes_per_second=500.0),
        ]
        group = build_criteria_group(configs, mode="all")
        assert len(group.criteria) == 2
        assert group.mode == "all"
        assert group.required_criteria is None
        assert isinstance(group.criteria[0], LowCPUCriterion)
        assert isinstance(group.criteria[1], LowNetworkCriterion)

    def test_build_with_required_criteria(self):
        configs = [
            CriterionConfig(type="low_cpu", threshold_percent=10.0),
            CriterionConfig(type="low_network", threshold_bytes_per_second=500.0),
        ]
        group = build_criteria_group(configs, mode="all(low_cpu)")
        assert group.mode == "all"
        assert group.required_criteria == {"low_cpu"}

    def test_build_unknown_type_raises(self):
        configs = [CriterionConfig(type="nonexistent")]
        with pytest.raises(ValueError, match="Unknown criterion type"):
            build_criteria_group(configs)

    def test_build_required_references_unknown_criterion(self):
        configs = [
            CriterionConfig(type="low_cpu", threshold_percent=10.0),
        ]
        with pytest.raises(ValueError, match="criteria_mode references unknown criteria"):
            build_criteria_group(configs, mode="all(low_cpu, low_network)")
