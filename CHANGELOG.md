# Changelog

All notable changes to this project are documented here.
This project adheres to [Semantic Versioning](https://semver.org/).

## [1.2.1] — 2026-08-31

### Fixed

- **Every crawl crashed on Screaming Frog 19.8 and other older builds.** The
  package always passed `--skip-empty`, which those versions do not have, and
  Screaming Frog does not ignore an unknown option — it aborts before crawling:

  ```
  FATAL - SeoSpider failed to start
  org.apache.commons.cli.UnrecognizedOptionException: Unrecognized option
  ```

  The result was an immediate failure with 0 URLs, on a perfectly good
  licensed install.

  Command-line options are now **detected from the binary's own `--help`**
  before use, the same way export-filter names already were. This is feature
  detection rather than version detection, deliberately: there is no
  `--version` flag, and what matters is the option set, not the number.

  - Optional flags (`--overwrite`, `--skip-empty`) are passed only when the
    installed build advertises them, and the run says which it skipped.
  - If `--help` cannot be read, **no** optional flag is sent. An unknown flag
    is fatal; a missing optional flag only costs a few empty CSV files.
  - `--config` on a build without it is refused up front, with an explanation,
    rather than aborting mid-crawl.
  - `--crawl-list` missing falls back to spider mode instead of failing.
  - Missing *essential* options are reported as a clear error rather than a
    Java stack trace.
  - Two levels of gating, because they are not the same risk. **Newer** flags
    (`--skip-empty`, `--overwrite`) are withheld unless positively advertised.
    **Long-standing** flags the product depends on (`--save-report`,
    `--crawl-list`, `--config`) are withheld only when a build lists its
    options and this one is absent — dropping `--save-report` on an unreadable
    `--help` would have silently discarded the Issues Overview, which is the
    audit itself.
  - `--doctor` gained a **CLI options** check, so a mismatch is visible before
    a crawl is attempted rather than after it fails.

## [1.2.0] — 2026-08-31

The report became a deliverable instead of a write-up.

### Added

- **`audit-workbook.xlsx` — the master workbook.** `build_report` now writes a
  full Excel workbook: Summary, Issue register, Analysis, a Data index, and
  **every crawl export as its own sheet**. On a full crawl that is ~70 data
  tables, where before none of the raw data reached the deliverable at all.
- **Highlighting, which is what makes it an audit rather than a data dump.**
  Cells are tinted where the value *is* the finding: issue priority as a
  coloured chip with a tinted row, 4xx/5xx status codes, non-indexable URLs,
  thin content under 300 words, responses over one second. A reader sees the
  problems before reading a cell.
- **Every sheet is navigable:** purple header row, banded rows, frozen header,
  autofilter, sized columns, coloured tab, gridlines off.
- **Brand identity across all output.** The workbook, HTML and Markdown carry
  one palette and one credit line naming the author and site.

### Changed

- The HTML report is rebuilt on the brand palette with a gradient masthead,
  priority-tinted issue rows, and print rules that keep colour when saved to
  PDF.
- `openpyxl` is now a dependency.

## [1.1.1] — 2026-08-31

### Changed

- Documentation wording. No functional change; identical code to 1.1.0.

## [1.1.0] — 2026-08-31

Three tools added and one hardened: a crawl allowlist, server-side
aggregation, and storage management.

### Added

- **`SF_ALLOWED_DOMAINS`.** By default this server will crawl any host it is
  asked to, which is fine locally and a liability unattended: a confused or
  prompt-injected agent can point a crawler at internal addresses or at third
  parties. With the variable set, `start_crawl` refuses anything else.
  Subdomains of a listed domain pass; look-alikes such as
  `example.com.evil.com` do not. `--doctor` reports whether it is active.
- **`aggregate_export`** — counts and group-by *without returning rows*.
  "How many 404s", "status codes by folder", "word count per section" now cost
  one small response instead of paging thousands of rows through a model to
  count them by hand. Optionally summarises a numeric column (sum/avg/min/max)
  per group.
- **`storage_summary`** — disk used per saved crawl, largest first. Crawl
  folders are never cleaned up automatically and an `everything=true` run
  writes hundreds of CSVs.
- **`delete_crawl`** — permanently remove a crawl folder. Requires
  `confirm=true` and refuses any path outside the audit root, so a crafted
  path cannot delete arbitrary directories.

### Changed

- **`read_export` filtering is much sharper.** `column` restricts the filter to
  one named column instead of matching across the whole row, and `mode`
  selects `contains` (default), `exact` or `regex`. An unknown column now
  errors with the list of real ones rather than silently matching nothing.

## [1.0.2] — 2026-08-31

### Fixed

- **The version is single-sourced from `pyproject.toml` again.** It had been
  restated in `__init__.py` and drifted immediately: 1.0.1 shipped while
  `--doctor` still reported `1.0.0`. `__version__` is now read from the
  installed distribution metadata, so there is one place a version number
  lives. A test asserts the two agree and that no release number is hardcoded.

## [1.0.1] — 2026-08-31

Packaging metadata brought in line with the current Python packaging guides.
No functional change to the server.

### Changed

- **License declared as an SPDX expression** (PEP 639): `license = "MIT"` plus
  `license-files`, replacing the deprecated `license = { file = "LICENSE" }`
  table. The old form put the *entire* text of the licence into the `License:`
  metadata field, which is what PyPI displayed.
- Dropped the now-redundant `License :: OSI Approved :: MIT License`
  classifier, which PEP 639 deprecates alongside a license expression.
- Added `Repository` and `Changelog` project URLs.
- Declared and tested support for Python 3.14; the CI matrix now covers
  3.10, 3.12, 3.13 and 3.14 on Linux, macOS and Windows.

## [1.0.0] — 2026-08-31

First public release. Drive the Screaming Frog SEO Spider from any MCP client.

Published as **`screamingfrog-audit-mcp`**. The obvious name was already taken
on PyPI by an unrelated project, and the distinguishing feature here is that it
runs on an unlicensed Spider, so the name leans on the audit surface instead.

### Added

- **Eleven MCP tools**: `check_install`, `available_filters`, `start_crawl`,
  `crawl_status`, `cancel_crawl`, `list_crawls`, `get_issues`, `get_analysis`,
  `list_exports`, `read_export`, `build_report`.
- **Background crawl jobs.** A crawl takes minutes and an MCP call should answer
  in seconds, so `start_crawl` forks a detached child and returns a `job_id`.
  Nothing blocks unless `wait_seconds` is passed, and the crawl survives the
  server restarting.
- **Capped, filterable reads.** A finished crawl folder is tens of megabytes of
  CSV. Every read tool caps at 500 rows, selects columns, filters by substring,
  pages, and truncates long cells.
- **Derived analysis** (`get_analysis`): crawl depth, link equity, sitemap
  reconciliation, content depth, performance outliers, indexability and
  duplication — each with a plain-English reading line.
- **Unbranded reporting** (`build_report`): `report.md`, a self-contained
  printable `report.html` with light/dark support and print rules, and
  `analysis.json`. No bundled PDF step, deliberately.
- **Free-tier support.** The headless CLI runs unlicensed. The 500-URL limit is
  per invocation, so `full=true` discovers URLs from robots.txt and the
  sitemaps, batches them under the cap through list mode, and merges the
  exports — crawling a site of any size.
- **Tier-aware expert mode.** API-backed export groups are requested only when
  licensed; Custom Extraction / Search / JavaScript / AI groups only when a
  `config` file is supplied. Requesting a permanently empty group costs minutes
  and returns nothing.
- **`config=` passthrough** for licensed installs, refused up front on the free
  tier rather than failing mid-crawl.
- **`--doctor` preflight.** An MCP server speaks stdio, so a startup failure
  reaches the user as a dead server with no reason. This checks Python, the MCP
  SDK, whether the Spider is found *and executes*, licence tier and
  audit-folder writability, then prints a client config matching the install.
- Cross-platform binary discovery with `SCREAMING_FROG_PATH`, and a
  configurable audit root via `SF_MCP_AUDIT_DIR`.

### Notes on correctness

These were found by testing rather than reasoning, and each would have been
invisible on the author's machine:

- **`os.kill(pid, 0)` is not a liveness probe on Windows.** Any signal other
  than CTRL_C/CTRL_BREAK routes to `TerminateProcess`, so polling a job would
  have killed the crawl and then reported it finished. Windows uses `tasklist`
  to check and `taskkill /T /F` to cancel, and never signals. `os.killpg` and
  `os.getpgid` do not exist there, and `start_new_session` is POSIX-only, so
  detaching uses creation flags.
- **A finished child that is never reaped becomes a zombie**, and `os.kill`
  reports a zombie as alive, so a crawl that ended in 55 seconds polled
  "running" indefinitely. Liveness now tracks the `Popen` handle; `poll()`
  reaps.
- **`subprocess.run(text=True)` decodes with the locale encoding**, which is
  cp1252 on Windows, so one undecodable byte would crash a crawl. All call
  sites pin UTF-8, guarded by a source-scanning test.
- **A single unrecognised export-filter name aborts an entire crawl** with a
  Java stack trace instead of skipping it, and Screaming Frog renames filters
  between versions. Names are validated against the installed binary on every
  run. Its own `--help` output also emits a placeholder `UNDEF:Unknown`, which
  is filtered.
- **Crawl data is attacker-controllable** and is escaped before it reaches the
  HTML report.
