# screamingfrog-audit-mcp

[![CI](https://github.com/mshahiddigital/screamingfrog-audit-mcp/actions/workflows/ci.yml/badge.svg)](https://github.com/mshahiddigital/screamingfrog-audit-mcp/actions/workflows/ci.yml) [![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue)](https://www.python.org/) [![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)

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

You need two things: **Python 3.10+** and the **Screaming Frog SEO Spider**
installed on the same machine ([download](https://www.screamingfrog.co.uk/seo-spider/)).
The free version is fine.

### Claude Code

```bash
claude mcp add screaming-frog -- \
  uvx --from git+https://github.com/mshahiddigital/screamingfrog-audit-mcp screamingfrog-audit-mcp
```

### Claude Desktop, Cursor, or any client with a JSON config

```json
{
  "mcpServers": {
    "screaming-frog": {
      "command": "uvx",
      "args": [
        "--from", "git+https://github.com/mshahiddigital/screamingfrog-audit-mcp",
        "screamingfrog-audit-mcp"
      ]
    }
  }
}
```

Config file locations:

| Client | Path |
|---|---|
| Claude Desktop (macOS) | `~/Library/Application Support/Claude/claude_desktop_config.json` |
| Claude Desktop (Windows) | `%APPDATA%\Claude\claude_desktop_config.json` |
| Cursor | `~/.cursor/mcp.json` |

Restart the client after editing. `uvx` comes with
[uv](https://docs.astral.sh/uv/getting-started/installation/).

### Prefer pip

```bash
pip install git+https://github.com/mshahiddigital/screamingfrog-audit-mcp
```

Then use `"command": "screamingfrog-audit-mcp"` with `"args": []`.

### First run

Ask your client: **"check my screaming frog install"**. It calls `check_install`,
which reports the binary it found, your tier, and what that tier can do.

### If the server won't start

An MCP server talks over stdio, so a startup failure shows up in your client as
a dead server with no reason given. Run the preflight in a terminal instead:

```bash
screamingfrog-audit-mcp --doctor
```

It checks your Python version, the MCP SDK, whether the SEO Spider is found
*and actually runs*, your licence tier, and whether the audit folder is
writable — then prints a client config matching how this copy was installed.

```
  [PASS] Python: Python 3.12.7 on Darwin
  [PASS] MCP SDK: MCP SDK 2.1.1, using MCPServer (mcp 2.x)
  [FAIL] SEO Spider: Screaming Frog SEO Spider not found
    Install it from https://www.screamingfrog.co.uk/seo-spider/ ,
    or set SCREAMING_FROG_PATH to the executable.
```

Running from `uvx`? Use
`uvx --from git+https://github.com/mshahiddigital/screamingfrog-audit-mcp screamingfrog-audit-mcp --doctor`.

> **Not on PyPI yet.** Once it is published, the above shortens to
> `uvx screamingfrog-audit-mcp`.

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
| `read_export` | Rows from one export: column-selectable, filterable, paged, capped |
| `build_report` | `report.md` + a printable, self-contained `report.html` + `analysis.json` |

## Two design decisions worth knowing

**Crawls are background jobs.** A crawl takes minutes; an MCP call should
answer in seconds. `start_crawl` forks a detached child and hands back a
`job_id`. Nothing blocks unless you pass `wait_seconds`. The crawl survives the
MCP server restarting.

**Reads are capped, on purpose.** A finished crawl folder is tens of megabytes
of CSV. Feeding that to a model is both useless and expensive. Every read tool
caps at 500 rows, lets you pick columns, and truncates long cells. Ask
`get_issues` first — it's the whole site in about 60 lines — and reach for
`read_export` only to answer a specific question.

## Where crawls are stored

`~/.screamingfrog-audit-mcp/audits/<label>/` by default. Each folder holds the raw
Screaming Frog CSV exports, `audit-summary.json`, and whatever
`build_report` wrote.

Override with `SF_MCP_AUDIT_DIR`:

```json
{
  "mcpServers": {
    "screaming-frog": {
      "command": "uvx",
      "args": [
        "--from", "git+https://github.com/mshahiddigital/screamingfrog-audit-mcp",
        "screamingfrog-audit-mcp"
      ],
      "env": { "SF_MCP_AUDIT_DIR": "/Users/you/audits" }
    }
  }
}
```

Set `SCREAMING_FROG_PATH` if the Spider is installed somewhere non-standard.

## Use it without MCP

The crawl pipeline is a plain module:

```bash
python -m screamingfrog_audit_mcp.runner --url https://example.com --output ./audit
python -m screamingfrog_audit_mcp.runner --url https://example.com --output ./audit --full
```

## Gotchas found the hard way

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
