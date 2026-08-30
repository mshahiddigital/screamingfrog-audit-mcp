# Changelog

All notable changes to this project are documented here.
This project adheres to [Semantic Versioning](https://semver.org/).

## [1.0.0] — 2026-08-31

First public release. Drive the Screaming Frog SEO Spider from any MCP client.

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
