"""Tests for the Cloud Monitoring API wrapper."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from waste.monitoring import MonitoringClient


class TestMonitoringClient:
    @patch("waste.monitoring.monitoring_v3.MetricServiceClient")
    def test_query_mean_returns_average(self, mock_client_cls):
        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client

        # Create mock time series with points
        point1 = MagicMock()
        point1.value.double_value = 0.04
        point2 = MagicMock()
        point2.value.double_value = 0.06

        ts = MagicMock()
        ts.points = [point1, point2]
        mock_client.list_time_series.return_value = [ts]

        client = MonitoringClient("test-project")
        result = client.query_mean(
            metric_type="compute.googleapis.com/instance/cpu/utilization",
            resource_filter='resource.labels.instance_id = "123"',
            days=7,
        )

        assert result == pytest.approx(0.05)
        mock_client.list_time_series.assert_called_once()

    @patch("waste.monitoring.monitoring_v3.MetricServiceClient")
    def test_query_mean_no_data_returns_none(self, mock_client_cls):
        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client
        mock_client.list_time_series.return_value = []

        client = MonitoringClient("test-project")
        result = client.query_mean(
            metric_type="some.metric",
            resource_filter="",
            days=7,
        )

        assert result is None

    @patch("waste.monitoring.monitoring_v3.MetricServiceClient")
    def test_query_sum_returns_total(self, mock_client_cls):
        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client

        point1 = MagicMock()
        point1.value.double_value = 100.0
        point1.value.int64_value = 0
        point2 = MagicMock()
        point2.value.double_value = 200.0
        point2.value.int64_value = 0

        ts = MagicMock()
        ts.points = [point1, point2]
        mock_client.list_time_series.return_value = [ts]

        client = MonitoringClient("test-project")
        result = client.query_sum(
            metric_type="some.metric",
            resource_filter="",
            days=7,
        )

        assert result == pytest.approx(300.0)

    @patch("waste.monitoring.monitoring_v3.MetricServiceClient")
    def test_query_sum_no_data_returns_none(self, mock_client_cls):
        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client
        mock_client.list_time_series.return_value = []

        client = MonitoringClient("test-project")
        result = client.query_sum(
            metric_type="some.metric",
            resource_filter="",
            days=7,
        )

        assert result is None

    @patch("waste.monitoring.monitoring_v3.MetricServiceClient")
    def test_query_rate_returns_mean_rate(self, mock_client_cls):
        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client

        point = MagicMock()
        point.value.double_value = 0.5

        ts = MagicMock()
        ts.points = [point]
        mock_client.list_time_series.return_value = [ts]

        client = MonitoringClient("test-project")
        result = client.query_rate(
            metric_type="bigtable.googleapis.com/server/request_count",
            resource_filter="",
            days=7,
        )

        assert result == pytest.approx(0.5)
