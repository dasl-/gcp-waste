"""Tests for HTML output formatter."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from waste.html_template import render_html
from waste.models import CriterionResult, IdleResource, ResourceType, ScanResult


class TestRenderHtml:
    def test_basic_html_output(self, sample_vm_resource):
        """HTML output contains expected structure."""
        sample_vm_resource.estimated_yearly_cost = 500.0
        sample_vm_resource.criterion_results = [
            CriterionResult(criterion_name="low_cpu", is_idle=True, reason="CPU < 5%"),
        ]
        result = ScanResult(
            project="test-project",
            idle_resources=[sample_vm_resource],
        )
        html = render_html(result)
        assert "<!DOCTYPE html>" in html
        assert "<title>" in html
        assert "GCP Waste" in html
        assert "Tabulator" in html
        assert "dev-server-1" in html
        assert "test-project" in html

    def test_data_json_embedded(self, sample_vm_resource):
        """Resource data is embedded as JSON in the HTML."""
        sample_vm_resource.estimated_yearly_cost = 1234.56
        result = ScanResult(
            project="test-project",
            idle_resources=[sample_vm_resource],
        )
        html = render_html(result)
        assert '"est_yearly_cost": 1234.56' in html
        assert '"resource_type": "compute_vm"' in html
        assert '"name": "dev-server-1"' in html

    def test_empty_result(self):
        """Empty scan result produces valid HTML with empty data array."""
        result = ScanResult(project="test-project")
        html = render_html(result)
        assert "<!DOCTYPE html>" in html
        assert "var DATA = []" in html

    def test_title_is_static(self):
        """Title is always 'GCP Waste' regardless of project."""
        result = ScanResult(project="test-project")
        html = render_html(result)
        assert "GCP Waste" in html

    def test_console_urls_present(self, sample_vm_resource):
        """Console URLs are generated for resources."""
        sample_vm_resource.estimated_yearly_cost = 100.0
        result = ScanResult(
            project="test-project",
            idle_resources=[sample_vm_resource],
        )
        html = render_html(result)
        assert "console.cloud.google.com" in html
        assert "compute/instancesDetail" in html

    def test_all_resource_types(
        self,
        sample_vm_resource,
        sample_bigtable_resource,
        sample_storage_resource,
        sample_persistent_disk_resource,
    ):
        """All resource types are included in the output."""
        for r in [
            sample_vm_resource,
            sample_bigtable_resource,
            sample_storage_resource,
            sample_persistent_disk_resource,
        ]:
            r.estimated_yearly_cost = 100.0
        result = ScanResult(
            project="test-project",
            idle_resources=[
                sample_vm_resource,
                sample_bigtable_resource,
                sample_storage_resource,
                sample_persistent_disk_resource,
            ],
        )
        html = render_html(result)
        assert '"compute_vm"' in html
        assert '"bigtable"' in html
        assert '"storage"' in html
        assert '"persistent_disk"' in html

    def test_detail_fields(self, sample_vm_resource, sample_persistent_disk_resource):
        """Detail fields (machine type, disk type+size) are included."""
        sample_vm_resource.estimated_yearly_cost = 100.0
        sample_persistent_disk_resource.estimated_yearly_cost = 50.0
        result = ScanResult(
            project="test-project",
            idle_resources=[sample_vm_resource, sample_persistent_disk_resource],
        )
        html = render_html(result)
        assert "e2-standard-2" in html
        # Size is on a separate line with <br> tag
        assert "pd-ssd" in html
        assert "(200.0 GB)" in html

    def test_estimated_cost_flag(self, sample_vm_resource):
        """Resources with lookup_fallback pricing are marked as estimated."""
        sample_vm_resource.estimated_yearly_cost = 100.0
        sample_vm_resource.metadata["pricing_source"] = "lookup_fallback"
        result = ScanResult(
            project="test-project",
            idle_resources=[sample_vm_resource],
        )
        html = render_html(result)
        assert '"is_estimated": true' in html

    def test_created_date_format(self, sample_vm_resource):
        """Creation time is formatted as YYYY-MM-DD."""
        sample_vm_resource.estimated_yearly_cost = 100.0
        result = ScanResult(
            project="test-project",
            idle_resources=[sample_vm_resource],
        )
        html = render_html(result)
        assert '"created": "2024-01-01"' in html

    def test_persistent_disk_attached_instances(self):
        """Persistent disk attached instances are included with URLs."""
        disk = IdleResource(
            resource_type=ResourceType.PERSISTENT_DISK,
            name="data-disk",
            project="test-project",
            location="us-east1-b",
            estimated_yearly_cost=50.0,
            metadata={
                "disk_type": "pd-ssd",
                "size_gb": "100",
                "attached_instances": "my-vm (RUNNING)",
            },
        )
        result = ScanResult(project="test-project", idle_resources=[disk])
        html = render_html(result)
        assert "my-vm (RUNNING)" in html
        assert "compute/instancesDetail" in html

    def test_persistent_disk_unattached(self):
        """Unattached persistent disk shows 'unattached' label."""
        disk = IdleResource(
            resource_type=ResourceType.PERSISTENT_DISK,
            name="orphan-disk",
            project="test-project",
            location="us-east1-b",
            estimated_yearly_cost=50.0,
            metadata={
                "disk_type": "pd-standard",
                "size_gb": "50",
                "attached_instances": "unattached",
            },
        )
        result = ScanResult(project="test-project", idle_resources=[disk])
        html = render_html(result)
        assert '"attached_to": "unattached"' in html

    def test_none_cost(self, sample_vm_resource):
        """Resource with None cost is handled."""
        sample_vm_resource.estimated_yearly_cost = None
        result = ScanResult(
            project="test-project",
            idle_resources=[sample_vm_resource],
        )
        html = render_html(result)
        assert '"est_yearly_cost": null' in html

    def test_criterion_reasons(self, sample_vm_resource):
        """Idle criterion names appear in the reasons field."""
        sample_vm_resource.estimated_yearly_cost = 100.0
        sample_vm_resource.criterion_results = [
            CriterionResult(criterion_name="low_cpu", is_idle=True, reason="CPU < 5%"),
            CriterionResult(criterion_name="low_network", is_idle=True, reason="Net < 1KB/s"),
        ]
        result = ScanResult(
            project="test-project",
            idle_resources=[sample_vm_resource],
        )
        html = render_html(result)
        assert "low_cpu, low_network" in html

    def test_filter_bar_present(self, sample_vm_resource):
        """HTML contains the filter bar UI elements."""
        sample_vm_resource.estimated_yearly_cost = 100.0
        result = ScanResult(
            project="test-project",
            idle_resources=[sample_vm_resource],
        )
        html = render_html(result)
        assert 'id="filter-project"' in html
        assert 'id="filter-name"' in html
        assert 'id="filter-type"' in html
        assert 'id="filter-min-cost"' in html
        assert 'id="filter-created-before"' in html
        assert 'id="filter-created-after"' in html
        assert 'id="clear-filters"' in html

    def test_summary_bar_present(self, sample_vm_resource):
        """HTML contains the summary bar elements."""
        sample_vm_resource.estimated_yearly_cost = 100.0
        result = ScanResult(
            project="test-project",
            idle_resources=[sample_vm_resource],
        )
        html = render_html(result)
        assert 'id="total-cost"' in html
        assert 'id="row-count"' in html
        assert "Generated" in html
        assert "UTC" in html
