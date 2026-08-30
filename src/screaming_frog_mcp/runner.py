"""The crawl child process.

Run as: python -m screaming_frog_mcp.runner --url https://example.com --output DIR

Kept separate from the server so the crawl survives the MCP server exiting, and
so the whole pipeline can be used from a shell without MCP at all.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from .analysis import summarize
from .crawler import FREE_URL_CAP, run_chunked, run_spider
from .finder import find_binary, install_hint


def main() -> int:
    ap = argparse.ArgumentParser(prog="screaming_frog_mcp.runner")
    ap.add_argument("--url", required=True)
    ap.add_argument("--output", required=True)
    ap.add_argument("--full", action="store_true",
                    help="Batch sitemap URLs through list mode to beat the free cap")
    ap.add_argument("--everything", action="store_true",
                    help="Export every report and tab filter this build supports")
    ap.add_argument("--config", default=None,
                    help="Path to a .seospiderconfig file (licensed installs only)")
    args = ap.parse_args()

    binary = find_binary()
    if binary is None:
        print(install_hint(), file=sys.stderr)
        return 2

    out_dir = Path(args.output).expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    started = time.time()
    if args.full:
        run_chunked(binary, args.url, out_dir, args.everything, args.config)
    else:
        run_spider(binary, args.url, out_dir, args.everything, args.config)

    summary = summarize(out_dir, args.url)
    stats = summary["stats"]
    print(f"Done: {stats['urls']} URLs in {time.time() - started:.0f}s "
          f"({summary['counts']['total_types']} issue types, "
          f"health {summary['health']['score']}/100)", flush=True)

    if not args.full and stats["urls"] >= FREE_URL_CAP:
        print(f"NOTE: hit the {FREE_URL_CAP}-URL free cap. Re-run with --full.",
              flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
