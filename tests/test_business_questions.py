"""
Map representative business questions to MCP tools (no Oracle required).

Ensures the server exposes the tools an assistant would need for common FSCM questions.
"""

import asyncio

import pytest

pytest.importorskip("fastmcp")

import peoplesoft_fin_server as pfs


# Natural-language intent -> tool name that should exist on the server.
BUSINESS_QUESTION_ROUTING = [
    ("What is our GL account definition for 610000?", "get_gl_account"),
    ("Search GL accounts matching 'travel' in SHARE", "search_gl_accounts"),
    ("Ledger balances for BU US001 this fiscal year", "get_ledger_account_summary"),
    ("Show journal ABC123 header for business unit US001", "get_journal_header"),
    ("Open accounting periods for US001", "list_open_periods"),
    ("Vendor master for VNDR01", "get_vendor"),
    ("Find vendors with 'ACME' in the name", "search_vendors"),
    ("Voucher details for VCHR0001", "get_voucher_header"),
    ("Recent posted vouchers in AP", "list_recent_vouchers"),
    ("Customer CUST01 profile", "get_customer"),
    ("Search customers by name", "search_customers"),
    ("Billing invoice header for INV123", "get_billing_invoice_header"),
    ("Purchase order PO00001 lines", "get_po_lines"),
    ("Find open purchase orders", "search_purchase_orders"),
    ("Fixed asset ASSET01 in BU US001", "get_asset"),
    ("What columns are on PS_LEDGER?", "describe_table"),
    ("List AP module tables", "list_tables"),
    ("Run ad hoc SQL against Financials", "query_peoplesoft_fin_db"),
    ("What is a SetID in PeopleSoft?", "explain_peoplesoft_concept"),
]


@pytest.fixture(scope="module")
def tool_names() -> set[str]:
    async def _names() -> set[str]:
        tools = await pfs.mcp.list_tools()
        return {t.name for t in tools}

    return asyncio.run(_names())


@pytest.mark.parametrize("question,expected_tool", BUSINESS_QUESTION_ROUTING)
def test_business_question_has_routing_tool(question: str, expected_tool: str, tool_names: set[str]):
    assert expected_tool in tool_names, (
        f"Missing tool {expected_tool!r} for: {question!r}"
    )
