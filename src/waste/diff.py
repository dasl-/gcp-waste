"""Extract and diff data from HTML waste reports.

Provides Python-side equivalents of the client-side JavaScript diff logic.
Useful for testing and for any future CLI diff command.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field


def extract_data_from_html(html: str) -> list[dict]:
    """Extract the embedded DATA JSON array from an HTML waste report."""
    match = re.search(r"var DATA = (\[[\s\S]*?\]);\s*$", html, re.MULTILINE)
    if not match:
        raise ValueError("Could not find 'var DATA = [...]' in HTML file")
    return json.loads(match.group(1))


def resource_key(entry: dict) -> str:
    """Composite key matching the JavaScript resourceKey() function."""
    return f"{entry['project']}\0{entry['resource_type']}\0{entry['name']}"


@dataclass
class DiffResult:
    """Result of diffing two HTML waste reports."""

    added: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)
    cost_changes: list[dict] = field(default_factory=list)

    @property
    def has_changes(self) -> bool:
        return bool(self.added or self.removed or self.cost_changes)


def diff_report_data(
    old_data: list[dict],
    new_data: list[dict],
    cost_threshold_pct: float = 25.0,
) -> DiffResult:
    """Diff two report datasets, mirroring the JavaScript applyDiff() logic.

    Args:
        old_data: Resource entries from the older report.
        new_data: Resource entries from the newer report.
        cost_threshold_pct: Flag cost changes larger than this percentage.
    """
    old_by_key = {resource_key(e): e for e in old_data}
    new_by_key = {resource_key(e): e for e in new_data}

    result = DiffResult()

    # Added: in new but not in old
    for key in new_by_key:
        if key not in old_by_key:
            result.added.append(key)

    # Removed: in old but not in new
    for key in old_by_key:
        if key not in new_by_key:
            result.removed.append(key)

    # Cost changes: in both, cost differs by > threshold
    for key in new_by_key:
        if key not in old_by_key:
            continue
        old_cost = old_by_key[key].get("est_yearly_cost")
        new_cost = new_by_key[key].get("est_yearly_cost")
        if old_cost is None or new_cost is None:
            continue
        if old_cost == 0 and new_cost == 0:
            continue
        if old_cost == 0:
            pct = float("inf")
        else:
            pct = abs(new_cost - old_cost) / abs(old_cost) * 100
        if pct > cost_threshold_pct:
            result.cost_changes.append({
                "key": key,
                "old_cost": old_cost,
                "new_cost": new_cost,
                "pct_change": pct,
            })

    return result
