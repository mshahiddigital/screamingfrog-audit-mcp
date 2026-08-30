"""Locate the installed Screaming Frog SEO Spider, on any platform.

The binary is named differently per platform and the CLI entrypoint is not
always the one users expect, so this is deliberately explicit rather than a
single hopeful path.
"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

# Set this to skip discovery entirely, e.g. for a non-standard install.
ENV_BINARY = "SCREAMING_FROG_PATH"

# The licence file lives in the same place on every platform. Its presence is
# the only reliable signal of licensed status without launching the app.
LICENCE_FILE = Path.home() / ".ScreamingFrogSEOSpider" / "licence.txt"

_MACOS = [
    "/Applications/Screaming Frog SEO Spider.app/Contents/MacOS/ScreamingFrogSEOSpiderLauncher",
    str(Path.home() / "Applications/Screaming Frog SEO Spider.app/Contents/MacOS/ScreamingFrogSEOSpiderLauncher"),
]

_LINUX = [
    "/usr/bin/screamingfrogseospider",
    "/usr/local/bin/screamingfrogseospider",
    "/opt/screamingfrogseospider/screamingfrogseospider",
    "/snap/bin/screaming-frog-seo-spider",
]

# On Windows the GUI exe cannot be driven headlessly; the CLI shim is a
# separate file and is the one that accepts --headless.
_WINDOWS = [
    r"C:\Program Files\Screaming Frog SEO Spider\ScreamingFrogSEOSpiderCli.exe",
    r"C:\Program Files (x86)\Screaming Frog SEO Spider\ScreamingFrogSEOSpiderCli.exe",
]


def candidates() -> list[str]:
    if sys.platform == "darwin":
        return _MACOS
    if sys.platform == "win32":
        return _WINDOWS
    return _LINUX


def find_binary() -> Path | None:
    """Return the SEO Spider executable, or None if it cannot be found."""
    override = os.environ.get(ENV_BINARY, "").strip()
    if override:
        p = Path(override).expanduser()
        return p if p.exists() else None

    for path in candidates():
        p = Path(path)
        if p.exists():
            return p

    for name in ("screamingfrogseospider", "ScreamingFrogSEOSpiderCli"):
        found = shutil.which(name)
        if found:
            return Path(found)
    return None


def is_licensed() -> bool:
    return LICENCE_FILE.exists()


def install_hint() -> str:
    looked = "\n".join(f"  {c}" for c in candidates())
    return (
        "Screaming Frog SEO Spider was not found. Install it from "
        "https://www.screamingfrog.co.uk/seo-spider/ , or set "
        f"{ENV_BINARY} to the executable.\n\nLooked in:\n{looked}"
    )
