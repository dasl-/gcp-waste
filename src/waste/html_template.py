"""HTML template and render function for self-contained HTML output."""

from __future__ import annotations

import html as html_mod
import json
import re
from datetime import datetime, timezone
from importlib import resources

from waste.models import ResourceType, ScanResult


def _load_vendor_file(filename: str) -> str:
    """Load a vendored file from the waste.vendor package."""
    return resources.files("waste.vendor").joinpath(filename).read_text(encoding="utf-8")


APP_JS = """\
// ---- HTML escaping utility ----
function escapeHtml(str) {
    var div = document.createElement("div");
    div.textContent = str;
    return div.innerHTML;
}

// ---- Column definitions ----
var columns = [
    {title:"Project", field:"project", minWidth:100, widthGrow:1, headerSort:true,
     cssClass:"col-project"},
    {title:"Type", field:"resource_type", minWidth:90, widthGrow:0.7, headerSort:true,
     cssClass:"col-type"},
    {title:"Name", field:"name", minWidth:160, widthGrow:2, headerSort:true,
     cssClass:"col-name",
     formatter: function(cell) {
         var row = cell.getRow().getData();
         var url = row.console_url;
         var name = escapeHtml(cell.getValue());
         var out = url ? '<a href="' + url + '" target="_blank" rel="noopener">' + name + '</a>' : name;
         if (row.attached_to) {
             var parts = row.attached_to.split("; ");
             var urls = row.attached_to_urls || [];
             var links = [];
             for (var i = 0; i < parts.length; i++) {
                 if (urls[i]) {
                     links.push('<a href="' + urls[i] + '" target="_blank" rel="noopener">' + escapeHtml(parts[i]) + '</a>');
                 } else {
                     links.push(escapeHtml(parts[i]));
                 }
             }
             out += '<br><span style="color:#75715e;font-size:0.9em">(' + links.join(", ") + ')</span>';
         }
         return out;
     }
    },
    {title:"Detail", field:"detail", minWidth:110, widthGrow:1.2, headerSort:true,
     cssClass:"col-detail", formatter:"html"
    },
    {title:"Location", field:"location", minWidth:90, widthGrow:0.8, headerSort:true,
     cssClass:"col-location"},
    {title:"Created", field:"created_detail", minWidth:100, widthGrow:0.8, headerSort:true,
     cssClass:"col-created", formatter:"html",
     sorter: function(a, b, aRow, bRow) {
         var da = aRow.getData().created || "";
         var db = bRow.getData().created || "";
         return da.localeCompare(db);
     }
    },
    {title:"Reasons", field:"reasons", minWidth:120, widthGrow:1.5, headerSort:true,
     cssClass:"col-reasons"},
    {title:"Est. Cost ($/yr)", field:"est_yearly_cost", minWidth:120, widthGrow:0.8,
     headerSort:true, sorter:"number", hozAlign:"right",
     cssClass:"col-cost",
     formatter: function(cell) {
         var v = cell.getValue();
         if (v === null || v === undefined) return "ERROR";
         var row = cell.getRow().getData();
         var prefix = row.is_estimated ? "~" : "";
         return prefix + "$" + v.toLocaleString(undefined, {minimumFractionDigits:2, maximumFractionDigits:2}) + "/yr";
     }
    },
];

// ---- Build table ----
var table = new Tabulator("#table", {
    data: DATA,
    columns: columns,
    layout: "fitColumns",
    resizableColumns: true,
    initialSort: [{column:"est_yearly_cost", dir:"desc"}],
    placeholder: "No matching resources",
    renderVertical: "basic",
});

// ---- Custom filter logic ----
function applyFilters() {
    var projectVal = document.getElementById("filter-project").value.trim();
    var nameVal = document.getElementById("filter-name").value.trim();
    var typeVal = document.getElementById("filter-type").value;
    var minCostVal = document.getElementById("filter-min-cost").value;
    var beforeVal = document.getElementById("filter-created-before").value;
    var afterVal = document.getElementById("filter-created-after").value;
    var locationVal = document.getElementById("filter-location").value.trim();
    var reasonVal = document.getElementById("filter-reason").value.trim();

    table.setFilter(function(data) {
        if (projectVal) {
            try {
                if (!new RegExp(projectVal, "i").test(data.project)) return false;
            } catch(e) {
                if (data.project.toLowerCase().indexOf(projectVal.toLowerCase()) === -1) return false;
            }
        }
        if (nameVal) {
            try {
                if (!new RegExp(nameVal, "i").test(data.name)) return false;
            } catch(e) {
                if (data.name.toLowerCase().indexOf(nameVal.toLowerCase()) === -1) return false;
            }
        }
        if (typeVal && data.resource_type !== typeVal) return false;
        if (minCostVal) {
            var minCost = parseFloat(minCostVal);
            if (!isNaN(minCost) && (data.est_yearly_cost === null || data.est_yearly_cost < minCost)) return false;
        }
        if (beforeVal && data.created) {
            if (data.created > beforeVal) return false;
        }
        if (afterVal && data.created) {
            if (data.created < afterVal) return false;
        }
        if (locationVal) {
            try {
                if (!new RegExp(locationVal, "i").test(data.location)) return false;
            } catch(e) {
                if (data.location.toLowerCase().indexOf(locationVal.toLowerCase()) === -1) return false;
            }
        }
        if (reasonVal) {
            try {
                if (!new RegExp(reasonVal, "i").test(data.reasons)) return false;
            } catch(e) {
                if (data.reasons.toLowerCase().indexOf(reasonVal.toLowerCase()) === -1) return false;
            }
        }
        return true;
    });
    updateHash();
}

// ---- Cost totaling ----
function updateSummary(rows) {
    if (!rows) rows = table.getRows("active");
    var total = 0;
    var count = 0;
    for (var i = 0; i < rows.length; i++) {
        count++;
        var cost = rows[i].getData().est_yearly_cost;
        if (cost !== null && cost !== undefined) total += cost;
    }
    document.getElementById("total-cost").textContent =
        "Total: $" + total.toLocaleString(undefined, {minimumFractionDigits:2, maximumFractionDigits:2}) + "/yr";
    document.getElementById("row-count").textContent =
        count + " of " + DATA.length + " resources";
}

// ---- URL hash sync ----
function updateHash() {
    var params = new URLSearchParams();
    var fields = {
        "project": "filter-project",
        "name": "filter-name",
        "type": "filter-type",
        "min_cost": "filter-min-cost",
        "before": "filter-created-before",
        "after": "filter-created-after",
        "location": "filter-location",
        "reason": "filter-reason"
    };
    for (var key in fields) {
        var val = document.getElementById(fields[key]).value.trim();
        if (val) params.set(key, val);
    }

    var sorters = table.getSorters();
    if (sorters.length > 0) {
        params.set("sort", sorters[0].field);
        params.set("dir", sorters[0].dir);
    }

    var hash = params.toString();
    history.replaceState(null, "", hash ? "#" + hash : window.location.pathname);
}

function loadFromHash() {
    var hash = window.location.hash.slice(1);
    if (!hash) return;
    var params = new URLSearchParams(hash);

    var fields = {
        "project": "filter-project",
        "name": "filter-name",
        "type": "filter-type",
        "min_cost": "filter-min-cost",
        "before": "filter-created-before",
        "after": "filter-created-after",
        "location": "filter-location",
        "reason": "filter-reason"
    };
    for (var key in fields) {
        if (params.has(key)) document.getElementById(fields[key]).value = params.get(key);
    }

    if (params.has("sort")) {
        var dir = params.get("dir") || "desc";
        table.setSort(params.get("sort"), dir);
    }

    applyFilters();
}

// ---- Event wiring ----
var filterTimer = null;
function debouncedApply() {
    clearTimeout(filterTimer);
    filterTimer = setTimeout(applyFilters, 300);
}

var textInputs = ["filter-project", "filter-name", "filter-min-cost", "filter-location", "filter-reason"];
for (var i = 0; i < textInputs.length; i++) {
    document.getElementById(textInputs[i]).addEventListener("input", debouncedApply);
}
document.getElementById("filter-type").addEventListener("change", applyFilters);
document.getElementById("filter-created-before").addEventListener("change", applyFilters);
document.getElementById("filter-created-after").addEventListener("change", applyFilters);

document.getElementById("clear-filters").addEventListener("click", function() {
    var allInputs = textInputs.concat(["filter-type", "filter-created-before", "filter-created-after"]);
    for (var i = 0; i < allInputs.length; i++) {
        document.getElementById(allInputs[i]).value = "";
    }
    applyFilters();
});

table.on("dataFiltered", function(filters, rows) {
    updateSummary(rows);
});
table.on("dataSorted", function() {
    if (initialized) updateHash();
});

// Initialize from URL hash. Deferred to next tick so Tabulator
// finishes all internal rendering before we apply filters.
var initialized = false;
setTimeout(function() {
    loadFromHash();
    updateSummary();
    initialized = true;
}, 0);
"""

HTML_TEMPLATE = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>💸 Potential GCP Waste</title>
<style>
{tabulator_css}
</style>
<style>
/* Monokai-inspired theme */
body {{
    font-family: "SF Mono", "Fira Code", "Fira Mono", Menlo, Consolas, monospace;
    margin: 0;
    padding: 20px;
    background: #1e1e1e;
    color: #f8f8f2;
}}
h1 {{
    margin: 0 0 12px 0;
    font-size: 1.4em;
    color: #e6db74;
}}
#filter-bar {{
    display: flex;
    flex-wrap: wrap;
    gap: 10px;
    align-items: flex-end;
    margin-bottom: 14px;
    padding: 12px 16px;
    background: #2d2d2d;
    border: 1px solid #444;
    border-radius: 6px;
}}
#filter-bar label {{
    display: flex;
    flex-direction: column;
    font-size: 12px;
    color: #75715e;
    font-weight: 600;
}}
#filter-bar input, #filter-bar select {{
    margin-top: 4px;
    padding: 6px 8px;
    border: 1px solid #555;
    border-radius: 4px;
    font-size: 13px;
    background: #3e3d32;
    color: #f8f8f2;
}}
#filter-bar input::placeholder {{
    color: #75715e;
}}
#filter-bar input[type="text"], #filter-bar input[type="number"] {{
    width: 130px;
}}
#filter-bar input:focus, #filter-bar select:focus {{
    outline: none;
    border-color: #a6e22e;
}}
#summary-bar {{
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 8px;
    padding: 0 4px;
    font-size: 14px;
    color: #f8f8f2;
}}
#total-cost {{
    font-weight: bold;
    font-size: 16px;
    color: #f92672;
}}
#row-count {{
    color: #75715e;
}}
#generated-date {{
    color: #75715e;
}}
/* Tabulator overrides for Monokai */
.tabulator {{
    background-color: #272822 !important;
    border: 1px solid #444 !important;
    border-radius: 6px;
    color: #f8f8f2 !important;
    font-family: inherit !important;
    font-size: 13px !important;
    overflow: visible !important;
}}
.tabulator .tabulator-header {{
    background-color: #3e3d32 !important;
    border-bottom: 2px solid #a6e22e !important;
    color: #a6e22e !important;
    font-weight: 600 !important;
}}
.tabulator .tabulator-header .tabulator-col {{
    background-color: #3e3d32 !important;
    border-right-color: #555 !important;
}}
.tabulator .tabulator-header .tabulator-col:hover {{
    background-color: #49483e !important;
}}
.tabulator .tabulator-header .tabulator-col .tabulator-col-content .tabulator-col-title {{
    color: #a6e22e !important;
}}
.tabulator .tabulator-header .tabulator-col.tabulator-sortable .tabulator-col-title {{
    padding-right: 20px !important;
}}
.tabulator .tabulator-header .tabulator-col .tabulator-col-sorter .tabulator-arrow {{
    border-bottom-color: #a6e22e !important;
}}
.tabulator .tabulator-tableholder .tabulator-table .tabulator-row {{
    background-color: #272822 !important;
    border-bottom: 1px solid #3e3d32 !important;
    color: #f8f8f2 !important;
}}
.tabulator .tabulator-tableholder .tabulator-table .tabulator-row:nth-child(even) {{
    background-color: #2d2d2d !important;
}}
.tabulator .tabulator-tableholder .tabulator-table .tabulator-row:hover {{
    background-color: #49483e !important;
}}
.tabulator .tabulator-tableholder .tabulator-table .tabulator-row .tabulator-cell {{
    border-right-color: #3e3d32 !important;
}}
.tabulator .tabulator-tableholder .tabulator-placeholder span {{
    color: #75715e !important;
}}
.tabulator .tabulator-footer {{
    background-color: #3e3d32 !important;
    border-top-color: #555 !important;
    color: #f8f8f2 !important;
}}
.tabulator a {{
    color: #66d9ef;
    text-decoration: underline;
    text-underline-offset: 2px;
}}
.tabulator a:hover {{
    color: #a6e22e;
}}
/* Sticky header: remove overflow from tableholder so page scrolls,
   then sticky positioning on the header works against the viewport. */
.tabulator .tabulator-tableholder {{
    overflow: visible !important;
}}
.tabulator .tabulator-header {{
    position: sticky !important;
    top: 0;
    z-index: 10;
}}
/* Cursor: default on cells, pointer only on links and sortable headers */
.tabulator .tabulator-tableholder .tabulator-table .tabulator-row .tabulator-cell {{
    cursor: default !important;
}}
.tabulator .tabulator-tableholder .tabulator-table .tabulator-row .tabulator-cell a {{
    cursor: pointer !important;
}}
.tabulator .tabulator-header .tabulator-col.tabulator-sortable {{
    cursor: pointer !important;
}}
/* Column colors matching CLI table output */
.tabulator .col-project {{ color: #f8f8f2; }}
.tabulator .col-type {{ color: #66d9ef; }}
.tabulator .col-name {{ color: #a6e22e; }}
.tabulator .col-detail {{ color: #66d9ef; }}
.tabulator .col-location {{ color: #e6db74; }}
.tabulator .col-created {{ color: #f8f8f2; }}
.tabulator .col-reasons {{ color: #ae81ff; }}
.tabulator .col-cost {{ color: #f92672; }}
#clear-filters {{
    padding: 6px 14px;
    cursor: pointer;
    border: 1px solid #555;
    border-radius: 4px;
    background: #3e3d32;
    color: #f8f8f2;
    font-size: 13px;
    font-family: inherit;
}}
#clear-filters:hover {{
    background: #49483e;
    border-color: #a6e22e;
}}
/* Muted text in cells */
.tabulator span[style*="color:#888"] {{
    color: #75715e !important;
}}
</style>
</head>
<body>
<h1>💸 Potential GCP Waste{readme_link}</h1>

<div id="filter-bar">
    <label>Project
        <input type="text" id="filter-project" placeholder="regex...">
    </label>
    <label>Type
        <select id="filter-type">
            <option value="">All</option>
            <option value="compute_vm">Compute VM</option>
            <option value="persistent_disk">Persistent Disk</option>
            <option value="bigtable">Bigtable</option>
            <option value="storage">Storage</option>
        </select>
    </label>
    <label>Name
        <input type="text" id="filter-name" placeholder="regex...">
    </label>
    <label>Location
        <input type="text" id="filter-location" placeholder="regex...">
    </label>
    <label>Created After
        <input type="date" id="filter-created-after">
    </label>
    <label>Created Before
        <input type="date" id="filter-created-before">
    </label>
    <label>Reasons
        <input type="text" id="filter-reason" placeholder="regex...">
    </label>
    <label>Min Cost ($/yr)
        <input type="number" id="filter-min-cost" placeholder="0" min="0" step="100">
    </label>
    <button id="clear-filters">Clear Filters</button>
</div>

<div id="summary-bar">
    <span><span id="row-count"></span> <span id="generated-date">{generated_date}</span></span>
    <span id="total-cost"></span>
</div>

<div id="table"></div>

<script>
{tabulator_js}
</script>
<script>
var DATA = {data_json};

{app_js}
</script>
</body>
</html>
"""


def render_html(result: ScanResult, sort: str = "cost", readme_uri: str | None = None) -> str:
    """Render ScanResult as a self-contained HTML string."""
    from waste.output import _console_url, _format_created, _get_detail, sort_resources

    tabulator_js = _load_vendor_file("tabulator.min.js")
    tabulator_css = _load_vendor_file("tabulator.min.css")

    resources = sort_resources(result.idle_resources, sort)

    data = []
    for r in resources:
        created = r.creation_time.strftime("%Y-%m-%d") if r.creation_time else ""
        created_detail = _format_created(r)
        # Put "(up ...)" on its own line in HTML
        if "\n" in created_detail:
            parts = created_detail.split("\n")
            created_detail = (
                html_mod.escape(parts[0])
                + '<br><span style="color:#75715e">'
                + html_mod.escape(parts[1])
                + "</span>"
            )
        else:
            created_detail = html_mod.escape(created_detail)

        # Add commas to GB sizes (e.g. "1000.0 GB" -> "1,000.0 GB")
        detail = _get_detail(r)
        detail = re.sub(
            r"\(([0-9]+\.?[0-9]*) (GB)\)",
            lambda m: f"({float(m.group(1)):,.1f} {m.group(2)})",
            detail,
        )
        # Put GPU info on its own line in detail
        if " + " in detail and r.resource_type == ResourceType.COMPUTE_VM:
            machine, gpu = detail.split(" + ", 1)
            detail_html = (
                html_mod.escape(machine)
                + '<br><span style="color:#75715e">'
                + html_mod.escape(gpu)
                + "</span>"
            )
        # Put size info on its own line in detail
        elif re.search(r"\([0-9,.]+\s*[KMGT]?B\)$", detail):
            detail_html = re.sub(
                r"^(.+?)\s*(\([0-9,.]+\s*[KMGT]?B\))$",
                lambda m: (
                    html_mod.escape(m.group(1))
                    + '<br><span style="color:#75715e">'
                    + html_mod.escape(m.group(2))
                    + "</span>"
                ),
                detail,
            )
        else:
            detail_html = html_mod.escape(detail)

        # Persistent disk attached instances
        attached_to = ""
        attached_to_urls: list[str] = []
        if r.resource_type == ResourceType.PERSISTENT_DISK:
            attached = r.metadata.get("attached_instances", "")
            if attached and attached != "unattached":
                parts = []
                for entry in attached.split(", "):
                    instance_name = entry.split(" (")[0]
                    status = entry.split(" (")[1].rstrip(")")
                    vm_url = (
                        f"https://console.cloud.google.com/compute/instancesDetail"
                        f"/zones/{r.location}/instances/{instance_name}?project={r.project}"
                    )
                    parts.append(f"{instance_name} ({status})")
                    attached_to_urls.append(vm_url)
                attached_to = "; ".join(parts)
            else:
                attached_to = "unattached"

        data.append({
            "project": r.project,
            "resource_type": r.resource_type.value,
            "name": r.name,
            "console_url": _console_url(r),
            "detail": detail_html,
            "attached_to": attached_to,
            "attached_to_urls": attached_to_urls,
            "location": r.location,
            "created": created,
            "created_detail": created_detail,
            "reasons": ", ".join(r.idle_criterion_names),
            "est_yearly_cost": r.estimated_yearly_cost,
            "is_estimated": r.metadata.get("pricing_source") == "lookup_fallback",
        })

    generated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    readme_link = ""
    if readme_uri:
        safe_uri = html_mod.escape(readme_uri, quote=True)
        readme_link = (
            f' <a href="{safe_uri}" target="_blank" rel="noopener"'
            f' style="font-size:0.5em;vertical-align:middle;color:#66d9ef">(README)</a>'
        )

    return HTML_TEMPLATE.format(
        tabulator_css=tabulator_css,
        tabulator_js=tabulator_js,
        data_json=json.dumps(data),
        app_js=APP_JS,
        generated_date=f"· Generated {generated}",
        readme_link=readme_link,
    )
