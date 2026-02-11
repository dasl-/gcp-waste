"""Tests for HTML report diff functionality."""

from __future__ import annotations

import json

import pytest

from waste.diff import DiffResult, diff_report_data, extract_data_from_html
from waste.html_template import render_html
from waste.models import CriterionResult, IdleResource, ResourceType, ScanResult


def _make_resource(name, project="test-project", cost=100.0, rtype=ResourceType.COMPUTE_VM):
    r = IdleResource(
        resource_type=rtype,
        name=name,
        project=project,
        location="us-east1-b",
        estimated_yearly_cost=cost,
        metadata={"machine_type": "e2-standard-2"},
    )
    r.criterion_results = [
        CriterionResult(criterion_name="low_cpu", is_idle=True, reason="CPU < 5%"),
    ]
    return r


def _render_with_resources(resources):
    result = ScanResult(project="test-project", idle_resources=resources)
    return render_html(result)


class TestExtractDataFromHtml:
    def test_extracts_data_array(self):
        html = _render_with_resources([_make_resource("vm-1")])
        data = extract_data_from_html(html)
        assert isinstance(data, list)
        assert len(data) == 1
        assert data[0]["name"] == "vm-1"
        assert data[0]["project"] == "test-project"
        assert data[0]["resource_type"] == "compute_vm"

    def test_extracts_multiple_resources(self):
        html = _render_with_resources([
            _make_resource("vm-1"),
            _make_resource("vm-2", cost=200.0),
        ])
        data = extract_data_from_html(html)
        assert len(data) == 2
        names = {d["name"] for d in data}
        assert names == {"vm-1", "vm-2"}

    def test_extracts_empty_data(self):
        html = _render_with_resources([])
        data = extract_data_from_html(html)
        assert data == []

    def test_raises_on_invalid_html(self):
        with pytest.raises(ValueError, match="Could not find"):
            extract_data_from_html("<html><body>no data here</body></html>")

    def test_cost_preserved(self):
        html = _render_with_resources([_make_resource("vm-1", cost=1234.56)])
        data = extract_data_from_html(html)
        assert data[0]["est_yearly_cost"] == 1234.56

    def test_null_cost_preserved(self):
        html = _render_with_resources([_make_resource("vm-1", cost=None)])
        data = extract_data_from_html(html)
        assert data[0]["est_yearly_cost"] is None


class TestDiffReportData:
    def test_no_changes(self):
        data = [{"project": "p", "resource_type": "compute_vm", "name": "vm-1", "est_yearly_cost": 100}]
        result = diff_report_data(data, data)
        assert not result.has_changes
        assert result.added == []
        assert result.removed == []
        assert result.cost_changes == []

    def test_added_resource(self):
        old = [{"project": "p", "resource_type": "compute_vm", "name": "vm-1", "est_yearly_cost": 100}]
        new = old + [{"project": "p", "resource_type": "compute_vm", "name": "vm-2", "est_yearly_cost": 200}]
        result = diff_report_data(old, new)
        assert len(result.added) == 1
        assert "vm-2" in result.added[0]
        assert result.removed == []

    def test_removed_resource(self):
        old = [
            {"project": "p", "resource_type": "compute_vm", "name": "vm-1", "est_yearly_cost": 100},
            {"project": "p", "resource_type": "compute_vm", "name": "vm-2", "est_yearly_cost": 200},
        ]
        new = [old[0]]
        result = diff_report_data(old, new)
        assert result.added == []
        assert len(result.removed) == 1
        assert "vm-2" in result.removed[0]

    def test_cost_change_above_threshold(self):
        old = [{"project": "p", "resource_type": "compute_vm", "name": "vm-1", "est_yearly_cost": 100}]
        new = [{"project": "p", "resource_type": "compute_vm", "name": "vm-1", "est_yearly_cost": 130}]
        result = diff_report_data(old, new, cost_threshold_pct=25.0)
        assert len(result.cost_changes) == 1
        assert result.cost_changes[0]["old_cost"] == 100
        assert result.cost_changes[0]["new_cost"] == 130
        assert result.cost_changes[0]["pct_change"] == 30.0

    def test_cost_change_below_threshold(self):
        old = [{"project": "p", "resource_type": "compute_vm", "name": "vm-1", "est_yearly_cost": 100}]
        new = [{"project": "p", "resource_type": "compute_vm", "name": "vm-1", "est_yearly_cost": 120}]
        result = diff_report_data(old, new, cost_threshold_pct=25.0)
        assert result.cost_changes == []

    def test_cost_change_exactly_at_threshold(self):
        """Exactly 25% change should not be flagged (> not >=)."""
        old = [{"project": "p", "resource_type": "compute_vm", "name": "vm-1", "est_yearly_cost": 100}]
        new = [{"project": "p", "resource_type": "compute_vm", "name": "vm-1", "est_yearly_cost": 125}]
        result = diff_report_data(old, new, cost_threshold_pct=25.0)
        assert result.cost_changes == []

    def test_cost_decrease_flagged(self):
        old = [{"project": "p", "resource_type": "compute_vm", "name": "vm-1", "est_yearly_cost": 200}]
        new = [{"project": "p", "resource_type": "compute_vm", "name": "vm-1", "est_yearly_cost": 100}]
        result = diff_report_data(old, new, cost_threshold_pct=25.0)
        assert len(result.cost_changes) == 1
        assert result.cost_changes[0]["pct_change"] == 50.0

    def test_null_cost_skipped(self):
        old = [{"project": "p", "resource_type": "compute_vm", "name": "vm-1", "est_yearly_cost": None}]
        new = [{"project": "p", "resource_type": "compute_vm", "name": "vm-1", "est_yearly_cost": 100}]
        result = diff_report_data(old, new)
        assert result.cost_changes == []

    def test_zero_to_nonzero_cost(self):
        old = [{"project": "p", "resource_type": "compute_vm", "name": "vm-1", "est_yearly_cost": 0}]
        new = [{"project": "p", "resource_type": "compute_vm", "name": "vm-1", "est_yearly_cost": 100}]
        result = diff_report_data(old, new)
        assert len(result.cost_changes) == 1

    def test_both_zero_cost_not_flagged(self):
        old = [{"project": "p", "resource_type": "compute_vm", "name": "vm-1", "est_yearly_cost": 0}]
        new = [{"project": "p", "resource_type": "compute_vm", "name": "vm-1", "est_yearly_cost": 0}]
        result = diff_report_data(old, new)
        assert result.cost_changes == []

    def test_different_projects_are_separate_keys(self):
        old = [{"project": "proj-a", "resource_type": "compute_vm", "name": "vm-1", "est_yearly_cost": 100}]
        new = [{"project": "proj-b", "resource_type": "compute_vm", "name": "vm-1", "est_yearly_cost": 100}]
        result = diff_report_data(old, new)
        assert len(result.added) == 1
        assert len(result.removed) == 1

    def test_different_types_are_separate_keys(self):
        old = [{"project": "p", "resource_type": "compute_vm", "name": "x", "est_yearly_cost": 100}]
        new = [{"project": "p", "resource_type": "storage", "name": "x", "est_yearly_cost": 100}]
        result = diff_report_data(old, new)
        assert len(result.added) == 1
        assert len(result.removed) == 1

    def test_combined_added_removed_cost_changed(self):
        old = [
            {"project": "p", "resource_type": "compute_vm", "name": "stays-same", "est_yearly_cost": 100},
            {"project": "p", "resource_type": "compute_vm", "name": "gets-removed", "est_yearly_cost": 50},
            {"project": "p", "resource_type": "compute_vm", "name": "cost-jumps", "est_yearly_cost": 100},
        ]
        new = [
            {"project": "p", "resource_type": "compute_vm", "name": "stays-same", "est_yearly_cost": 100},
            {"project": "p", "resource_type": "compute_vm", "name": "newly-added", "est_yearly_cost": 75},
            {"project": "p", "resource_type": "compute_vm", "name": "cost-jumps", "est_yearly_cost": 200},
        ]
        result = diff_report_data(old, new)
        assert len(result.added) == 1
        assert len(result.removed) == 1
        assert len(result.cost_changes) == 1
        assert result.has_changes

    def test_custom_threshold(self):
        old = [{"project": "p", "resource_type": "compute_vm", "name": "vm-1", "est_yearly_cost": 100}]
        new = [{"project": "p", "resource_type": "compute_vm", "name": "vm-1", "est_yearly_cost": 111}]
        # 11% change, below default 25% but above 10%
        assert diff_report_data(old, new, cost_threshold_pct=25.0).cost_changes == []
        assert len(diff_report_data(old, new, cost_threshold_pct=10.0).cost_changes) == 1


class TestDiffWithRenderedHtml:
    """End-to-end: render two HTML reports, extract data, diff."""

    def test_roundtrip_diff(self):
        old_html = _render_with_resources([
            _make_resource("vm-1", cost=100.0),
            _make_resource("vm-2", cost=200.0),
        ])
        new_html = _render_with_resources([
            _make_resource("vm-1", cost=100.0),
            _make_resource("vm-3", cost=300.0),
        ])

        old_data = extract_data_from_html(old_html)
        new_data = extract_data_from_html(new_html)
        result = diff_report_data(old_data, new_data)

        assert len(result.added) == 1
        assert "vm-3" in result.added[0]
        assert len(result.removed) == 1
        assert "vm-2" in result.removed[0]
        assert result.cost_changes == []

    def test_roundtrip_cost_change(self):
        old_html = _render_with_resources([_make_resource("vm-1", cost=100.0)])
        new_html = _render_with_resources([_make_resource("vm-1", cost=200.0)])

        old_data = extract_data_from_html(old_html)
        new_data = extract_data_from_html(new_html)
        result = diff_report_data(old_data, new_data)

        assert result.added == []
        assert result.removed == []
        assert len(result.cost_changes) == 1
        assert result.cost_changes[0]["pct_change"] == 100.0


class TestHtmlContainsDiffUi:
    """Verify the HTML output includes the compare UI elements."""

    def test_compare_bar_present(self, sample_vm_resource):
        sample_vm_resource.estimated_yearly_cost = 100.0
        result = ScanResult(project="test-project", idle_resources=[sample_vm_resource])
        html = render_html(result)
        assert 'id="compare-bar"' in html
        assert 'id="compare-select"' in html
        assert 'id="compare-browse"' in html
        assert 'id="compare-clear"' in html
        assert 'id="compare-file"' in html
        assert 'id="diff-summary"' in html

    def test_menu_button_present(self, sample_vm_resource):
        sample_vm_resource.estimated_yearly_cost = 100.0
        result = ScanResult(project="test-project", idle_resources=[sample_vm_resource])
        html = render_html(result)
        assert 'id="menu-btn"' in html
        assert 'id="title-bar"' in html

    def test_diff_javascript_present(self, sample_vm_resource):
        sample_vm_resource.estimated_yearly_cost = 100.0
        result = ScanResult(project="test-project", idle_resources=[sample_vm_resource])
        html = render_html(result)
        assert "function applyDiff" in html
        assert "function extractDataFromHtml" in html
        assert "function clearDiff" in html
        assert "function resourceKey" in html
        assert "COST_THRESHOLD_PCT" in html

    def test_diff_css_present(self, sample_vm_resource):
        sample_vm_resource.estimated_yearly_cost = 100.0
        result = ScanResult(project="test-project", idle_resources=[sample_vm_resource])
        html = render_html(result)
        assert "diff-added" in html
        assert "diff-removed" in html
        assert "diff-cost-changed" in html
