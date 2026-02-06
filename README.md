# gcp-waste

GCP Idle Resource Finder — identify underutilized Google Cloud resources to reduce cloud spending.

Scans Compute Engine VMs, Bigtable clusters, and Cloud Storage buckets, querying metrics from Cloud Monitoring to determine idleness based on configurable criteria.

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
- `compute.viewer` — VM listing
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

# High concurrency with quota project to avoid rate limits
gcp-waste scan -p ".*-dev" -j 16 --quota-project my-project
```

### CLI Options

| Flag | Short | Default | Description |
|------|-------|---------|-------------|
| `--project` | `-p` | required | GCP project ID or regex pattern |
| `--type` | `-t` | `all` | Resource type: `all`, `compute`, `bigtable`, `storage` |
| `--config` | `-c` | built-in defaults | Path to config YAML |
| `--output` | `-o` | `table` | Output format: `table`, `json`, `csv` |
| `--sort` | `-s` | `cost` | Sort by: `cost`, `name`, `type`, `project`, `location`, `created` |
| `--min-age` | | | Only scan resources older than N days |
| `--idle-days` | | | Require idleness for N consecutive days |
| `--concurrency` | `-j` | `4` | Max parallel workers for API calls |
| `--quota-project` | | | GCP project for API quota (avoids default 180 req/min limit) |
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
- `low_network` — average network throughput below threshold (default: 1000 bytes/sec)
- `low_memory` — average memory usage below threshold (default: 10%, requires Ops Agent)

**Bigtable:**
- `low_requests` — average request rate below threshold (default: 1 req/sec)

**Storage:**
- `no_recent_access` — zero API requests over N days (default: 90 days)

### Criteria Modes

Control how criteria combine to determine idleness:

- `"all"` — all criteria must match (AND)
- `"any"` — any criterion can match (OR)
- `"all(low_cpu, low_network)"` — only listed criteria are decisive; others are informational
- `"any(low_cpu, low_network)"` — any of the listed criteria can match

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

See `config.example.yaml` for full documentation of all options.

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
  monitoring.py        # Cloud Monitoring API wrapper
  pricing.py           # Cost estimation
  checkers/            # Resource type scanners
    base.py            # Abstract base checker
    registry.py        # Checker registry
    compute.py         # Compute Engine VMs
    bigtable.py        # Bigtable clusters
    storage.py         # Cloud Storage buckets
  criteria/            # Composable idleness criteria
    base.py            # Criterion and CriteriaGroup
    cpu.py, network.py, memory.py, requests.py, access.py
  utils/
    permissions.py     # Permission checking with remediation hints
```
