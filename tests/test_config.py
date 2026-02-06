"""Tests for configuration loading and validation."""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from waste.config import WasteConfig, load_config


class TestWasteConfig:
    def test_default_config(self):
        config = WasteConfig()
        assert config.thresholds.compute.criteria_mode == "all"
        assert config.thresholds.bigtable.criteria_mode == "all"
        assert config.thresholds.storage.criteria_mode == "any"
        assert len(config.thresholds.compute.criteria) == 2
        assert len(config.thresholds.bigtable.criteria) == 1
        assert len(config.thresholds.storage.criteria) == 1

    def test_default_compute_criteria(self):
        config = WasteConfig()
        cpu_crit = config.thresholds.compute.criteria[0]
        assert cpu_crit.type == "low_cpu"
        assert cpu_crit.threshold_percent == 5.0

        net_crit = config.thresholds.compute.criteria[1]
        assert net_crit.type == "low_network"
        assert net_crit.threshold_bytes_per_second == 1000

    def test_blocklist_matching(self):
        config = WasteConfig(
            blocklist={
                "my-project": {
                    "compute": ["prod-web-*", "critical-db-1"],
                    "storage": ["backup-*"],
                }
            }
        )
        assert config.is_blocklisted("my-project", "compute", "prod-web-server-1")
        assert config.is_blocklisted("my-project", "compute", "critical-db-1")
        assert not config.is_blocklisted("my-project", "compute", "dev-server-1")
        assert config.is_blocklisted("my-project", "storage", "backup-2024")
        assert not config.is_blocklisted("other-project", "compute", "prod-web-server-1")

    def test_blocklist_empty(self):
        config = WasteConfig()
        assert not config.is_blocklisted("my-project", "compute", "any-resource")


class TestLoadConfig:
    def test_load_none_returns_defaults(self, tmp_path, monkeypatch):
        # Run from a directory with no config files to test built-in defaults
        monkeypatch.chdir(tmp_path)
        config = load_config(None)
        assert isinstance(config, WasteConfig)
        assert config.thresholds.compute.criteria_mode == "all"

    def test_load_yaml(self, tmp_path: Path):
        config_file = tmp_path / "config.yaml"
        config_file.write_text(textwrap.dedent("""\
            thresholds:
              compute:
                criteria_mode: "any"
                min_age_days: 14
                criteria:
                  - type: low_cpu
                    threshold_percent: 10.0
            blocklist:
              test-project:
                compute:
                  - "skip-me-*"
        """))

        config = load_config(config_file)
        assert config.thresholds.compute.criteria_mode == "any"
        assert config.thresholds.compute.min_age_days == 14
        assert config.thresholds.compute.criteria[0].threshold_percent == 10.0
        assert config.is_blocklisted("test-project", "compute", "skip-me-123")

    def test_load_empty_yaml(self, tmp_path: Path):
        config_file = tmp_path / "empty.yaml"
        config_file.write_text("")
        config = load_config(config_file)
        assert isinstance(config, WasteConfig)
