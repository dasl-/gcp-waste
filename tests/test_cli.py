"""Tests for CLI entry point."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from waste.cli import app, _resolve_projects
from waste.models import ScanResult


runner = CliRunner()


class TestCLI:
    def test_no_args_shows_help(self):
        result = runner.invoke(app, [])
        assert result.exit_code == 0
        assert "GCP Idle Resource Finder" in result.output or "Usage" in result.output

    def test_scan_requires_project(self):
        result = runner.invoke(app, ["scan"])
        assert result.exit_code != 0

    @patch("waste.cli._scan_project")
    def test_scan_with_project(self, mock_scan_project):
        mock_scan_project.return_value = ScanResult(project="test-project")

        result = runner.invoke(app, ["scan", "--project", "test-project"])
        assert result.exit_code == 0
        mock_scan_project.assert_called_once()

    @patch("waste.cli._scan_project")
    def test_scan_single_type(self, mock_scan_project):
        mock_scan_project.return_value = ScanResult(project="test-project")

        result = runner.invoke(
            app, ["scan", "--project", "test-project", "--type", "compute"]
        )
        assert result.exit_code == 0
        mock_scan_project.assert_called_once()

    @patch("waste.cli._scan_project")
    def test_scan_invalid_type(self, mock_scan_project):
        result = runner.invoke(
            app, ["scan", "--project", "test-project", "--type", "invalid"]
        )
        assert result.exit_code != 0

    @patch("waste.cli._scan_project")
    def test_scan_json_output(self, mock_scan_project):
        mock_scan_project.return_value = ScanResult(project="test-project")

        result = runner.invoke(
            app, ["scan", "--project", "test-project", "--output", "json"]
        )
        assert result.exit_code == 0

    @patch("waste.cli._scan_project")
    def test_scan_csv_output(self, mock_scan_project):
        mock_scan_project.return_value = ScanResult(project="test-project")

        result = runner.invoke(
            app, ["scan", "--project", "test-project", "--output", "csv"]
        )
        assert result.exit_code == 0


class TestResolveProjects:
    def test_literal_project_id(self):
        # A plain project ID is returned as-is without API call
        result = _resolve_projects("my-project-123")
        assert result == ["my-project-123"]

    @patch("waste.cli._list_accessible_projects")
    def test_regex_matches_projects(self, mock_list):
        mock_list.return_value = [
            "myorg-mysql-dev",
            "myorg-mysql-prod",
            "myorg-web-dev",
            "other-project",
        ]
        result = _resolve_projects("myorg-mysql-.*")
        assert result == ["myorg-mysql-dev", "myorg-mysql-prod"]

    @patch("waste.cli._list_accessible_projects")
    def test_regex_caret_anchor(self, mock_list):
        mock_list.return_value = ["prod-api", "prod-web", "staging-api"]
        result = _resolve_projects("^prod-")
        assert result == ["prod-api", "prod-web"]

    @patch("waste.cli._list_accessible_projects")
    def test_regex_no_matches_exits(self, mock_list):
        from click.exceptions import Exit

        mock_list.return_value = ["project-a", "project-b"]
        with pytest.raises(Exit):
            _resolve_projects("^nonexistent-.*")

    @patch("waste.cli._list_accessible_projects")
    @patch("waste.cli._scan_project")
    def test_scan_with_regex(self, mock_scan_project, mock_list):
        mock_list.return_value = ["team-dev", "team-staging", "other-project"]
        mock_scan_project.return_value = ScanResult(project="team-dev")

        result = runner.invoke(
            app, ["scan", "--project", "^team-"]
        )
        assert result.exit_code == 0
        assert mock_scan_project.call_count == 2
