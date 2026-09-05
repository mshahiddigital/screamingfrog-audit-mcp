"""The MCP server: Screaming Frog SEO Spider as tools.

TWO CONSTRAINTS SHAPE EVERY TOOL HERE
-------------------------------------
1. A crawl takes minutes, an MCP call should answer in seconds. `start_crawl`
   forks a detached child and returns a job_id. Nothing blocks unless the
   caller asks with `wait_seconds`.

2. A finished crawl folder is tens of megabytes of CSV. Handing that to a model
   is useless and expensive. Every read tool is capped, column-selectable and
   filterable, and `read_export` truncates long cells. Ask `get_issues` first;
   reach for raw rows only to answer a specific question.

stdio transport: nothing may be written to stdout. All child output goes to log
files inside the crawl folder.
"""

from __future__ import annotations

import csv
import json
import os
import re
import shutil
import sys
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

# The MCP SDK renamed FastMCP to MCPServer in 2.0. Both are supported, because
# pinning to one major would break half of the installs out there: a fresh
# resolve of "mcp" now lands on 2.x, while plenty of environments still hold a
# pinned 1.x. The decorator and run() signatures are identical across both.
try:                                        # mcp >= 2.0
    from mcp.server.mcpserver import MCPServer as _Server
except ImportError:                         # mcp 1.x
    from mcp.server.fastmcp import FastMCP as _Server

from . import __version__
from .analysis import full_analysis, summarize
from .crawler import (FREE_URL_CAP, OPTIONAL_FLAGS, accepted_names,
                      missing_essentials, supported_flags)
from .finder import ENV_BINARY, find_binary, install_hint, is_licensed
from .jobs import Jobs
from . import consolidate as consolidation
from .report import build as build_report_files

ENV_AUDIT_DIR = "SF_MCP_AUDIT_DIR"
ENV_ALLOWED = "SF_ALLOWED_DOMAINS"

AUDIT_ROOT = Path(
    os.environ.get(ENV_AUDIT_DIR) or (Path.home() / ".screamingfrog-audit-mcp" / "audits")
).expanduser()

MAX_ROWS = 500      # hard ceiling on any row-returning tool
MAX_CELL = 300      # characters per cell before truncation

server = _Server("screaming-frog")
jobs = Jobs(AUDIT_ROOT)


# ── helpers ──────────────────────────────────────────────────────────────────

def _slug(url: str) -> str:
    host = urlparse(url if "//" in url else f"https://{url}").netloc
    return (host or url).replace("www.", "").replace(".", "-").replace("/", "-")


def _resolve(crawl: str) -> Path:
    p = Path(crawl).expanduser()
    return p.resolve() if p.is_absolute() else (AUDIT_ROOT / crawl).resolve()


def _no_exports_reason(folder: Path, wanted: str = "") -> str:
    """Why this folder has no CSVs, phrased so the next call is obvious."""
    man = consolidation.manifest(folder)
    if not man:
        return ""
    kept = ", ".join(k["file"] for k in man.get("kept", [])) or "none"
    target = f"'{wanted}' and the other exports" if wanted else "The exports"
    return (f"{target} in {folder.name} were consolidated into "
            f"{man.get('workbook')} on {man.get('consolidated_at')} and deleted. "
            f"{man.get('deleted_count')} tables live in that workbook now, one "
            f"sheet each. Still on disk: {kept}. This tool reads CSVs, so crawl "
            f"the site again if you need to query it row by row.")


def _require_binary() -> Path:
    binary = find_binary()
    if binary is None:
        raise RuntimeError(install_hint())
    return binary


def _tail(path: Path, lines: int = 3) -> list[str]:
    if not path.exists():
        return []
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    return [ln for ln in text.splitlines() if ln.strip()][-lines:]


def _clip(value) -> str:
    value = str(value or "").replace("\n", " ").strip()
    return value if len(value) <= MAX_CELL else value[:MAX_CELL] + "…"


def _normalise(url: str) -> str:
    return url if url.startswith(("http://", "https://")) else "https://" + url


def _allowed_domains() -> list[str]:
    raw = os.environ.get(ENV_ALLOWED, "")
    return [d.strip().lower().lstrip(".") for d in raw.split(",") if d.strip()]


def _check_allowed(url: str) -> None:
    """Refuse hosts outside the allowlist, when one is configured.

    An MCP server that will crawl any host an agent names is a liability in
    unattended use: a prompt-injected or confused agent can point it at
    internal addresses or at third parties. Setting SF_ALLOWED_DOMAINS turns
    this server into one that can only ever touch sites you nominated.
    """
    allowed = _allowed_domains()
    if not allowed:
        return
    host = (urlparse(url).hostname or "").lower()
    if not any(host == d or host.endswith("." + d) for d in allowed):
        raise ValueError(
            f"{host!r} is not in {ENV_ALLOWED}. "
            f"Allowed: {', '.join(allowed)}. "
            "Add the domain to that environment variable to crawl it."
        )


# ── environment ──────────────────────────────────────────────────────────────

@server.tool()
def check_install() -> dict:
    """Report whether Screaming Frog is installed, whether it is licensed, and
    what the current limits are. Call this first if anything else fails."""
    binary = find_binary()
    licensed = is_licensed()
    result = {
        "server_version": __version__,
        "installed": binary is not None,
        "binary": str(binary) if binary else None,
        "licensed": licensed,
        "tier": "licensed" if licensed else "free",
        "url_cap_per_invocation": None if licensed else FREE_URL_CAP,
        "audit_root": str(AUDIT_ROOT),
        "env_overrides": {ENV_BINARY: "path to the SEO Spider executable",
                          ENV_AUDIT_DIR: "where crawl folders are written",
                          ENV_ALLOWED: "comma-separated domains this server may crawl"},
        "allowed_domains": _allowed_domains() or "any (no allowlist configured)",
    }
    if binary is None:
        result["how_to_fix"] = install_hint()
        return result
    flags = supported_flags()
    result["cli_flags_detected"] = len(flags)
    result["optional_flags_supported"] = {f: (f in flags) for f in OPTIONAL_FLAGS}
    gone = missing_essentials()
    if gone:
        result["warning"] = (
            f"This build is missing essential options: {', '.join(gone)}. "
            "Crawling may not work at all.")
    result["available"] = [
        "headless crawling", "spider, list and sitemap modes",
        "all tab exports", "all saved reports", "sitemap generation",
    ]
    if licensed:
        result["available"] += [
            "config files via the config argument on start_crawl",
            "JavaScript rendering and custom extraction (set in your config)",
            "the API-backed tables in everything mode, where you have connected them",
        ]
        result["note"] = (
            "No URL cap, so full=true is only useful if you prefer crawling "
            "strictly what the sitemaps list."
        )
    else:
        result["unavailable_on_free"] = [
            "save/load crawl", "crawl comparison", "config files",
            "JavaScript rendering", "scheduling",
            "GA4 / Search Console / PageSpeed / Ahrefs / Moz integrations",
        ]
        result["note"] = (
            "The free 500-URL cap is per invocation, not per site. Pass full=true "
            "to start_crawl to batch sitemap URLs past it."
        )
    return result


@server.tool()
def available_filters(kind: str = "export-tabs", contains: str = "") -> dict:
    """List the export names the INSTALLED Screaming Frog build accepts.

    Filter names change between Screaming Frog versions and a single unknown
    name aborts an entire crawl, so never guess them.

    kind      'export-tabs' or 'save-report'
    contains  search, e.g. 'Title' or 'Accessibility'
    """
    _require_binary()
    if kind not in ("export-tabs", "save-report"):
        raise ValueError("kind must be 'export-tabs' or 'save-report'")
    names = sorted(n for n in accepted_names(kind) if not n.startswith("UNDEF"))
    if contains:
        names = [n for n in names if contains.lower() in n.lower()]
    return {"kind": kind, "count": len(names), "names": names[:MAX_ROWS]}


# ── crawling ─────────────────────────────────────────────────────────────────

@server.tool()
def start_crawl(url: str, label: str = "", full: bool = False,
                everything: bool = False, config: str = "",
                wait_seconds: int = 0) -> dict:
    """Start a headless Screaming Frog crawl in the background.

    Returns a job_id immediately. Poll it with crawl_status.

    url           site to crawl, e.g. https://example.com
    label         crawl folder name (default: <host>-<date>)
    full          beat the free 500-URL cap by batching sitemap URLs through
                  list mode. Slower; use for sites over ~500 pages.
    everything    export every report and tab filter this build supports,
                  instead of the curated default set. Much slower. On a
                  licensed install this also covers the API-backed tables.
    config        path to a .seospiderconfig file. LICENSED INSTALLS ONLY:
                  config files unlock JavaScript rendering, custom extraction
                  and the API integrations. The free tier rejects them, so
                  passing one here without a licence is refused up front
                  rather than failing mid-crawl.
    wait_seconds  block up to this long, then return the summary if the crawl
                  finished. 0 returns straight away.
    """
    _require_binary()
    url = _normalise(url)
    _check_allowed(url)
    if config:
        if not is_licensed():
            raise RuntimeError(
                "config files are a licensed Screaming Frog feature. On the free "
                "tier the Spider rejects --config, so this would fail mid-crawl. "
                "Re-run without config, or license the SEO Spider.")
        if not Path(config).expanduser().exists():
            raise RuntimeError(f"config file not found: {config}")
    folder = label.strip() or f"{_slug(url)}-{datetime.now():%Y-%m-%d}"
    out_dir = (AUDIT_ROOT / folder).resolve()

    args = ["--url", url, "--output", str(out_dir)]
    if full:
        args.append("--full")
    if everything:
        args.append("--everything")
    if config:
        args += ["--config", str(Path(config).expanduser())]

    job = jobs.launch(args, out_dir, folder, {
        "url": url,
        "mode": "full (sitemap-batched)" if full else "spider",
        "everything": everything,
        "config": config or None,
    })

    if wait_seconds > 0:
        proc = jobs.handle(job["job_id"])
        deadline = time.time() + min(wait_seconds, 3600)
        while time.time() < deadline and proc is not None and proc.poll() is None:
            time.sleep(2)

    return crawl_status(job["job_id"])


@server.tool()
def crawl_status(job_id: str = "") -> dict:
    """Check a crawl started by start_crawl. Omit job_id for the most recent.

    While running: elapsed time and the last runner lines. Once finished: the
    headline counts. Then call get_issues for the register.
    """
    if not job_id:
        job_id = jobs.latest()
        if not job_id:
            return {"state": "none", "message": "No crawls have been started."}

    job = jobs.read(job_id)
    out_dir = Path(job["output_dir"])
    summary_path = out_dir / "audit-summary.json"

    if jobs.running(job):
        job["state"] = "running"
    elif job.get("state") == "cancelled":
        pass
    elif summary_path.exists():
        job["state"] = "complete"
    else:
        job["state"] = "failed"
    jobs.write(job)

    started = datetime.fromisoformat(job["started_at"])
    result = {
        "job_id": job_id,
        "state": job["state"],
        "url": job.get("url"),
        "mode": job.get("mode"),
        "crawl": out_dir.name,
        "output_dir": str(out_dir),
        "elapsed_seconds": int((datetime.now() - started).total_seconds()),
    }

    if job["state"] == "running":
        done = len(list(out_dir.glob("batch-*/internal_all.csv")))
        if done:
            result["batches_finished"] = done
        result["log_tail"] = _tail(out_dir / "runner.log", 3)
        result["hint"] = "Poll again in 30 to 60s. A 250-page site takes about a minute."
    elif job["state"] == "complete":
        s = json.loads(summary_path.read_text(encoding="utf-8"))
        result["stats"] = s.get("stats", {})
        result["counts"] = s.get("counts", {})
        result["health"] = s.get("health", {})
        result["exports_written"] = len(list(out_dir.glob("*.csv")))
        result["next"] = (f"get_issues(crawl='{out_dir.name}') for the ranked "
                          f"register, or build_report for a shareable write-up.")
        if (result["stats"].get("urls", 0) >= FREE_URL_CAP
                and job.get("mode") == "spider" and not is_licensed()):
            result["warning"] = (
                f"Hit the {FREE_URL_CAP}-URL free cap. Re-run with full=true to "
                "crawl the whole site in batches.")
    else:
        result["log_tail"] = _tail(out_dir / "runner.log", 10)
        if job["state"] == "failed":
            result["error"] = "The crawl exited without writing audit-summary.json."
    return result


@server.tool()
def cancel_crawl(job_id: str) -> dict:
    """Stop a running crawl. Exports already written are kept."""
    job = jobs.read(job_id)
    if not jobs.running(job):
        return {"job_id": job_id, "state": job.get("state", "finished"),
                "message": "Already finished."}
    jobs.cancel(job)
    return {"job_id": job_id, "state": "cancelled", "output_dir": job["output_dir"]}


# ── reading a finished crawl ─────────────────────────────────────────────────

@server.tool()
def list_crawls(limit: int = 25) -> dict:
    """List crawl folders in the audit root, newest first."""
    AUDIT_ROOT.mkdir(parents=True, exist_ok=True)
    rows = []
    for d in sorted(AUDIT_ROOT.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True):
        if not d.is_dir() or d.name.startswith("."):
            continue
        summary = d / "audit-summary.json"
        entry = {
            "crawl": d.name,
            "finished": summary.exists(),
            "modified": datetime.fromtimestamp(d.stat().st_mtime).isoformat(timespec="minutes"),
        }
        if summary.exists():
            try:
                s = json.loads(summary.read_text(encoding="utf-8"))
                entry["site"] = s.get("site")
                entry["urls"] = s.get("stats", {}).get("urls")
                entry["health"] = s.get("health", {}).get("score")
                entry["issue_counts"] = s.get("counts")
            except (OSError, json.JSONDecodeError):
                pass
        rows.append(entry)
        if len(rows) >= limit:
            break
    return {"audit_root": str(AUDIT_ROOT), "count": len(rows), "crawls": rows}


@server.tool()
def get_issues(crawl: str, priority: str = "", limit: int = 60,
               include_fixes: bool = True) -> dict:
    """The priority-ranked issue register from a finished crawl.

    This is Screaming Frog's own Issues Overview, sorted High to Low then by
    affected URLs. START HERE, not with raw CSV rows.

    crawl          folder name from list_crawls, or an absolute path
    priority       optional filter: High, Medium or Low
    include_fixes  include the description and how-to-fix text (verbose)
    """
    folder = _resolve(crawl)
    path = folder / "audit-summary.json"
    if not path.exists():
        if not folder.exists():
            raise ValueError(f"No such crawl: {folder.name}. Call list_crawls.")
        summary = summarize(folder, folder.name)     # crawl folder from elsewhere
    else:
        summary = json.loads(path.read_text(encoding="utf-8"))
        if "health" not in summary:
            summary = summarize(folder, summary.get("site", folder.name))

    issues = summary.get("issues", [])
    if priority:
        issues = [i for i in issues if i["priority"].lower() == priority.lower()]
    if not include_fixes:
        issues = [{k: v for k, v in i.items() if k not in ("description", "how_to_fix")}
                  for i in issues]
    return {
        "site": summary.get("site"),
        "crawl": folder.name,
        "crawled_at": summary.get("crawled_at"),
        "stats": summary.get("stats"),
        "health": summary.get("health"),
        "counts": summary.get("counts"),
        "total_matching": len(issues),
        "returned": min(len(issues), limit),
        "issues": issues[:limit],
    }


@server.tool()
def get_analysis(crawl: str, section: str = "") -> dict:
    """The derived analysis: what the SET of URLs means, not what each URL is.

    Sections: depth, link_equity, sitemap, content, performance, indexability,
    duplication. Each carries a 'reading' line explaining how to interpret it.

    section  return one section only. Omit for all of them (large).
    """
    folder = _resolve(crawl)
    if not folder.exists():
        raise ValueError(f"No such crawl: {folder.name}. Call list_crawls.")

    cached = folder / "analysis.json"
    if cached.exists():
        data = json.loads(cached.read_text(encoding="utf-8"))
        source = "analysis.json"
    else:
        data = full_analysis(folder)
        cached.write_text(json.dumps(data, indent=2), encoding="utf-8")
        source = "computed"

    if section:
        if section not in data:
            raise ValueError(f"No section '{section}'. Available: {', '.join(sorted(data))}")
        return {"crawl": folder.name, "source": source, section: data[section]}
    return {"crawl": folder.name, "source": source,
            "sections": sorted(data), "analysis": data}


@server.tool()
def list_exports(crawl: str, contains: str = "") -> dict:
    """List the CSV exports in a crawl folder, with row counts.

    Use this to find the right export before calling read_export.
    """
    folder = _resolve(crawl)
    if not folder.exists():
        raise ValueError(f"No such crawl: {folder.name}. Call list_crawls.")
    if not any(folder.glob("*.csv")):
        reason = _no_exports_reason(folder)
        if reason:
            return {"crawl": folder.name, "count": 0, "exports": [],
                    "consolidated": True, "message": reason}
    rows = []
    for f in sorted(folder.glob("*.csv")):
        if contains and contains.lower() not in f.name.lower():
            continue
        try:
            with open(f, newline="", encoding="utf-8-sig") as fh:
                n = max(sum(1 for _ in fh) - 1, 0)
        except OSError:
            n = -1
        rows.append({"export": f.name, "rows": n})
    rows.sort(key=lambda r: -r["rows"])
    return {"crawl": folder.name, "count": len(rows), "exports": rows}


@server.tool()
def read_export(crawl: str, export: str, columns: str = "", contains: str = "",
                column: str = "", mode: str = "contains",
                limit: int = 50, offset: int = 0) -> dict:
    """Read rows from one CSV export, capped and filtered.

    crawl    folder name or absolute path
    export   file name from list_exports, e.g. 'h1_missing.csv'
             (the .csv suffix is optional)
    columns  comma-separated columns to keep. Empty returns the first 8;
             Screaming Frog exports can be 60 columns wide.
    contains the filter value. Empty returns everything.
    column   restrict the filter to one column. Empty matches across the row.
    mode     'contains' (default, case-insensitive substring), 'exact'
             (case-insensitive full match) or 'regex' (Python regex).
    limit    max rows returned (hard ceiling 500)
    offset   skip this many matching rows, for paging
    """
    folder = _resolve(crawl)
    name = export if export.endswith(".csv") else f"{export}.csv"
    path = folder / name
    if not path.exists():
        raise ValueError(_no_exports_reason(folder, name) or
                         f"No export '{name}' in {folder.name}. Call list_exports first.")

    limit = max(1, min(limit, MAX_ROWS))
    wanted = [c.strip() for c in columns.split(",") if c.strip()]
    match = _matcher(contains, mode)

    with open(path, newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        headers = reader.fieldnames or []
        if column and column not in headers:
            raise ValueError(
                f"No column {column!r} in {name}. Columns: {', '.join(headers)}")
        keep = [c for c in wanted if c in headers] or headers[:8]
        rows, matched, taken = [], 0, 0
        for row in reader:
            if not match(_field(row, column)):
                continue
            matched += 1
            if matched <= offset:
                continue
            if taken < limit:
                rows.append({c: _clip(row.get(c, "")) for c in keep})
                taken += 1

    result = {
        "crawl": folder.name, "export": name,
        "all_columns": headers,
        "columns_returned": keep,
        "total_matching_rows": matched,
        "returned": len(rows),
        "offset": offset,
        "rows": rows,
    }
    result["filter"] = {"contains": contains, "column": column or "any", "mode": mode} \
        if contains else None
    unknown = [c for c in wanted if c not in headers]
    if unknown:
        result["ignored_unknown_columns"] = unknown
    if matched > offset + len(rows):
        result["more"] = f"Call again with offset={offset + len(rows)}."
    return result


def _field(row: dict, column: str) -> str:
    """One column's value, or the whole row joined, for filtering."""
    if column:
        return str(row.get(column) or "")
    return " ".join(str(v) for v in row.values() if v)


def _matcher(needle: str, mode: str):
    """Build a predicate for the requested filter mode."""
    if not needle:
        return lambda _: True
    if mode == "exact":
        target = needle.lower()
        return lambda value: value.lower() == target
    if mode == "regex":
        try:
            rx = re.compile(needle, re.I)
        except re.error as e:
            raise ValueError(f"Invalid regex {needle!r}: {e}") from None
        return lambda value: rx.search(value) is not None
    if mode != "contains":
        raise ValueError(f"mode must be contains, exact or regex, not {mode!r}")
    target = needle.lower()
    return lambda value: target in value.lower()


@server.tool()
def aggregate_export(crawl: str, export: str, group_by: str,
                     contains: str = "", column: str = "",
                     mode: str = "contains", metric: str = "",
                     limit: int = 30) -> dict:
    """Count and group rows WITHOUT returning them.

    Answers "how many 404s", "status code distribution", "which folder holds
    the thin pages" in one small response, instead of paging thousands of rows
    through the model to count them by hand. Reach for this before read_export
    whenever the question is "how many" or "broken down by".

    group_by  the column to group on, e.g. 'Status Code' or 'Indexability'
    metric    optional numeric column to summarise per group (sum/avg/min/max),
              e.g. 'Word Count'
    contains / column / mode  the same filter as read_export, applied first
    limit     max groups returned, largest first (hard ceiling 500)
    """
    folder = _resolve(crawl)
    name = export if export.endswith(".csv") else f"{export}.csv"
    path = folder / name
    if not path.exists():
        raise ValueError(_no_exports_reason(folder, name) or
                         f"No export '{name}' in {folder.name}. Call list_exports first.")

    limit = max(1, min(limit, MAX_ROWS))
    match = _matcher(contains, mode)
    groups: dict[str, int] = {}
    values: dict[str, list] = {}
    matched = 0

    with open(path, newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        headers = reader.fieldnames or []
        for label, col in (("group_by", group_by), ("column", column), ("metric", metric)):
            if col and col not in headers:
                raise ValueError(
                    f"No column {col!r} for {label} in {name}. "
                    f"Columns: {', '.join(headers)}")
        for row in reader:
            if not match(_field(row, column)):
                continue
            matched += 1
            key = (row.get(group_by) or "(blank)").strip() or "(blank)"
            groups[key] = groups.get(key, 0) + 1
            if metric:
                raw = str(row.get(metric) or "").replace(",", "").strip()
                try:
                    values.setdefault(key, []).append(float(raw))
                except ValueError:
                    pass

    ordered = sorted(groups.items(), key=lambda kv: -kv[1])[:limit]
    out = []
    for key, count in ordered:
        entry = {"value": key, "rows": count,
                 "pct": round(100 * count / matched, 1) if matched else 0.0}
        nums = values.get(key)
        if nums:
            entry["metric"] = {
                "column": metric, "sum": round(sum(nums), 2),
                "avg": round(sum(nums) / len(nums), 2),
                "min": min(nums), "max": max(nums),
            }
        out.append(entry)

    return {
        "crawl": folder.name, "export": name, "group_by": group_by,
        "rows_matched": matched, "distinct_values": len(groups),
        "returned": len(out), "groups": out,
    }


@server.tool()
def storage_summary(limit: int = 25) -> dict:
    """Disk used by saved crawls, largest first.

    Crawl folders are never cleaned up automatically, and an --everything run
    writes hundreds of CSVs, so this is how you find what to delete.
    """
    AUDIT_ROOT.mkdir(parents=True, exist_ok=True)
    rows, total = [], 0
    for d in AUDIT_ROOT.iterdir():
        if not d.is_dir() or d.name.startswith("."):
            continue
        size = files = 0
        for f in d.rglob("*"):
            if f.is_file():
                try:
                    size += f.stat().st_size
                except OSError:
                    pass
                files += 1
        total += size
        rows.append({"crawl": d.name, "mb": round(size / 1_048_576, 2),
                     "files": files,
                     "modified": datetime.fromtimestamp(
                         d.stat().st_mtime).isoformat(timespec="minutes")})
    rows.sort(key=lambda r: -r["mb"])
    return {
        "audit_root": str(AUDIT_ROOT),
        "crawls": len(rows),
        "total_mb": round(total / 1_048_576, 2),
        "largest": rows[:max(1, min(limit, MAX_ROWS))],
    }


@server.tool()
def delete_crawl(crawl: str, confirm: bool = False) -> dict:
    """Permanently delete one crawl folder and everything in it.

    Destructive and irreversible, so it requires confirm=true and refuses any
    path outside the audit root. Check storage_summary first.
    """
    folder = _resolve(crawl)
    root = AUDIT_ROOT.resolve()
    if not folder.is_dir():
        raise ValueError(f"No such crawl: {folder.name}")
    # Never let a crafted path escape the audit root.
    if root != folder and root not in folder.parents:
        raise ValueError(
            f"Refusing to delete {folder}: outside the audit root {root}.")
    if folder == root:
        raise ValueError("Refusing to delete the audit root itself.")

    size = sum(f.stat().st_size for f in folder.rglob("*") if f.is_file())
    if not confirm:
        return {
            "crawl": folder.name, "deleted": False,
            "would_free_mb": round(size / 1_048_576, 2),
            "confirm_required": "Call again with confirm=true to delete this permanently.",
        }
    shutil.rmtree(folder)
    return {"crawl": folder.name, "deleted": True,
            "freed_mb": round(size / 1_048_576, 2)}


# ── reporting ────────────────────────────────────────────────────────────────

@server.tool()
def build_report(crawl: str, label: str = "", consolidate: bool = False) -> dict:
    """Write the branded deliverable for a finished crawl into its folder.

    Produces four files:
      audit-workbook.xlsx  the master workbook — Summary, Issue register,
                           Analysis, a Data index, and EVERY crawl export as
                           its own styled sheet. Purple headers, banded rows,
                           frozen panes, autofilter, coloured tabs, and cells
                           highlighted where the value IS the finding: issue
                           priority, 4xx/5xx status, non-indexable, thin
                           content, slow responses.
      report.html          printable, brand-coloured, with a masthead
      report.md            the same content as plain text
      analysis.json        the derived layer, machine-readable

    There is no bundled PDF step, deliberately: shipping a headless browser to
    print a page your browser already prints is a bad trade. Open the HTML and
    use Print to PDF; the stylesheet has print rules.

    label        the audited business or site name shown on the report
    consolidate  true leaves ONE master workbook behind: each export is written
                 to its own sheet, the saved workbook is reopened and checked
                 row by row, and only then are the CSVs deleted, with a
                 consolidated.json manifest recording what went where. Anything
                 too large to carry in full is kept and named. Off by default,
                 because read_export and aggregate_export need those CSVs — turn
                 it on when the folder is a finished deliverable rather than a
                 crawl you are still asking questions about.
    """
    folder = _resolve(crawl)
    if not folder.exists():
        raise ValueError(f"No such crawl: {folder.name}. Call list_crawls.")
    if not any(folder.glob("*.csv")):
        raise ValueError(_no_exports_reason(folder) or
                         f"{folder.name} contains no exports to report on.")
    return build_report_files(folder, label, consolidate=consolidate)


def main() -> None:
    # --doctor runs the same checks in a normal terminal. An MCP server speaks
    # stdio, so a startup failure is invisible in the client; this is the only
    # way a user can see why.
    if "--doctor" in sys.argv[1:]:
        from .doctor import run
        raise SystemExit(run())
    if {"-h", "--help"} & set(sys.argv[1:]):
        print("screamingfrog-audit-mcp — MCP server for the Screaming Frog SEO Spider\n")
        print("  screamingfrog-audit-mcp            run the server (stdio, for MCP clients)")
        print("  screamingfrog-audit-mcp --doctor   check this machine and print a client config")
        raise SystemExit(0)

    AUDIT_ROOT.mkdir(parents=True, exist_ok=True)
    server.run()


if __name__ == "__main__":
    main()
