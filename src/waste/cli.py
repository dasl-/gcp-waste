"""CLI entry point using Typer."""

import logging
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Annotated, Optional

import typer
from rich.console import Console

from waste.config import WasteConfig, load_config
from waste.criteria import build_criteria_group
from waste.models import ScanResult
from waste.monitoring import MonitoringClient
from waste.output import output_result
from waste.pricing import PricingClient
from waste.utils.permissions import PermissionChecker

logger = logging.getLogger(__name__)

app = typer.Typer(
    name="gcp-waste",
    help="GCP Idle Resource Finder - identify underutilized Google Cloud resources.",
    invoke_without_command=True,
)

console = Console()
stderr_console = Console(stderr=True)


@app.callback()
def main(ctx: typer.Context) -> None:
    """GCP Idle Resource Finder - identify underutilized Google Cloud resources."""
    if ctx.invoked_subcommand is None:
        typer.echo(ctx.get_help())
        raise typer.Exit(0)


def _setup_logging(verbose: bool) -> None:
    if verbose:
        # Show our app logs at INFO, keep noisy SDK logs at WARNING
        logging.basicConfig(level=logging.WARNING, format="%(levelname)s: %(message)s")
        logging.getLogger("waste").setLevel(logging.INFO)
    else:
        logging.basicConfig(level=logging.WARNING, format="%(levelname)s: %(message)s")


def _configure_http_pool(pool_size: int) -> None:
    """Increase default HTTP connection pool size for concurrent API calls.

    The requests library's HTTPAdapter captures DEFAULT_POOLCONNECTIONS and
    DEFAULT_POOLSIZE as default parameter values at class definition time.
    Changing the module constants after import has no effect, so we patch
    the __defaults__ tuple on HTTPAdapter.__init__ directly.
    """
    from requests.adapters import HTTPAdapter

    # HTTPAdapter.__init__(self, pool_connections=10, pool_maxsize=10, max_retries=..., pool_block=...)
    defaults = list(HTTPAdapter.__init__.__defaults__)
    defaults[0] = pool_size  # pool_connections
    defaults[1] = pool_size  # pool_maxsize
    HTTPAdapter.__init__.__defaults__ = tuple(defaults)


def _list_accessible_projects() -> list[str]:
    """List all GCP project IDs the caller has access to."""
    from google.cloud import resourcemanager_v3

    client = resourcemanager_v3.ProjectsClient()
    projects = []
    for project in client.search_projects():
        if project.state.name == "ACTIVE":
            projects.append(project.project_id)
    return sorted(projects)


def _resolve_projects(pattern: str) -> list[str]:
    """Resolve a project pattern to a list of project IDs.

    If the pattern looks like a literal project ID (alphanumeric, hyphens only),
    it's returned as-is. Otherwise, it's treated as a regex and matched against
    all accessible projects.
    """
    # A plain project ID only has lowercase letters, digits, and hyphens
    if re.fullmatch(r"[a-z][a-z0-9-]*", pattern):
        return [pattern]

    # Treat as regex
    try:
        regex = re.compile(pattern)
    except re.error as e:
        stderr_console.print(f"[red]Invalid regex:[/red] {e}")
        raise typer.Exit(1)

    stderr_console.print(f"Listing accessible projects matching [bold]{pattern}[/bold]...")
    all_projects = _list_accessible_projects()
    matched = [p for p in all_projects if regex.search(p)]

    if not matched:
        stderr_console.print(f"[red]No accessible projects match pattern:[/red] {pattern}")
        raise typer.Exit(1)

    stderr_console.print(f"Matched [bold]{len(matched)}[/bold] project(s): {', '.join(matched)}\n")
    return matched


@app.command()
def scan(
    project: Annotated[
        str,
        typer.Option("--project", "-p", help="GCP project ID or regex pattern to match multiple projects"),
    ],
    resource_type: Annotated[
        str,
        typer.Option("--type", "-t", help="Resource type: all, compute, bigtable, storage"),
    ] = "all",
    config_path: Annotated[
        Optional[Path],
        typer.Option("--config", "-c", help="Path to config YAML"),
    ] = None,
    output_format: Annotated[
        str,
        typer.Option("--output", "-o", help="Output format: table, json, csv"),
    ] = "table",
    min_age: Annotated[
        Optional[int],
        typer.Option("--min-age", help="Only scan resources older than N days"),
    ] = None,
    idle_days: Annotated[
        Optional[int],
        typer.Option("--idle-days", help="Require idleness for N consecutive days"),
    ] = None,
    verbose: Annotated[
        bool,
        typer.Option("--verbose", "-v", help="Verbose output"),
    ] = False,
    sort: Annotated[
        str,
        typer.Option("--sort", "-s", help="Sort by: cost, name, type, project, location, created"),
    ] = "cost",
    concurrency: Annotated[
        int,
        typer.Option("--concurrency", "-j", help="Max parallel workers for API calls"),
    ] = 4,
    quota_project: Annotated[
        Optional[str],
        typer.Option("--quota-project", help="GCP project to use for API quota (avoids default 180 req/min limit)"),
    ] = None,
) -> None:
    """Scan GCP project(s) for idle/underutilized resources.

    The --project flag accepts a literal project ID or a regex pattern.
    If a regex is given, all accessible projects matching the pattern are scanned.

    Examples:
        gcp-waste scan -p my-project
        gcp-waste scan -p "myorg-.*-dev"
        gcp-waste scan -p "^prod-"
    """
    _setup_logging(verbose)

    from waste.output import SORT_KEYS

    if sort not in SORT_KEYS:
        stderr_console.print(f"[red]Unknown sort key:[/red] {sort}")
        stderr_console.print(f"Valid keys: {', '.join(SORT_KEYS)}")
        raise typer.Exit(1)

    credentials = None
    if quota_project:
        import google.auth

        credentials, _ = google.auth.default(quota_project_id=quota_project)
        logger.info("Using quota project: %s", quota_project)

    logger.info("Loading configuration from %s", config_path or "defaults")
    config = load_config(config_path)
    types_to_scan = _resolve_types(resource_type)

    # Each project spawns a monitoring client + one checker client per resource
    # type, each with its own gRPC channel and OAuth token-refresh session.
    # The pool must be large enough for all of them to refresh concurrently.
    _configure_http_pool(concurrency * (len(types_to_scan) + 1))
    logger.info("Resource types to scan: %s", ", ".join(types_to_scan))
    projects = _resolve_projects(project)
    logger.info("Projects to scan: %s", ", ".join(projects))

    combined = ScanResult(project=project)

    if len(projects) == 1:
        result = _scan_project(
            projects[0], config, types_to_scan, idle_days, min_age, verbose,
            concurrency, credentials, quota_project,
        )
        combined.merge(result)
    else:
        workers = min(concurrency, len(projects))
        logger.info("Scanning %d projects with %d workers", len(projects), workers)
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = {}
            for proj in projects:
                stderr_console.print(f"Scanning [bold]{proj}[/bold]...")
                future = executor.submit(
                    _scan_project, proj, config, types_to_scan,
                    idle_days, min_age, verbose, concurrency, credentials,
                    quota_project,
                )
                futures[future] = proj

            for future in as_completed(futures):
                proj = futures[future]
                try:
                    result = future.result()
                    combined.merge(result)
                except Exception as e:
                    combined.errors.append(f"Error scanning project {proj}: {e}")
                    logger.exception("Error scanning project %s", proj)

    logger.info(
        "Scan complete: %d idle resource(s) found, estimated yearly savings: $%.2f",
        len(combined.idle_resources),
        combined.total_estimated_savings,
    )
    output_result(combined, format=output_format, console=console, sort=sort)


def _scan_project(
    project: str,
    config: WasteConfig,
    types_to_scan: list[str],
    idle_days: Optional[int],
    min_age: Optional[int],
    verbose: bool,
    max_workers: int = 4,
    credentials=None,
    quota_project: str | None = None,
) -> ScanResult:
    """Scan a single project for idle resources."""
    logger.info("[%s] Starting scan", project)
    perm_checker = PermissionChecker(project)
    perm_checker.check_and_warn_all("all", stderr_console)

    monitoring = MonitoringClient(project, credentials=credentials, quota_project=quota_project)
    pricing = PricingClient()

    result = ScanResult(project=project)

    def _run_and_collect(rtype: str) -> tuple[str, list | None, str | None]:
        """Run a checker, returning (type, idle_list, error_msg)."""
        logger.info("[%s] Scanning %s resources...", project, rtype)
        try:
            idle = _run_checker(
                rtype, project, config, monitoring, pricing,
                idle_days, min_age, max_workers, credentials,
            )
            logger.info("[%s] Found %d idle %s resource(s)", project, len(idle), rtype)
            return rtype, idle, None
        except PermissionError as e:
            logger.info("[%s] Skipping %s: permission denied", project, rtype)
            return rtype, None, str(e)
        except Exception as e:
            logger.info("[%s] Error scanning %s: %s", project, rtype, e)
            if verbose:
                logging.exception(f"Error scanning {rtype} in {project}")
            return rtype, None, f"Error scanning {rtype} in {project}: {e}"

    if len(types_to_scan) > 1:
        with ThreadPoolExecutor(max_workers=len(types_to_scan)) as executor:
            futures = {
                executor.submit(_run_and_collect, rtype): rtype
                for rtype in types_to_scan
            }
            for future in as_completed(futures):
                rtype, idle, error = future.result()
                if idle is not None:
                    result.idle_resources.extend(idle)
                if error is not None:
                    result.skipped_types.append(rtype)
                    result.errors.append(error)
    else:
        for rtype in types_to_scan:
            rtype, idle, error = _run_and_collect(rtype)
            if idle is not None:
                result.idle_resources.extend(idle)
            if error is not None:
                result.skipped_types.append(rtype)
                result.errors.append(error)

    logger.info("[%s] Scan complete", project)
    return result


def _resolve_types(resource_type: str) -> list[str]:
    """Resolve the resource type option to a list of checker keys."""
    if resource_type == "all":
        return ["compute", "bigtable", "storage", "persistent_disk"]
    if resource_type in ("compute", "bigtable", "storage", "persistent_disk"):
        return [resource_type]
    stderr_console.print(f"[red]Unknown resource type:[/red] {resource_type}")
    stderr_console.print("Valid types: all, compute, bigtable, storage, persistent_disk")
    raise typer.Exit(1)


def _run_checker(
    rtype: str,
    project: str,
    config: WasteConfig,
    monitoring: MonitoringClient,
    pricing: PricingClient,
    idle_days: Optional[int],
    min_age: Optional[int],
    max_workers: int = 4,
    credentials=None,
) -> list:
    """Run a single checker and return its idle resources."""
    from waste.checkers.registry import CHECKER_REGISTRY

    checker_cls = CHECKER_REGISTRY[rtype]
    type_config = getattr(config.thresholds, rtype)

    criteria_group = build_criteria_group(
        type_config.criteria,
        mode=type_config.criteria_mode,
    )

    effective_idle_days = idle_days if idle_days is not None else type_config.min_age_days
    effective_min_age = min_age if min_age is not None else type_config.min_age_days

    kwargs: dict = {
        "project": project,
        "config": config,
        "monitoring": monitoring,
        "pricing": pricing,
        "criteria_group": criteria_group,
        "idle_days": effective_idle_days,
        "min_age_days": effective_min_age,
        "max_workers": max_workers,
        "credentials": credentials,
    }

    if rtype == "storage" and type_config.min_size_gb is not None:
        kwargs["min_size_gb"] = type_config.min_size_gb

    checker = checker_cls(**kwargs)
    return checker.check()


if __name__ == "__main__":
    app()
