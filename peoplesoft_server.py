"""
Compatibility entry point: same MCP as ``peoplesoft_fin_server.py``.

Use this if you run ``uv run peoplesoft_server.py`` (name matches the HR ``peoplesoft-mcp`` repo).
"""
from peoplesoft_fin_server import run_mcp

if __name__ == "__main__":
    run_mcp()
