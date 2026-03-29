"""
Map representative PeopleTools / metadata questions to MCP tools (no Oracle required).
"""

import asyncio

import pytest

pytest.importorskip("fastmcp")

import peoplesoft_fin_server as pfs


PEOPLETOOLS_QUESTION_ROUTING = [
    ("What fields are on record PS_JOB?", "get_record_definition"),
    ("Search records matching VCHR in the name", "search_records"),
    ("Component structure for RUN_GL_JRNL", "get_component_structure"),
    ("Pages in component VCHR_EXPRESS", "get_component_pages"),
    ("Fields on page VCHR_LINE_WRK", "get_page_fields"),
    ("Field bindings for a page", "get_page_field_bindings"),
    ("PeopleCode on record.field FieldFormula", "get_peoplecode"),
    ("What roles use permission list PTPT1000?", "get_roles_for_permission_list"),
    ("Details for permission list SUPERVISOR", "get_permission_list_details"),
    ("Process definition for GL_JOURNAL", "get_process_definition"),
    ("Application Engine steps for program MY_AE", "get_application_engine_steps"),
    ("Integration Broker service operations", "get_integration_broker_services"),
    ("Message definition for MY_MSG", "get_message_definition"),
    ("Query definition for MY_QRY", "get_query_definition"),
    ("SQL definition for MY_SQL", "get_sql_definition"),
    ("Search SQL definitions containing LEDGER", "search_sql_definitions"),
    ("Search PeopleCode for VoucherBuild", "search_peoplecode"),
    ("Where is field BUSINESS_UNIT used?", "get_field_usage"),
    ("Translate values for voucher status field", "get_translate_field_values"),
]


@pytest.fixture(scope="module")
def tool_names() -> set[str]:
    async def _names() -> set[str]:
        tools = await pfs.mcp.list_tools()
        return {t.name for t in tools}

    return asyncio.run(_names())


@pytest.mark.parametrize("question,expected_tool", PEOPLETOOLS_QUESTION_ROUTING)
def test_peopletools_question_has_routing_tool(
    question: str, expected_tool: str, tool_names: set[str]
):
    assert expected_tool in tool_names, (
        f"Missing tool {expected_tool!r} for: {question!r}"
    )
