"""PyInstaller entry for the bssync-mcp binary.

Kept as a thin wrapper (rather than pointing PyInstaller directly at the
mcp package's server.py) so the entry script and `bssync.mcp.server`
stay as distinct objects — avoids a double-import footgun where the
frozen app's `__main__` and `bssync.mcp.server` would otherwise be the
same file loaded twice under different module names.

Pip-installed users don't hit this file; they use the console script
`bssync-mcp = bssync.mcp.server:main` from pyproject.toml.
"""
from bssync.mcp.server import main

if __name__ == "__main__":
    main()
