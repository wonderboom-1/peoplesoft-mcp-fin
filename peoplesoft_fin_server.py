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
from starlette.responses import HTMLResponse, JSONResponse, Response, StreamingResponse

from db import execute_query
from llm import FoundryConfigError, chat_with_tools, chat_with_tools_stream

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


@mcp.resource("peoplesoft-fin://enhancement-research")
def get_enhancement_research() -> str:
    """MCP enhancement research: LOB handling, component/page tools, AE metadata."""
    path = DOCS_DIR / "mcp-enhancement-research-report.md"
    if path.exists():
        return path.read_text()
    return "Enhancement research report not found."


@mcp.resource("peoplesoft-fin://sql-metadata-research")
def get_sql_metadata_research() -> str:
    """SQL metadata research: PSSQLDEFN, PSSQLTEXTDEFN, PSAESTMTDEFN join paths."""
    path = DOCS_DIR / "peoplesoft-sql-metadata-research.md"
    if path.exists():
        return path.read_text()
    return "SQL metadata research not found."


@mcp.resource("peoplesoft-fin://peopletools-tables-by-tool")
def get_peopletools_tables_by_tool() -> str:
    """Tool-to-table dependency map for DB grants and migrations."""
    path = DOCS_DIR / "peopletools-tables-by-tool.md"
    if path.exists():
        return path.read_text()
    return "PeopleTools tables-by-tool guide not found."


import re as _re

_column_cache: dict[str, list[str]] = {}

# Multi-part tokens that are SQL functions/keywords, not PeopleSoft columns
_SQL_FUNCS = frozenset({
    "ROW_NUMBER", "DENSE_RANK", "TO_DATE", "TO_CHAR", "TO_NUMBER",
    "TO_TIMESTAMP", "TO_CLOB", "TO_NCHAR", "DBMS_LOB", "CONNECT_BY",
    "SYS_CONTEXT", "NVL2", "CURRENT_DATE", "ORDER_BY", "GROUP_BY",
    "FETCH_FIRST", "ROWS_ONLY", "WITHIN_GROUP",
})


# PeopleSoft physical table names can differ from the metadata RECNAME.
# Example: PS_JRNL_HDR / PS_JRNL_LN come from records JRNL_HEADER / JRNL_LINE.
# Map the SQL table suffix → real RECNAME so PSRECFIELD lookups succeed.
_TABLE_TO_RECNAME: dict[str, str] = {
    "JRNL_HDR": "JRNL_HEADER",
    "JRNL_LN": "JRNL_LINE",
    "JRNL_HDR_H": "JRNL_HDR_H",
    "VCHR_HDR": "VOUCHER",
    "VCHR_LINE": "VOUCHER_LINE",
    "VCHR_DIST_LN": "DISTRIB_LINE",
}


async def _get_columns_for_table(recname: str) -> list[str]:
    """Lookup column names from PSRECFIELD (cached after first hit)."""
    rec = recname.upper()
    if rec in _column_cache:
        return _column_cache[rec]
    # Try the name as-is first, then the mapped RECNAME if different.
    candidates = [rec]
    mapped = _TABLE_TO_RECNAME.get(rec)
    if mapped and mapped != rec:
        candidates.append(mapped)
    cols: list[str] = []
    for candidate in candidates:
        result = await execute_query(
            "SELECT FIELDNAME FROM PSRECFIELD WHERE RECNAME = :1 ORDER BY FIELDNUM",
            [candidate],
        )
        if "error" not in result and result.get("results"):
            cols = [r["FIELDNAME"] for r in result["results"]]
            break
    _column_cache[rec] = cols
    return cols


async def _find_similar_tables(recname: str, limit: int = 10) -> list[str]:
    """Search PSRECDEFN for tables with names similar to a missing one."""
    fragments = recname.upper().replace("_", "%")
    result = await execute_query(
        "SELECT RECNAME, RECDESCR FROM PSRECDEFN "
        "WHERE RECTYPE = 0 AND RECNAME LIKE :1 "
        "ORDER BY RECNAME FETCH FIRST :2 ROWS ONLY",
        [f"%{fragments}%", limit],
    )
    if "error" in result or not result.get("results"):
        return []
    return [f"PS_{r['RECNAME']} — {r['RECDESCR']}" for r in result["results"]]


def _extract_ps_table_names(sql: str) -> list[str]:
    """Extract PS_* record names from FROM / JOIN clauses in a SQL statement."""
    matches = _re.findall(r'(?:FROM|JOIN)\s+PS_(\w+)', sql, _re.IGNORECASE)
    return list(dict.fromkeys(m.upper() for m in matches))


# Common PeopleTools system tables that don't have the PS_ prefix
_PEOPLETOOLS_TABLES = frozenset({
    "PSRECDEFN", "PSRECFIELD", "PSDBFIELD", "PSKEYDEFN", "PSINDEXDEFN",
    "PSXLATITEM", "PSPNLDEFN", "PSPNLFIELD", "PSPNLGRPDEFN", "PSPNLGROUP",
    "PSMENUITEM", "PSPCMPROG", "PSPCMTXT", "PSPCMPROG_COMP",
    "PSAEAPPLDEFN", "PSAESTEPDEFN", "PSAESTEPMSGDEFN", "PSAESECTDEFN",
    "PSSQLDEFN", "PSSQLTEXTDEFN",
    "PSQRYDEFN", "PSQRYRECORD", "PSQRYFIELD", "PSQRYCRITERIA", "PSQRYACCLST",
    "PSOPERATION", "PSMSGDEFN", "PSMSGPARTDEFN",
    "PSCLASSDEFN", "PSROLEDEFN", "PSROLECLASS", "PSOPRDEFN", "PSAUTHITEM",
    "PSPRCSDEFN", "PSAERUNCNTL", "PSAERUNCONTROL",
    "PSPRCSRQST", "PSPRCSPARMS",
})


def _extract_peopletools_table_names(sql: str) -> list[str]:
    """Extract PeopleTools system table names (PS* without underscore) from FROM/JOIN."""
    matches = _re.findall(r'(?:FROM|JOIN)\s+(PS[A-Z]\w+)', sql, _re.IGNORECASE)
    return list(dict.fromkeys(m.upper() for m in matches if "." not in m))


async def _get_columns_for_system_table(table_name: str) -> list[str]:
    """Get column names for a PeopleTools system table from Oracle metadata."""
    result = await execute_query(
        "SELECT COLUMN_NAME FROM ALL_TAB_COLUMNS "
        "WHERE TABLE_NAME = :1 ORDER BY COLUMN_ID",
        [table_name.upper()],
    )
    if "error" not in result and result.get("results"):
        return [r["COLUMN_NAME"] for r in result["results"]]
    return []


def _schema_block(table_cols: dict[str, list[str]]) -> str:
    """Format table→column map for error messages."""
    return "\n".join(f"PS_{rec}: {', '.join(cols)}" for rec, cols in table_cols.items())


async def _pre_validate_sql(sql: str) -> dict | None:
    """
    Pre-validate SQL against PSRECFIELD / ALL_TAB_COLUMNS *before* hitting Oracle.

    Checks:
      1. All PS_* tables in FROM/JOIN actually exist in PSRECDEFN.
      2. PeopleTools system table columns via ALL_TAB_COLUMNS.
      3. Qualified column refs (alias.COL) match real columns on those tables.

    Returns an error dict if problems found, or None if OK.
    """
    recnames = _extract_ps_table_names(sql)
    pt_tables = _extract_peopletools_table_names(sql)

    if not recnames and not pt_tables:
        return None

    all_valid: set[str] = set()
    table_cols: dict[str, list[str]] = {}
    missing_tables: list[str] = []

    # PS_* application tables via PSRECFIELD
    for rec in recnames:
        cols = await _get_columns_for_table(rec)
        if cols:
            table_cols[rec] = cols
            all_valid.update(cols)
        else:
            missing_tables.append(rec)

    # --- Check 1: doubled PS_ prefix (e.g. PS_PSAEAPPLDEFN) --------------------
    doubled = [r for r in missing_tables if r.startswith("PS") and not r.startswith("PS_")]
    if doubled:
        return {
            "error": (
                "PeopleTools system tables do NOT have a PS_ prefix. "
                + ", ".join(f"PS_{r} should be just {r}" for r in doubled)
                + ". Rewrite the query using the correct table name."
            )
        }

    # PeopleTools system tables via ALL_TAB_COLUMNS
    pt_table_cols: dict[str, list[str]] = {}
    for tbl in pt_tables:
        cols = await _get_columns_for_system_table(tbl)
        if cols:
            pt_table_cols[tbl] = cols
            all_valid.update(cols)

    if not all_valid:
        return None

    # Strip string literals so quoted values like 'GL_ACCOUNT_TBL' aren't parsed
    sql_stripped = _re.sub(r"'[^']*'", "''", sql.upper())

    # Combine all known tables for exclusion
    known_table_names = {f"PS_{r}" for r in recnames} | set(recnames) | set(pt_tables)

    # --- Check 2: qualified column refs (alias.COLUMN) ----------------------------
    # Only check qualified refs — bare identifiers are too error-prone because they
    # pick up table aliases, column aliases, CTE names, inline-view aliases, etc.
    refs = set(_re.findall(r'\w+\.([A-Z][A-Z0-9_]+)', sql_stripped))
    refs -= _SQL_FUNCS
    refs -= known_table_names

    invalid = refs - all_valid

    if invalid:
        schema_parts: list[str] = []
        for rec, cols in table_cols.items():
            schema_parts.append(f"PS_{rec}: {', '.join(cols)}")
        for tbl, cols in pt_table_cols.items():
            schema_parts.append(f"{tbl}: {', '.join(cols)}")
        return {
            "error": (
                f"Invalid column(s): {', '.join(sorted(invalid))}. "
                "These do not exist on the referenced tables.\n\n"
                "Actual columns:\n" + "\n".join(schema_parts)
                + "\n\nRewrite the query using ONLY these column names."
            )
        }

    return None


@mcp.tool()
async def query_peoplesoft_fin_db(sql_query: str, parameters: list | None = None) -> dict:
    """
    Execute SQL against the PeopleSoft Financials Oracle database.

    IMPORTANT — before writing ANY SQL you MUST:
    1. Call describe_table('RECORD_NAME') to get the real column names.
       Do NOT guess — PeopleSoft schemas vary and wrong columns cause ORA-00904.
    2. Use list_tables(pattern) to verify a table exists before querying it.
       Do NOT guess table names — wrong names cause ORA-00942.
    3. Use get_translate_values for status/code fields instead of hard-coding.
    4. Check get_table_indexes for performance on large tables.

    :param sql_query: SQL with optional binds :1, :2, ...
    :param parameters: Bind values
    """
    if parameters is None:
        parameters = []

    # Fast pre-validation: catch bad columns/tables without hitting Oracle
    pre_err = await _pre_validate_sql(sql_query)
    if pre_err is not None:
        return pre_err

    result = await execute_query(sql_query, parameters)

    # Fallback post-validation for anything the pre-check missed
    err = result.get("error", "")

    if "ORA-00904" in err:
        schema_lines: list[str] = []
        # PS_* application tables
        recnames = _extract_ps_table_names(sql_query)
        for rec in recnames:
            cols = await _get_columns_for_table(rec)
            if cols:
                schema_lines.append(f"PS_{rec}: {', '.join(cols)}")
        # PeopleTools system tables (PSRECDEFN, PSSQLTEXTDEFN, etc.)
        pt_tables = _extract_peopletools_table_names(sql_query)
        for tbl in pt_tables:
            cols = await _get_columns_for_system_table(tbl)
            if cols:
                schema_lines.append(f"{tbl}: {', '.join(cols)}")
        if schema_lines:
            result["error"] += (
                "\n\nActual columns for the referenced tables:\n"
                + "\n".join(schema_lines)
                + "\n\nRewrite the query using ONLY these column names."
            )

    elif "ORA-00942" in err:
        recnames = _extract_ps_table_names(sql_query)
        suggestions: list[str] = []
        for rec in recnames:
            # Detect doubled prefix: PS_PSAEAPPLDEFN → the real table is PSAEAPPLDEFN
            if rec.startswith("PS") and not rec.startswith("PS_"):
                suggestions.append(
                    f"PS_{rec} does not exist. PeopleTools system tables do NOT "
                    f"have a PS_ prefix — use {rec} directly (e.g. PSRECDEFN, "
                    f"PSAEAPPLDEFN, PSDBFIELD)."
                )
                continue
            exists = await _get_columns_for_table(rec)
            if not exists:
                similar = await _find_similar_tables(rec)
                if similar:
                    suggestions.append(
                        f"PS_{rec} does not exist. Similar tables:\n  "
                        + "\n  ".join(similar)
                    )
                else:
                    suggestions.append(
                        f"PS_{rec} does not exist. Use list_tables(pattern='{rec.split('_')[0]}') "
                        "to find the correct table name."
                    )
        if suggestions:
            result["error"] += (
                "\n\n" + "\n".join(suggestions)
                + "\n\nUse list_tables() or describe_table() to verify table names before querying."
            )

    return result


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

from tools.performance import register_tools as register_performance_tools

register_performance_tools(mcp)


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
async def _chat(request: Request) -> StreamingResponse | JSONResponse:
    """Chat endpoint: streams SSE events as Claude processes the request."""
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON body."}, status_code=400)

    message = (body.get("message") or "").strip()
    if not message:
        return JSONResponse({"error": "Missing 'message' field."}, status_code=400)

    history = body.get("history") or []

    return StreamingResponse(
        chat_with_tools_stream(mcp, message, history),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


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
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
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
