"""PyInstaller entry for the bssync-mcp binary.

Kept as a thin wrapper (rather than pointing PyInstaller directly at
mcp_server.py) so the entry script and the bssync.mcp_server module stay
as distinct objects — avoids a double-import footgun where the frozen
app's `__main__` and `bssync.mcp_server` would otherwise be the same file
loaded twice under different module names.

Pip-installed users don't hit this file; they use the console script
`bssync-mcp = bssync.mcp_server:main` from pyproject.toml.
"""
from bssync.mcp_server import main

if __name__ == "__main__":
    main()
