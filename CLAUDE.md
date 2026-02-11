# gcp-waste

GCP idle resource finder. Scans projects for underutilized Compute VMs, persistent disks, Bigtable clusters, and Cloud Storage buckets.

## Quick Reference

```bash
# Run tests
.venv/bin/python -m pytest tests/ -v

# Run the tool
.venv/bin/gcp-waste scan -p <project-id>
.venv/bin/gcp-waste scan -p <project-id> --pricing-backend bigquery \
  --bigquery-billing-table "project.dataset.gcp_billing_export_resource_v1_XXXXXX_YYYYYY_ZZZZZZ" -o csv
```

## Architecture

```
src/waste/
  cli.py          CLI entry point (Typer). Orchestrates scanning across projects.
  config.py       YAML config loading (Pydantic models). Defines defaults.
  models.py       Data models: IdleResource, ScanResult, CriterionResult.
  monitoring.py   Cloud Monitoring API wrapper (query_mean, query_sum, query_rate).
  output.py       Output formatters (Rich table, JSON, CSV, HTML).
  html_template.py Self-contained HTML output with Tabulator JS (interactive table).
  pricing.py      PricingBackend ABC + LookupPricingBackend (hardcoded rate tables).
  bigquery_pricing.py  BigQueryPricingBackend: queries GCP billing export for actual costs.
  vendor/         Vendored JS/CSS (Tabulator 6.3.1) for HTML output.

  checkers/       One checker per resource type. Each lists resources, fetches
    base.py        metrics, evaluates criteria, and produces IdleResource objects.
                   BaseChecker.has_criterion() gates metric queries.
    compute.py     Compute Engine VMs
    persistent_disk.py  Persistent Disks
    bigtable.py    Bigtable clusters
    storage.py     Cloud Storage buckets
    registry.py    Maps resource type keys to checker classes.

  criteria/       Composable idleness criteria, evaluated by checkers.
    base.py        Criterion ABC and CriteriaGroup (AND/OR composition).
    cpu.py         LowCPUCriterion (threshold_percent)
    egress.py      LowEgressCriterion (threshold_bytes_per_second, sent only)
    network.py     LowNetworkCriterion (threshold_bytes_per_second, sent+received)
    memory.py      LowMemoryCriterion (threshold_percent)
    disk.py        LowDiskReadCriterion (threshold_bytes_per_second)
    requests.py    LowReadBytesCriterion (threshold_bytes_per_second)
    access.py      NoRecentAccessCriterion (days)
    __init__.py    CRITERION_REGISTRY and build_criteria_group().
```

## Checklists for Common Changes

### Adding or changing a criterion

1. `src/waste/criteria/<file>.py` — implement the criterion class
2. `src/waste/criteria/__init__.py` — add to `CRITERION_REGISTRY` and `__all__`
3. `src/waste/checkers/<checker>.py` — query the metric behind `self.has_criterion()` guard, feed into criterion's `METRIC_KEY`
4. `src/waste/config.py` — update default in `ThresholdsConfig`
5. `config.example.yaml` — update the example config
6. `tests/` — add/update criterion tests and checker tests

### Adding a new resource type

1. `src/waste/models.py` — add to `ResourceType` enum
2. `src/waste/checkers/<new>.py` — implement checker (subclass `BaseChecker`)
3. `src/waste/checkers/registry.py` — register the checker
4. `src/waste/criteria/` — add criteria if needed (see checklist above)
5. `src/waste/config.py` — add `ResourceTypeConfig` in `ThresholdsConfig`
6. `src/waste/output.py` — add `_get_detail()`, `_console_url()` cases
6b. `src/waste/html_template.py` — update HTML output if needed
7. `src/waste/pricing.py` — add pricing logic in `LookupPricingBackend`
8. `src/waste/cli.py` — add to type filter options if needed
9. `config.example.yaml` — add default config
10. `src/waste/bigquery_pricing.py` — add identifier extraction and matching
11. `tests/` — add checker tests, criterion tests, pricing tests

### Changing output columns or formatting

1. `src/waste/output.py` — `output_table()` for Rich, `output_csv()` for CSV, `_serialize_result()` for JSON
2. `src/waste/html_template.py` — `render_html()` for interactive HTML (Tabulator JS)
3. All four formats should stay in sync for the same data.

## Config Files

There are **two** places where criterion defaults live and must stay in sync:

1. `src/waste/config.py` — `ThresholdsConfig` (Python defaults, used when no YAML loaded)
2. `config.example.yaml` — example config for users (checked into git)

`config.yaml` is gitignored and is the user's personal config. Users are responsible for updating it to match their preferences.

## BigQuery Billing Export Reference

The `BigQueryPricingBackend` queries the [GCP detailed usage cost](https://cloud.google.com/billing/docs/how-to/export-data-bigquery-tables/detailed-usage) export table. Each row is a cost line item for a specific SKU applied to a specific resource during a time window.

### Key Columns

See [detailed usage cost schema](https://cloud.google.com/billing/docs/how-to/export-data-bigquery-tables/detailed-usage#schema) for the full schema. Columns used by `BigQueryPricingBackend`:

| Column | Type | Description |
|---|---|---|
| `service.description` | STRING | GCP service name (e.g., "Compute Engine", "Cloud Bigtable", "Cloud Storage") |
| `sku.description` | STRING | Billing SKU (e.g., "SSD backed PD Capacity", "Server Node") |
| `project.id` | STRING | GCP project ID |
| `resource.global_name` | STRING | Full resource URI — primary identifier for per-resource cost rollup |
| `resource.name` | STRING | Resource name (format varies by resource type, see below) |
| `cost` | FLOAT | Cost at list price |
| `cost_at_effective_price_default` | FLOAT | Cost at [effective price](https://cloud.google.com/billing/docs/how-to/export-data-bigquery-tables/detailed-usage#effective_price) (preferred over `cost` when available) |
| `usage_start_time` | TIMESTAMP | Start of usage window |

### Resource Identification by Type

**Compute VMs**
- `resource.global_name`: `//compute.googleapis.com/projects/{project_number}/zones/{zone}/instances/{instance_id}` (numeric IDs)
- `resource.name`: `projects/{project_number}/instances/{name}` (CPU/RAM SKUs) or just `{name}` (IP/network SKUs)
- A single VM has many SKU rows (CPU, RAM, GPU, IP, network). Always group by `resource.global_name`.

**Persistent Disks**
- `resource.global_name`: `//compute.googleapis.com/projects/{project_number}/zones/{zone}/disk/{disk_id}` (numeric disk ID)
- `resource.name`: Human-readable disk name
- May span multiple SKUs (capacity + provisioned IOPS + provisioned throughput)

**Cloud Bigtable**
- `resource.global_name`: `//bigtable.googleapis.com/projects/{project_id}/instances/{instance_name}`
- Billing is per-instance, not per-cluster. The backend splits costs across clusters proportionally by node count.

**Cloud Storage**
- `resource.global_name`: `//storage.googleapis.com/projects/_/buckets/{bucket_name}`
- `resource.name`: Bucket name

### Known Gaps in Billing Export

- **Vertex AI Workbench disks**: Many `-boot` and `-data-workspace` suffixed disks have zero rows in the billing export. The backend falls back to lookup table pricing for these.
- **VM `resource.name` varies by SKU**: CPU/RAM SKUs use `projects/{num}/instances/{name}`, IP/network SKUs use just `{name}`. Always group by `resource.global_name`.
- **Some VMs missing compute cost rows**: Certain VMs (e.g., Dataproc launcher VMs) have only zero-cost licensing/network rows. The backend falls back to lookup table pricing.
- **Billing data latency**: Typically hours to a day. The query excludes the most recent 4 days to avoid unsettled data.
