"""Read a finished crawl folder: the issue register, headline stats, and the
derived analyses.

Screaming Frog tells you what each URL IS. The derived layer says what the SET
of URLs MEANS: what is buried, what the internal linking starves, what the
sitemap promises that the crawl cannot find. Those are the passes an
experienced auditor runs by hand in the UI, computed from the exports instead.
"""

from __future__ import annotations

import csv
import json
import statistics
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

PRIORITY_RANK = {"High": 0, "Medium": 1, "Low": 2}
TYPE_RANK = {"Issue": 0, "Warning": 1, "Opportunity": 2}

# Priority sets the magnitude, issue type scales it: forty cosmetic
# opportunities should never outweigh one real defect.
PRIORITY_WEIGHT = {"High": 10.0, "Medium": 4.0, "Low": 1.0}
TYPE_WEIGHT = {"Issue": 1.0, "Warning": 0.6, "Opportunity": 0.3}

THIN_CONTENT_WORDS = 300
SLOW_RESPONSE_SECONDS = 1.0
HEAVY_PAGE_BYTES = 2_000_000


def load_csv(folder: Path, name: str) -> list[dict]:
    path = folder / name
    if not path.exists():
        return []
    with open(path, newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def _num(value, default=0.0) -> float:
    try:
        return float(str(value).replace(",", "").strip())
    except (TypeError, ValueError):
        return default


# ─────────────────────────────────────────────────────────────── issue register

def read_issues(folder: Path) -> list[dict]:
    """Screaming Frog's own Issues Overview, ranked."""
    issues = []
    for row in load_csv(folder, "issues_overview_report.csv"):
        issues.append({
            "issue": (row.get("Issue Name") or "").strip(),
            "type": (row.get("Issue Type") or "").strip(),
            "priority": (row.get("Issue Priority") or "").strip(),
            "urls": int(_num(row.get("URLs"))),
            "pct": round(_num(row.get("% of Total")), 2),
            "description": (row.get("Description") or "").strip(),
            "how_to_fix": (row.get("How To Fix") or "").strip(),
        })
    issues.sort(key=lambda i: (
        PRIORITY_RANK.get(i["priority"], 9),
        TYPE_RANK.get(i["type"], 9),
        -i["urls"],
    ))
    return issues


def crawl_stats(folder: Path) -> dict:
    rows = load_csv(folder, "internal_all.csv")
    stats = {"urls": 0, "status": {}, "indexable": 0, "non_indexable": 0}
    for row in rows:
        stats["urls"] += 1
        code = (row.get("Status Code") or "?").strip()
        stats["status"][code] = stats["status"].get(code, 0) + 1
        if (row.get("Indexability") or "").strip().lower() == "indexable":
            stats["indexable"] += 1
        else:
            stats["non_indexable"] += 1
    return stats


def health_score(issues: list[dict]) -> dict:
    """100 minus a priority x type weighted penalty. The formula is reported
    alongside the number, because an unexplained score is a horoscope."""
    penalty = sum(
        PRIORITY_WEIGHT.get(i["priority"], 1.0) * TYPE_WEIGHT.get(i["type"], 0.5)
        for i in issues
    )
    score = max(0, min(100, round(100 - penalty)))
    band = ("Excellent" if score >= 90 else "Good" if score >= 75
            else "Needs work" if score >= 50 else "Poor")
    return {
        "score": score,
        "band": band,
        "penalty": round(penalty, 1),
        "formula": ("100 - sum(priority_weight x type_weight) over every issue "
                    "type found. High=10, Medium=4, Low=1; "
                    "Issue=x1.0, Warning=x0.6, Opportunity=x0.3."),
    }


def summarize(folder: Path, site: str) -> dict:
    """Build (and cache) audit-summary.json for a finished crawl."""
    issues = read_issues(folder)
    stats = crawl_stats(folder)
    summary = {
        "site": site,
        "crawled_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "output_dir": str(folder),
        "stats": stats,
        "health": health_score(issues),
        "counts": {
            "high": sum(1 for i in issues if i["priority"] == "High"),
            "medium": sum(1 for i in issues if i["priority"] == "Medium"),
            "low": sum(1 for i in issues if i["priority"] == "Low"),
            "total_types": len(issues),
        },
        "issues": issues,
    }
    (folder / "audit-summary.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8")
    return summary


# ──────────────────────────────────────────────────────────── derived analyses

def _html_rows(folder: Path) -> list[dict]:
    rows = load_csv(folder, "internal_html.csv") or load_csv(folder, "internal_all.csv")
    return [r for r in rows
            if "html" in (r.get("Content Type") or "").lower()
            or not r.get("Content Type")]


def depth_analysis(rows: list[dict]) -> dict:
    """How far pages sit from the entry point. Anything past depth 3 is a page
    users and crawlers reach by accident, not by design."""
    dist = Counter()
    deep = []
    for r in rows:
        d = int(_num(r.get("Crawl Depth"), -1))
        if d < 0:
            continue
        dist[d] += 1
        if d >= 4:
            deep.append({"url": r.get("Address", ""), "depth": d})
    deep.sort(key=lambda x: -x["depth"])
    return {
        "distribution": {str(k): v for k, v in sorted(dist.items())},
        "max_depth": max(dist) if dist else 0,
        "pages_deeper_than_3": len(deep),
        "deepest": deep[:25],
        "reading": ("Pages at depth 4+ receive little internal link equity and "
                    "are crawled less often. Link them from a hub page."),
    }


def link_equity_analysis(rows: list[dict]) -> dict:
    """Which pages the internal linking starves."""
    scored = []
    orphans = []
    for r in rows:
        url = r.get("Address", "")
        inlinks = int(_num(r.get("Unique Inlinks"), 0))
        scored.append({
            "url": url,
            "unique_inlinks": inlinks,
            "link_score": int(_num(r.get("Link Score"), 0)),
        })
        if inlinks == 0:
            orphans.append(url)
    scored.sort(key=lambda x: x["unique_inlinks"])
    counts = [s["unique_inlinks"] for s in scored]
    return {
        "pages": len(scored),
        "median_unique_inlinks": statistics.median(counts) if counts else 0,
        "no_internal_inlinks": len(orphans),
        "least_linked": scored[:25],
        "reading": ("A page with zero or one unique inlink is invisible to "
                    "internal PageRank no matter how good the content is."),
    }


def sitemap_analysis(folder: Path, rows: list[dict]) -> dict:
    """What the sitemap promises versus what the crawl actually found."""
    sitemap_urls = {
        (r.get("Address") or "").strip()
        for r in load_csv(folder, "sitemaps_all.csv")
        if r.get("Address")
    }
    crawled = {(r.get("Address") or "").strip() for r in rows}
    indexable = {
        (r.get("Address") or "").strip() for r in rows
        if (r.get("Indexability") or "").strip().lower() == "indexable"
    }
    if not sitemap_urls:
        return {"available": False,
                "reading": "No sitemap export in this crawl, so nothing to reconcile."}
    in_sitemap_not_indexable = sorted(sitemap_urls - indexable)
    indexable_not_in_sitemap = sorted(indexable - sitemap_urls)
    return {
        "available": True,
        "sitemap_urls": len(sitemap_urls),
        "crawled_urls": len(crawled),
        "in_sitemap_but_not_indexable": len(in_sitemap_not_indexable),
        "indexable_but_missing_from_sitemap": len(indexable_not_in_sitemap),
        "examples_not_indexable": in_sitemap_not_indexable[:15],
        "examples_missing": indexable_not_in_sitemap[:15],
        "reading": ("A sitemap listing non-indexable URLs sends mixed signals. "
                    "An indexable page missing from the sitemap is a "
                    "discovery gap."),
    }


def content_analysis(rows: list[dict]) -> dict:
    """Word count distribution, and where thin pages cluster."""
    counts, thin = [], []
    by_folder: dict[str, list[int]] = defaultdict(list)
    for r in rows:
        wc = int(_num(r.get("Word Count"), 0))
        url = r.get("Address", "")
        counts.append(wc)
        segment = "/".join(url.split("/")[:4]) or url
        by_folder[segment].append(wc)
        if 0 < wc < THIN_CONTENT_WORDS:
            thin.append({"url": url, "words": wc})
    thin.sort(key=lambda x: x["words"])
    clusters = sorted(
        ({"section": k, "pages": len(v),
          "median_words": int(statistics.median(v))} for k, v in by_folder.items()
         if len(v) >= 3),
        key=lambda x: x["median_words"],
    )
    return {
        "pages": len(counts),
        "median_words": int(statistics.median(counts)) if counts else 0,
        "thin_pages": len(thin),
        "thin_threshold_words": THIN_CONTENT_WORDS,
        "thinnest": thin[:25],
        "thinnest_sections": clusters[:10],
        "reading": ("Thin pages matter in clusters, not individually. A whole "
                    "section below the median is a template problem."),
    }


def performance_analysis(rows: list[dict]) -> dict:
    """Response time and payload outliers."""
    slow, heavy, times = [], [], []
    for r in rows:
        url = r.get("Address", "")
        rt = _num(r.get("Response Time"), 0)
        size = _num(r.get("Size (Bytes)"), 0)
        if rt:
            times.append(rt)
        if rt >= SLOW_RESPONSE_SECONDS:
            slow.append({"url": url, "seconds": round(rt, 2)})
        if size >= HEAVY_PAGE_BYTES:
            heavy.append({"url": url, "bytes": int(size)})
    slow.sort(key=lambda x: -x["seconds"])
    heavy.sort(key=lambda x: -x["bytes"])
    return {
        "median_response_seconds": round(statistics.median(times), 3) if times else 0,
        "slow_pages": len(slow),
        "slow_threshold_seconds": SLOW_RESPONSE_SECONDS,
        "slowest": slow[:20],
        "heavy_pages": len(heavy),
        "heaviest": heavy[:20],
        "reading": ("This is server response time, not a Core Web Vitals score. "
                    "It measures the host, not the rendered page."),
    }


def indexability_analysis(rows: list[dict]) -> dict:
    """The indexable-to-crawled ratio, and why URLs drop out."""
    reasons = Counter()
    indexable = 0
    for r in rows:
        if (r.get("Indexability") or "").strip().lower() == "indexable":
            indexable += 1
        else:
            reasons[(r.get("Indexability Status") or "unknown").strip() or "unknown"] += 1
    total = len(rows)
    return {
        "crawled": total,
        "indexable": indexable,
        "non_indexable": total - indexable,
        "indexable_ratio": round(indexable / total, 3) if total else 0,
        "reasons": dict(reasons.most_common()),
        "reading": ("Non-indexable is not automatically wrong. Read the reasons: "
                    "a canonicalised duplicate is intended, a noindexed money "
                    "page is not."),
    }


def duplication_analysis(rows: list[dict]) -> dict:
    """Repeated titles and H1s that split relevance across URLs."""
    titles, h1s = defaultdict(list), defaultdict(list)
    for r in rows:
        url = r.get("Address", "")
        t = (r.get("Title 1") or "").strip()
        h = (r.get("H1-1") or "").strip()
        if t:
            titles[t].append(url)
        if h:
            h1s[h].append(url)
    dup_titles = sorted(
        ({"title": k, "count": len(v), "urls": v[:5]} for k, v in titles.items() if len(v) > 1),
        key=lambda x: -x["count"])
    dup_h1s = sorted(
        ({"h1": k, "count": len(v), "urls": v[:5]} for k, v in h1s.items() if len(v) > 1),
        key=lambda x: -x["count"])
    return {
        "duplicate_title_groups": len(dup_titles),
        "duplicate_h1_groups": len(dup_h1s),
        "worst_titles": dup_titles[:15],
        "worst_h1s": dup_h1s[:15],
        "reading": ("Two pages with the same title compete for the same query. "
                    "Search engines pick one, usually not the one you want."),
    }


def full_analysis(folder: Path) -> dict:
    rows = _html_rows(folder)
    return {
        "depth": depth_analysis(rows),
        "link_equity": link_equity_analysis(rows),
        "sitemap": sitemap_analysis(folder, rows),
        "content": content_analysis(rows),
        "performance": performance_analysis(rows),
        "indexability": indexability_analysis(rows),
        "duplication": duplication_analysis(rows),
    }
