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
MAX_TOOL_ROUNDS = 24
MAX_TOKENS = 8192

# Token-management constants to stay under the 200K prompt limit
MAX_TOOL_RESULT_CHARS = 12_000
MAX_HISTORY_PAIRS = 10
MAX_HISTORY_MSG_CHARS = 4_000

SYSTEM_PROMPT = (
    "You are an assistant for Oracle PeopleSoft Financials (FSCM). "
    "You have access to MCP tools that query a live PeopleSoft database "
    "(GL, AP, AR, purchasing, assets, PeopleTools metadata, and raw SQL "
    "via query_peoplesoft_fin_db).\n\n"
    "Rules:\n"
    "1. Always try semantic tools first (get_vendor, search_vendors, "
    "get_gl_account, list_tables, etc.) before writing raw SQL.\n"
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
    "Use get_voucher_distribution_lines for distrib rows, not get_voucher_lines.\n"
    "8. PeopleTools system/metadata tables do NOT have a PS_ prefix — their names "
    "start with PS directly (e.g. PSAEAPPLDEFN, PSRECDEFN, PSDBFIELD, PSRECFIELD, "
    "PSPNLDEFN, PSPNLFIELD, PSXLATITEM, PSKEYDEFN, PSPNLGRPDEFN, "
    "PSSQLDEFN, PSSQLTEXTDEFN). "
    "Application data tables use the PS_ prefix (e.g. PS_VENDOR, PS_LEDGER). "
    "Never write PS_PSSQLDEFN — just PSSQLDEFN.\n"
    "9. To find SQL objects by owner/user, query PSSQLDEFN (has LASTUPDOPRID, "
    "LASTUPDDTTM, SQLID, SQLTYPE, OBJECTOWNERID, VERSION). "
    "PSSQLTEXTDEFN stores the actual SQL text (SQLID, SQLTYPE, MARKET, SEQNUM, SQLTEXT) "
    "but does NOT have LASTUPDOPRID/LASTUPDDTTM. Use PSSQLDEFN for ownership queries "
    "and get_sql_definition(sql_id) to retrieve SQL text.\n"
    "10. PS_BUS_UNIT_TBL_GL does NOT have a SETID column. To find the SetID "
    "for a business unit, query PS_SET_CNTRL_REC (cols: SETCNTRLVALUE, "
    "REC_GROUP_ID, RECNAME, SETID) where SETCNTRLVALUE = <business_unit> "
    "and RECNAME = <target_record>. Always call describe_table() first "
    "to verify columns before writing SQL."
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
