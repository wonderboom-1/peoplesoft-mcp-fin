#!/usr/bin/env python3
"""
PeopleSoft Finance MCP Server — Model Context Protocol for PeopleSoft Financials (FSCM).

Interpreter (WSL):
  - ``./run_peoplesoft_fin_mcp.sh`` — local Python only, no CPython download from GitHub.
  - Or: ``uv run --no-python-downloads --python /usr/bin/python3.12 peoplesoft_fin_server.py``
    (override path with ``UV_PYTHON`` if needed).
"""
from pathlib import Path

import fastmcp
from fastmcp import FastMCP
from starlette.middleware import Middleware
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, Response

from db import execute_query
from llm import FoundryConfigError, chat_with_tools

mcp = FastMCP("peoplesoft-mcp-fin")

DOCS_DIR = Path(__file__).parent / "docs"


@mcp.resource("peoplesoft-fin://schema-guide")
def get_schema_guide() -> str:
    """Major Financials tables by module (GL, AP, AR, PO, AM)."""
    path = DOCS_DIR / "peoplesoft_fin_schema_guide.md"
    if path.exists():
        return path.read_text()
    return "Schema guide not found."


@mcp.resource("peoplesoft-fin://concepts")
def get_concepts_guide() -> str:
    """Business Unit, SetID, ledger, fiscal year/period, voucher lifecycle."""
    path = DOCS_DIR / "peoplesoft_fin_concepts.md"
    if path.exists():
        return path.read_text()
    return "Concepts guide not found."


@mcp.resource("peoplesoft-fin://query-examples")
def get_query_examples() -> str:
    """SQL patterns for GL, AP, AR, and purchasing."""
    path = DOCS_DIR / "sql_query_examples_fin.md"
    if path.exists():
        return path.read_text()
    return "Query examples not found."


@mcp.resource("peoplesoft-fin://peopletools-guide")
def get_peopletools_guide() -> str:
    """PeopleTools metadata (shared with HCM installs)."""
    path = DOCS_DIR / "peopletools_guide.md"
    if path.exists():
        return path.read_text()
    return (
        "Copy peopletools_guide.md from the HR peoplesoft-mcp docs or use "
        "PeopleTools tools (get_record_definition, etc.) for metadata."
    )


@mcp.tool()
async def query_peoplesoft_fin_db(sql_query: str, parameters: list | None = None) -> dict:
    """
    Execute SQL against the PeopleSoft Financials Oracle database.

    Before writing SQL:
    1. Use describe_table('RECORD_NAME') for field list (PSRECFIELD).
    2. Use get_translate_values for status/code fields.
    3. Use get_table_indexes for performance.

    :param sql_query: SQL with optional binds :1, :2, ...
    :param parameters: Bind values
    """
    if parameters is None:
        parameters = []
    return await execute_query(sql_query, parameters)


from tools.introspection import register_tools as register_introspection_tools

register_introspection_tools(mcp)

from tools.gl import register_tools as register_gl_tools

register_gl_tools(mcp)

from tools.ap import register_tools as register_ap_tools

register_ap_tools(mcp)

from tools.ar import register_tools as register_ar_tools

register_ar_tools(mcp)

from tools.purchasing import register_tools as register_purchasing_tools

register_purchasing_tools(mcp)

from tools.assets import register_tools as register_assets_tools

register_assets_tools(mcp)

from tools.peopletools import register_tools as register_peopletools_tools

register_peopletools_tools(mcp)


@mcp.custom_route("/", methods=["GET"])
async def _http_root(request: Request) -> HTMLResponse:
    """Browser-friendly landing page (MCP JSON-RPC is on /mcp)."""
    mcp_path = "/mcp"
    return HTMLResponse(
        f"""<!DOCTYPE html>
<html lang="en">
<head><meta charset="utf-8"/><title>peoplesoft-mcp-fin</title></head>
<body>
<h1>peoplesoft-mcp-fin</h1>
<p>PeopleSoft Financials MCP server is running.</p>
<p>Connect an MCP client to <strong><a href="{mcp_path}">{mcp_path}</a></strong>
(streamable HTTP). A normal browser does not speak that protocol.</p>
</body>
</html>"""
    )


@mcp.custom_route("/favicon.ico", methods=["GET"])
async def _favicon(_request: Request) -> Response:
    return Response(status_code=204)


@mcp.custom_route("/chat", methods=["POST"])
async def _chat(request: Request) -> JSONResponse:
    """Chat endpoint: accepts a user message + optional history, runs Claude tool loop server-side."""
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON body."}, status_code=400)

    message = (body.get("message") or "").strip()
    if not message:
        return JSONResponse({"error": "Missing 'message' field."}, status_code=400)

    history = body.get("history") or []

    try:
        result = await chat_with_tools(mcp, message, history)
        return JSONResponse(result)
    except FoundryConfigError as exc:
        return JSONResponse({"error": str(exc)}, status_code=503)
    except Exception as exc:
        return JSONResponse({"error": f"LLM error: {exc}"}, status_code=502)


def _header(headers: list[tuple[bytes, bytes]], name: bytes) -> str | None:
    for k, v in headers:
        if k.lower() == name.lower():
            return v.decode("latin-1")
    return None


class PeoplesoftFinMcpHttpCompatMiddleware:
    """
    - Browser GET /mcp without ``text/event-stream`` in Accept gets 406 from MCP; return HTML help.
    - POST /mcp with weak Accept (e.g. ``*/*``) fails MCP validation; inject a valid Accept header.
    Uses ``scope["app"].state.path`` so it stays aligned with FastMCP's streamable HTTP path.
    """

    def __init__(self, app):  # noqa: ANN001
        self.app = app

    async def __call__(self, scope, receive, send):  # noqa: ANN001
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        app_inst = scope.get("app")
        mcp_path = getattr(app_inst.state, "path", None) if app_inst is not None else None
        if not mcp_path:
            await self.app(scope, receive, send)
            return

        raw_path = scope.get("path") or "/"
        n_req = (raw_path.rstrip("/") or "/") if raw_path.startswith("/") else f"/{raw_path.rstrip('/')}"
        n_mcp = (mcp_path.rstrip("/") or "/") if mcp_path.startswith("/") else f"/{mcp_path.rstrip('/')}"
        if n_req != n_mcp:
            await self.app(scope, receive, send)
            return

        method = scope.get("method", "GET")
        headers = list(scope.get("headers") or [])

        if method == "GET":
            accept = _header(headers, b"accept") or ""
            tokens = [
                t.strip().split(";")[0].lower()
                for t in accept.split(",")
                if t.strip()
            ]
            if not any(t.startswith("text/event-stream") for t in tokens):
                page = f"""<!DOCTYPE html>
<html lang="en">
<head><meta charset="utf-8"/><title>MCP endpoint</title></head>
<body>
<h1>MCP streamable HTTP</h1>
<p>This URL (<code>{mcp_path}</code>) is for <strong>MCP clients</strong>, not a normal web page.</p>
<p>Browsers do not send <code>Accept: text/event-stream</code>; MCP would respond with <strong>406</strong>.</p>
<p>Use an MCP-enabled client at the same URL. This server uses JSON responses for POST (easier for clients).</p>
<p><a href="/">Back to server home</a></p>
</body>
</html>"""
                resp = HTMLResponse(page, status_code=200)
                await resp(scope, receive, send)
                return

        if method == "POST":
            accept_hdr = _header(headers, b"accept") or ""
            types = [
                mt.strip().split(";")[0].lower()
                for mt in accept_hdr.split(",")
                if mt.strip()
            ]
            has_json = any(t.startswith("application/json") for t in types)
            # Keep in sync with ``mcp.run(..., json_response=True)`` below.
            if not has_json:
                headers = [(k, v) for k, v in headers if k.lower() != b"accept"]
                headers.append((b"accept", b"application/json"))
                scope = {**scope, "headers": headers}

        await self.app(scope, receive, send)


def _mcp_http_compat_middleware() -> Middleware:
    return Middleware(PeoplesoftFinMcpHttpCompatMiddleware)


def _first_free_tcp_port(host: str, start: int, *, attempts: int = 40) -> int:
    """Pick the first bindable TCP port in ``start .. start + attempts - 1``."""
    import socket

    for port in range(start, start + attempts):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind((host, port))
            except OSError:
                continue
            return port
    raise OSError(
        f"No free TCP port on {host!r} in range {start}..{start + attempts - 1}"
    )


def run_mcp() -> None:
    """
    Start the MCP server. Uses stdio when stdin is a pipe (e.g. Cursor); uses HTTP
    on 127.0.0.1 when stdin is an interactive TTY so stray newlines are not parsed as JSON-RPC.
    """
    import os
    import sys

    override = (os.environ.get("PEOPLESOFT_FIN_MCP_TRANSPORT") or "").strip().lower()
    if override in ("stdio", "http"):
        transport = override
    else:
        transport = "stdio" if not sys.stdin.isatty() else "http"

    if transport == "http":
        host = os.environ.get("PEOPLESOFT_FIN_MCP_HTTP_HOST", "127.0.0.1")
        preferred = int(os.environ.get("PEOPLESOFT_FIN_MCP_HTTP_PORT", "8765"))
        port = _first_free_tcp_port(host, preferred)
        if port != preferred:
            print(
                f"Port {preferred} is in use (e.g. suspended job after Ctrl+Z); "
                f"using {port} instead. Stop the old server with `fg` then Ctrl+C, or `kill` it.\n",
                file=sys.stderr,
            )
        print(
            f"Interactive terminal detected: HTTP at http://{host}:{port}/ (info page) "
            f"and http://{host}:{port}/mcp (MCP).\n"
            "(stdio is for IDE clients with a piped stdin; blank lines are invalid JSON-RPC on stdio.)\n"
            "Override: PEOPLESOFT_FIN_MCP_TRANSPORT=stdio|http\n",
            file=sys.stderr,
        )
        mcp.run(
            transport="http",
            host=host,
            port=port,
            json_response=True,
            middleware=[_mcp_http_compat_middleware()],
        )
    else:
        mcp.run(transport="stdio")


if __name__ == "__main__":
    run_mcp()
