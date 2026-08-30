"""Preflight diagnostics: `screamingfrog-audit-mcp --doctor`.

An MCP server talks over stdio, so when it fails to start the user sees
nothing useful — the client just reports a dead server with no reason. This
runs the same checks in a normal terminal and says exactly what is wrong,
then prints a ready-to-paste client config.

Every check is non-destructive and read-only.
"""

from __future__ import annotations

import os
import platform
import subprocess
import sys
from pathlib import Path

from . import __version__
from .finder import ENV_BINARY, LICENCE_FILE, candidates, find_binary, is_licensed

PASS, FAIL, WARN = "PASS", "FAIL", "WARN"

ENV_AUDIT_DIR = "SF_MCP_AUDIT_DIR"


def _default_audit_root() -> Path:
    return Path(
        os.environ.get(ENV_AUDIT_DIR) or (Path.home() / ".screamingfrog-audit-mcp" / "audits")
    ).expanduser()


def _check_python() -> tuple[str, str, str]:
    v = sys.version_info
    ok = v >= (3, 10)
    return (
        PASS if ok else FAIL,
        f"Python {v.major}.{v.minor}.{v.micro} on {platform.system()}",
        "" if ok else "Python 3.10 or newer is required.",
    )


def _check_sdk() -> tuple[str, str, str]:
    try:
        import mcp  # noqa: F401
    except ImportError:
        return FAIL, "MCP SDK not installed", "pip install mcp"
    try:
        import importlib.metadata as md
        version = md.version("mcp")
    except Exception:
        version = "unknown"
    try:
        from mcp.server.mcpserver import MCPServer  # noqa: F401
        flavour = "MCPServer (mcp 2.x)"
    except ImportError:
        try:
            from mcp.server.fastmcp import FastMCP  # noqa: F401
            flavour = "FastMCP (mcp 1.x)"
        except ImportError:
            return (FAIL, f"MCP SDK {version} exposes neither MCPServer nor FastMCP",
                    "Reinstall the SDK: pip install -U mcp")
    return PASS, f"MCP SDK {version}, using {flavour}", ""


def _check_binary() -> tuple[str, str, str]:
    binary = find_binary()
    if binary is None:
        looked = "\n".join(f"      {c}" for c in candidates())
        return (
            FAIL,
            "Screaming Frog SEO Spider not found",
            "Install it from https://www.screamingfrog.co.uk/seo-spider/ ,\n"
            f"    or set {ENV_BINARY} to the executable.\n"
            f"    Looked in:\n{looked}",
        )
    override = " (from " + ENV_BINARY + ")" if os.environ.get(ENV_BINARY) else ""
    return PASS, f"Screaming Frog found{override}: {binary}", ""


def _check_binary_runs() -> tuple[str, str, str]:
    binary = find_binary()
    if binary is None:
        return WARN, "Skipped: no binary to run", ""
    try:
        proc = subprocess.run(
            [str(binary), "--help", "export-tabs"],
            capture_output=True, text=True, timeout=180,
            encoding="utf-8", errors="replace",
        )
    except subprocess.TimeoutExpired:
        return (WARN, "The binary did not answer --help within 180s",
                "It may still work; a first launch can be slow.")
    except OSError as e:
        return FAIL, f"Could not execute the binary: {e}", "Check file permissions."

    names = [ln.strip() for ln in proc.stdout.splitlines()
             if ln.strip() and not ln.startswith((" ", "\t", "The option"))]
    if not names:
        return (FAIL, "The binary ran but listed no export filters",
                "This build may be too old. Update the SEO Spider.")
    return PASS, f"Binary responds: {len(names)} export filters available", ""


def _check_licence() -> tuple[str, str, str]:
    if is_licensed():
        return PASS, f"Licensed (found {LICENCE_FILE})", ""
    return (
        WARN,
        "No licence file: running on the free tier",
        "Fine, and fully supported. Headless crawling, every export and every\n"
        "    report work unlicensed. The limit is 500 URLs per invocation, so\n"
        "    use full=true on larger sites. Config files are unavailable.",
    )


def _check_audit_dir() -> tuple[str, str, str]:
    root = _default_audit_root()
    try:
        root.mkdir(parents=True, exist_ok=True)
        probe = root / ".doctor-write-test"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
    except OSError as e:
        return (FAIL, f"Audit folder not writable: {root}",
                f"{e}\n    Set {ENV_AUDIT_DIR} to a folder you can write to.")
    return PASS, f"Audit folder writable: {root}", ""


def _client_config() -> str:
    """The exact snippet to paste, matching how this copy was installed."""
    if Path(sys.argv[0]).name.startswith("screamingfrog-audit-mcp"):
        command, args = sys.argv[0], []
    else:
        command, args = sys.executable, ["-m", "screamingfrog_audit_mcp"]
    arg_lines = "".join(f'\n        "{a}",' for a in args).rstrip(",")
    return (
        '{\n'
        '  "mcpServers": {\n'
        '    "screaming-frog": {\n'
        f'      "command": "{command}",\n'
        f'      "args": [{arg_lines}\n      ]\n'
        '    }\n'
        '  }\n'
        '}'
    )


def run() -> int:
    checks = [
        ("Python", _check_python),
        ("MCP SDK", _check_sdk),
        ("SEO Spider", _check_binary),
        ("Spider runs", _check_binary_runs),
        ("Licence", _check_licence),
        ("Audit folder", _check_audit_dir),
    ]

    print(f"screamingfrog-audit-mcp {__version__} — preflight check\n")
    failures = 0
    for label, fn in checks:
        status, message, hint = fn()
        if status == FAIL:
            failures += 1
        print(f"  [{status}] {label}: {message}")
        if hint:
            print(f"    {hint}")

    print()
    if failures:
        print(f"{failures} check(s) failed. Fix those before adding the server to")
        print("your MCP client, or it will fail to start with no visible error.")
        return 1

    print("All checks passed. Client config for this install:\n")
    print(_client_config())
    print("\nClaude Desktop (macOS): ~/Library/Application Support/Claude/claude_desktop_config.json")
    print("Claude Desktop (Windows): %APPDATA%\\Claude\\claude_desktop_config.json")
    print("Cursor: ~/.cursor/mcp.json")
    print("Claude Code: claude mcp add screaming-frog -- <command> <args>")
    return 0
