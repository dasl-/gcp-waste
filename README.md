# gcp-waste

GCP Idle Resource Finder — identify underutilized Google Cloud resources to reduce cloud spending.

Scans Compute Engine VMs, Persistent Disks, Bigtable clusters, and Cloud Storage buckets, querying metrics from Cloud Monitoring to determine idleness based on configurable criteria.

## Installation

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

For development:

```bash
pip install -e ".[dev]"
```

## Authentication

Authenticate with Google Cloud before running:

```bash
gcloud auth application-default login
```

### Required IAM Permissions

- `monitoring.viewer` — metrics access
- `compute.viewer` — VM and disk listing
- `bigtable.viewer` — Bigtable listing
- `storage.viewer` — bucket listing

Missing permissions are detected and reported with remediation hints.

## Usage

```bash
# Scan a single project
gcp-waste scan -p my-project

# Scan multiple projects matching a regex
gcp-waste scan -p "myorg-.*-dev"
gcp-waste scan -p "^prod-"

# Filter by resource type
gcp-waste scan -p my-project -t compute

# Custom config, JSON output, sorted by name
gcp-waste scan -p my-project -c config.yaml -o json -s name

# Interactive HTML report
gcp-waste scan -p my-project -o html > report.html

# Hide low-cost resources
gcp-waste scan -p my-project --min-cost 100

# High concurrency with quota project to avoid rate limits
gcp-waste scan -p ".*-dev" -j 16 --quota-project my-project
```

### CLI Options

| Flag | Short | Default | Description |
|------|-------|---------|-------------|
| `--project` | `-p` | required | GCP project ID or regex pattern |
| `--type` | `-t` | `all` | Resource type: `all`, `compute`, `persistent_disk`, `bigtable`, `storage` |
| `--config` | `-c` | built-in defaults | Path to config YAML |
| `--output` | `-o` | `table` | Output format: `table`, `json`, `csv`, `html` |
| `--sort` | `-s` | `cost` | Sort by: `cost`, `name`, `type`, `project`, `location`, `created` |
| `--min-age` | | | Only scan resources older than N days |
| `--idle-days` | | | Require idleness for N consecutive days |
| `--min-cost` | | | Hide resources with estimated yearly cost below this amount (dollars) |
| `--concurrency` | `-j` | `4` | Max parallel workers for API calls |
| `--quota-project` | | | GCP project for API quota (avoids default 180 req/min limit) |
| `--pricing-backend` | | `lookup` | Pricing backend: `lookup`, `bigquery`, or custom `dotted.module.ClassName` |
| `--bigquery-billing-table` | | | Fully-qualified BigQuery table for billing export (required for `bigquery` backend) |
| `--html-readme-uri` | | | URI to link as README in the HTML output title |
| `--verbose` | `-v` | `false` | Verbose output |

## Configuration

Copy the example config and customize:

```bash
cp config.example.yaml config.yaml
```

### Idleness Criteria

Each resource type has configurable criteria that determine whether a resource is idle:

**Compute VMs:**
- `low_cpu` — average CPU utilization below threshold (default: 5%)
- `low_network` — average network throughput (sent + received) below threshold (default: 1000 bytes/sec)
- `low_egress` — average egress (sent only) throughput below threshold (default: 1000 bytes/sec)
- `low_memory` — average memory usage below threshold (default: 10%, requires Ops Agent)

VMs that have been up for less than `min_age_days` are skipped (not enough metric data).

**Persistent Disks:**
- `low_disk_read` — average read throughput below threshold (default: 1000 bytes/sec). No data (e.g. unattached disks) is treated as idle.

**Bigtable:**
- `low_read_bytes` — average read throughput below threshold (default: 1000 bytes/sec)

**Storage:**
- `low_read_bytes` — average egress throughput below threshold (default: 1000 bytes/sec)

### Criteria Modes

Control how criteria combine to determine idleness:

- `"all"` — all criteria must match (AND)
- `"any"` — any criterion can match (OR)
- `"all(low_cpu, low_network)"` — only listed criteria are evaluated; unlisted are skipped
- `"any(low_cpu, low_network)"` — any of the listed criteria can match; unlisted are skipped

### Blocklist

Exclude known-good resources from scan results using exact names or glob patterns:

```yaml
blocklist:
  my-project:
    compute:
      - "prod-web-*"
      - "critical-db-01"
    storage:
      - "backup-*"
```

### Other Config Options

```yaml
# Exclude projects matching these regex patterns
exclude_projects:
  - ".*-sandbox"
  - "test-.*"

# Hide resources with estimated yearly cost below this amount
min_yearly_cost: 50.0
```

See `config.example.yaml` for full documentation of all options.

## BigQuery Pricing

The default `lookup` pricing backend uses hardcoded rate tables for cost estimates. For actual costs based on your billing data, use the `bigquery` backend with a [detailed usage cost](https://cloud.google.com/billing/docs/how-to/export-data-bigquery-tables/detailed-usage) billing export table.

### Setup

1. [Enable billing export to BigQuery](https://cloud.google.com/billing/docs/how-to/export-data-bigquery) with **Detailed usage cost data** enabled.
2. Note the fully-qualified table name (format: `project.dataset.gcp_billing_export_resource_v1_XXXXXX_YYYYYY_ZZZZZZ`).
3. Install the BigQuery dependency: `pip install -e ".[bigquery]"`

### Usage

```bash
# Via CLI flag
gcp-waste scan -p my-project --pricing-backend bigquery \
  --bigquery-billing-table "my-project.my_dataset.gcp_billing_export_resource_v1_AAAAAA_BBBBBB_CCCCCC"

# Or set in config.yaml to avoid repeating:
#   bigquery_billing_table: "my-project.my_dataset.gcp_billing_export_resource_v1_AAAAAA_BBBBBB_CCCCCC"
gcp-waste scan -p my-project --pricing-backend bigquery
```

The backend queries a 26-day window (30 days ago to 4 days ago, excluding recent unsettled data) and annualizes the costs. Resources not found in the billing export fall back to lookup table estimates.

## HTML Output

The `-o html` format produces a self-contained HTML file with an interactive table (powered by [Tabulator](https://tabulator.info/)). Features:

- **Sortable columns** — click column headers
- **Filter bar** — regex filtering on project/name/location/reasons, type dropdown, min cost, date range
- **Shareable URLs** — filter/sort state encoded in the URL hash fragment
- **Live cost total** — updates as you filter
- **Clickable links** — resource names link to GCP Console

```bash
gcp-waste scan -p "myorg-.*" -o html > report.html
gcp-waste scan -p my-project -o html --html-readme-uri="https://wiki/runbook" > report.html
```

## Scaling to Many Projects

### Rate Limits

The Cloud Monitoring API has a default quota of 180 requests/min/user when using Application Default Credentials. When scanning many projects concurrently, use `--quota-project` to route API quota through your own project (which typically has a much higher limit):

```bash
gcp-waste scan -p ".*" -j 16 --quota-project my-project
```

### File Descriptor Limits

High concurrency across many projects opens many gRPC connections simultaneously. On macOS the default file descriptor limit (256) may be too low, causing `Too many open files` errors. Raise it before running:

```bash
ulimit -n 2048 && gcp-waste scan -p ".*" -j 16 --quota-project my-project
```

To make this permanent, add `ulimit -n 2048` to your `~/.zshrc` or `~/.bashrc`.

## Development

```bash
# Run tests
pytest tests/ -v

# Run with coverage
pytest tests/ --cov=gcp-waste
```

## Project Structure

```
src/waste/
  cli.py              # CLI entry point (Typer)
  config.py            # YAML config loading (Pydantic)
  models.py            # IdleResource, ScanResult dataclasses
  output.py            # Table/JSON/CSV formatters (Rich)
  html_template.py     # Interactive HTML output (Tabulator JS)
  monitoring.py        # Cloud Monitoring API wrapper
  pricing.py           # Cost estimation (lookup tables)
  bigquery_pricing.py  # Cost estimation (BigQuery billing export)
  checkers/            # Resource type scanners
    base.py            # Abstract base checker
    registry.py        # Checker registry
    compute.py         # Compute Engine VMs
    persistent_disk.py # Persistent Disks
    bigtable.py        # Bigtable clusters
    storage.py         # Cloud Storage buckets
  criteria/            # Composable idleness criteria
    base.py            # Criterion and CriteriaGroup
    cpu.py, egress.py, network.py, memory.py, disk.py, requests.py, access.py
  vendor/              # Vendored JS/CSS for HTML output
  utils/
    permissions.py     # Permission checking with remediation hints
```
