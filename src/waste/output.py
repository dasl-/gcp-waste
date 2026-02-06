"""Output formatters for scan results."""

from __future__ import annotations

import csv
import io
import json
from dataclasses import asdict
from datetime import datetime, timezone
from typing import Literal

from rich.console import Console
from rich.table import Table

from waste.models import IdleResource, ResourceType, ScanResult

# Valid sort keys and their sort-key functions.
# Cost sorts descending (most expensive first); others sort ascending.
SORT_KEYS: dict[str, tuple[callable, bool]] = {
    "cost": (lambda r: r.estimated_yearly_cost or 0, True),
    "name": (lambda r: r.name, False),
    "type": (lambda r: r.resource_type.value, False),
    "project": (lambda r: r.project, False),
    "location": (lambda r: r.location, False),
    "created": (lambda r: r.creation_time or datetime.min.replace(tzinfo=timezone.utc), False),
}


def sort_resources(
    resources: list[IdleResource], sort_key: str = "cost"
) -> list[IdleResource]:
    """Sort resources by the given key."""
    key_func, reverse = SORT_KEYS[sort_key]
    return sorted(resources, key=key_func, reverse=reverse)


def format_cost(cost: float | None) -> str:
    """Format a cost value for display."""
    if cost is None:
        return "N/A"
    return f"${cost:,.2f}/yr"


def _format_duration(delta) -> str:
    """Format a timedelta into a human-readable duration string."""
    total_seconds = int(delta.total_seconds())
    days = total_seconds // 86400
    hours = (total_seconds % 86400) // 3600

    if days > 365:
        years = days // 365
        remaining_days = days % 365
        return f"{years}y {remaining_days}d"
    if days > 0:
        return f"{days}d {hours}h"
    return f"{hours}h"


def _format_created(resource) -> str:
    """Format creation time and, for VMs, include uptime."""
    if resource.creation_time is None:
        return ""
    created_str = resource.creation_time.strftime("%Y-%m-%d")
    if resource.resource_type == ResourceType.COMPUTE_VM:
        last_start = resource.metadata.get("last_start_time")
        if last_start:
            start_dt = datetime.fromisoformat(last_start)
            uptime = datetime.now(timezone.utc) - start_dt
            return f"{created_str}\n(up {_format_duration(uptime)})"
    return created_str


def _console_url(resource) -> str:
    """Build a Google Cloud Console URL for a resource."""
    p = resource.project
    if resource.resource_type == ResourceType.COMPUTE_VM:
        zone = resource.location
        name = resource.name
        return f"https://console.cloud.google.com/compute/instancesDetail/zones/{zone}/instances/{name}?project={p}"
    if resource.resource_type == ResourceType.BIGTABLE:
        instance_id = resource.metadata.get("instance_id", "")
        return f"https://console.cloud.google.com/bigtable/instances/{instance_id}/overview?project={p}"
    if resource.resource_type == ResourceType.STORAGE:
        return f"https://console.cloud.google.com/storage/browser/{resource.name}?project={p}"
    if resource.resource_type == ResourceType.PERSISTENT_DISK:
        zone = resource.location
        name = resource.name
        return f"https://console.cloud.google.com/compute/disksDetail/zones/{zone}/disks/{name}?project={p}"
    return ""


def _get_detail(resource) -> str:
    """Get a detail string for a resource (e.g. machine type for VMs)."""
    if resource.resource_type == ResourceType.COMPUTE_VM:
        return resource.metadata.get("machine_type", "")
    if resource.resource_type == ResourceType.BIGTABLE:
        node_count = resource.metadata.get("node_count", "")
        return f"{node_count} nodes" if node_count else ""
    if resource.resource_type == ResourceType.STORAGE:
        storage_class = resource.metadata.get("storage_class", "")
        size_gb = resource.metadata.get("size_gb", "")
        if size_gb:
            return f"{storage_class} ({float(size_gb):.1f} GB)"
        return storage_class
    if resource.resource_type == ResourceType.PERSISTENT_DISK:
        disk_type = resource.metadata.get("disk_type", "")
        size_gb = resource.metadata.get("size_gb", "")
        if size_gb:
            return f"{disk_type} ({float(size_gb):.1f} GB)"
        return disk_type
    return ""


def output_table(
    result: ScanResult,
    console: Console | None = None,
    sort: str = "cost",
) -> None:
    """Output scan results as a Rich table."""
    if console is None:
        console = Console()

    if not result.idle_resources:
        console.print(f"\nNo idle resources found in [bold]{result.project}[/bold].")
        if result.skipped_types:
            console.print(
                f"  Skipped resource types: {', '.join(result.skipped_types)}"
            )
        return

    # Detect multi-project results
    projects = {r.project for r in result.idle_resources}
    multi_project = len(projects) > 1

    title = (
        f"Idle Resources matching {result.project}"
        if multi_project
        else f"Idle Resources in {result.project}"
    )
    table = Table(title=title, show_lines=True)
    if multi_project:
        table.add_column("Project", style="bold white")
    table.add_column("Type", style="cyan", no_wrap=True)
    table.add_column("Name", style="green")
    table.add_column("Detail", style="blue")
    table.add_column("Location", style="yellow")
    table.add_column("Created", style="white")
    table.add_column("Reasons", style="red")
    table.add_column("Est. Cost", style="magenta", justify="right")

    for resource in sort_resources(result.idle_resources, sort):
        reasons = ", ".join(resource.idle_criterion_names)
        detail = _get_detail(resource)
        created = _format_created(resource)
        url = _console_url(resource)
        name = f"[link={url}]{resource.name}[/link]" if url else resource.name
        if resource.resource_type == ResourceType.PERSISTENT_DISK:
            attached = resource.metadata.get("attached_instances", "")
            if attached and attached != "unattached":
                p = resource.project
                zone = resource.location
                parts = []
                for entry in attached.split(", "):
                    instance_name = entry.split(" (")[0]
                    status = entry.split(" (")[1].rstrip(")")
                    vm_url = f"https://console.cloud.google.com/compute/instancesDetail/zones/{zone}/instances/{instance_name}?project={p}"
                    parts.append(f"[link={vm_url}]{instance_name}[/link] ({status})")
                name += "\n(" + ", ".join(parts) + ")"
            else:
                name += "\n(unattached)"
        row = []
        if multi_project:
            row.append(resource.project)
        row.extend([
            resource.resource_type.value,
            name,
            detail,
            resource.location,
            created,
            reasons,
            format_cost(resource.estimated_yearly_cost),
        ])
        table.add_row(*row)

    console.print()
    console.print(table)
    console.print(
        f"\n[bold]Total estimated yearly savings:[/bold] "
        f"[magenta]{format_cost(result.total_estimated_savings)}[/magenta]"
    )

    if result.errors:
        console.print()
        for error in result.errors:
            console.print(f"[yellow]Warning:[/yellow] {error}")

    if result.skipped_types:
        console.print(
            f"\n[yellow]Skipped resource types:[/yellow] "
            f"{', '.join(result.skipped_types)}"
        )


def _serialize_result(result: ScanResult) -> dict:
    """Convert ScanResult to a JSON-serializable dict."""
    resources = []
    for r in result.idle_resources:
        resources.append({
            "resource_type": r.resource_type.value,
            "name": r.name,
            "project": r.project,
            "location": r.location,
            "console_url": _console_url(r),
            "creation_time": (
                r.creation_time.isoformat() if r.creation_time else None
            ),
            "idle_reasons": r.idle_criterion_names,
            "estimated_yearly_cost": r.estimated_yearly_cost,
            "metadata": r.metadata,
            "criteria_details": [
                {
                    "criterion": cr.criterion_name,
                    "is_idle": cr.is_idle,
                    "reason": cr.reason,
                    "metrics": cr.metrics,
                }
                for cr in r.criterion_results
            ],
        })

    return {
        "project": result.project,
        "idle_resources": resources,
        "total_estimated_yearly_savings": result.total_estimated_savings,
        "errors": result.errors,
        "skipped_types": result.skipped_types,
    }


def output_json(
    result: ScanResult,
    console: Console | None = None,
    sort: str = "cost",
) -> None:
    """Output scan results as JSON."""
    if console is None:
        console = Console()
    result.idle_resources = sort_resources(result.idle_resources, sort)
    data = _serialize_result(result)
    console.print_json(json.dumps(data, indent=2))


def output_csv(
    result: ScanResult,
    console: Console | None = None,
    sort: str = "cost",
) -> None:
    """Output scan results as CSV."""
    if console is None:
        console = Console()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["type", "name", "detail", "project", "location", "console_url", "created", "reasons", "est_yearly_cost"])

    for resource in sort_resources(result.idle_resources, sort):
        created = resource.creation_time.isoformat() if resource.creation_time else ""
        writer.writerow([
            resource.resource_type.value,
            resource.name,
            _get_detail(resource),
            resource.project,
            resource.location,
            _console_url(resource),
            created,
            "; ".join(resource.idle_criterion_names),
            f"{resource.estimated_yearly_cost:.2f}" if resource.estimated_yearly_cost else "",
        ])

    console.print(output.getvalue())


FORMATTERS = {
    "table": output_table,
    "json": output_json,
    "csv": output_csv,
}


def output_result(
    result: ScanResult,
    format: Literal["table", "json", "csv"] = "table",
    console: Console | None = None,
    sort: str = "cost",
) -> None:
    """Output scan results in the specified format."""
    formatter = FORMATTERS[format]
    formatter(result, console, sort=sort)
