"""
LLM integration for PeopleSoft Finance MCP — Claude on Azure AI Foundry.

Reads MICROSOFT_FOUNDRY_API_KEY and MICROSOFT_FOUNDRY_BASE_URL from the
environment (loaded by python-dotenv in db.py) and implements the Claude
Messages API tool loop using aiohttp + FastMCP's mcp.call_tool().
"""
from __future__ import annotations

import json
import os
from typing import Any

import aiohttp
from fastmcp import FastMCP

ANTHROPIC_VERSION = "2023-06-01"
DEFAULT_MODEL = "claude-sonnet-4-5"
MAX_TOOL_ROUNDS = 24
MAX_TOKENS = 8192

SYSTEM_PROMPT = (
    "You are an assistant for Oracle PeopleSoft Financials (FSCM). "
    "You have access to MCP tools that query a live PeopleSoft database "
    "(GL, AP, AR, purchasing, assets, PeopleTools metadata, and raw SQL "
    "via query_peoplesoft_fin_db).\n\n"
    "Rules:\n"
    "- Prefer semantic tools (describe_table, list_tables, get_vendor, etc.) "
    "before ad-hoc SQL.\n"
    "- When using query_peoplesoft_fin_db, use bind placeholders :1, :2 and "
    "pass parameters when appropriate.\n"
    "- Explain results clearly for finance and IT users; cite tool names "
    "briefly when useful.\n"
    "- If the database returns an error, explain it and suggest a safer next step."
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


async def list_tools_for_claude(mcp: FastMCP) -> list[dict[str, Any]]:
    """Convert FastMCP tool definitions to the Anthropic tool schema format."""
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
    return claude_tools


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


async def chat_with_tools(
    mcp: FastMCP,
    user_message: str,
    history: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """
    Run a full Claude tool loop against Azure AI Foundry.

    Returns ``{"reply": str, "tool_calls": [{"name", "args", "result"}, ...]}``.
    """
    config = get_foundry_config()
    claude_tools = await list_tools_for_claude(mcp)

    messages: list[dict[str, Any]] = []
    if history:
        for entry in history:
            role = entry.get("role")
            content = entry.get("content", "")
            if role in ("user", "assistant") and content:
                messages.append({"role": role, "content": content})
    messages.append({"role": "user", "content": user_message})

    tool_calls_log: list[dict[str, Any]] = []

    headers = {
        "Content-Type": "application/json",
        "anthropic-version": ANTHROPIC_VERSION,
        "Authorization": f"Bearer {config['api_key']}",
        "api-key": config["api_key"],
        "x-api-key": config["api_key"],
    }

    async with aiohttp.ClientSession() as session:
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

            async with session.post(
                config["messages_url"], headers=headers, json=body
            ) as resp:
                data = await resp.json()

            if "error" in data:
                err_msg = data["error"]
                if isinstance(err_msg, dict):
                    err_msg = err_msg.get("message", str(err_msg))
                raise RuntimeError(f"Claude API error: {err_msg}")

            blocks = data.get("content", [])
            if not blocks:
                raise RuntimeError("Claude returned an empty response.")

            tool_uses = [b for b in blocks if b.get("type") == "tool_use"]

            if not tool_uses:
                text = "\n".join(
                    b.get("text", "") for b in blocks if b.get("type") == "text"
                ).strip()
                return {"reply": text or "(No text response)", "tool_calls": tool_calls_log}

            messages.append({"role": "assistant", "content": blocks})

            tool_results: list[dict[str, Any]] = []
            for block in tool_uses:
                tool_name = block["name"]
                tool_args = block.get("input", {})

                try:
                    result = await mcp.call_tool(tool_name, tool_args)
                    result_text = _tool_result_to_text(result)
                except Exception as exc:
                    result_text = f"Error executing tool: {exc}"

                preview = result_text[:2000] if len(result_text) > 2000 else result_text
                tool_calls_log.append({
                    "name": tool_name,
                    "args": tool_args,
                    "result": preview,
                })

                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": block["id"],
                    "content": result_text,
                })

            messages.append({"role": "user", "content": tool_results})

    raise RuntimeError(f"Stopped after {MAX_TOOL_ROUNDS} tool rounds (safety limit).")