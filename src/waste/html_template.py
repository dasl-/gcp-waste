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
    rowFormatter: function(row) {
        var data = row.getData();
        var el = row.getElement();
        el.classList.remove("diff-added", "diff-removed", "diff-cost-changed");
        if (data._diff === "added") el.classList.add("diff-added");
        else if (data._diff === "removed") el.classList.add("diff-removed");
        else if (data._diff === "cost-changed") el.classList.add("diff-cost-changed");
    },
});

table.on("tableBuilt", function() {
    // Switch to page-level scrolling with sticky header now that
    // the DOM is fully built.  During construction Tabulator's
    // default overflow:auto keeps forced layouts contained and cheap.
    var el = document.querySelector(".tabulator");
    if (el) el.style.overflow = "visible";
    var holder = document.querySelector(".tabulator-tableholder");
    if (holder) holder.style.overflow = "visible";
    var header = document.querySelector(".tabulator-header");
    if (header) {
        header.style.position = "sticky";
        header.style.top = "0";
        header.style.zIndex = "10";
    }
    document.getElementById("loading").style.display = "none";
});

// ---- Custom filter logic ----
function makeFilter(val) {
    if (!val) return null;
    try { return new RegExp(val, "i"); }
    catch(e) {
        var lower = val.toLowerCase();
        return {test: function(s) { return s.toLowerCase().indexOf(lower) !== -1; }};
    }
}

function applyFilters() {
    var projectRe = makeFilter(document.getElementById("filter-project").value.trim());
    var nameRe = makeFilter(document.getElementById("filter-name").value.trim());
    var typeVal = document.getElementById("filter-type").value;
    var minCostVal = document.getElementById("filter-min-cost").value;
    var minCost = minCostVal ? parseFloat(minCostVal) : NaN;
    var beforeVal = document.getElementById("filter-created-before").value;
    var afterVal = document.getElementById("filter-created-after").value;
    var locationRe = makeFilter(document.getElementById("filter-location").value.trim());
    var reasonRe = makeFilter(document.getElementById("filter-reason").value.trim());

    table.setFilter(function(data) {
        if (projectRe && !projectRe.test(data.project)) return false;
        if (nameRe && !nameRe.test(data.name)) return false;
        if (typeVal && data.resource_type !== typeVal) return false;
        if (!isNaN(minCost) && (data.est_yearly_cost === null || data.est_yearly_cost < minCost)) return false;
        if (beforeVal && data.created && data.created > beforeVal) return false;
        if (afterVal && data.created && data.created < afterVal) return false;
        if (locationRe && !locationRe.test(data.location)) return false;
        if (reasonRe && !reasonRe.test(data.reasons)) return false;
        return true;
    });
    updateHash();
}

// ---- Cost totaling ----
function fmtCost(v) {
    return "$" + v.toLocaleString(undefined, {minimumFractionDigits:2, maximumFractionDigits:2}) + "/yr";
}

function updateSummary(rows) {
    if (!rows) rows = table.getRows("active");
    var total = 0, count = 0;
    var addedCost = 0, removedCost = 0, changedDelta = 0;
    var hasDiff = false;
    for (var i = 0; i < rows.length; i++) {
        var d = rows[i].getData();
        count++;
        var cost = d.est_yearly_cost;
        if (cost !== null && cost !== undefined) {
            if (d._diff !== "removed") total += cost;
        }
        if (d._diff) {
            hasDiff = true;
            if (d._diff === "added" && cost != null) addedCost += cost;
            else if (d._diff === "removed" && cost != null) removedCost += cost;
            else if (d._diff === "cost-changed" && cost != null && d._old_cost != null) changedDelta += cost - d._old_cost;
        }
    }

    var el = document.getElementById("total-cost");
    if (hasDiff) {
        var parts = ["Total: " + fmtCost(total)];
        if (addedCost)    parts.push('<span class="added">+' + fmtCost(addedCost) + ' added</span>');
        if (removedCost)  parts.push('<span class="removed">\\u2212' + fmtCost(removedCost) + ' removed</span>');
        if (changedDelta) {
            var sign = changedDelta > 0 ? "+" : "\\u2212";
            parts.push('<span class="cost-changed">' + sign + fmtCost(Math.abs(changedDelta)) + ' changed</span>');
        }
        el.innerHTML = parts.join(" &nbsp; ");
    } else {
        el.textContent = "Total: " + fmtCost(total);
    }
    document.getElementById("row-count").textContent =
        count + " of " + DATA.length + " resources";
}

// ---- URL hash sync ----
var activeCompareFile = "";  // filename of the currently loaded comparison

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

    if (activeCompareFile) params.set("compare", activeCompareFile);

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

    if (params.has("compare")) {
        var file = params.get("compare");
        document.getElementById("compare-bar").classList.add("visible");
        document.getElementById("menu-btn").classList.add("active");
        var select = document.getElementById("compare-select");
        if (!select.querySelector('option[value="' + CSS.escape(file) + '"]')) {
            var opt = document.createElement("option");
            opt.value = file;
            opt.textContent = file;
            select.appendChild(opt);
        }
        select.value = file;
        loadComparisonFromUrl(file);
    }
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

// ---- Diff / Compare logic ----
var COST_THRESHOLD_PCT = 25;

function resourceKey(row) {
    return row.project + "\\0" + row.resource_type + "\\0" + row.name;
}

function extractDataFromHtml(html) {
    var match = html.match(/var DATA = (\\[[\\s\\S]*?\\]);\\s*$/m);
    if (!match) return null;
    try { return JSON.parse(match[1]); }
    catch(e) { return null; }
}

function applyDiff(oldData) {
    var oldByKey = {};
    for (var i = 0; i < oldData.length; i++) {
        oldByKey[resourceKey(oldData[i])] = oldData[i];
    }

    var addedCount = 0, removedCount = 0, costChangedCount = 0;

    // Build merged dataset: current rows with diff status + removed rows
    var merged = [];
    var currentKeys = {};
    for (var i = 0; i < DATA.length; i++) {
        var row = Object.assign({}, DATA[i]);
        var key = resourceKey(row);
        currentKeys[key] = true;

        if (!oldByKey[key]) {
            row._diff = "added";
            addedCount++;
        } else {
            var oldCost = oldByKey[key].est_yearly_cost;
            var newCost = row.est_yearly_cost;
            if (oldCost != null && newCost != null && !(oldCost === 0 && newCost === 0)) {
                var pct = oldCost === 0 ? Infinity : Math.abs(newCost - oldCost) / Math.abs(oldCost) * 100;
                if (pct > COST_THRESHOLD_PCT) {
                    row._diff = "cost-changed";
                    row._old_cost = oldCost;
                    costChangedCount++;
                }
            }
        }
        merged.push(row);
    }

    // Add removed rows (present in old, absent in current)
    for (var i = 0; i < oldData.length; i++) {
        var key = resourceKey(oldData[i]);
        if (!currentKeys[key]) {
            var row = Object.assign({}, oldData[i]);
            row._diff = "removed";
            removedCount++;
            merged.push(row);
        }
    }

    // Replace table data and apply row formatter
    table.setData(merged);

    // Update summary counts
    var summary = document.getElementById("diff-summary");
    summary.style.display = "flex";
    summary.querySelector(".added").textContent = addedCount ? "+" + addedCount + " added" : "";
    summary.querySelector(".removed").textContent = removedCount ? "\\u2212" + removedCount + " removed" : "";
    summary.querySelector(".cost-changed").textContent = costChangedCount ? "~" + costChangedCount + " cost changed" : "";

    document.getElementById("compare-clear").style.display = "";
    document.getElementById("compare-bar").classList.add("has-diff");
    if (initialized) updateHash();
}

function clearDiff() {
    table.setData(DATA);
    document.getElementById("diff-summary").style.display = "none";
    document.getElementById("compare-clear").style.display = "none";
    document.getElementById("compare-bar").classList.remove("has-diff");
    document.getElementById("compare-select").value = "";
    activeCompareFile = "";
    updateHash();
}

// Discover sibling HTML files when served from a web server
function discoverSiblingReports() {
    var select = document.getElementById("compare-select");
    // Determine base directory URL
    var loc = window.location;
    if (loc.protocol === "file:") return;  // Cannot list local directories

    var currentFile = loc.pathname.split("/").pop();
    var dirUrl = loc.href.substring(0, loc.href.lastIndexOf("/") + 1);

    fetch(dirUrl).then(function(resp) {
        if (!resp.ok) return;
        return resp.text();
    }).then(function(html) {
        if (!html) return;
        // Parse HTML or XML directory listing for .html files
        var files = [];
        // Match href="...*.html" in both HTML and XML listings
        var re = /href="([^"]*\\.html)"/gi;
        var m;
        while ((m = re.exec(html)) !== null) {
            var name = m[1];
            // Ignore full URLs to other hosts
            if (name.indexOf("://") !== -1) continue;
            // Extract just the filename
            name = name.split("/").pop();
            if (name && name !== currentFile && files.indexOf(name) === -1) {
                files.push(name);
            }
        }
        files.sort().reverse();  // newest first by name convention
        for (var i = 0; i < files.length; i++) {
            var opt = document.createElement("option");
            opt.value = files[i];
            opt.textContent = files[i];
            select.appendChild(opt);
        }
    }).catch(function() { /* ignore fetch errors */ });
}

function loadComparisonFromUrl(url) {
    fetch(url).then(function(resp) {
        if (!resp.ok) throw new Error("Failed to fetch " + url);
        return resp.text();
    }).then(function(html) {
        var oldData = extractDataFromHtml(html);
        if (!oldData) { alert("Could not parse report data from selected file."); return; }
        activeCompareFile = url.split("/").pop();
        applyDiff(oldData);
    }).catch(function(err) {
        alert("Error loading comparison file: " + err.message);
    });
}

function loadComparisonFromFile(file) {
    var reader = new FileReader();
    reader.onload = function(e) {
        var oldData = extractDataFromHtml(e.target.result);
        if (!oldData) { alert("Could not parse report data from selected file."); return; }
        activeCompareFile = file.name;
        applyDiff(oldData);
    };
    reader.readAsText(file);
}

// Wire up menu toggle
document.getElementById("menu-btn").addEventListener("click", function() {
    var bar = document.getElementById("compare-bar");
    bar.classList.toggle("visible");
    this.classList.toggle("active");
});

// Wire up compare UI
document.getElementById("compare-select").addEventListener("change", function() {
    var val = this.value;
    if (!val) return;
    loadComparisonFromUrl(val);
});

document.getElementById("compare-browse").addEventListener("click", function() {
    document.getElementById("compare-file").click();
});

document.getElementById("compare-file").addEventListener("change", function() {
    if (this.files.length > 0) loadComparisonFromFile(this.files[0]);
});

document.getElementById("compare-clear").addEventListener("click", function() {
    clearDiff();
});

discoverSiblingReports();
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
#title-bar {{
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin: 0 0 12px 0;
}}
h1 {{
    margin: 0;
    font-size: 1.4em;
    color: #e6db74;
}}
#menu-btn {{
    background: none;
    border: 1px solid #555;
    border-radius: 4px;
    padding: 4px 8px;
    cursor: pointer;
    font-size: 18px;
    line-height: 1;
    color: #75715e;
}}
#menu-btn:hover {{
    border-color: #a6e22e;
    color: #f8f8f2;
}}
#menu-btn.active {{
    border-color: #a6e22e;
    color: #a6e22e;
}}
.readme-link {{
    font-size: 0.875em;
    vertical-align: middle;
    color: #66d9ef;
    text-decoration: none;
}}
.readme-link:hover {{
    color: #a6e22e;
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
#total-cost .added {{ color: #a6e22e; font-size: 13px; font-weight: normal; }}
#total-cost .removed {{ color: #f92672; font-size: 13px; font-weight: normal; }}
#total-cost .cost-changed {{ color: #e6db74; font-size: 13px; font-weight: normal; }}
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
/* Sticky header and overflow:visible are applied via JS after tableBuilt
   to avoid O(n^2) forced-layout thrashing in Safari during construction. */
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
#loading {{
    text-align: center;
    padding: 40px;
    font-size: 16px;
    color: #75715e;
}}
/* Diff highlighting — selectors must be at least as specific as the
   Monokai row/cell overrides above (.tabulator .tabulator-tableholder
   .tabulator-table .tabulator-row = 0-4-0) to win. */
.tabulator .tabulator-tableholder .tabulator-table .tabulator-row.diff-added {{
    border-left: 3px solid #a6e22e !important;
}}
.tabulator .tabulator-tableholder .tabulator-table .tabulator-row.diff-removed {{
    border-left: 3px solid #f92672 !important;
}}
.tabulator .tabulator-tableholder .tabulator-table .tabulator-row.diff-removed .tabulator-cell {{
    text-decoration: line-through;
    opacity: 0.4;
}}
.tabulator .tabulator-tableholder .tabulator-table .tabulator-row.diff-cost-changed {{
    border-left: 3px solid #e6db74 !important;
}}
#compare-bar {{
    display: none;
    align-items: center;
    gap: 10px;
    margin-bottom: 14px;
    padding: 10px 16px;
    background: #2d2d2d;
    border: 1px solid #444;
    border-radius: 6px;
    font-size: 13px;
    color: #75715e;
}}
#compare-bar.visible {{
    display: flex;
}}
#compare-bar.has-diff {{
    border-color: #a6e22e;
}}
#compare-file {{
    display: none;
}}
#compare-select {{
    padding: 6px 8px;
    border: 1px solid #555;
    border-radius: 4px;
    background: #3e3d32;
    color: #f8f8f2;
    font-size: 13px;
    font-family: inherit;
    max-width: 300px;
}}
#compare-select:focus {{
    outline: none;
    border-color: #a6e22e;
}}
#compare-browse, #compare-clear {{
    padding: 6px 14px;
    cursor: pointer;
    border: 1px solid #555;
    border-radius: 4px;
    background: #3e3d32;
    color: #f8f8f2;
    font-size: 13px;
    font-family: inherit;
}}
#compare-browse:hover, #compare-clear:hover {{
    background: #49483e;
    border-color: #a6e22e;
}}
#compare-clear {{
    display: none;
}}
#diff-summary {{
    display: none;
    gap: 12px;
    font-size: 13px;
}}
#diff-summary .added {{ color: #a6e22e; }}
#diff-summary .removed {{ color: #f92672; }}
#diff-summary .cost-changed {{ color: #e6db74; }}
/* Muted text in cells */
.tabulator span[style*="color:#888"] {{
    color: #75715e !important;
}}
</style>
</head>
<body>
<div id="title-bar">
<h1>💸 Potential GCP Waste{readme_link}</h1>
<button id="menu-btn" title="Compare reports">&#9776;</button>
</div>

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
        <input type="text" id="filter-created-after" placeholder="yyyy-mm-dd" onfocus="this.type='date'" onblur="if(!this.value)this.type='text'">
    </label>
    <label>Created Before
        <input type="text" id="filter-created-before" placeholder="yyyy-mm-dd" onfocus="this.type='date'" onblur="if(!this.value)this.type='text'">
    </label>
    <label>Reasons
        <input type="text" id="filter-reason" placeholder="regex...">
    </label>
    <label>Min Cost ($/yr)
        <input type="number" id="filter-min-cost" placeholder="0" min="0" step="100">
    </label>
    <button id="clear-filters">Clear Filters</button>
</div>

<div id="compare-bar">
    <span>Compare:</span>
    <select id="compare-select"><option value="">Select a previous report&hellip;</option></select>
    <span style="color:#555">or</span>
    <button id="compare-browse">Browse&hellip;</button>
    <input type="file" id="compare-file" accept=".html">
    <button id="compare-clear">Clear comparison</button>
    <span id="diff-summary">
        <span class="added"></span>
        <span class="removed"></span>
        <span class="cost-changed"></span>
    </span>
</div>

<div id="summary-bar">
    <span><span id="row-count"></span> <span id="generated-date">{generated_date}</span></span>
    <span id="total-cost"></span>
</div>

<div id="loading">Loading table…</div>
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
            f' class="readme-link">README</a>'
        )

    return HTML_TEMPLATE.format(
        tabulator_css=tabulator_css,
        tabulator_js=tabulator_js,
        data_json=json.dumps(data),
        app_js=APP_JS,
        generated_date=f"· Generated {generated}",
        readme_link=readme_link,
    )
