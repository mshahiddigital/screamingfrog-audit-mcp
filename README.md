# screamingfrog-audit-mcp

[![CI](https://github.com/mshahiddigital/screamingfrog-audit-mcp/actions/workflows/ci.yml/badge.svg)](https://github.com/mshahiddigital/screamingfrog-audit-mcp/actions/workflows/ci.yml) [![PyPI](https://img.shields.io/pypi/v/screamingfrog-audit-mcp)](https://pypi.org/project/screamingfrog-audit-mcp/) [![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue)](https://www.python.org/) [![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)

Drive the [Screaming Frog SEO Spider](https://www.screamingfrog.co.uk/seo-spider/)
from Claude, Cursor, or any other MCP client. Crawl a site, get a ranked issue
register back, ask questions of the crawl data, and render a shareable report —
without opening the GUI or writing a single command.

### It works on the free, unlicensed SEO Spider

That is the point of this server, and it is unusual: the other MCP servers for
Screaming Frog build on its saved-crawl database, which is a licensed feature,
so they need a paid install. This one drives the crawl directly and never
touches that database.

The free tier caps you at 500 URLs **per invocation** — not per site. So
`full=true` reads `robots.txt` and the sitemaps, splits the URLs into batches
under the cap, runs each through list mode, and merges the exports. A
3,000-page site audits completely on a free install.

A licence removes the cap and unlocks `config=` for JavaScript rendering and
custom extraction. Both tiers are supported and the server adapts to whichever
you have.

```
You:  Crawl example.com and tell me what's actually broken.

→ start_crawl(url="https://example.com")
→ crawl_status()                     # 248 URLs, 51s
→ get_issues(priority="High")

Claude: Three high-priority problems. The big one: robots.txt disallows
/_next/, which hides 85 JS and CSS bundles from Google...
```

## Install

Two prerequisites: **Python 3.10+** and the **Screaming Frog SEO Spider**
installed on the same machine ([download](https://www.screamingfrog.co.uk/seo-spider/)).
The free version is fine — see [the free-tier situation](#the-free-tier-situation).

Every setup below uses `uvx`, which downloads and runs the package on demand
with no virtualenv to manage. It ships with
[uv](https://docs.astral.sh/uv/getting-started/installation/):
`curl -LsSf https://astral.sh/uv/install.sh | sh` (macOS/Linux) or
`powershell -c "irm https://astral.sh/uv/install.ps1 | iex"` (Windows).

Prefer pip? `pip install screamingfrog-audit-mcp`, then use
`"command": "screamingfrog-audit-mcp"` with `"args": []` in any config below.

### Claude Code

```bash
claude mcp add screaming-frog -- uvx screamingfrog-audit-mcp
```

Add `-s user` to make it available in every project rather than just this one.

### Claude Desktop

Settings → Developer → **Edit Config**, which opens `claude_desktop_config.json`:

| OS | Path |
|---|---|
| macOS | `~/Library/Application Support/Claude/claude_desktop_config.json` |
| Windows | `%APPDATA%\Claude\claude_desktop_config.json` |

```json
{
  "mcpServers": {
    "screaming-frog": {
      "command": "uvx",
      "args": ["screamingfrog-audit-mcp"]
    }
  }
}
```

**Quit and reopen Claude Desktop** — it only reads that file at startup, and a
window reload is not enough. The server then appears under the tools icon in
the chat box.

### Codex CLI

```bash
codex mcp add screaming-frog -- uvx screamingfrog-audit-mcp
```

Check it with `codex mcp list`. That writes to `~/.codex/config.toml`, which you
can also edit by hand — note TOML, not JSON, and `mcp_servers` with an
underscore:

```toml
[mcp_servers.screaming-frog]
command = "uvx"
args = ["screamingfrog-audit-mcp"]
```

### ChatGPT desktop app (Codex)

The ChatGPT app bundles Codex and reads the **same** `~/.codex/config.toml`, so
the command above configures both. Nothing extra to do — restart the app and
the tools appear in Codex.

> **ChatGPT on the web or mobile cannot use this server.** Those connectors call
> a remote HTTPS endpoint, and this server is a local process that drives the
> Screaming Frog installed on *your* machine. It has to run where the Spider is.

### Hermes

```bash
hermes mcp add screaming-frog --command uvx --args screamingfrog-audit-mcp
```

It connects, lists the tools it found, and asks which to enable — answer `Y` for
all 14. Confirm with `hermes mcp list`, then start a new session. The entry
lands in `~/.hermes/config.yaml`, which you can also edit directly:

```yaml
mcp_servers:
  screaming-frog:
    command: uvx
    args:
      - screamingfrog-audit-mcp
    enabled: true
```

### Cursor

Settings → MCP → **Add new global MCP server**, or edit `~/.cursor/mcp.json`
directly. Same shape as Claude Desktop:

```json
{
  "mcpServers": {
    "screaming-frog": {
      "command": "uvx",
      "args": ["screamingfrog-audit-mcp"]
    }
  }
}
```

### VS Code (Copilot)

`.vscode/mcp.json` for one workspace, or run **MCP: Open User Configuration**
for every workspace. VS Code uses `servers`, not `mcpServers`:

```json
{
  "servers": {
    "screaming-frog": {
      "type": "stdio",
      "command": "uvx",
      "args": ["screamingfrog-audit-mcp"]
    }
  }
}
```

### Any other MCP client

It is a standard **stdio** server: whatever the config shape, the command is
`uvx` and the argument is `screamingfrog-audit-mcp`.

The one requirement is that the client launches local processes on the machine
where Screaming Frog is installed. Clients that only accept a remote HTTPS
endpoint cannot drive a local crawler, whatever the config says.

### Optional settings

Add these to the `env` block of any config (a `[mcp_servers.screaming-frog.env]`
table in Codex):

| Variable | What it does |
|---|---|
| `SCREAMING_FROG_PATH` | Path to the SEO Spider executable, if it is installed somewhere non-standard |
| `SF_MCP_AUDIT_DIR` | Where crawl folders are written (default `~/.screamingfrog-audit-mcp/audits`) |
| `SF_ALLOWED_DOMAINS` | Comma-separated domains this server may crawl. Set it for anything unattended |

```json
{
  "mcpServers": {
    "screaming-frog": {
      "command": "uvx",
      "args": ["screamingfrog-audit-mcp"],
      "env": {
        "SF_MCP_AUDIT_DIR": "/Users/you/audits",
        "SF_ALLOWED_DOMAINS": "example.com,acme.co.uk"
      }
    }
  }
}
```

### First run

Ask your client: **"check my screaming frog install"**. It calls `check_install`,
which reports the binary it found, your licence tier, and what that tier can do.

### If the server won't start

An MCP server talks over stdio, so a startup failure shows up in your client as
a dead server with no reason given. Run the preflight in a terminal instead:

```bash
uvx screamingfrog-audit-mcp --doctor
```

It checks your Python version, the MCP SDK, whether the SEO Spider is found
*and actually runs*, which command-line options your build supports, your
licence tier, and whether the audit folder is writable — then prints a config
matching how this copy was installed.

```
  [PASS] Python: Python 3.12.7 on Darwin
  [PASS] MCP SDK: MCP SDK 2.1.1, using MCPServer (mcp 2.x)
  [FAIL] SEO Spider: Screaming Frog SEO Spider not found
    Install it from https://www.screamingfrog.co.uk/seo-spider/ ,
    or set SCREAMING_FROG_PATH to the executable.
```

Common causes: `uvx` not on the client's PATH (use an absolute path to `uvx`,
which `which uvx` will give you), or the config edited but the app not fully
restarted.

## The free-tier situation

The received wisdom is that the Screaming Frog CLI needs a licence. It does
not. Verified against a build reporting `Licence Status: Missing`:

| | |
|---|---|
| **Works unlicensed** | `--headless`, spider / list / sitemap crawl modes, every tab export, every saved report, sitemap generation |
| **Licence-gated** | save/load crawl, crawl comparison, config files, JavaScript rendering, scheduling, and the GA4 / Search Console / PageSpeed / Ahrefs / Moz integrations |
| **Capped** | 500 URLs **per invocation** — not per site |

Because the cap is per invocation, `start_crawl(full=true)` discovers URLs from
`robots.txt` and the sitemaps, batches them under the cap through list mode,
and merges the exports back into one set. That crawls a site of any size on the
free tier.

A licence removes the cap and makes `full` unnecessary. Everything else works
the same.

## Tools

| Tool | What it does |
|---|---|
| `check_install` | Install status, licence status, current limits, and how to fix a failed lookup |
| `available_filters` | The export names **your** Screaming Frog build accepts |
| `start_crawl` | Background headless crawl. `full` beats the free cap, `everything` exports every table |
| `crawl_status` | Poll a running crawl. Omit `job_id` for the most recent |
| `cancel_crawl` | Stop a crawl, keep partial exports |
| `list_crawls` | Crawl folders, newest first, with headline counts |
| `get_issues` | The priority-ranked issue register. **Start here** |
| `get_analysis` | What the *set* of URLs means: depth, link equity, sitemap accuracy, content depth, performance, indexability, duplication |
| `list_exports` | The CSV exports in a crawl, with row counts |
| `read_export` | Rows from one export: column-selectable, paged, capped, filtered by `contains` / `exact` / `regex` on any column |
| `aggregate_export` | **Counts and group-by without returning rows** — "how many 404s", "status codes by folder" — in one small response |
| `storage_summary` | Disk used per saved crawl, largest first |
| `delete_crawl` | Permanently delete a crawl folder (requires `confirm`) |
| `build_report` | The branded deliverable: **`audit-workbook.xlsx`** (Summary, Issue register, Analysis, Data index, and every export as its own highlighted sheet), a printable `report.html`, `report.md` and `analysis.json`. `consolidate=True` folds the CSV exports into the workbook and deletes them, leaving one file |

## Two design decisions worth knowing

**Crawls are background jobs.** A crawl takes minutes; an MCP call should
answer in seconds. `start_crawl` forks a detached child and hands back a
`job_id`. Nothing blocks unless you pass `wait_seconds`. The crawl survives the
MCP server restarting.

**Reads are capped, on purpose.** A finished crawl folder is tens of megabytes
of CSV. Feeding that to a model is both useless and expensive. Every read tool
caps at 500 rows, lets you pick columns, and truncates long cells. Ask
`get_issues` first — it's the whole site in about 60 lines — and
`aggregate_export` when the question is "how many" or "broken down by", since
counting rows by hand through a model is the expensive way to get a number.
Reach for `read_export` only when you actually need the rows.

## The deliverable

`build_report` writes four files into the crawl folder:

| File | What it is |
|---|---|
| `audit-workbook.xlsx` | The master workbook. Summary, Issue register, Analysis, Data index, and **every crawl export as its own sheet** — around 70 tables on a full crawl |
| `report.html` | Printable summary. Open it and Print to PDF |
| `report.md` | The same content as plain text |
| `analysis.json` | The derived layer, machine-readable |

Every sheet has a frozen header, autofilter, banded rows, sized columns and a
coloured tab. **Cells are highlighted where the value is the finding** — issue
priority, 4xx/5xx status codes, non-indexable URLs, thin content, slow
responses — so the problems are visible before you read a cell.

Reports carry a credit line naming the tool and its author.

### One workbook instead of seventy CSVs

A finished crawl leaves around seventy exports in the folder, and the workbook
already carries every one of them. `build_report(consolidate=True)` folds them
in and deletes them, so the folder holds the workbook, the report files, and a
`consolidated.json` manifest naming which sheet holds which table.

The delete is earned. Each sheet is written, the saved workbook is **reopened
from disk**, and every sheet is checked against the row count it should hold.
Only then is a file removed. If the save fails, the reopen fails, or a sheet
comes back short, nothing is deleted and the reason is reported. An export too
large to carry in full is kept on disk and named in the manifest, because a
sampled sheet is not a substitute for the file.

It is off by default: `read_export` and `aggregate_export` read those CSVs. Turn
it on when the folder is a finished deliverable rather than a crawl you are
still asking questions about. Those tools then explain the consolidation and
point at the workbook instead of reporting the folder as empty.

## Where crawls are stored

`~/.screamingfrog-audit-mcp/audits/<label>/` by default. Each folder holds the raw
Screaming Frog CSV exports, `audit-summary.json`, and whatever
`build_report` wrote — or, after a consolidated report, the workbook and
manifest in place of those exports.

Override with `SF_MCP_AUDIT_DIR`:

```json
{
  "mcpServers": {
    "screaming-frog": {
      "command": "uvx",
      "args": ["screamingfrog-audit-mcp"],
      "env": { "SF_MCP_AUDIT_DIR": "/Users/you/audits" }
    }
  }
}
```

Set `SCREAMING_FROG_PATH` if the Spider is installed somewhere non-standard.

## Restricting what it may crawl

By default this server will crawl any host it is asked to. That is fine on your
own machine, and a liability when an agent runs unattended: a confused or
prompt-injected one can point a crawler at internal addresses or at third
parties who did not ask to be crawled.

Set `SF_ALLOWED_DOMAINS` and `start_crawl` refuses anything else:

```json
"env": { "SF_ALLOWED_DOMAINS": "example.com,acme.co.uk" }
```

Subdomains of a listed domain are allowed; look-alikes are not, so
`shop.example.com` passes and `example.com.evil.com` does not. `--doctor`
reports whether an allowlist is active.

### Environment variables

All three are listed with examples under
[Optional settings](#optional-settings) in the install section.

## Use it without MCP

The crawl pipeline is a plain module:

```bash
python -m screamingfrog_audit_mcp.runner --url https://example.com --output ./audit
python -m screamingfrog_audit_mcp.runner --url https://example.com --output ./audit --full
```

## Gotchas found the hard way

- **An unknown command-line flag aborts the whole crawl**, it is not ignored:
  `FATAL - SeoSpider failed to start ... UnrecognizedOptionException`. The
  option set differs between versions — `--skip-empty` does not exist in 19.8,
  for instance — so this server reads the binary's own `--help` and passes only
  what your build advertises. Works on old and new versions alike.
- **One wrong filter name aborts the whole crawl.** Screaming Frog renames tab
  filters between versions, and an unrecognised name fails the run with a Java
  stack trace rather than skipping it. Every name is validated against your
  installed binary at crawl time, so an upgrade degrades instead of breaking.
- **Its own `--help` output contains a poisoned entry.** The binary lists a
  placeholder `UNDEF:Unknown`, and passing it back aborts the crawl with
  `Using UNDEF as tab is not supported`. It's filtered out.
- **`os.kill(pid, 0)` is not a liveness probe on Windows.** Any signal other
  than CTRL_C/CTRL_BREAK routes to `TerminateProcess`, so the usual "does this
  pid exist" idiom would kill the crawl and then report it finished. Windows
  uses `tasklist` to check and `taskkill` to cancel, and never signals.
  Detaching differs too: `start_new_session` is POSIX-only.
- **`everything` mode is curated, not literal.** The Spider lists ~1,150 tab
  filters, but 800+ are Custom Extraction / Custom Search / Custom JavaScript /
  AI filters that need a licence-gated config file and are permanently empty.
  Requesting them costs minutes and returns nothing, so those groups plus the
  API-dependent ones are excluded.

## Development

```bash
git clone https://github.com/mshahiddigital/screamingfrog-audit-mcp
cd screamingfrog-audit-mcp
pip install -e ".[dev]"
pytest
```

The test suite runs on synthetic export fixtures, so it passes on a machine
that has never had Screaming Frog installed.

## Changelog

See [CHANGELOG.md](CHANGELOG.md).

## License

MIT. Not affiliated with or endorsed by Screaming Frog Ltd. You need your own
copy of the SEO Spider; issue names, descriptions and fix guidance in the
output are Screaming Frog's own.
