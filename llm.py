"""
LLM integration for PeopleSoft Finance MCP — Claude on Azure AI Foundry.

Reads MICROSOFT_FOUNDRY_API_KEY and MICROSOFT_FOUNDRY_BASE_URL from the
environment (loaded by python-dotenv in db.py) and implements the Claude
Messages API tool loop using aiohttp + FastMCP's mcp.call_tool().

Optimizations over the original blocking implementation:
- SSE streaming for progressive frontend updates
- Parallel tool execution via asyncio
- Cached tool schemas (built once, reused across requests)
- Persistent aiohttp session (avoids TLS handshake per request)
"""
from __future__ import annotations

import asyncio
import json
import os
from typing import Any, AsyncIterator

import aiohttp
from fastmcp import FastMCP

ANTHROPIC_VERSION = "2023-06-01"
DEFAULT_MODEL = "claude-sonnet-4-5"
MAX_TOOL_ROUNDS = 15
MAX_TOKENS = 8192

# Token-management constants to stay under the 200K prompt limit
MAX_TOOL_RESULT_CHARS = 8_000
MAX_HISTORY_PAIRS = 6
MAX_HISTORY_MSG_CHARS = 3_000

SYSTEM_PROMPT = (
    "You are an assistant for Oracle PeopleSoft Financials (FSCM). "
    "You have access to MCP tools that query a live PeopleSoft database "
    "(GL, AP, AR, purchasing, assets, PeopleTools metadata, and raw SQL "
    "via query_peoplesoft_fin_db).\n\n"
    "Rules:\n"
    "1. Always try semantic tools first (get_vendor, search_vendors, "
    "get_gl_account, get_budget_vs_actual, search_budget_exceptions, "
    "get_commitment_control_budget, check_budget_status, get_period_close_status, "
    "get_journal_posting_summary, get_exchange_rate, convert_amount, "
    "list_tables, etc.) before writing raw SQL.\n"
    "2. BEFORE writing any SQL with query_peoplesoft_fin_db, you MUST call "
    "describe_table(table_name) to verify the exact column names. "
    "Do NOT guess column names — PeopleSoft table schemas vary across "
    "installations and versions. A wrong column causes ORA-00904.\n"
    "3. Use get_translate_values to decode status/code fields rather than "
    "hard-coding lookup values.\n"
    "4. When using query_peoplesoft_fin_db, use bind placeholders :1, :2 and "
    "pass parameters when appropriate.\n"
    "5. Explain results clearly for finance and IT users; cite tool names "
    "briefly when useful.\n"
    "6. If the database returns an error, explain it and suggest a safer next step.\n"
    "7. For Payables vouchers, prefer tools and tables in this order: PS_VOUCHER "
    "(header), PS_VOUCHER_LINE (lines), PS_DISTRIB_LINE (GL distributions). "
    "Use get_voucher_distribution_lines for distrib rows, not get_voucher_lines. "
    "PS_VOUCHER has NO CURRENCY_CD — use TXN_CURRENCY_CD (transaction currency) "
    "or BASE_CURRENCY (base currency). "
    "PS_VENDOR_LOC is for payment/purchasing config (terms, freight, ERS) — it has NO address columns. "
    "For vendor country/address data, use PS_VENDOR_ADDR (COUNTRY, ADDRESS1, CITY, STATE, POSTAL, EFFDT, EFF_STATUS).\n"
    "7b. Journal tables: PS_JRNL_HEADER (not PS_JRNL_HDR) and PS_JRNL_LN. "
    "PS_JRNL_HEADER has NO LAST_UPDATE_DATE — use DTTM_STAMP_SEC.\n"
    "7c. For budget vs actual analysis, USE get_budget_vs_actual or search_budget_exceptions "
    "tools — do NOT write raw SQL. PS_LEDGER and PS_LEDGER_BUDG use POSTED_TOTAL_AMT "
    "(NOT MONETARY_AMOUNT or BUDGET_AMOUNT) and have LEDGER (NOT LEDGER_GROUP). "
    "PS_LEDGER_KK also uses POSTED_TOTAL_AMT. For commitment control budgets use "
    "get_commitment_control_budget or check_budget_status.\n"
    "7d. PS_VENDOR has NO EFFDT or EFF_STATUS columns — use VENDOR_STATUS for status. "
    "PS_CUSTOMER has NO EFFDT or EFF_STATUS columns — use CUST_STATUS for status. "
    "PS_ACCT_CD_TBL does NOT exist — the chart-of-accounts table is PS_GL_ACCOUNT_TBL. "
    "For effective-dating examples, use PS_GL_ACCOUNT_TBL or PS_DEPT_TBL (both have "
    "EFFDT and EFF_STATUS). Always call describe_table() before assuming a table has EFFDT.\n"
    "7e. PS_ASSET uses BUSINESS_UNIT (NOT BUSINESS_UNIT_AM), TAG_NUMBER (NOT TAG_NBR), "
    "ACQUISITION_DT (NOT ACQUIRE_DT), MODEL (NOT MODEL_NBR). "
    "PS_ASSET has NO COST or QUANTITY columns — cost data is in PS_COST (BUSINESS_UNIT, ASSET_ID, BOOK).\n"
    "7f. PS_FIN_OPEN_PERIOD has NO FISCAL_YEAR, ACCOUNTING_PERIOD, or OPEN_STATUS columns. "
    "It uses OPEN_YEAR_FROM/TO, OPEN_PERIOD_FROM/TO, OPEN_FROM_DATE/TO_DATE, "
    "LEDGER_GROUP, CALENDAR_ID, TRANSACTION_TYPE, LEDGER_CODE, GL_ADJUST_TYPE. "
    "For period status use the get_period_close_status or list_open_periods tools.\n"
    "7g. For currency conversion, USE get_exchange_rate or convert_amount tools — "
    "do NOT write raw SQL against PS_RT_RATE_TBL. "
    "PS_RT_RATE_TBL cols: RT_RATE_INDEX, FROM_CUR, TO_CUR, RT_TYPE, EFFDT, "
    "RATE_MULT, RATE_DIV (converted = source * RATE_MULT / RATE_DIV). "
    "Common RT_TYPE: CURR, SPOT, AVGMO, AVGYR. Default RT_RATE_INDEX is 'MARKET'. "
    "PS_RT_RATE_TBL has NO EXCHANGE_RATE, CURRENCY_CD, or RATE column.\n"
    "8. PeopleTools system/metadata tables do NOT have a PS_ prefix — their names "
    "start with PS directly (e.g. PSAEAPPLDEFN, PSRECDEFN, PSDBFIELD, PSRECFIELD, "
    "PSPNLDEFN, PSPNLFIELD, PSXLATITEM, PSKEYDEFN, PSPNLGRPDEFN, "
    "PSSQLDEFN, PSSQLTEXTDEFN, PSTREEDEFN, PSTREENODE, PSTREELEAF, PSTREESTRCT). "
    "Application data tables use the PS_ prefix (e.g. PS_VENDOR, PS_LEDGER). "
    "Never write PS_PSSQLDEFN — just PSSQLDEFN.\n"
    "9. To find SQL objects by owner/user, query PSSQLDEFN (has LASTUPDOPRID, "
    "LASTUPDDTTM, SQLID, SQLTYPE, OBJECTOWNERID, VERSION). "
    "PSSQLTEXTDEFN stores the actual SQL text (SQLID, SQLTYPE, MARKET, SEQNUM, SQLTEXT) "
    "but does NOT have LASTUPDOPRID/LASTUPDDTTM. Use PSSQLDEFN for ownership queries "
    "and get_sql_definition(sql_id) to retrieve SQL text.\n"
    "10. PS_BUS_UNIT_TBL_GL and PS_BUS_UNIT_TBL_AP do NOT have DESCR or SETID. "
    "For business unit descriptions, join PS_BUS_UNIT_TBL_FS (cols: BUSINESS_UNIT, "
    "DESCR, DESCRSHORT). To find the SetID for a business unit, query "
    "PS_SET_CNTRL_REC (cols: SETCNTRLVALUE, REC_GROUP_ID, RECNAME, SETID) "
    "where SETCNTRLVALUE = <business_unit> and RECNAME = <target_record>. "
    "Always call describe_table() first to verify columns before writing SQL.\n"
    "11. In multi-table JOINs, ALWAYS qualify every column with its table alias "
    "(e.g. a.OPRID, not bare OPRID). PeopleTools tables share many column names "
    "(OPRID, OPRCLASS, EFFDT, etc.) and unqualified references cause ORA-00918.\n"
    "12. For PeopleTools security tables (PSOPRDEFN, PSROLEUSER, PSROLECLASS, "
    "PSCLASSDEFN, PSAUTHITEM, PSAUTHBUSCOMP, PSOPRCLS, PSOPERATION, PSMENUDEFN, "
    "PSMENUITEM, PS_SCRTY_ACC_GRP, PSROLEDEFN) and App Engine tables (PSAEAPPLDEFN, "
    "PSAESECTDEFN, PSAESTEPDEFN, PSAESTEPMSGDEFN), ALWAYS call describe_table() first "
    "to get exact column names. Common mistakes to avoid:\n"
    "  - PSROLEUSER uses ROLEUSER not OPRID; PSOPRDEFN uses OPRCLASS not CLASSID; "
    "PSOPRDEFN has NO OPRSTATUS column (use ACCTLOCK for lock status)\n"
    "  - PSOPRCLS cols: OPRID, OPRCLASS (no CLASSID)\n"
    "  - PSCLASSDEFN cols: CLASSID, VERSION, CLASSDEFNDESC, TIMEOUTMINUTES, "
    "LASTUPDDTTM, LASTUPDOPRID (no DESCR, no CLASSDESCLONG, no EFFDT)\n"
    "  - PSAUTHITEM cols: CLASSID, MENUNAME, BARNAME, BARITEMNAME, PNLITEMNAME, "
    "DISPLAYONLY, AUTHORIZEDACTIONS (no PNLGRPNAME, no MARKET, no AUTHVALUE)\n"
    "  - PSMENUITEM cols: MENUNAME, BARNAME, ITEMNAME, ITEMNUM, ITEMTYPE, "
    "PNLGRPNAME, MARKET, BARLABEL, ITEMLABEL, XFERCOUNT, SEARCHRECNAME "
    "(no MENUITEMLABEL, no MENUITEMTYPE)\n"
    "  - To JOIN PSAUTHITEM to PSMENUITEM: ON a.MENUNAME=b.MENUNAME "
    "AND a.BARNAME=b.BARNAME AND a.BARITEMNAME=b.ITEMNAME\n"
    "  - PSAUTHBUSCOMP only has CLASSID, BCNAME, BCMETHOD, AUTHORIZEDACTIONS (no MENUNAME)\n"
    "  - PSOPERATION uses IB_OPERATIONNAME (no OPERNAME/OPERTYPE/OPERSTYLE)\n"
    "  - PSAESTEPDEFN has NO AE_ACTION_TYPE, FIELDNAME, or RECNAME\n"
    "  - Tables that do NOT exist: PSAESTEPDTLDEFN, PSIBCDEFN, PSAUTHPNLGRP, PSAUTHRECN, "
    "PSPRCSDEFN (use PS_PRCSDEFN instead)\n"
    "  - PS_SCRTY_ACC_GRP has NO OPRID or BUSINESS_UNIT columns\n"
    "  - For IB services use get_integration_broker_services or query PSOPERATION\n"
    "  - App Engine SQL is in PSSQLTEXTDEFN via SQLID; use get_sql_definition()\n"
    "  - Roles for user: SELECT ROLENAME FROM PSROLEUSER WHERE ROLEUSER = :1\n"
    "  - Permission lists for role: SELECT CLASSID FROM PSROLECLASS WHERE ROLENAME = :1\n"
    "  - Role descriptions are in PSROLEDEFN, NOT PSROLECLASS.\n"
    "  - PSSQLDEFN.SQLTYPE is NUMBER (not string) — use TO_CHAR(SQLTYPE) in UNION ALL\n"
    "  - PSDBFIELD uses DESCRLONG (not LONGNAME/DESCR); PSPNLGRPDEFN/PSPNLDEFN/"
    "PSMENUDEFN/PSQRYDEFN all use DESCR (not PNLGRPDESC/PNLDESCR/MENUDESCRLONG)\n"
    "  - Process definitions: use PS_PRCSDEFN (has PS_ prefix, it is an app table).\n"
    "13. PeopleTools DTTM columns (LASTUPDDTTM, LASTSIGNONDTTM) are TIMESTAMP, not DATE. "
    "SYSDATE minus TIMESTAMP returns INTERVAL, not NUMBER. "
    "Use EXTRACT(DAY FROM (SYSTIMESTAMP - col)) or TRUNC(CAST(SYSTIMESTAMP AS DATE) - CAST(col AS DATE)) for day counts."
)


class FoundryConfigError(Exception):
    """Raised when required Foundry environment variables are missing."""


def _build_messages_url(base_url: str) -> str:
    """
    Normalize a Foundry base URL into the full Messages API endpoint.

    Handles all common forms:
      - https://host.services.ai.azure.com
      - https://host.services.ai.azure.com/anthropic
      - https://host.services.ai.azure.com/anthropic/v1/messages
    """
    import re

    url = base_url.rstrip("/")
    url = re.sub(r"/v1/messages/?$", "", url, flags=re.IGNORECASE)
    url = re.sub(r"/anthropic/?$", "", url, flags=re.IGNORECASE)
    return f"{url}/anthropic/v1/messages"


def get_foundry_config() -> dict[str, str]:
    """Return Foundry connection details from environment variables."""
    api_key = os.environ.get("MICROSOFT_FOUNDRY_API_KEY", "").strip()
    base_url = os.environ.get("MICROSOFT_FOUNDRY_BASE_URL", "").strip()
    model = os.environ.get("MICROSOFT_FOUNDRY_MODEL", "").strip() or DEFAULT_MODEL

    if not api_key:
        raise FoundryConfigError(
            "MICROSOFT_FOUNDRY_API_KEY is not set. Add it to .env in the project root."
        )
    if not base_url:
        raise FoundryConfigError(
            "MICROSOFT_FOUNDRY_BASE_URL is not set. Add it to .env in the project root."
        )

    messages_url = _build_messages_url(base_url)
    return {"api_key": api_key, "base_url": base_url, "model": model, "messages_url": messages_url}


# ---------------------------------------------------------------------------
# Cached tool schemas — built once, reused across all requests
# ---------------------------------------------------------------------------
_cached_tools: list[dict[str, Any]] | None = None


async def list_tools_for_claude(mcp: FastMCP) -> list[dict[str, Any]]:
    """Convert FastMCP tool definitions to the Anthropic tool schema format (cached)."""
    global _cached_tools
    if _cached_tools is not None:
        return _cached_tools

    tools = await mcp.list_tools()
    claude_tools: list[dict[str, Any]] = []
    for t in tools:
        schema = dict(t.inputSchema) if hasattr(t, "inputSchema") else {}
        if hasattr(t, "parameters"):
            schema = dict(t.parameters) if t.parameters else {}
        schema.setdefault("type", "object")
        if schema.get("type") == "object" and "properties" not in schema:
            schema["properties"] = {}
        claude_tools.append({
            "name": t.name,
            "description": (t.description or f"PeopleSoft MCP tool: {t.name}")[:8000],
            "input_schema": schema,
        })
    _cached_tools = claude_tools
    return _cached_tools


# ---------------------------------------------------------------------------
# Persistent aiohttp session — reused across requests (avoids TLS handshake)
# ---------------------------------------------------------------------------
_http_session: aiohttp.ClientSession | None = None


def _get_session() -> aiohttp.ClientSession:
    """Return a long-lived aiohttp session, creating one if needed."""
    global _http_session
    if _http_session is None or _http_session.closed:
        _http_session = aiohttp.ClientSession()
    return _http_session


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _tool_result_to_text(result: Any) -> str:
    """Extract text from a FastMCP ToolResult (list of content blocks)."""
    if isinstance(result, str):
        return result
    content = getattr(result, "content", None)
    if content is None:
        return json.dumps(result, default=str)
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if hasattr(block, "text"):
                parts.append(block.text)
            else:
                parts.append(json.dumps(block, default=str))
        return "\n".join(parts) or json.dumps(result, default=str)
    return str(content)


def _sse(event: str, data: dict[str, Any]) -> str:
    """Format a single Server-Sent Event."""
    return f"event: {event}\ndata: {json.dumps(data, default=str)}\n\n"


# ---------------------------------------------------------------------------
# Streaming chat with tools (SSE async generator)
# ---------------------------------------------------------------------------

async def chat_with_tools_stream(
    mcp: FastMCP,
    user_message: str,
    history: list[dict[str, Any]] | None = None,
) -> AsyncIterator[str]:
    """
    Async generator yielding SSE events for each step of the Claude tool loop.

    Event types:
      status      - progress message (e.g. "Calling Claude...")
      tool_start  - tool invoked (name, args, index)
      tool_result - tool finished (name, args, result, index)
      text        - final assistant text
      done        - end of response
      error       - error occurred
    """
    try:
        config = get_foundry_config()
    except FoundryConfigError as exc:
        yield _sse("error", {"error": str(exc)})
        return

    claude_tools = await list_tools_for_claude(mcp)
    session = _get_session()

    messages: list[dict[str, Any]] = []
    if history:
        # Keep only the last MAX_HISTORY_PAIRS user+assistant pairs
        valid = [
            e for e in history
            if e.get("role") in ("user", "assistant") and e.get("content")
        ]
        if len(valid) > MAX_HISTORY_PAIRS * 2:
            valid = valid[-(MAX_HISTORY_PAIRS * 2):]
        for entry in valid:
            content = entry["content"]
            if isinstance(content, str) and len(content) > MAX_HISTORY_MSG_CHARS:
                content = content[:MAX_HISTORY_MSG_CHARS] + "\n… [truncated]"
            messages.append({"role": entry["role"], "content": content})
    messages.append({"role": "user", "content": user_message})

    headers = {
        "Content-Type": "application/json",
        "anthropic-version": ANTHROPIC_VERSION,
        "Authorization": f"Bearer {config['api_key']}",
        "api-key": config["api_key"],
        "x-api-key": config["api_key"],
    }

    yield _sse("status", {"message": "Calling Claude…"})

    rounds = 0
    while rounds < MAX_TOOL_ROUNDS:
        rounds += 1

        body: dict[str, Any] = {
            "model": config["model"],
            "max_tokens": MAX_TOKENS,
            "system": SYSTEM_PROMPT,
            "messages": messages,
        }
        if claude_tools:
            body["tools"] = claude_tools

        try:
            async with session.post(
                config["messages_url"], headers=headers, json=body
            ) as resp:
                if resp.status == 429:
                    retry_after = int(resp.headers.get("retry-after", "2"))
                    yield _sse("status", {"message": f"Rate limited — retrying in {retry_after}s…"})
                    await asyncio.sleep(retry_after)
                    rounds -= 1
                    continue
                data = await resp.json()
        except Exception as exc:
            yield _sse("error", {"error": f"Network error calling Claude: {exc}"})
            return

        if "error" in data:
            err_msg = data["error"]
            if isinstance(err_msg, dict):
                err_msg = err_msg.get("message", str(err_msg))
            yield _sse("error", {"error": f"Claude API error: {err_msg}"})
            return

        blocks = data.get("content", [])
        if not blocks:
            yield _sse("error", {"error": "Claude returned an empty response."})
            return

        tool_uses = [b for b in blocks if b.get("type") == "tool_use"]

        if not tool_uses:
            text = "\n".join(
                b.get("text", "") for b in blocks if b.get("type") == "text"
            ).strip()
            yield _sse("text", {"text": text or "(No text response)"})
            yield _sse("done", {})
            return

        messages.append({"role": "assistant", "content": blocks})

        # Emit tool_start for each tool call
        n = len(tool_uses)
        yield _sse("status", {"message": f"Executing {n} tool{'s' if n != 1 else ''}…"})
        for i, block in enumerate(tool_uses):
            yield _sse("tool_start", {
                "index": i,
                "name": block["name"],
                "args": block.get("input", {}),
            })

        # Execute tools in parallel; stream results as each finishes
        result_queue: asyncio.Queue[tuple[int, str, str, dict, str]] = asyncio.Queue()

        async def _exec_tool(idx: int, blk: dict[str, Any]) -> None:
            name = blk["name"]
            args = blk.get("input", {})
            try:
                result = await mcp.call_tool(name, args)
                result_text = _tool_result_to_text(result)
            except Exception as exc:
                result_text = f"Error executing tool: {exc}"
            await result_queue.put((idx, blk["id"], name, args, result_text))

        tasks = [asyncio.create_task(_exec_tool(i, b)) for i, b in enumerate(tool_uses)]

        tool_results_for_claude: list[dict[str, Any]] = []
        for _ in range(len(tool_uses)):
            idx, tool_use_id, name, args, result_text = await result_queue.get()
            preview = result_text[:2000] if len(result_text) > 2000 else result_text
            yield _sse("tool_result", {
                "index": idx,
                "name": name,
                "args": args,
                "result": preview,
            })
            claude_text = result_text
            if len(claude_text) > MAX_TOOL_RESULT_CHARS:
                claude_text = (
                    claude_text[:MAX_TOOL_RESULT_CHARS]
                    + f"\n… [truncated, showing first {MAX_TOOL_RESULT_CHARS} of {len(result_text)} chars]"
                )
            tool_results_for_claude.append({
                "type": "tool_result",
                "tool_use_id": tool_use_id,
                "content": claude_text,
            })

        await asyncio.gather(*tasks)

        messages.append({"role": "user", "content": tool_results_for_claude})
        yield _sse("status", {"message": "Calling Claude with tool results…"})

    yield _sse("error", {"error": f"Stopped after {MAX_TOOL_ROUNDS} tool rounds (safety limit)."})


# ---------------------------------------------------------------------------
# Non-streaming wrapper (backward compatible with original API)
# ---------------------------------------------------------------------------

def _parse_sse_event(raw: str) -> tuple[str, dict[str, Any]]:
    """Parse a single SSE event string into (event_type, data_dict)."""
    event_type = ""
    data_str = ""
    for line in raw.strip().split("\n"):
        if line.startswith("event: "):
            event_type = line[7:]
        elif line.startswith("data: "):
            data_str = line[6:]
    return event_type, json.loads(data_str) if data_str else {}


async def chat_with_tools(
    mcp: FastMCP,
    user_message: str,
    history: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """
    Run a full Claude tool loop (non-streaming).

    Returns ``{"reply": str, "tool_calls": [{"name", "args", "result"}, ...]}``.
    """
    tool_calls_log: list[dict[str, Any]] = []
    reply_text = ""

    async for event_str in chat_with_tools_stream(mcp, user_message, history):
        event_type, data = _parse_sse_event(event_str)
        if event_type == "tool_result":
            tool_calls_log.append({
                "name": data["name"],
                "args": data["args"],
                "result": data["result"],
            })
        elif event_type == "text":
            reply_text = data["text"]
        elif event_type == "error":
            raise RuntimeError(data["error"])

    return {"reply": reply_text or "(No text response)", "tool_calls": tool_calls_log}
