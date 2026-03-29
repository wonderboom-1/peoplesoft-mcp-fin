"""
General Ledger semantic tools for PeopleSoft Financials.
Targets FSCM 9.x-style tables (PS_LEDGER, PS_JRNL_HDR/LN, PS_GL_ACCOUNT_TBL).
"""
from db import execute_query


def register_tools(mcp):
    """Register GL tools."""

    @mcp.tool()
    async def get_gl_account(setid: str, account: str) -> dict:
        """
        Get chart-of-accounts row for an account (effective-dated).

        :param setid: SetID for GL (e.g., SHARE)
        :param account: GL account
        :return: Account definition and description
        """
        sql = """
            SELECT
                G.SETID,
                G.ACCOUNT,
                G.EFFDT,
                G.EFF_STATUS,
                G.DESCR,
                G.ACCOUNT_TYPE,
                G.OFF_ACCOUNT,
                G.STAT_ACCOUNT
            FROM PS_GL_ACCOUNT_TBL G
            WHERE G.SETID = :1 AND G.ACCOUNT = :2
            AND G.EFFDT = (
                SELECT MAX(G2.EFFDT) FROM PS_GL_ACCOUNT_TBL G2
                WHERE G2.SETID = G.SETID AND G2.ACCOUNT = G.ACCOUNT
                AND G2.EFFDT <= SYSDATE
            )
        """
        result = await execute_query(sql, [setid.upper(), account.upper()])
        if "error" in result:
            return result
        if not result.get("results"):
            return {"error": f"Account '{account}' not found for SetID '{setid}'."}
        row = result["results"][0]
        return {
            "setid": row["SETID"],
            "account": row["ACCOUNT"],
            "effective_date": str(row["EFFDT"]) if row["EFFDT"] else None,
            "status": row["EFF_STATUS"],
            "description": row["DESCR"],
            "account_type": row["ACCOUNT_TYPE"],
            "offset_account": row["OFF_ACCOUNT"],
            "stat_account": row["STAT_ACCOUNT"],
        }

    @mcp.tool()
    async def search_gl_accounts(
        setid: str,
        pattern: str | None = None,
        account_type: str | None = None,
        limit: int = 50,
    ) -> dict:
        """
        Search GL accounts by description or account number pattern (current effective date).

        :param setid: SetID
        :param pattern: Partial match on ACCOUNT or DESCR
        :param account_type: Optional ACCOUNT_TYPE filter
        :param limit: Max rows
        """
        params = [setid.upper()]
        cond = ["G.SETID = :1", """G.EFFDT = (
            SELECT MAX(G2.EFFDT) FROM PS_GL_ACCOUNT_TBL G2
            WHERE G2.SETID = G.SETID AND G2.ACCOUNT = G.ACCOUNT AND G2.EFFDT <= SYSDATE
        )"""]
        idx = 2
        if pattern:
            cond.append(
                f"(UPPER(G.ACCOUNT) LIKE :{idx} OR UPPER(G.DESCR) LIKE :{idx})"
            )
            params.append(f"%{pattern.upper()}%")
            idx += 1
        if account_type:
            cond.append(f"G.ACCOUNT_TYPE = :{idx}")
            params.append(account_type.upper())
            idx += 1
        where_sql = " AND ".join(cond)
        sql = f"""
            SELECT G.SETID, G.ACCOUNT, G.DESCR, G.ACCOUNT_TYPE, G.EFF_STATUS
            FROM PS_GL_ACCOUNT_TBL G
            WHERE {where_sql}
            AND G.EFF_STATUS = 'A'
            ORDER BY G.ACCOUNT
            FETCH FIRST :lim ROWS ONLY
        """
        params.append(limit)
        return await execute_query(sql, params)

    @mcp.tool()
    async def get_ledger_account_summary(
        business_unit: str,
        ledger: str,
        fiscal_year: int,
        accounting_period: int,
        account_pattern: str | None = None,
        limit: int = 100,
    ) -> dict:
        """
        Summarize posted ledger balances by account for a BU/ledger/year/period (PS_LEDGER).

        :param business_unit: Business Unit
        :param ledger: Ledger group code (e.g., ACTUALS)
        :param fiscal_year: Fiscal year
        :param accounting_period: Accounting period (1-12 or per your calendar)
        :param account_pattern: Optional LIKE pattern on ACCOUNT
        :param limit: Max accounts returned
        """
        params = [
            business_unit.upper(),
            ledger.upper(),
            fiscal_year,
            accounting_period,
        ]
        acct_cond = ""
        if account_pattern:
            acct_cond = " AND L.ACCOUNT LIKE :5 "
            params.append(account_pattern.upper().replace("*", "%"))
        sql = f"""
            SELECT
                L.ACCOUNT,
                SUM(L.MONETARY_AMOUNT) AS TOTAL_AMOUNT,
                L.CURRENCY_CD
            FROM PS_LEDGER L
            WHERE L.BUSINESS_UNIT = :1
            AND L.LEDGER = :2
            AND L.FISCAL_YEAR = :3
            AND L.ACCOUNTING_PERIOD = :4
            {acct_cond}
            GROUP BY L.ACCOUNT, L.CURRENCY_CD
            ORDER BY L.ACCOUNT
            FETCH FIRST :lim ROWS ONLY
        """
        params.append(limit)
        return await execute_query(sql, params)

    @mcp.tool()
    async def get_journal_header(business_unit: str, journal_id: str) -> dict:
        """
        Get journal header (PS_JRNL_HDR) by business unit and journal ID.

        :param business_unit: BU
        :param journal_id: Journal ID
        """
        sql = """
            SELECT H.*
            FROM PS_JRNL_HDR H
            WHERE H.BUSINESS_UNIT = :1 AND H.JOURNAL_ID = :2
        """
        return await execute_query(sql, [business_unit.upper(), journal_id.upper()])

    @mcp.tool()
    async def get_journal_lines(
        business_unit: str,
        journal_id: str,
        limit: int = 500,
    ) -> dict:
        """
        Get journal lines (PS_JRNL_LN) for a journal.

        :param business_unit: BU
        :param journal_id: Journal ID
        :param limit: Max lines
        """
        sql = """
            SELECT * FROM PS_JRNL_LN J
            WHERE J.BUSINESS_UNIT = :1 AND J.JOURNAL_ID = :2
            ORDER BY J.JOURNAL_LINE
            FETCH FIRST :3 ROWS ONLY
        """
        return await execute_query(sql, [business_unit.upper(), journal_id.upper(), limit])

    @mcp.tool()
    async def list_open_periods(business_unit: str, ledger_group: str | None = None) -> dict:
        """
        List open GL periods (PS_OPEN_PERIOD) if used in your installation.

        :param business_unit: BU
        :param ledger_group: Optional ledger group filter
        """
        params = [business_unit.upper()]
        lg = ""
        if ledger_group:
            lg = " AND O.LEDGER_GROUP = :2 "
            params.append(ledger_group.upper())
        sql = f"""
            SELECT O.BUSINESS_UNIT, O.LEDGER_GROUP, O.FISCAL_YEAR,
                   O.ACCOUNTING_PERIOD, O.OPEN_STATUS
            FROM PS_OPEN_PERIOD O
            WHERE O.BUSINESS_UNIT = :1 {lg}
            ORDER BY O.FISCAL_YEAR DESC, O.ACCOUNTING_PERIOD DESC
            FETCH FIRST 36 ROWS ONLY
        """
        return await execute_query(sql, params)
