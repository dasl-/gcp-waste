"""BigQuery-based pricing backend using actual billing export data.

Queries the standard GCP detailed usage export table to get actual
per-resource costs. Requires a BigQuery billing export to be configured:
https://cloud.google.com/billing/docs/how-to/export-data-bigquery
"""

from __future__ import annotations

import logging

from google.cloud import bigquery

from waste.models import IdleResource, ResourceType
from waste.pricing import LookupPricingBackend, PricingBackend

logger = logging.getLogger(__name__)

# 26-day window: 30 days ago to 4 days ago (exclude recent unsettled data).
#
# Groups by (resource.global_name, project.id) so that all SKUs for the same
# resource are summed together. This is critical for VMs, which have separate
# SKU rows for CPU, RAM, GPU, IP, and network — all sharing the same
# global_name but potentially different resource.name formats.
#
# ANY_VALUE(resource.name) gives us the human-readable name for fallback
# matching (disks, storage buckets).
#
# _PARTITIONTIME filter: the standard billing export table is partitioned by
# ingestion time (not usage date), so without this filter BigQuery scans the
# entire table. We add 5-day padding on each side of the usage window to
# account for rows where ingestion time differs from usage time.
_QUERY = """\
SELECT resource.global_name, ANY_VALUE(resource.name) AS name,
       project.id AS project_id,
       SUM(COALESCE(cost_at_effective_price_default, cost)) * 365.0 / 26 AS yearly_cost
FROM `{table}`
WHERE project.id IN UNNEST(@projects)
  AND usage_start_time >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 30 DAY)
  AND usage_start_time < TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 4 DAY)
  AND _PARTITIONTIME >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 35 DAY)
  AND _PARTITIONTIME < CURRENT_TIMESTAMP()
  AND COALESCE(cost_at_effective_price_default, cost) > 0
  AND service.description IN ("Compute Engine", "Cloud Bigtable", "Cloud Storage", "Networking", "BigQuery")
  AND (
    resource.name IN UNNEST(@resource_names)
    OR REGEXP_EXTRACT(resource.global_name, r"/([^/]+)$") IN UNNEST(@trailing_ids)
  )
GROUP BY resource.global_name, project.id
"""


class BigQueryPricingBackend(PricingBackend):
    """Pricing backend that queries GCP billing export in BigQuery."""

    def __init__(self, table: str) -> None:
        self._table = table
        self._bq_client = bigquery.Client()
        self._lookup_fallback = LookupPricingBackend()

    def estimate_yearly_cost(self, resource: IdleResource) -> float | None:
        return None  # Not used directly; enrich() handles batch pricing

    def enrich(self, resources: list[IdleResource]) -> None:
        if not resources:
            return

        logger.info("BigQuery pricing: enriching %d idle resource(s) with actual costs...", len(resources))

        # Extract identifiers for the BQ query
        projects: set[str] = set()
        resource_names: set[str] = set()
        trailing_ids: set[str] = set()

        for r in resources:
            projects.add(r.project)
            if r.resource_type == ResourceType.COMPUTE_VM:
                instance_id = r.metadata.get("instance_id", "")
                if instance_id:
                    trailing_ids.add(instance_id)
            elif r.resource_type == ResourceType.PERSISTENT_DISK:
                resource_names.add(r.name)
            elif r.resource_type == ResourceType.BIGTABLE:
                instance_id = r.metadata.get("instance_id", "")
                if instance_id:
                    trailing_ids.add(instance_id)
            elif r.resource_type == ResourceType.STORAGE:
                resource_names.add(r.name)

        if not resource_names and not trailing_ids:
            return

        query = _QUERY.format(table=self._table)
        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ArrayQueryParameter("projects", "STRING", sorted(projects)),
                bigquery.ArrayQueryParameter("resource_names", "STRING", sorted(resource_names)),
                bigquery.ArrayQueryParameter("trailing_ids", "STRING", sorted(trailing_ids)),
            ]
        )

        logger.info(
            "BigQuery pricing: querying %d project(s), %d resource names, %d trailing IDs",
            len(projects), len(resource_names), len(trailing_ids),
        )
        logger.info("BigQuery pricing: query:\n%s", query)

        job = self._bq_client.query(query, job_config=job_config)
        logger.info("BigQuery pricing: query job %s submitted, waiting for results...", job.job_id)
        rows = job.result()
        elapsed = (int(job._properties.get("statistics", {}).get("endTime", 0))
                   - int(job._properties.get("statistics", {}).get("creationTime", 0))) / 1000.0
        logger.info("BigQuery pricing: query complete in %.1fs, processing %s rows", elapsed, rows.total_rows)

        # Build lookup maps from results.
        # cost_by_global: keyed by (project_id, global_name) — used for VMs and Bigtable
        #   where global_name contains the numeric instance_id.
        # cost_by_name: keyed by (project_id, resource_name) — used for disks and storage
        #   where resource.name is the human-readable name.
        cost_by_global: dict[tuple[str, str], float] = {}
        cost_by_name: dict[tuple[str, str], float] = {}
        for row in rows:
            if row.global_name:
                cost_by_global[(row.project_id, row.global_name)] = row.yearly_cost
                # Only populate cost_by_name for disks and storage buckets
                # (the resource types that use name-based matching). VMs can
                # share the same resource.name as their attached disk for
                # IP/network SKUs, which would inflate the disk's cost.
                if row.name and ("/disk/" in row.global_name or "/buckets/" in row.global_name):
                    key = (row.project_id, row.name)
                    cost_by_name[key] = cost_by_name.get(key, 0.0) + row.yearly_cost

        # Bigtable billing is per-instance, but we report per-cluster.
        # Compute total nodes per instance so we can split costs proportionally.
        bt_instance_nodes: dict[tuple[str, str], int] = {}  # (project, instance_id) -> total nodes
        for r in resources:
            if r.resource_type == ResourceType.BIGTABLE:
                key = (r.project, r.metadata.get("instance_id", ""))
                nodes = int(r.metadata.get("node_count", "1"))
                bt_instance_nodes[key] = bt_instance_nodes.get(key, 0) + nodes

        # Match results back to resources; fall back to lookup tables for
        # resources missing from the billing export.
        matched = 0
        fallback = []
        for r in resources:
            cost = self._match_cost(r, cost_by_global, cost_by_name, bt_instance_nodes)
            if cost is not None:
                r.estimated_yearly_cost = cost
                matched += 1
            else:
                r.estimated_yearly_cost = self._lookup_fallback.estimate_yearly_cost(r)
                r.metadata["pricing_source"] = "lookup_fallback"
                fallback.append(r)

        if fallback:
            logger.warning(
                "BigQuery pricing: no billing data for %d/%d resources (used lookup fallback): %s",
                len(fallback), len(resources),
                ", ".join(f"{r.name} ({r.project})" for r in fallback),
            )
        else:
            logger.info("BigQuery pricing: matched all %d resources", matched)

    def _match_cost(
        self,
        resource: IdleResource,
        cost_by_global: dict[tuple[str, str], float],
        cost_by_name: dict[tuple[str, str], float],
        bt_instance_nodes: dict[tuple[str, str], int] | None = None,
    ) -> float | None:
        """Match a BQ result row to an idle resource."""
        # VMs and Bigtable: match via global_name suffix containing instance_id.
        # global_name format:
        #   VM:       //compute.googleapis.com/projects/{num}/zones/{z}/instances/{instance_id}
        #   Bigtable: //bigtable.googleapis.com/projects/{proj}/instances/{instance_name}
        if resource.resource_type in (ResourceType.COMPUTE_VM, ResourceType.BIGTABLE):
            instance_id = resource.metadata.get("instance_id", "")
            if instance_id:
                suffix = f"/instances/{instance_id}"
                for (proj, gname), cost in cost_by_global.items():
                    if proj == resource.project and gname.endswith(suffix):
                        # Bigtable billing is per-instance; split across clusters
                        # proportionally by node count.
                        if resource.resource_type == ResourceType.BIGTABLE and bt_instance_nodes:
                            cluster_nodes = int(resource.metadata.get("node_count", "1"))
                            total_nodes = bt_instance_nodes.get((resource.project, instance_id), cluster_nodes)
                            return cost * cluster_nodes / total_nodes
                        return cost

        # Disks and storage: match via human-readable resource.name.
        key = (resource.project, resource.name)
        if key in cost_by_name:
            return cost_by_name[key]

        return None
