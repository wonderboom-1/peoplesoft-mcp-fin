"""
Accounts Payable semantic tools (vendor, voucher, payment).

Typical FSCM layout (this repo targets):
  PS_VOUCHER — voucher header
  PS_VOUCHER_LINE — invoice / expense lines
  PS_DISTRIB_LINE — distribution (GL) lines, child of voucher line
Legacy names (VCHR_HDR, VCHR_LINE, VCHR_DIST_LN) are still tried as fallbacks.
"""
from db import execute_query


_voucher_header_table: str | None = None


async def _query_voucher_detail_table(
    record_names: tuple[str, ...],
    business_unit: str,
    voucher_id: str,
    limit: int,
) -> dict:
    """
    Query BU + VOUCHER_ID against the first candidate record whose table exists.

    Skips ORA-00942 (table missing). Stops on first successful execute — including
    zero rows — so we do not read from a legacy table when the modern one exists but is empty.
    """
    bu, vid = business_unit.upper(), voucher_id.upper()
    for tbl in record_names:
        sql = f"""
            SELECT * FROM PS_{tbl} D
            WHERE D.BUSINESS_UNIT = :1 AND D.VOUCHER_ID = :2
            ORDER BY 1
            FETCH FIRST :3 ROWS ONLY
        """
        r = await execute_query(sql, [bu, vid, limit])
        if "error" in r:
            if "ORA-00942" in r.get("error", ""):
                continue
            return r
        out = dict(r)
        out["record_name"] = tbl
        out["table_name"] = f"PS_{tbl}"
        return out
    return {
        "error": "No matching voucher detail table found for this installation. "
        "Use list_tables(pattern='VOUCHER') or list_tables(pattern='DISTRIB')."
    }


async def _resolve_voucher_header() -> str | None:
    """Discover the voucher header table in this installation (cached)."""
    global _voucher_header_table
    if _voucher_header_table is not None:
        return _voucher_header_table if _voucher_header_table != "" else None

    preferred = ["VOUCHER", "VCHR_HDR", "VOUCHER_HDR"]
    for rec in preferred:
        check = await execute_query(
            "SELECT 1 FROM PSRECDEFN WHERE RECNAME = :1 AND RECTYPE = 0",
            [rec],
        )
        if "error" not in check and check.get("results"):
            _voucher_header_table = rec
            return rec

    result = await execute_query(
        """
        SELECT RECNAME FROM PSRECDEFN
        WHERE RECTYPE = 0
          AND (
            RECNAME = 'VOUCHER'
            OR RECNAME LIKE '%VCHR%HDR%'
          )
        ORDER BY CASE RECNAME
                   WHEN 'VOUCHER' THEN 0
                   WHEN 'VCHR_HDR' THEN 1
                   WHEN 'VOUCHER_HDR' THEN 2
                   ELSE 3
                 END,
                 LENGTH(RECNAME)
        FETCH FIRST 1 ROWS ONLY
        """,
        [],
    )
    if "error" not in result and result.get("results"):
        _voucher_header_table = result["results"][0]["RECNAME"]
        return _voucher_header_table

    _voucher_header_table = ""
    return None


def register_tools(mcp):
    """Register AP tools."""

    @mcp.tool()
    async def get_vendor(setid: str, vendor_id: str) -> dict:
        """
        Get vendor master (PS_VENDOR) row.

        :param setid: Vendor SetID
        :param vendor_id: Vendor ID
        """
        sql = """
            SELECT * FROM PS_VENDOR V
            WHERE V.SETID = :1 AND V.VENDOR_ID = :2
            FETCH FIRST 1 ROWS ONLY
        """
        result = await execute_query(sql, [setid.upper(), vendor_id.upper()])
        if "error" in result:
            return result
        if not result.get("results"):
            return {"error": f"Vendor '{vendor_id}' not found for SetID '{setid}'."}
        return {"vendor": result["results"][0]}

    @mcp.tool()
    async def search_vendors(
        setid: str,
        name_pattern: str | None = None,
        vendor_id: str | None = None,
        limit: int = 50,
    ) -> dict:
        """Search vendors by name or ID."""
        params: list = [setid.upper()]
        cond = ["V.SETID = :1"]
        n = 2
        if name_pattern:
            # Each :placeholder occurrence needs its own value for oracledb positional binds.
            pat = f"%{name_pattern.upper()}%"
            cond.append(
                f"(UPPER(V.NAME1) LIKE :{n} OR UPPER(V.VENDOR_NAME_SHORT) LIKE :{n + 1})"
            )
            params.extend([pat, pat])
            n += 2
        if vendor_id:
            cond.append(f"V.VENDOR_ID LIKE :{n}")
            params.append(f"%{vendor_id.upper()}%")
            n += 1
        where_sql = " AND ".join(cond)
        sql = f"""
            SELECT V.SETID, V.VENDOR_ID, V.NAME1,
                   V.VENDOR_NAME_SHORT, V.VENDOR_STATUS
            FROM PS_VENDOR V
            WHERE {where_sql}
            ORDER BY V.VENDOR_ID
            FETCH FIRST :{n} ROWS ONLY
        """
        params.append(limit)
        return await execute_query(sql, params)

    @mcp.tool()
    async def get_voucher_header(business_unit: str, voucher_id: str) -> dict:
        """
        Get voucher header (standard Payables; typically PS_VOUCHER / VOUCHER record).

        :param business_unit: AP business unit
        :param voucher_id: Voucher ID
        """
        rec = await _resolve_voucher_header()
        if not rec:
            return {
                "error": "No voucher header table found in this installation. "
                "Use list_tables(pattern='VCHR') or list_tables(pattern='VOUCHER') "
                "to discover voucher-related tables."
            }
        sql = f"""
            SELECT * FROM PS_{rec} H
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
        """
        Voucher invoice / expense lines (PS_VOUCHER_LINE, record VOUCHER_LINE).

        For GL distribution rows under each line, use get_voucher_distribution_lines.
        """
        return await _query_voucher_detail_table(
            ("VOUCHER_LINE", "VCHR_LINE", "VCHR_ACCTG_LINE"),
            business_unit,
            voucher_id,
            limit,
        )

    @mcp.tool()
    async def get_voucher_distribution_lines(
        business_unit: str,
        voucher_id: str,
        limit: int = 500,
    ) -> dict:
        """
        Voucher distribution / accounting lines (PS_DISTRIB_LINE, record DISTRIB_LINE).

        Child of voucher line keys (typically VOUCHER_LINE_NUM + DISTRIB_LINE_NUM).
        """
        return await _query_voucher_detail_table(
            (
                "DISTRIB_LINE",
                "VCHR_DIST_LN",
                "VOUCHER_DIST_LN",
                "VOUCHER_DIST",
            ),
            business_unit,
            voucher_id,
            limit,
        )

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
        rec = await _resolve_voucher_header()
        if not rec:
            return {
                "error": "No voucher header table found in this installation. "
                "Use list_tables(pattern='VCHR') or list_tables(pattern='VOUCHER') "
                "to discover voucher-related tables."
            }

        if vendor_id:
            sql = f"""
                SELECT * FROM PS_{rec} H
                WHERE H.BUSINESS_UNIT = :1 AND H.VENDOR_ID = :2
                AND H.INVOICE_DT >= TRUNC(SYSDATE) - :3
                ORDER BY H.INVOICE_DT DESC
                FETCH FIRST :4 ROWS ONLY
            """
            params: list = [business_unit.upper(), vendor_id.upper(), days, limit]
        else:
            sql = f"""
                SELECT * FROM PS_{rec} H
                WHERE H.BUSINESS_UNIT = :1
                AND H.INVOICE_DT >= TRUNC(SYSDATE) - :2
                ORDER BY H.INVOICE_DT DESC
                FETCH FIRST :3 ROWS ONLY
            """
            params = [business_unit.upper(), days, limit]

        result = await execute_query(sql, params)
        if "error" in result and "ORA-00904" in result.get("error", ""):
            return {
                "error": result["error"]
                + f"\n\nThe voucher table PS_{rec} exists but some column names differ. "
                "Use describe_table('" + rec + "') to get the actual columns."
            }
        return result
