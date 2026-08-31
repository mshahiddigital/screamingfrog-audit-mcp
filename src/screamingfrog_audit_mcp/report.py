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

from . import branding as B
from . import workbook
from .analysis import full_analysis, summarize

CSS = """
:root{
  --bg:#F5F0E8; --surface:#FBF6EC; --card:#EFE7D6;
  --ink:#111827; --ink2:#374151; --muted:#6B7280; --line:#E6DED1;
  --brand:#9D0BC4; --brand2:#B80CF2;
  --high:#DC2626; --med:#D97706; --low:#6B7280; --good:#16A34A;
}
*{box-sizing:border-box}
body{margin:0;padding:0;background:var(--bg);color:var(--ink);
font:15px/1.65 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif}
main{max-width:62rem;margin:0 auto;padding:0 1.25rem 3rem}
.masthead{background:linear-gradient(135deg,var(--brand) 0%,var(--brand2) 100%);
color:#fff;padding:2.5rem 1.25rem 2rem;margin-bottom:2rem}
.masthead .inner{max-width:62rem;margin:0 auto}
.masthead h1{font-size:2rem;margin:0 0 .35rem;letter-spacing:-.02em}
.masthead .site{font-size:1.05rem;opacity:.95;margin:0}
.masthead .by{margin:1rem 0 0;font-size:.85rem;opacity:.85}
.masthead .by a{color:#fff;text-decoration:underline}
h2{font-size:1.15rem;margin:2.5rem 0 .75rem;padding-bottom:.45rem;
border-bottom:2px solid var(--brand)}
h3{font-size:.98rem;margin:1.6rem 0 .5rem;color:var(--ink)}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(9.5rem,1fr));gap:.75rem;margin:1rem 0}
.stat{background:var(--surface);border:1px solid var(--line);
border-left:4px solid var(--brand);border-radius:.4rem;padding:.9rem}
.stat b{display:block;font-size:1.75rem;line-height:1.15;color:var(--ink)}
.stat span{color:var(--muted);font-size:.78rem}
.score b{color:var(--brand)}
.wrap{overflow-x:auto;-webkit-overflow-scrolling:touch;
border:1px solid var(--line);border-radius:.4rem;background:var(--surface)}
table{border-collapse:collapse;width:100%;font-size:.85rem}
th,td{text-align:left;padding:.55rem .65rem;border-bottom:1px solid var(--line);vertical-align:top}
th{background:var(--brand);color:#fff;font-weight:600;white-space:nowrap;
position:sticky;top:0}
tbody tr:nth-child(even){background:#FBF6EC}
td.u{word-break:break-all;max-width:28rem}
.chip{display:inline-block;padding:.12rem .55rem;border-radius:1rem;font-size:.72rem;
font-weight:700;color:#fff;letter-spacing:.02em}
.High{background:var(--high)}.Medium{background:var(--med)}.Low{background:var(--low)}
tr.r-High td{background:#FDE8E8}
tr.r-Medium td{background:#FEF3E2}
.note{color:var(--muted);font-size:.85rem;margin:.45rem 0 0}
footer{margin-top:3rem;padding:1.5rem 1.25rem;background:var(--card);
border-top:3px solid var(--brand);color:var(--ink2);font-size:.85rem}
footer .inner{max-width:62rem;margin:0 auto}
footer a{color:var(--brand);font-weight:600}
@media print{
  body{background:#fff}
  .masthead{-webkit-print-color-adjust:exact;print-color-adjust:exact}
  th{-webkit-print-color-adjust:exact;print-color-adjust:exact}
  h2{page-break-after:avoid} tr{page-break-inside:avoid} .stat{break-inside:avoid}
}
"""


def _e(v) -> str:
    return html.escape(str(v if v is not None else ""))


def _table(headers: list[str], rows: list[list], empty: str = "Nothing found.",
           row_classes: list[str] | None = None) -> str:
    if not rows:
        return f'<p class="note">{_e(empty)}</p>'
    head = "".join(f"<th>{_e(h)}</th>" for h in headers)
    classes = row_classes or [""] * len(rows)
    body = "".join(
        f'<tr class="{cls}">' + "".join(f"<td>{c}</td>" for c in r) + "</tr>"
        for r, cls in zip(rows, classes)
    )
    return f'<div class="wrap"><table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>'


# ──────────────────────────────────────────────────────────────────── markdown

def markdown_report(summary: dict, analysis: dict, label: str) -> str:
    h = summary["health"]
    s = summary["stats"]
    c = summary["counts"]
    out = [
        f"# Technical SEO Audit: {label}",
        "",
        f"*{B.CREDIT_LINE}*",
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

    out += ["", "---", "", f"**{B.CREDIT_LONG}**", "",
            "Crawl data from Screaming Frog SEO Spider; issue names, descriptions "
            "and fix guidance are Screaming Frog's own."]
    return "\n".join(out) + "\n"


# ──────────────────────────────────────────────────────────────────────── html

def html_report(summary: dict, analysis: dict, label: str) -> str:
    h, s, c = summary["health"], summary["stats"], summary["counts"]

    issue_rows = [
        [f'<span class="chip {_e(i["priority"])}">{_e(i["priority"])}</span>',
         _e(i["type"]), i["urls"], _e(i["issue"])]
        for i in summary["issues"]
    ]
    issue_classes = [f'r-{i["priority"]}' for i in summary["issues"]]

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

    band_label, _ = B.band(h["score"])
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{_e(B.report_title(label))}</title>
<style>{CSS}</style></head><body>
<header class="masthead"><div class="inner">
  <h1>Technical SEO Audit</h1>
  <p class="site">{_e(label)} &middot; {_e(summary['crawled_at'])}</p>
  <p class="by">Prepared with <strong>{_e(B.TOOL)}</strong> by {_e(B.AUTHOR)},
     {_e(B.STUDIO)} &middot; <a href="{_e(B.AUTHOR_SITE)}">{_e(B.AUTHOR_SITE_SHORT)}</a></p>
</div></header>
<main>

<div class="grid">
  <div class="stat"><b>{s['urls']}</b><span>URLs crawled</span></div>
  <div class="stat score"><b>{h['score']}</b><span>Health / 100 ({_e(band_label)})</span></div>
  <div class="stat"><b>{c['high']}</b><span>High priority</span></div>
  <div class="stat"><b>{c['medium']}</b><span>Medium priority</span></div>
  <div class="stat"><b>{s['indexable']}</b><span>Indexable</span></div>
  <div class="stat"><b>{s['non_indexable']}</b><span>Non-indexable</span></div>
</div>
<p class="note">Health score: {_e(h['formula'])}</p>

<h2>Issue register</h2>
{_table(["Priority", "Type", "URLs", "Issue"], issue_rows, "No issues reported.", issue_classes)}

<h2>What the set of URLs means</h2>
{section_html}

<h3>Why URLs are not indexable</h3>
{reasons}
<p class="note">{_e(ix['reading'])}</p>

<h2>How to fix</h2>
{"".join(f"<h3>{_e(i['issue'])}</h3><p>{_e(i['how_to_fix'])}</p>"
         for i in summary["issues"] if i["how_to_fix"]) or '<p class="note">Nothing to fix.</p>'}

</main>
<footer><div class="inner">
  <p><strong>{_e(B.CREDIT_LONG)}</strong></p>
  <p class="note">Crawl data from Screaming Frog SEO Spider; issue names, descriptions
  and fix guidance are Screaming Frog&rsquo;s own. Print this page to save it as a PDF.</p>
</div></footer>
</body></html>
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

    result = {
        "label": label,
        "health": summary["health"],
        "markdown": str(md),
        "html": str(page),
        "analysis_json": str(folder / "analysis.json"),
        "generated_at": datetime.now().isoformat(timespec="seconds"),
    }

    # The master workbook: every export as its own styled, highlighted sheet.
    try:
        book = workbook.build(folder, summary, analysis, label,
                              folder / "audit-workbook.xlsx")
        result["workbook"] = book["path"]
        result["sheets"] = book["sheets"]
        result["data_tables"] = book["data_tables"]
    except ImportError:
        result["workbook_error"] = (
            "openpyxl is not installed, so the workbook was skipped. "
            "pip install openpyxl")
    return result
