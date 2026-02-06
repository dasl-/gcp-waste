"""Cloud Monitoring API wrapper for querying resource metrics."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from google.api_core import exceptions as api_exceptions
from google.api_core import retry as api_retry
from google.api_core.client_options import ClientOptions
from google.cloud import monitoring_v3
from google.protobuf import timestamp_pb2

logger = logging.getLogger(__name__)

# Retry on quota exhaustion (429) with exponential backoff, in addition to
# the default transient errors (503 Unavailable, 504 Deadline Exceeded).
_MONITORING_RETRY = api_retry.Retry(
    predicate=api_retry.if_exception_type(
        api_exceptions.DeadlineExceeded,
        api_exceptions.ServiceUnavailable,
        api_exceptions.ResourceExhausted,
    ),
    initial=2.0,
    maximum=60.0,
    multiplier=2.0,
    deadline=300.0,
)


class MonitoringClient:
    """Wrapper around Cloud Monitoring API for querying resource metrics."""

    def __init__(self, project: str, credentials=None, quota_project: str | None = None):
        self.project = project
        self.project_name = f"projects/{project}"
        client_options = None
        if quota_project:
            client_options = ClientOptions(quota_project_id=quota_project)
        self._client = monitoring_v3.MetricServiceClient(
            credentials=credentials, client_options=client_options,
        )

    def query_mean(
        self,
        metric_type: str,
        resource_filter: str,
        days: int = 7,
    ) -> float | None:
        """Query the mean value of a metric over the given time window.

        Args:
            metric_type: The metric type string, e.g.
                "compute.googleapis.com/instance/cpu/utilization".
            resource_filter: Additional filter for the resource, e.g.
                'resource.labels.instance_id = "1234"'.
            days: Number of days to look back.

        Returns:
            The mean value of the metric, or None if no data points found.
        """
        now = datetime.now(timezone.utc)
        start = now - timedelta(days=days)

        start_ts = timestamp_pb2.Timestamp()
        start_ts.FromDatetime(start)
        end_ts = timestamp_pb2.Timestamp()
        end_ts.FromDatetime(now)

        interval = monitoring_v3.TimeInterval(
            start_time=start_ts,
            end_time=end_ts,
        )

        metric_filter = f'metric.type = "{metric_type}"'
        if resource_filter:
            metric_filter += f" AND {resource_filter}"

        aggregation = monitoring_v3.Aggregation(
            alignment_period={"seconds": days * 86400},
            per_series_aligner=monitoring_v3.Aggregation.Aligner.ALIGN_MEAN,
        )

        results = self._client.list_time_series(
            request={
                "name": self.project_name,
                "filter": metric_filter,
                "interval": interval,
                "view": monitoring_v3.ListTimeSeriesRequest.TimeSeriesView.FULL,
                "aggregation": aggregation,
            },
            retry=_MONITORING_RETRY,
        )

        values = []
        for ts in results:
            for point in ts.points:
                values.append(point.value.double_value)

        if not values:
            logger.info("  query_mean(%s): no data", metric_type.split("/")[-1])
            return None

        result = sum(values) / len(values)
        logger.info("  query_mean(%s): %.6f", metric_type.split("/")[-1], result)
        return result

    def query_sum(
        self,
        metric_type: str,
        resource_filter: str,
        days: int = 7,
    ) -> float | None:
        """Query the total sum of a metric over the given time window.

        Args:
            metric_type: The metric type string.
            resource_filter: Additional filter for the resource.
            days: Number of days to look back.

        Returns:
            The sum of all data points, or None if no data found.
        """
        now = datetime.now(timezone.utc)
        start = now - timedelta(days=days)

        start_ts = timestamp_pb2.Timestamp()
        start_ts.FromDatetime(start)
        end_ts = timestamp_pb2.Timestamp()
        end_ts.FromDatetime(now)

        interval = monitoring_v3.TimeInterval(
            start_time=start_ts,
            end_time=end_ts,
        )

        metric_filter = f'metric.type = "{metric_type}"'
        if resource_filter:
            metric_filter += f" AND {resource_filter}"

        aggregation = monitoring_v3.Aggregation(
            alignment_period={"seconds": days * 86400},
            per_series_aligner=monitoring_v3.Aggregation.Aligner.ALIGN_SUM,
        )

        results = self._client.list_time_series(
            request={
                "name": self.project_name,
                "filter": metric_filter,
                "interval": interval,
                "view": monitoring_v3.ListTimeSeriesRequest.TimeSeriesView.FULL,
                "aggregation": aggregation,
            },
            retry=_MONITORING_RETRY,
        )

        total = 0.0
        found = False
        for ts in results:
            for point in ts.points:
                total += point.value.double_value + point.value.int64_value
                found = True

        if not found:
            logger.info("  query_sum(%s): no data", metric_type.split("/")[-1])
            return None

        logger.info("  query_sum(%s): %.2f", metric_type.split("/")[-1], total)
        return total

    def query_rate(
        self,
        metric_type: str,
        resource_filter: str,
        days: int = 7,
    ) -> float | None:
        """Query the mean rate (per second) of a metric over the given time window.

        Args:
            metric_type: The metric type string.
            resource_filter: Additional filter for the resource.
            days: Number of days to look back.

        Returns:
            The mean rate per second, or None if no data found.
        """
        aggregation = monitoring_v3.Aggregation(
            alignment_period={"seconds": days * 86400},
            per_series_aligner=monitoring_v3.Aggregation.Aligner.ALIGN_RATE,
        )

        now = datetime.now(timezone.utc)
        start = now - timedelta(days=days)

        start_ts = timestamp_pb2.Timestamp()
        start_ts.FromDatetime(start)
        end_ts = timestamp_pb2.Timestamp()
        end_ts.FromDatetime(now)

        interval = monitoring_v3.TimeInterval(
            start_time=start_ts,
            end_time=end_ts,
        )

        metric_filter = f'metric.type = "{metric_type}"'
        if resource_filter:
            metric_filter += f" AND {resource_filter}"

        results = self._client.list_time_series(
            request={
                "name": self.project_name,
                "filter": metric_filter,
                "interval": interval,
                "view": monitoring_v3.ListTimeSeriesRequest.TimeSeriesView.FULL,
                "aggregation": aggregation,
            },
            retry=_MONITORING_RETRY,
        )

        values = []
        for ts in results:
            for point in ts.points:
                values.append(point.value.double_value)

        if not values:
            logger.info("  query_rate(%s): no data", metric_type.split("/")[-1])
            return None

        result = sum(values) / len(values)
        logger.info("  query_rate(%s): %.6f", metric_type.split("/")[-1], result)
        return result
