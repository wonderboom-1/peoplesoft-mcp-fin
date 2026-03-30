"""
Regression tests for SQL pre-validation in _pre_validate_sql.

Verifies that bad column names and undefined aliases are caught
*before* hitting Oracle (no DB connection required — uses mocked lookups).
"""

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

pytest.importorskip("fastmcp")

import peoplesoft_fin_server as pfs

LEDGER_COLS = [
    "ACCOUNT", "ACCOUNTING_PERIOD", "AFFILIATE", "AFFILIATE_INTRA1",
    "AFFILIATE_INTRA2", "ALTACCT", "BASE_CURRENCY", "BOOK_CODE",
    "BUDGET_REF", "BUSINESS_UNIT", "CF9B_AK_SBR", "CHARTFIELD1",
    "CHARTFIELD2", "CHARTFIELD3", "CLASS_FLD", "CURRENCY_CD",
    "DATE_CODE", "DEPTID", "DTTM_STAMP_SEC", "FISCAL_YEAR",
    "FUND_CODE", "GL_ADJUST_TYPE", "LEDGER", "OPERATING_UNIT",
    "POSTED_BASE_AMT", "POSTED_TOTAL_AMT", "POSTED_TOTAL_CR",
    "POSTED_TOTAL_DR", "POSTED_TRAN_AMT", "POSTED_TRAN_CR",
    "POSTED_TRAN_DR", "PROCESS_INSTANCE", "PRODUCT", "PROGRAM_CODE",
    "PROJECT_ID", "STATISTICS_CODE",
]

BUS_UNIT_FS_COLS = ["BUSINESS_UNIT", "DESCR", "DESCRSHORT"]


async def _mock_get_columns(recname: str):
    mapping = {
        "LEDGER": LEDGER_COLS,
        "BUS_UNIT_TBL_FS": BUS_UNIT_FS_COLS,
    }
    return mapping.get(recname.upper(), [])


async def _mock_get_system_cols(table_name: str):
    return []


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


@pytest.fixture(autouse=True)
def patch_db():
    """Mock DB lookups so tests run without Oracle."""
    with (
        patch.object(pfs, "_get_columns_for_table", side_effect=_mock_get_columns),
        patch.object(pfs, "_get_columns_for_system_table", side_effect=_mock_get_system_cols),
    ):
        yield


class TestBareInvalidColumn:
    """Check 4: unqualified column names that don't exist on the table."""

    def test_ledger_descr_caught(self):
        sql = (
            "SELECT DISTINCT LEDGER, LEDGER_DESCR "
            "FROM PS_LEDGER "
            "WHERE BUSINESS_UNIT = :1 AND FISCAL_YEAR = :2 "
            "AND ROWNUM <= 20 ORDER BY LEDGER"
        )
        result = _run(pfs._pre_validate_sql(sql))
        assert result is not None, "Expected pre-validation to catch LEDGER_DESCR"
        assert "LEDGER_DESCR" in result["error"]

    def test_valid_bare_columns_pass(self):
        sql = (
            "SELECT DISTINCT LEDGER, BUSINESS_UNIT, FISCAL_YEAR "
            "FROM PS_LEDGER WHERE BUSINESS_UNIT = :1"
        )
        result = _run(pfs._pre_validate_sql(sql))
        assert result is None, f"Valid SQL should pass, got: {result}"

    def test_multiple_invalid_bare_columns(self):
        sql = (
            "SELECT LEDGER_DESCR, BUDGET_AMOUNT "
            "FROM PS_LEDGER WHERE BUSINESS_UNIT = :1"
        )
        result = _run(pfs._pre_validate_sql(sql))
        assert result is not None
        err = result["error"]
        assert "LEDGER_DESCR" in err or "BUDGET_AMOUNT" in err


class TestUndefinedAlias:
    """Check 3: aliases used in alias.COL but not defined in FROM/JOIN."""

    def test_undefined_alias_bu_caught(self):
        sql = (
            "SELECT bu.BUSINESS_UNIT, fs.DESCR "
            "FROM PS_BUS_UNIT_TBL_FS fs "
            "WHERE fs.BUSINESS_UNIT = :1 AND ROWNUM = 1"
        )
        result = _run(pfs._pre_validate_sql(sql))
        assert result is not None, "Expected pre-validation to catch undefined alias 'bu'"
        assert "BU" in result["error"].upper()

    def test_defined_aliases_pass(self):
        sql = (
            "SELECT fs.BUSINESS_UNIT, fs.DESCR "
            "FROM PS_BUS_UNIT_TBL_FS fs "
            "WHERE fs.BUSINESS_UNIT = :1"
        )
        result = _run(pfs._pre_validate_sql(sql))
        assert result is None, f"Valid aliased SQL should pass, got: {result}"


class TestAliasExtractionNoKeywords:
    """Verify SQL keywords aren't treated as table aliases."""

    def test_where_not_captured_as_alias(self):
        sql = "SELECT LEDGER FROM PS_LEDGER WHERE BUSINESS_UNIT = :1"
        _run(pfs._pre_validate_sql(sql))
        # If WHERE were an alias, alias_to_rec would map WHERE->LEDGER.
        # The fix strips SQL keywords. We verify indirectly: valid SQL passes.
        result = _run(pfs._pre_validate_sql(sql))
        assert result is None


class TestBlocklistBareColumns:
    """Blocklist catches known-bad columns even without alias prefix."""

    def test_ledger_descr_blocklist_message(self):
        sql = (
            "SELECT LEDGER_DESCR FROM PS_LEDGER WHERE BUSINESS_UNIT = :1"
        )
        result = _run(pfs._pre_validate_sql(sql))
        assert result is not None
        assert "LEDGER_DESCR" in result["error"]
        assert "describe_table" in result["error"].lower() or "Blocked" in result["error"]
