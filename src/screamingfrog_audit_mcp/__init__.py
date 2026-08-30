"""screamingfrog-audit-mcp: drive the Screaming Frog SEO Spider from any MCP client."""

from importlib.metadata import PackageNotFoundError, version

# Single-sourced from the installed distribution metadata, so pyproject.toml is
# the ONLY place a version number lives. Hardcoding it here drifted once
# already: the package shipped as 1.0.1 while --doctor still reported 1.0.0.
try:
    __version__ = version("screamingfrog-audit-mcp")
except PackageNotFoundError:          # running from a source tree, not installed
    __version__ = "0.0.0+source"

__all__ = ["__version__"]
