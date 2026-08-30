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
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

from mcp.server.fastmcp import FastMCP

from . import __version__
from .analysis import full_analysis, summarize
from .crawler import FREE_URL_CAP, accepted_names
from .finder import ENV_BINARY, find_binary, install_hint, is_licensed
from .jobs import Jobs
from .report import build as build_report_files

ENV_AUDIT_DIR = "SF_MCP_AUDIT_DIR"

AUDIT_ROOT = Path(
    os.environ.get(ENV_AUDIT_DIR) or (Path.home() / ".screaming-frog-mcp" / "audits")
).expanduser()

MAX_ROWS = 500      # hard ceiling on any row-returning tool
MAX_CELL = 300      # characters per cell before truncation

mcp = FastMCP("screaming-frog")
jobs = Jobs(AUDIT_ROOT)


# ── helpers ──────────────────────────────────────────────────────────────────

def _slug(url: str) -> str:
    host = urlparse(url if "//" in url else f"https://{url}").netloc
    return (host or url).replace("www.", "").replace(".", "-").replace("/", "-")


def _resolve(crawl: str) -> Path:
    p = Path(crawl).expanduser()
    return p.resolve() if p.is_absolute() else (AUDIT_ROOT / crawl).resolve()


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


# ── environment ──────────────────────────────────────────────────────────────

@mcp.tool()
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
                          ENV_AUDIT_DIR: "where crawl folders are written"},
    }
    if binary is None:
        result["how_to_fix"] = install_hint()
        return result
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


@mcp.tool()
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

@mcp.tool()
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
    if config:
        if not is_licensed():
            raise RuntimeError(
                "config files are a licensed Screaming Frog feature. On the free "
                "tier the Spider rejects --config, so this would fail mid-crawl. "
                "Re-run without config, or license the SEO Spider.")
        if not Path(config).expanduser().exists():
            raise RuntimeError(f"config file not found: {config}")
    url = _normalise(url)
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


@mcp.tool()
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


@mcp.tool()
def cancel_crawl(job_id: str) -> dict:
    """Stop a running crawl. Exports already written are kept."""
    job = jobs.read(job_id)
    if not jobs.running(job):
        return {"job_id": job_id, "state": job.get("state", "finished"),
                "message": "Already finished."}
    jobs.cancel(job)
    return {"job_id": job_id, "state": "cancelled", "output_dir": job["output_dir"]}


# ── reading a finished crawl ─────────────────────────────────────────────────

@mcp.tool()
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


@mcp.tool()
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


@mcp.tool()
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


@mcp.tool()
def list_exports(crawl: str, contains: str = "") -> dict:
    """List the CSV exports in a crawl folder, with row counts.

    Use this to find the right export before calling read_export.
    """
    folder = _resolve(crawl)
    if not folder.exists():
        raise ValueError(f"No such crawl: {folder.name}. Call list_crawls.")
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


@mcp.tool()
def read_export(crawl: str, export: str, columns: str = "", contains: str = "",
                limit: int = 50, offset: int = 0) -> dict:
    """Read rows from one CSV export, capped and filtered.

    crawl    folder name or absolute path
    export   file name from list_exports, e.g. 'h1_missing.csv'
             (the .csv suffix is optional)
    columns  comma-separated columns to keep. Empty returns the first 8;
             Screaming Frog exports can be 60 columns wide.
    contains substring filter matched across the whole row
    limit    max rows returned (hard ceiling 500)
    offset   skip this many matching rows, for paging
    """
    folder = _resolve(crawl)
    name = export if export.endswith(".csv") else f"{export}.csv"
    path = folder / name
    if not path.exists():
        raise ValueError(f"No export '{name}' in {folder.name}. Call list_exports first.")

    limit = max(1, min(limit, MAX_ROWS))
    wanted = [c.strip() for c in columns.split(",") if c.strip()]

    with open(path, newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        headers = reader.fieldnames or []
        keep = [c for c in wanted if c in headers] or headers[:8]
        rows, matched, taken = [], 0, 0
        for row in reader:
            if contains and contains.lower() not in " ".join(
                    str(v) for v in row.values() if v).lower():
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
    unknown = [c for c in wanted if c not in headers]
    if unknown:
        result["ignored_unknown_columns"] = unknown
    if matched > offset + len(rows):
        result["more"] = f"Call again with offset={offset + len(rows)}."
    return result


# ── reporting ────────────────────────────────────────────────────────────────

@mcp.tool()
def build_report(crawl: str, label: str = "") -> dict:
    """Write a shareable write-up of a finished crawl into its folder:
    report.md, a self-contained printable report.html, and analysis.json.

    The HTML is styled, responsive, light and dark aware, and has print rules,
    so opening it and printing to PDF produces a clean document. There is no
    bundled PDF step, deliberately: shipping a headless browser to print a page
    your browser already prints is a bad trade.

    label  display name in the report (default: the crawled site)
    """
    folder = _resolve(crawl)
    if not folder.exists():
        raise ValueError(f"No such crawl: {folder.name}. Call list_crawls.")
    if not any(folder.glob("*.csv")):
        raise ValueError(f"{folder.name} contains no exports to report on.")
    return build_report_files(folder, label)


def main() -> None:
    AUDIT_ROOT.mkdir(parents=True, exist_ok=True)
    mcp.run()


if __name__ == "__main__":
    main()
