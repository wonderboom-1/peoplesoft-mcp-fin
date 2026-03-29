"""
Accounts Payable semantic tools (vendor, voucher, payment).
Tables: PS_VENDOR, PS_VCHR_HDR, payment tables (naming varies by release).
"""
from db import execute_query


def register_tools(mcp):
    """Register AP tools."""

    @mcp.tool()
    async def get_vendor(setid: str, vendor_id: str) -> dict:
        """
        Get vendor master (PS_VENDOR) current effective row.

        :param setid: Vendor SetID
        :param vendor_id: Vendor ID
        """
        sql = """
            SELECT
                V.SETID,
                V.VENDOR_ID,
                V.VENDOR_NAME_SHORT,
                V.NAME1,
                V.NAME2,
                V.ADDRESS1,
                V.CITY,
                V.STATE,
                V.POSTAL,
                V.COUNTRY,
                V.VENDOR_CLASS,
                V.CURRENCY_CD,
                V.VNDR_STATUS,
                V.EFF_STATUS,
                V.EFFDT
            FROM PS_VENDOR V
            WHERE V.SETID = :1 AND V.VENDOR_ID = :2
            AND V.EFFDT = (
                SELECT MAX(V2.EFFDT) FROM PS_VENDOR V2
                WHERE V2.SETID = V.SETID AND V2.VENDOR_ID = V.VENDOR_ID
                AND V2.EFFDT <= SYSDATE
            )
        """
        result = await execute_query(sql, [setid.upper(), vendor_id.upper()])
        if "error" in result:
            return result
        if not result.get("results"):
            return {"error": f"Vendor '{vendor_id}' not found for SetID '{setid}'."}
        row = result["results"][0]
        return {
            "setid": row["SETID"],
            "vendor_id": row["VENDOR_ID"],
            "name_short": row["VENDOR_NAME_SHORT"],
            "name1": row["NAME1"],
            "name2": row["NAME2"],
            "address": {
                "line1": row["ADDRESS1"],
                "city": row["CITY"],
                "state": row["STATE"],
                "postal": row["POSTAL"],
                "country": row["COUNTRY"],
            },
            "vendor_class": row["VENDOR_CLASS"],
            "currency": row["CURRENCY_CD"],
            "status": row["VNDR_STATUS"],
            "eff_status": row["EFF_STATUS"],
        }

    @mcp.tool()
    async def search_vendors(
        setid: str,
        name_pattern: str | None = None,
        vendor_id: str | None = None,
        limit: int = 50,
    ) -> dict:
        """Search vendors by name or ID (current effective date)."""
        params = [setid.upper()]
        cond = [
            "V.SETID = :1",
            """V.EFFDT = (
                SELECT MAX(V2.EFFDT) FROM PS_VENDOR V2
                WHERE V2.SETID = V.SETID AND V2.VENDOR_ID = V.VENDOR_ID AND V2.EFFDT <= SYSDATE
            )""",
        ]
        n = 2
        if name_pattern:
            cond.append(f"(UPPER(V.NAME1) LIKE :{n} OR UPPER(V.VENDOR_NAME_SHORT) LIKE :{n})")
            params.append(f"%{name_pattern.upper()}%")
            n += 1
        if vendor_id:
            cond.append(f"V.VENDOR_ID LIKE :{n}")
            params.append(f"%{vendor_id.upper()}%")
            n += 1
        where_sql = " AND ".join(cond)
        sql = f"""
            SELECT V.SETID, V.VENDOR_ID, V.NAME1, V.VENDOR_NAME_SHORT, V.VNDR_STATUS
            FROM PS_VENDOR V
            WHERE {where_sql}
            ORDER BY V.VENDOR_ID
            FETCH FIRST :lim ROWS ONLY
        """
        params.append(limit)
        return await execute_query(sql, params)

    @mcp.tool()
    async def get_voucher_header(business_unit: str, voucher_id: str) -> dict:
        """
        Get voucher header from PS_VCHR_HDR (standard Payables voucher).

        :param business_unit: AP business unit
        :param voucher_id: Voucher ID
        """
        sql = """
            SELECT * FROM PS_VCHR_HDR H
            WHERE H.BUSINESS_UNIT = :1 AND H.VOUCHER_ID = :2
        """
        result = await execute_query(sql, [business_unit.upper(), voucher_id.upper()])
        if "error" in result:
            return result
        if not result.get("results"):
            return {"error": f"Voucher '{voucher_id}' not found for BU '{business_unit}'."}
        return {"voucher": result["results"][0]}

    @mcp.tool()
    async def get_voucher_lines(
        business_unit: str,
        voucher_id: str,
        limit: int = 200,
    ) -> dict:
        """Get voucher line distribution (PS_VCHR_DIST_LN or PS_VCHR_LINE - try dist first)."""
        # Many installs use PS_VCHR_DIST_LN for accounting lines
        sql = """
            SELECT * FROM PS_VCHR_DIST_LN D
            WHERE D.BUSINESS_UNIT = :1 AND D.VOUCHER_ID = :2
            ORDER BY D.VOUCHER_LINE_NUM, D.DISTRIB_LINE_NUM
            FETCH FIRST :3 ROWS ONLY
        """
        r = await execute_query(sql, [business_unit.upper(), voucher_id.upper(), limit])
        if "error" not in r and r.get("results"):
            return r
        sql2 = """
            SELECT * FROM PS_VCHR_LINE L
            WHERE L.BUSINESS_UNIT = :1 AND L.VOUCHER_ID = :2
            FETCH FIRST :3 ROWS ONLY
        """
        return await execute_query(sql2, [business_unit.upper(), voucher_id.upper(), limit])

    @mcp.tool()
    async def list_recent_vouchers(
        business_unit: str,
        vendor_id: str | None = None,
        days: int = 90,
        limit: int = 50,
    ) -> dict:
        """
        List recent vouchers by invoice date (last N days).

        :param business_unit: BU
        :param vendor_id: Optional vendor filter
        :param days: Lookback days
        :param limit: Max rows
        """
        if vendor_id:
            sql = """
                SELECT H.BUSINESS_UNIT, H.VOUCHER_ID, H.VENDOR_ID, H.INVOICE_ID,
                       H.INVOICE_DT, H.GROSS_AMT, H.POST_STATUS_AP, H.ENTRY_STATUS
                FROM PS_VCHR_HDR H
                WHERE H.BUSINESS_UNIT = :1 AND H.VENDOR_ID = :2
                AND H.INVOICE_DT >= TRUNC(SYSDATE) - :3
                ORDER BY H.INVOICE_DT DESC
                FETCH FIRST :4 ROWS ONLY
            """
            params = [
                business_unit.upper(),
                vendor_id.upper(),
                days,
                limit,
            ]
        else:
            sql = """
                SELECT H.BUSINESS_UNIT, H.VOUCHER_ID, H.VENDOR_ID, H.INVOICE_ID,
                       H.INVOICE_DT, H.GROSS_AMT, H.POST_STATUS_AP, H.ENTRY_STATUS
                FROM PS_VCHR_HDR H
                WHERE H.BUSINESS_UNIT = :1
                AND H.INVOICE_DT >= TRUNC(SYSDATE) - :2
                ORDER BY H.INVOICE_DT DESC
                FETCH FIRST :3 ROWS ONLY
            """
            params = [business_unit.upper(), days, limit]
        return await execute_query(sql, params)
