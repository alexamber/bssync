"""bssync MCP server package.

The FastMCP instance and lifespan live in `bssync.mcp.server`; tools,
resources, and prompts are registered on it by their respective modules
via decorators. Importing `bssync.mcp.server` triggers the whole graph.
"""
