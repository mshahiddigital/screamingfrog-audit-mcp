"""Drive the Screaming Frog SEO Spider headlessly.

WHY THE FREE TIER STILL WORKS
-----------------------------
The common belief that --headless needs a licence is wrong. Verified against a
build reporting "Licence Status: Missing":

  WORKS   --headless --crawl --crawl-list --crawl-sitemap --export-tabs
          --save-report --bulk-export --output-folder --overwrite
          --skip-empty --export-format --create-sitemap
  GATED   --save-crawl / --load-crawl / crawl comparison, --config files,
          JavaScript rendering, scheduling, and the GA4 / Search Console /
          PageSpeed / Ahrefs / Moz integrations
  CAPPED  500 URLs per INVOCATION, not per site

Because the cap is per invocation, `crawl(..., full=True)` discovers URLs from
robots.txt and the sitemaps, splits them into batches under the cap, runs each
through list mode, and merges the exports. That crawls a site of any size on
the free tier.
"""

from __future__ import annotations

import csv
import re
import subprocess
import urllib.request
from pathlib import Path
from urllib.parse import urlparse

from .finder import find_binary, is_licensed

FREE_URL_CAP = 500
BATCH_SIZE = 450

UA = "Mozilla/5.0 (compatible; screaming-frog-mcp/1.0; +https://pypi.org/project/screaming-frog-mcp/)"

# The default export set: the tables that answer the questions people actually
# ask of a crawl. --skip-empty means a clean site simply produces fewer files.
REPORTS = [
    "Crawl Overview",
    "Issues Overview",
    "Redirects:All Redirects",
    "Redirects:Redirect Chains",
    "Redirects:Redirects to Error",
    "Canonicals:Canonical Chains",
    "Canonicals:Non-Indexable Canonicals",
    "Pagination:Non-200 Pagination URLs",
    "Hreflang:Non-200 hreflang URLs",
    "Insecure Content",
    "SERP Summary",
    "Orphan Pages",
    "Structured Data:Validation Errors & Warnings Summary",
    "HTTP Headers:HTTP Header Summary",
    "Accessibility:Accessibility Violations Summary",
]

TABS = [
    "Internal:All",
    "Internal:HTML",
    "Response Codes:Internal Client Error (4xx)",
    "Response Codes:Internal Server Error (5xx)",
    "Response Codes:Internal Redirection (3xx)",
    "Response Codes:Internal Blocked by Robots.txt",
    "Response Codes:External Client Error (4xx)",
    "Page Titles:Missing",
    "Page Titles:Duplicate",
    "Page Titles:Over X Characters",
    "Page Titles:Over X Pixels",
    "Page Titles:Same as H1",
    "Meta Description:Missing",
    "Meta Description:Duplicate",
    "H1:Missing",
    "H1:Duplicate",
    "H1:Multiple",
    "Images:Missing Alt Text",
    "Images:Over X kB",
    "Canonicals:Missing",
    "Canonicals:Non-Indexable Canonical",
    "Directives:Noindex",
    "Directives:Nofollow",
    "Content:Low Content Pages",
    "Content:Soft 404 Pages",
    "Content:Exact Duplicates",
    "URL:Over X Characters",
    "URL:Non ASCII Characters",
    "URL:Uppercase",
    "Security:HTTP URLs",
    "Security:Missing HSTS Header",
    "Security:Mixed Content",
    "Validation:Invalid HTML Elements in <head>",
    "Sitemaps:URLs in Sitemap",
    "Sitemaps:Orphan URLs",
]

# Accessibility ships 103 individual axe-core rule filters. The rollups carry
# the same findings without 100 near-empty files.
ACCESSIBILITY_KEEP = {
    "Accessibility:All",
    "Accessibility:Accessibility Score Poor",
    "Accessibility:Accessibility Score Needs Improvement",
    "Accessibility:Accessibility Score Good",
    "Accessibility:Best Practice Violation",
    "Accessibility:WCAG 2.0 A Violation",
    "Accessibility:WCAG 2.0 AA Violation",
    "Accessibility:WCAG 2.0 AAA Violation",
    "Accessibility:WCAG 2.1 AA Violation",
    "Accessibility:WCAG 2.2 AA Violation",
}

# The binary prints a placeholder "UNDEF:Unknown" in its own help output.
# Passing it back aborts the entire crawl with "Using UNDEF as tab is not
# supported", so it is matched on the group, not the full name.
BOGUS_GROUPS = {"UNDEF"}

_NAME_CACHE: dict[str, set[str]] = {}


# ────────────────────────────────────────────────────── filter-name validation

def accepted_names(kind: str) -> set[str]:
    """Ask the installed binary which --export-tabs / --save-report names it takes.

    Screaming Frog renames filters between versions and ONE unknown name aborts
    the whole crawl with a Java stack trace instead of skipping it. So names are
    always checked against the live binary, never trusted from this file.
    """
    if kind in _NAME_CACHE:
        return _NAME_CACHE[kind]
    binary = find_binary()
    if binary is None:
        return set()
    try:
        out = subprocess.run(
            [str(binary), "--help", kind],
            capture_output=True, text=True, timeout=180,
        ).stdout
    except (OSError, subprocess.SubprocessError):
        _NAME_CACHE[kind] = set()
        return set()
    names = {
        line.strip() for line in out.splitlines()
        if line.strip() and not line.startswith((" ", "\t", "The option"))
    }
    _NAME_CACHE[kind] = names
    return names


def _filtered(wanted: list[str], kind: str) -> tuple[list[str], list[str]]:
    accepted = accepted_names(kind)
    if not accepted:
        return wanted, []
    keep = [n for n in wanted if n in accepted]
    dropped = [n for n in wanted if n not in accepted]
    return keep, dropped


# Expert mode exports every table the build can produce, minus the groups that
# would come back permanently empty. Screaming Frog lists ~1,150 tab filters and
# over 800 of them are placeholders in the two families below, so requesting
# them costs minutes of crawl time and returns nothing.
#
# Groups that only ever fill in from a config file. Excluded unless one is
# supplied, because Screaming Frog reserves ~100 empty placeholder slots for
# each and there is no way to know which slots a config uses without reading it.
CONFIG_ONLY_GROUPS = {"AI", "Custom Extraction", "Custom JavaScript", "Custom Search"}

# Groups that need an API integration or crawl comparison, both licence-gated.
LICENCE_ONLY_GROUPS = {
    "Search Console", "Analytics", "PageSpeed", "Link Metrics", "Change Detection",
}

EXPERT_EXCLUDE_GROUPS = CONFIG_ONLY_GROUPS | LICENCE_ONLY_GROUPS


def _expert_excluded(licensed: bool, has_config: bool) -> set[str]:
    """Expert mode adapts to what the install can actually produce.

    Requesting a permanently-empty group is not harmless: it costs minutes of
    crawl time and returns nothing.
    """
    excluded = set(BOGUS_GROUPS)
    if not licensed:
        excluded |= LICENCE_ONLY_GROUPS
    if not has_config:
        excluded |= CONFIG_ONLY_GROUPS
    return excluded


def expert_tabs(licensed: bool = False, has_config: bool = False) -> list[str]:
    excluded = _expert_excluded(licensed, has_config)
    keep = []
    for name in sorted(accepted_names("export-tabs")):
        group = name.split(":", 1)[0]
        if group in excluded:
            continue
        if group == "Accessibility" and name not in ACCESSIBILITY_KEEP:
            continue
        keep.append(name)
    return keep


def expert_reports(licensed: bool = False, has_config: bool = False) -> list[str]:
    excluded = _expert_excluded(licensed, has_config)
    return [
        r for r in sorted(accepted_names("save-report"))
        if r.split(":", 1)[0] not in excluded
    ]


def export_args(out_dir: Path, everything: bool = False,
                config: str | None = None) -> list[str]:
    if everything:
        licensed, has_config = is_licensed(), bool(config)
        reports = expert_reports(licensed, has_config)
        tabs = expert_tabs(licensed, has_config)
        print(f"  Expert mode ({'licensed' if licensed else 'free'} tier): "
              f"{len(reports)} reports + {len(tabs)} tab filters", flush=True)
    else:
        reports, dropped_r = _filtered(REPORTS, "save-report")
        tabs, dropped_t = _filtered(TABS, "export-tabs")
        for name in dropped_r + dropped_t:
            print(f"  Skipping unrecognised export: {name}")

    args = ["--headless", "--output-folder", str(out_dir), "--overwrite", "--skip-empty"]
    if config:
        args += ["--config", str(Path(config).expanduser())]
    if reports:
        args += ["--save-report", ",".join(reports)]
    if tabs:
        args += ["--export-tabs", ",".join(tabs)]
    return args


# ─────────────────────────────────────────────────────────────── URL discovery

def _fetch(url: str, timeout: int = 20) -> tuple[str, int]:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read().decode("utf-8", "replace"), r.status
    except Exception:
        return "", 0


def discover_sitemaps(base: str) -> list[str]:
    """Sitemap URLs from robots.txt, falling back to the conventional paths."""
    parsed = urlparse(base)
    root = f"{parsed.scheme}://{parsed.netloc}"
    found: list[str] = []

    body, status = _fetch(f"{root}/robots.txt")
    if status == 200:
        found += re.findall(r"(?im)^\s*sitemap:\s*(\S+)", body)

    if not found:
        for guess in ("/sitemap.xml", "/sitemap_index.xml", "/sitemap-index.xml"):
            _, s = _fetch(root + guess)
            if s == 200:
                found.append(root + guess)
                break

    seen, unique = set(), []
    for url in found:
        if url not in seen:
            seen.add(url)
            unique.append(url)
    return unique


def read_sitemap(url: str, depth: int = 0) -> list[str]:
    """Read a sitemap, following sitemap-index nesting."""
    if depth > 2:
        return []
    body, status = _fetch(url, timeout=30)
    if status != 200 or not body:
        return []
    locs = re.findall(r"<loc>\s*([^<\s]+)\s*</loc>", body, re.I)
    if re.search(r"<sitemapindex", body, re.I):
        nested: list[str] = []
        for child in locs:
            nested += read_sitemap(child, depth + 1)
        return nested
    return locs


def collect_urls(base: str) -> list[str]:
    urls, seen = [], set()
    for sm in discover_sitemaps(base):
        for u in read_sitemap(sm):
            if u not in seen:
                seen.add(u)
                urls.append(u)
    return urls


# ──────────────────────────────────────────────────────────────────── crawling

def run_spider(binary: Path, url: str, out_dir: Path, everything: bool,
               config: str | None = None) -> int:
    print(f"Crawling {url} (spider mode)...", flush=True)
    return _run(binary, ["--crawl", url] + export_args(out_dir, everything, config),
                out_dir / "crawl.log")


def run_chunked(binary: Path, url: str, out_dir: Path, everything: bool,
                config: str | None = None) -> int:
    """Sitemap-driven list-mode crawl in batches, to beat the free URL cap."""
    urls = collect_urls(url)
    if not urls:
        print("No sitemap URLs found, falling back to spider mode.", flush=True)
        return run_spider(binary, url, out_dir, everything, config)

    batches = [urls[i:i + BATCH_SIZE] for i in range(0, len(urls), BATCH_SIZE)]
    print(f"Discovered {len(urls)} URLs, {len(batches)} batch(es) of <= {BATCH_SIZE}.",
          flush=True)

    parts = []
    for i, batch in enumerate(batches, 1):
        part = out_dir / f"batch-{i:02d}"
        part.mkdir(parents=True, exist_ok=True)
        listing = part / "urls.txt"
        listing.write_text("\n".join(batch) + "\n", encoding="utf-8")
        print(f"  Batch {i}/{len(batches)}: {len(batch)} URLs...", flush=True)
        _run(binary, ["--crawl-list", str(listing)] + export_args(part, everything, config),
             part / "crawl.log")
        parts.append(part)

    merge_batches(parts, out_dir)
    return 0


def _run(binary: Path, args: list[str], log_path: Path, timeout: int = 7200) -> int:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with open(log_path, "w", encoding="utf-8") as log:
        proc = subprocess.run([str(binary)] + args, stdout=log,
                              stderr=subprocess.STDOUT, timeout=timeout)
    return proc.returncode


def merge_batches(parts: list[Path], out_dir: Path) -> None:
    """Merge every CSV produced across batches, de-duplicated by first column."""
    names: set[str] = set()
    for p in parts:
        names.update(f.name for f in p.glob("*.csv"))

    for name in sorted(names):
        header, rows, seen = None, [], set()
        for p in parts:
            path = p / name
            if not path.exists():
                continue
            with open(path, newline="", encoding="utf-8-sig") as f:
                reader = csv.reader(f)
                try:
                    head = next(reader)
                except StopIteration:
                    continue
                header = header or head
                for row in reader:
                    key = row[0] if row else ""
                    if key and key in seen:
                        continue
                    seen.add(key)
                    rows.append(row)
        if header:
            with open(out_dir / name, "w", newline="", encoding="utf-8") as f:
                w = csv.writer(f)
                w.writerow(header)
                w.writerows(rows)
    print(f"Merged {len(names)} export(s) from {len(parts)} batch(es).", flush=True)
