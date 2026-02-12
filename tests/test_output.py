"""Tests for output rendering and multi-format support."""

from __future__ import annotations

import csv
import io
import json
from datetime import datetime, timezone

import pytest

from waste.models import IdleResource, ResourceType, ScanResult
from waste.output import FORMAT_EXTENSIONS, render_csv, render_format, render_json


def _make_result() -> ScanResult:
    """Create a ScanResult with a single idle resource for testing."""
    result = ScanResult(project="test-project")
    result.idle_resources = [
        IdleResource(
            resource_type=ResourceType.COMPUTE_VM,
            name="idle-vm-1",
            project="test-project",
            location="us-central1-a",
            creation_time=datetime(2024, 6, 1, tzinfo=timezone.utc),
            metadata={"machine_type": "e2-standard-2", "instance_id": "12345"},
            estimated_yearly_cost=500.0,
        ),
    ]
    return result


class TestRenderCsv:
    def test_returns_string(self):
        result = _make_result()
        output = render_csv(result)
        assert isinstance(output, str)

    def test_valid_csv(self):
        result = _make_result()
        output = render_csv(result)
        reader = csv.reader(io.StringIO(output))
        rows = list(reader)
        assert len(rows) == 2  # header + 1 resource
        assert rows[0][0] == "type"
        assert rows[1][0] == "compute_vm"

    def test_empty_result(self):
        result = ScanResult(project="test-project")
        output = render_csv(result)
        reader = csv.reader(io.StringIO(output))
        rows = list(reader)
        assert len(rows) == 1  # header only


class TestRenderJson:
    def test_returns_string(self):
        result = _make_result()
        output = render_json(result)
        assert isinstance(output, str)

    def test_valid_json(self):
        result = _make_result()
        output = render_json(result)
        data = json.loads(output)
        assert data["project"] == "test-project"
        assert len(data["idle_resources"]) == 1
        assert data["idle_resources"][0]["name"] == "idle-vm-1"

    def test_empty_result(self):
        result = ScanResult(project="test-project")
        output = render_json(result)
        data = json.loads(output)
        assert data["idle_resources"] == []


class TestRenderFormat:
    def test_csv_dispatch(self):
        result = _make_result()
        output = render_format(result, "csv")
        assert "type,name" in output

    def test_json_dispatch(self):
        result = _make_result()
        output = render_format(result, "json")
        data = json.loads(output)
        assert "idle_resources" in data

    def test_table_raises(self):
        result = _make_result()
        with pytest.raises(ValueError, match="Cannot render format 'table'"):
            render_format(result, "table")

    def test_unknown_format_raises(self):
        result = _make_result()
        with pytest.raises(ValueError):
            render_format(result, "xml")


class TestFormatExtensions:
    def test_extensions(self):
        assert FORMAT_EXTENSIONS["csv"] == ".csv"
        assert FORMAT_EXTENSIONS["json"] == ".json"
        assert FORMAT_EXTENSIONS["html"] == ".html"
        assert "table" not in FORMAT_EXTENSIONS
