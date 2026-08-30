"""Render a finished crawl as a plain Markdown report and a self-contained,
printable HTML page.

Deliberately unbranded and dependency-free. There is no PDF step, because
pulling in a headless browser to print a page you can print from your browser
is a poor trade for everyone installing this. Open the HTML and use Print to
PDF; the stylesheet has print rules.
"""

from __future__ import annotations

import html
import json
from datetime import datetime
from pathlib import Path

from .analysis import full_analysis, summarize

CSS = """
:root{--bg:#fff;--fg:#16181d;--muted:#646b7a;--line:#e4e7ec;--card:#f7f8fa;
--high:#c02626;--med:#b06a00;--low:#5b6472;--accent:#2c5fd8}
@media (prefers-color-scheme:dark){:root{--bg:#14161a;--fg:#e8eaed;--muted:#9aa3b2;
--line:#2a2e36;--card:#1c1f25;--high:#ff6b6b;--med:#e2a03f;--low:#8b94a3;--accent:#7aa2f7}}
*{box-sizing:border-box}
body{margin:0;padding:2.5rem 1.25rem;background:var(--bg);color:var(--fg);
font:15px/1.6 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif}
main{max-width:60rem;margin:0 auto}
h1{font-size:1.9rem;margin:0 0 .25rem}
h2{font-size:1.2rem;margin:2.5rem 0 .75rem;padding-bottom:.4rem;border-bottom:1px solid var(--line)}
h3{font-size:1rem;margin:1.5rem 0 .5rem}
.sub{color:var(--muted);margin:0 0 2rem}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(9rem,1fr));gap:.75rem;margin:1rem 0}
.stat{background:var(--card);border:1px solid var(--line);border-radius:.5rem;padding:.85rem}
.stat b{display:block;font-size:1.6rem;line-height:1.2}
.stat span{color:var(--muted);font-size:.8rem}
.wrap{overflow-x:auto;-webkit-overflow-scrolling:touch}
table{border-collapse:collapse;width:100%;font-size:.85rem;margin:.5rem 0}
th,td{text-align:left;padding:.5rem .6rem;border-bottom:1px solid var(--line);vertical-align:top}
th{color:var(--muted);font-weight:600;white-space:nowrap}
td.u{word-break:break-all;max-width:28rem}
.chip{display:inline-block;padding:.1rem .5rem;border-radius:1rem;font-size:.75rem;
font-weight:600;color:#fff}
.High{background:var(--high)}.Medium{background:var(--med)}.Low{background:var(--low)}
.note{color:var(--muted);font-size:.85rem;margin:.4rem 0 0}
footer{margin-top:3rem;padding-top:1rem;border-top:1px solid var(--line);
color:var(--muted);font-size:.8rem}
@media print{body{padding:0;font-size:11pt}h2{page-break-after:avoid}
table{page-break-inside:auto}tr{page-break-inside:avoid}.stat{break-inside:avoid}}
"""


def _e(v) -> str:
    return html.escape(str(v if v is not None else ""))


def _table(headers: list[str], rows: list[list], empty: str = "Nothing found.") -> str:
    if not rows:
        return f'<p class="note">{_e(empty)}</p>'
    head = "".join(f"<th>{_e(h)}</th>" for h in headers)
    body = "".join(
        "<tr>" + "".join(f"<td>{c}</td>" for c in r) + "</tr>" for r in rows
    )
    return f'<div class="wrap"><table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>'


# ──────────────────────────────────────────────────────────────────── markdown

def markdown_report(summary: dict, analysis: dict, label: str) -> str:
    h = summary["health"]
    s = summary["stats"]
    c = summary["counts"]
    out = [
        f"# Technical SEO crawl: {label}",
        "",
        f"Crawled {summary['crawled_at']} | {s['urls']} URLs | "
        f"health {h['score']}/100 ({h['band']})",
        "",
        "## Headline",
        "",
        f"- URLs crawled: **{s['urls']}**",
        f"- Indexable: **{s['indexable']}** | non-indexable: **{s['non_indexable']}**",
        f"- Issue types: **{c['total_types']}** "
        f"(High {c['high']}, Medium {c['medium']}, Low {c['low']})",
        f"- Status codes: " + ", ".join(f"{k}: {v}" for k, v in sorted(s["status"].items())),
        "",
        f"Health score formula: {h['formula']}",
        "",
        "## Issue register",
        "",
        "| Priority | Type | URLs | Issue |",
        "|---|---|---:|---|",
    ]
    for i in summary["issues"]:
        out.append(f"| {i['priority']} | {i['type']} | {i['urls']} | {i['issue']} |")
    if not summary["issues"]:
        out.append("| - | - | 0 | No issues reported |")

    out += ["", "## What the set of URLs means", ""]
    d, le = analysis["depth"], analysis["link_equity"]
    ct, ix = analysis["content"], analysis["indexability"]
    perf, dup = analysis["performance"], analysis["duplication"]
    out += [
        f"- **Depth**: max {d['max_depth']}, {d['pages_deeper_than_3']} pages deeper than 3. {d['reading']}",
        f"- **Link equity**: median {le['median_unique_inlinks']} unique inlinks, "
        f"{le['no_internal_inlinks']} pages with none. {le['reading']}",
        f"- **Content**: median {ct['median_words']} words, {ct['thin_pages']} under "
        f"{ct['thin_threshold_words']}. {ct['reading']}",
        f"- **Indexability**: {ix['indexable']}/{ix['crawled']} indexable "
        f"({ix['indexable_ratio']:.0%}). {ix['reading']}",
        f"- **Performance**: median {perf['median_response_seconds']}s response, "
        f"{perf['slow_pages']} slow, {perf['heavy_pages']} heavy. {perf['reading']}",
        f"- **Duplication**: {dup['duplicate_title_groups']} duplicate title groups, "
        f"{dup['duplicate_h1_groups']} duplicate H1 groups. {dup['reading']}",
    ]
    sm = analysis["sitemap"]
    if sm.get("available"):
        out.append(
            f"- **Sitemap**: {sm['sitemap_urls']} listed, "
            f"{sm['in_sitemap_but_not_indexable']} not indexable, "
            f"{sm['indexable_but_missing_from_sitemap']} indexable pages missing. "
            f"{sm['reading']}")

    out += ["", "## How to fix", ""]
    for i in summary["issues"]:
        if i["how_to_fix"]:
            out += [f"### {i['issue']} ({i['priority']}, {i['urls']} URLs)",
                    "", i["how_to_fix"], ""]

    out += ["", "---", "",
            "Generated by screaming-frog-mcp. Data from Screaming Frog SEO Spider.",
            "Issue names, descriptions and fix guidance are Screaming Frog's own."]
    return "\n".join(out) + "\n"


# ──────────────────────────────────────────────────────────────────────── html

def html_report(summary: dict, analysis: dict, label: str) -> str:
    h, s, c = summary["health"], summary["stats"], summary["counts"]

    issue_rows = [
        [f'<span class="chip {_e(i["priority"])}">{_e(i["priority"])}</span>',
         _e(i["type"]), i["urls"], _e(i["issue"])]
        for i in summary["issues"]
    ]

    d, le, ct = analysis["depth"], analysis["link_equity"], analysis["content"]
    perf, dup, ix = analysis["performance"], analysis["duplication"], analysis["indexability"]

    sections = [
        ("Least-linked pages",
         _table(["URL", "Unique inlinks", "Link score"],
                [[f'<td class="u">{_e(p["url"])}</td>'[4:-5], p["unique_inlinks"], p["link_score"]]
                 for p in le["least_linked"]]),
         le["reading"]),
        ("Deepest pages",
         _table(["URL", "Depth"],
                [[_e(p["url"]), p["depth"]] for p in d["deepest"]],
                "Nothing deeper than 3 clicks."),
         d["reading"]),
        ("Thinnest pages",
         _table(["URL", "Words"],
                [[_e(p["url"]), p["words"]] for p in ct["thinnest"]],
                "No pages below the thin-content threshold."),
         ct["reading"]),
        ("Slowest responses",
         _table(["URL", "Seconds"],
                [[_e(p["url"]), p["seconds"]] for p in perf["slowest"]],
                "No slow responses."),
         perf["reading"]),
        ("Duplicate titles",
         _table(["Title", "Pages"],
                [[_e(t["title"]), t["count"]] for t in dup["worst_titles"]],
                "No duplicate titles."),
         dup["reading"]),
    ]
    section_html = "".join(
        f"<h3>{_e(name)}</h3>{table}<p class=\"note\">{_e(reading)}</p>"
        for name, table, reading in sections
    )

    reasons = _table(["Reason", "URLs"],
                     [[_e(k), v] for k, v in ix["reasons"].items()],
                     "Everything crawled is indexable.")

    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Technical SEO crawl: {_e(label)}</title>
<style>{CSS}</style></head><body><main>
<h1>Technical SEO crawl</h1>
<p class="sub">{_e(label)} &middot; {_e(summary['crawled_at'])}</p>

<div class="grid">
  <div class="stat"><b>{s['urls']}</b><span>URLs crawled</span></div>
  <div class="stat"><b>{h['score']}</b><span>Health / 100 ({_e(h['band'])})</span></div>
  <div class="stat"><b>{c['high']}</b><span>High priority</span></div>
  <div class="stat"><b>{c['medium']}</b><span>Medium priority</span></div>
  <div class="stat"><b>{s['indexable']}</b><span>Indexable</span></div>
  <div class="stat"><b>{s['non_indexable']}</b><span>Non-indexable</span></div>
</div>
<p class="note">Health score: {_e(h['formula'])}</p>

<h2>Issue register</h2>
{_table(["Priority", "Type", "URLs", "Issue"], issue_rows, "No issues reported.")}

<h2>What the set of URLs means</h2>
{section_html}

<h3>Why URLs are not indexable</h3>
{reasons}
<p class="note">{_e(ix['reading'])}</p>

<h2>How to fix</h2>
{"".join(f"<h3>{_e(i['issue'])}</h3><p>{_e(i['how_to_fix'])}</p>"
         for i in summary["issues"] if i["how_to_fix"]) or '<p class="note">Nothing to fix.</p>'}

<footer>Generated by screaming-frog-mcp. Data from Screaming Frog SEO Spider;
issue names, descriptions and fix guidance are Screaming Frog&rsquo;s own.
Print this page to save it as a PDF.</footer>
</main></body></html>
"""


def build(folder: Path, label: str = "") -> dict:
    """Write report.md, report.html and analysis.json into the crawl folder."""
    summary_path = folder / "audit-summary.json"
    if summary_path.exists():
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
    else:
        summary = summarize(folder, label or folder.name)
    if "health" not in summary:                       # summary from an older run
        summary = summarize(folder, summary.get("site", label or folder.name))

    label = label or summary.get("site") or folder.name
    analysis = full_analysis(folder)
    (folder / "analysis.json").write_text(json.dumps(analysis, indent=2), encoding="utf-8")

    md = folder / "report.md"
    page = folder / "report.html"
    md.write_text(markdown_report(summary, analysis, label), encoding="utf-8")
    page.write_text(html_report(summary, analysis, label), encoding="utf-8")

    return {
        "label": label,
        "health": summary["health"],
        "markdown": str(md),
        "html": str(page),
        "analysis_json": str(folder / "analysis.json"),
        "generated_at": datetime.now().isoformat(timespec="seconds"),
    }
