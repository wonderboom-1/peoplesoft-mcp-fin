"""
Financial Performance tools for PeopleSoft Financials MCP.
Budget vs Actual, Commitment Control, and period-end KPIs.
"""
from db import execute_query


def register_tools(mcp):
    """Register financial performance tools."""

    @mcp.tool()
    async def get_budget_vs_actual(
        business_unit: str,
        fiscal_year: int,
        ledger_actuals: str = "ACTUALS",
        ledger_budget: str = "BUDGET",
        account: str | None = None,
        accounting_period: int | None = None,
        limit: int = 100,
    ) -> dict:
        """
        Compare budget ledger vs actuals ledger by account and period.

        Returns each account's budget amount, actual amount, variance, and
        percent consumed. Negative variance = over budget.

        :param business_unit: Business Unit
        :param fiscal_year: Fiscal year
        :param ledger_actuals: Actuals ledger name (default ACTUALS)
        :param ledger_budget: Budget ledger name (default BUDGET)
        :param account: Optional account or LIKE pattern (e.g. '6%')
        :param accounting_period: Optional single period; omit for full-year
        :param limit: Max rows returned
        """
        params: list = [
            business_unit.upper(),
            fiscal_year,
            ledger_actuals.upper(),
            business_unit.upper(),
            fiscal_year,
            ledger_budget.upper(),
        ]
        idx = 7

        acct_cond_a = ""
        acct_cond_b = ""
        if account:
            acct_cond_a = f" AND A.ACCOUNT LIKE :{idx} "
            acct_cond_b = f" AND B.ACCOUNT LIKE :{idx + 1} "
            pat = account.upper().replace("*", "%")
            params.extend([pat, pat])
            idx += 2

        period_cond_a = ""
        period_cond_b = ""
        if accounting_period is not None:
            period_cond_a = f" AND A.ACCOUNTING_PERIOD = :{idx} "
            period_cond_b = f" AND B.ACCOUNTING_PERIOD = :{idx + 1} "
            params.extend([accounting_period, accounting_period])
            idx += 2

        params.append(limit)

        sql = f"""
            SELECT
                NVL(ACT.ACCOUNT, BUD.ACCOUNT) AS ACCOUNT,
                NVL(ACT.CURRENCY_CD, BUD.CURRENCY_CD) AS CURRENCY_CD,
                NVL(BUD.BUDGET_AMT, 0) AS BUDGET_AMT,
                NVL(ACT.ACTUAL_AMT, 0) AS ACTUAL_AMT,
                NVL(BUD.BUDGET_AMT, 0) - NVL(ACT.ACTUAL_AMT, 0) AS VARIANCE,
                CASE WHEN NVL(BUD.BUDGET_AMT, 0) <> 0
                     THEN ROUND(NVL(ACT.ACTUAL_AMT, 0) / BUD.BUDGET_AMT * 100, 2)
                     ELSE NULL END AS PCT_CONSUMED
            FROM (
                SELECT A.ACCOUNT, A.CURRENCY_CD,
                       SUM(A.POSTED_TOTAL_AMT) AS ACTUAL_AMT
                FROM PS_LEDGER A
                WHERE A.BUSINESS_UNIT = :1 AND A.FISCAL_YEAR = :2
                  AND A.LEDGER = :3 {acct_cond_a} {period_cond_a}
                GROUP BY A.ACCOUNT, A.CURRENCY_CD
            ) ACT
            FULL OUTER JOIN (
                SELECT B.ACCOUNT, B.CURRENCY_CD,
                       SUM(B.POSTED_TOTAL_AMT) AS BUDGET_AMT
                FROM PS_LEDGER B
                WHERE B.BUSINESS_UNIT = :4 AND B.FISCAL_YEAR = :5
                  AND B.LEDGER = :6 {acct_cond_b} {period_cond_b}
                GROUP BY B.ACCOUNT, B.CURRENCY_CD
            ) BUD ON ACT.ACCOUNT = BUD.ACCOUNT AND ACT.CURRENCY_CD = BUD.CURRENCY_CD
            ORDER BY NVL(ACT.ACCOUNT, BUD.ACCOUNT)
            FETCH FIRST :{idx} ROWS ONLY
        """

        result = await execute_query(sql, params)
        if "error" in result:
            return result
        return {
            "business_unit": business_unit.upper(),
            "fiscal_year": fiscal_year,
            "ledger_actuals": ledger_actuals.upper(),
            "ledger_budget": ledger_budget.upper(),
            "row_count": len(result.get("results", [])),
            "results": result.get("results", []),
        }

    @mcp.tool()
    async def search_budget_exceptions(
        business_unit: str,
        fiscal_year: int,
        threshold_pct: float = 90.0,
        ledger_actuals: str = "ACTUALS",
        ledger_budget: str = "BUDGET",
        limit: int = 50,
    ) -> dict:
        """
        Find accounts where actuals exceed a percentage of budget.

        Useful for financial oversight: shows accounts approaching or over budget.

        :param business_unit: Business Unit
        :param fiscal_year: Fiscal year
        :param threshold_pct: Minimum percent consumed to include (default 90)
        :param ledger_actuals: Actuals ledger name
        :param ledger_budget: Budget ledger name
        :param limit: Max rows
        """
        sql = """
            SELECT
                BUD.ACCOUNT,
                BUD.CURRENCY_CD,
                BUD.BUDGET_AMT,
                NVL(ACT.ACTUAL_AMT, 0) AS ACTUAL_AMT,
                BUD.BUDGET_AMT - NVL(ACT.ACTUAL_AMT, 0) AS REMAINING,
                ROUND(NVL(ACT.ACTUAL_AMT, 0) / BUD.BUDGET_AMT * 100, 2) AS PCT_CONSUMED
            FROM (
                SELECT B.ACCOUNT, B.CURRENCY_CD,
                       SUM(B.POSTED_TOTAL_AMT) AS BUDGET_AMT
                FROM PS_LEDGER B
                WHERE B.BUSINESS_UNIT = :1 AND B.FISCAL_YEAR = :2
                  AND B.LEDGER = :3
                GROUP BY B.ACCOUNT, B.CURRENCY_CD
                HAVING SUM(B.POSTED_TOTAL_AMT) <> 0
            ) BUD
            LEFT JOIN (
                SELECT A.ACCOUNT, A.CURRENCY_CD,
                       SUM(A.POSTED_TOTAL_AMT) AS ACTUAL_AMT
                FROM PS_LEDGER A
                WHERE A.BUSINESS_UNIT = :4 AND A.FISCAL_YEAR = :5
                  AND A.LEDGER = :6
                GROUP BY A.ACCOUNT, A.CURRENCY_CD
            ) ACT ON BUD.ACCOUNT = ACT.ACCOUNT AND BUD.CURRENCY_CD = ACT.CURRENCY_CD
            WHERE ROUND(NVL(ACT.ACTUAL_AMT, 0) / BUD.BUDGET_AMT * 100, 2) >= :7
            ORDER BY ROUND(NVL(ACT.ACTUAL_AMT, 0) / BUD.BUDGET_AMT * 100, 2) DESC
            FETCH FIRST :8 ROWS ONLY
        """
        params = [
            business_unit.upper(), fiscal_year, ledger_budget.upper(),
            business_unit.upper(), fiscal_year, ledger_actuals.upper(),
            threshold_pct, limit,
        ]
        result = await execute_query(sql, params)
        if "error" in result:
            return result
        return {
            "business_unit": business_unit.upper(),
            "fiscal_year": fiscal_year,
            "threshold_pct": threshold_pct,
            "exceptions_found": len(result.get("results", [])),
            "results": result.get("results", []),
        }

    @mcp.tool()
    async def get_commitment_control_budget(
        business_unit: str,
        ledger_group: str,
        fiscal_year: int,
        account: str | None = None,
        limit: int = 100,
    ) -> dict:
        """
        Query commitment control (KK) budget balances from PS_LEDGER_KK.

        Shows budget, pre-encumbrance, encumbrance, and expense amounts
        per account for a given ledger group and fiscal year.

        :param business_unit: Business Unit
        :param ledger_group: KK ledger group (e.g., COMMIT)
        :param fiscal_year: Fiscal year
        :param account: Optional account or LIKE pattern
        :param limit: Max rows
        """
        params: list = [business_unit.upper(), ledger_group.upper(), fiscal_year]
        idx = 4
        acct_cond = ""
        if account:
            acct_cond = f" AND K.ACCOUNT LIKE :{idx} "
            params.append(account.upper().replace("*", "%"))
            idx += 1
        params.append(limit)

        sql = f"""
            SELECT
                K.ACCOUNT,
                K.CURRENCY_CD,
                K.ACCOUNTING_PERIOD,
                SUM(CASE WHEN K.LEDGER = 'BUDGETS' THEN K.POSTED_TOTAL_AMT ELSE 0 END) AS BUDGET_AMT,
                SUM(CASE WHEN K.LEDGER = 'PRE_ENCMBR' THEN K.POSTED_TOTAL_AMT ELSE 0 END) AS PRE_ENCUMBRANCE,
                SUM(CASE WHEN K.LEDGER = 'ENCUMBRNCE' THEN K.POSTED_TOTAL_AMT ELSE 0 END) AS ENCUMBRANCE,
                SUM(CASE WHEN K.LEDGER = 'ACTUALS' THEN K.POSTED_TOTAL_AMT ELSE 0 END) AS EXPENSE
            FROM PS_LEDGER_KK K
            WHERE K.BUSINESS_UNIT = :1
              AND K.LEDGER IN (
                  SELECT G.LEDGER FROM PS_LED_GRP_LED_TBL G
                  WHERE G.LEDGER_GROUP = :2
              )
              AND K.FISCAL_YEAR = :3
              {acct_cond}
            GROUP BY K.ACCOUNT, K.CURRENCY_CD, K.ACCOUNTING_PERIOD
            ORDER BY K.ACCOUNT, K.ACCOUNTING_PERIOD
            FETCH FIRST :{idx} ROWS ONLY
        """
        result = await execute_query(sql, params)
        if "error" in result:
            return result
        return {
            "business_unit": business_unit.upper(),
            "ledger_group": ledger_group.upper(),
            "fiscal_year": fiscal_year,
            "row_count": len(result.get("results", [])),
            "results": result.get("results", []),
        }

    @mcp.tool()
    async def check_budget_status(
        business_unit: str,
        ledger_group: str,
        fiscal_year: int,
        account: str | None = None,
        limit: int = 100,
    ) -> dict:
        """
        Summarize commitment control budget status: available balance and consumed %.

        Rolls up all periods for each account in the KK ledger group and flags
        accounts where expenses + encumbrances exceed budget.

        :param business_unit: Business Unit
        :param ledger_group: KK ledger group
        :param fiscal_year: Fiscal year
        :param account: Optional account or LIKE pattern
        :param limit: Max rows
        """
        params: list = [business_unit.upper(), ledger_group.upper(), fiscal_year]
        idx = 4
        acct_cond = ""
        if account:
            acct_cond = f" AND K.ACCOUNT LIKE :{idx} "
            params.append(account.upper().replace("*", "%"))
            idx += 1
        params.append(limit)

        sql = f"""
            SELECT
                K.ACCOUNT,
                K.CURRENCY_CD,
                SUM(CASE WHEN K.LEDGER = 'BUDGETS' THEN K.POSTED_TOTAL_AMT ELSE 0 END) AS BUDGET_AMT,
                SUM(CASE WHEN K.LEDGER IN ('ACTUALS','ENCUMBRNCE','PRE_ENCMBR')
                         THEN K.POSTED_TOTAL_AMT ELSE 0 END) AS CONSUMED_AMT,
                SUM(CASE WHEN K.LEDGER = 'BUDGETS' THEN K.POSTED_TOTAL_AMT ELSE 0 END)
                  - SUM(CASE WHEN K.LEDGER IN ('ACTUALS','ENCUMBRNCE','PRE_ENCMBR')
                             THEN K.POSTED_TOTAL_AMT ELSE 0 END) AS AVAILABLE_BALANCE,
                CASE WHEN SUM(CASE WHEN K.LEDGER = 'BUDGETS' THEN K.POSTED_TOTAL_AMT ELSE 0 END) <> 0
                     THEN ROUND(
                         SUM(CASE WHEN K.LEDGER IN ('ACTUALS','ENCUMBRNCE','PRE_ENCMBR')
                                  THEN K.POSTED_TOTAL_AMT ELSE 0 END)
                         / SUM(CASE WHEN K.LEDGER = 'BUDGETS' THEN K.POSTED_TOTAL_AMT ELSE 0 END) * 100, 2)
                     ELSE NULL END AS PCT_CONSUMED,
                CASE WHEN SUM(CASE WHEN K.LEDGER IN ('ACTUALS','ENCUMBRNCE','PRE_ENCMBR')
                                   THEN K.POSTED_TOTAL_AMT ELSE 0 END)
                        > SUM(CASE WHEN K.LEDGER = 'BUDGETS' THEN K.POSTED_TOTAL_AMT ELSE 0 END)
                     THEN 'Y' ELSE 'N' END AS OVER_BUDGET
            FROM PS_LEDGER_KK K
            WHERE K.BUSINESS_UNIT = :1
              AND K.LEDGER IN (
                  SELECT G.LEDGER FROM PS_LED_GRP_LED_TBL G
                  WHERE G.LEDGER_GROUP = :2
              )
              AND K.FISCAL_YEAR = :3
              {acct_cond}
            GROUP BY K.ACCOUNT, K.CURRENCY_CD
            HAVING SUM(CASE WHEN K.LEDGER = 'BUDGETS' THEN K.POSTED_TOTAL_AMT ELSE 0 END) <> 0
            ORDER BY K.ACCOUNT
            FETCH FIRST :{idx} ROWS ONLY
        """
        result = await execute_query(sql, params)
        if "error" in result:
            return result

        over_budget_count = sum(
            1 for r in result.get("results", []) if r.get("OVER_BUDGET") == "Y"
        )
        return {
            "business_unit": business_unit.upper(),
            "ledger_group": ledger_group.upper(),
            "fiscal_year": fiscal_year,
            "accounts_checked": len(result.get("results", [])),
            "over_budget_count": over_budget_count,
            "results": result.get("results", []),
        }

    @mcp.tool()
    async def get_period_close_status(
        business_unit: str,
        fiscal_year: int,
        accounting_period: int | None = None,
    ) -> dict:
        """
        Period open/close status across all ledger groups for a business unit.

        Queries PS_FIN_OPEN_PERIOD which stores open year/period ranges per
        ledger group, then falls back to PS_CAL_DETP_TBL.

        :param business_unit: Business Unit
        :param fiscal_year: Fiscal year
        :param accounting_period: Optional single period; omit for all periods
        """
        params: list = [business_unit.upper(), fiscal_year]
        period_cond = ""
        if accounting_period is not None:
            period_cond = " AND :3 BETWEEN O.OPEN_PERIOD_FROM AND O.OPEN_PERIOD_TO "
            params.append(accounting_period)

        sql = f"""
            SELECT
                O.LEDGER_GROUP,
                O.CALENDAR_ID,
                O.OPEN_YEAR_FROM,
                O.OPEN_PERIOD_FROM,
                O.OPEN_YEAR_TO,
                O.OPEN_PERIOD_TO,
                O.OPEN_FROM_DATE,
                O.OPEN_TO_DATE,
                CASE WHEN :2 BETWEEN O.OPEN_YEAR_FROM AND O.OPEN_YEAR_TO
                     THEN 'O' ELSE 'C' END AS OPEN_STATUS
            FROM PS_FIN_OPEN_PERIOD O
            WHERE O.BUSINESS_UNIT = :1
              AND (:2 BETWEEN O.OPEN_YEAR_FROM AND O.OPEN_YEAR_TO)
              {period_cond}
            ORDER BY O.LEDGER_GROUP
        """
        result = await execute_query(sql, params)
        if "error" in result:
            params2: list = [business_unit.upper(), fiscal_year]
            pc = ""
            if accounting_period is not None:
                pc = " AND C.ACCOUNTING_PERIOD = :3 "
                params2.append(accounting_period)
            sql2 = f"""
                SELECT
                    C.ACCOUNTING_PERIOD,
                    C.OPEN_CLOSE_STATUS AS OPEN_STATUS,
                    COUNT(*) AS LEDGER_GROUP_COUNT
                FROM PS_CAL_DETP_TBL C
                WHERE C.SETID = (
                    SELECT S.SETID FROM PS_SET_CNTRL_REC S
                    WHERE S.SETCNTRLVALUE = :1 AND S.RECNAME = 'CAL_DETP_TBL'
                    FETCH FIRST 1 ROWS ONLY
                )
                  AND C.FISCAL_YEAR = :2
                  {pc}
                GROUP BY C.ACCOUNTING_PERIOD, C.OPEN_CLOSE_STATUS
                ORDER BY C.ACCOUNTING_PERIOD, C.OPEN_CLOSE_STATUS
            """
            result = await execute_query(sql2, params2)
            if "error" in result:
                return {"error": (
                    "Neither PS_FIN_OPEN_PERIOD nor PS_CAL_DETP_TBL returned results. "
                    "Use describe_table() to find the correct period table."
                )}

            summary: dict = {}
            for row in result.get("results", []):
                p = row["ACCOUNTING_PERIOD"]
                if p not in summary:
                    summary[p] = {"period": p, "open_groups": 0, "closed_groups": 0}
                if row["OPEN_STATUS"] == "O":
                    summary[p]["open_groups"] = row["LEDGER_GROUP_COUNT"]
                else:
                    summary[p]["closed_groups"] = row["LEDGER_GROUP_COUNT"]

            return {
                "business_unit": business_unit.upper(),
                "fiscal_year": fiscal_year,
                "periods": list(summary.values()),
                "detail": result.get("results", []),
            }

        return {
            "business_unit": business_unit.upper(),
            "fiscal_year": fiscal_year,
            "ledger_groups": result.get("results", []),
        }

    @mcp.tool()
    async def get_journal_posting_summary(
        business_unit: str,
        fiscal_year: int,
        accounting_period: int | None = None,
    ) -> dict:
        """
        Count posted vs unposted journals for period-end monitoring.

        Groups journals by JRNL_HDR_STATUS and flags any stale unposted entries.

        Status codes: N=Not yet posted, P=Posted, V=Valid (ready to post),
        E=Errors, D=Deleted, I=Incomplete.

        :param business_unit: Business Unit
        :param fiscal_year: Fiscal year
        :param accounting_period: Optional period filter
        """
        params: list = [business_unit.upper(), fiscal_year]
        period_cond = ""
        if accounting_period is not None:
            period_cond = " AND H.ACCOUNTING_PERIOD = :3 "
            params.append(accounting_period)

        sql = f"""
            SELECT
                H.JRNL_HDR_STATUS,
                COUNT(*) AS JOURNAL_COUNT,
                SUM(H.JRNL_TOTAL_LINES) AS TOTAL_LINES,
                MIN(H.JOURNAL_DATE) AS EARLIEST_DATE,
                MAX(H.JOURNAL_DATE) AS LATEST_DATE
            FROM PS_JRNL_HEADER H
            WHERE H.BUSINESS_UNIT = :1
              AND H.FISCAL_YEAR = :2
              {period_cond}
            GROUP BY H.JRNL_HDR_STATUS
            ORDER BY H.JRNL_HDR_STATUS
        """
        result = await execute_query(sql, params)
        if "error" in result:
            return result

        status_labels = {
            "N": "Not posted",
            "P": "Posted",
            "V": "Valid (ready to post)",
            "E": "Errors",
            "D": "Deleted",
            "I": "Incomplete",
        }

        rows = result.get("results", [])
        total = sum(r.get("JOURNAL_COUNT", 0) for r in rows)
        posted = sum(r.get("JOURNAL_COUNT", 0) for r in rows if r.get("JRNL_HDR_STATUS") == "P")
        unposted = total - posted

        enriched = []
        for r in rows:
            status = r.get("JRNL_HDR_STATUS", "")
            enriched.append({
                **r,
                "STATUS_DESCRIPTION": status_labels.get(status, "Unknown"),
                "EARLIEST_DATE": str(r["EARLIEST_DATE"]) if r.get("EARLIEST_DATE") else None,
                "LATEST_DATE": str(r["LATEST_DATE"]) if r.get("LATEST_DATE") else None,
            })

        return {
            "business_unit": business_unit.upper(),
            "fiscal_year": fiscal_year,
            "total_journals": total,
            "posted": posted,
            "unposted": unposted,
            "by_status": enriched,
        }
