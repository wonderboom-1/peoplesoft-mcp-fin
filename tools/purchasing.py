"""
Purchasing semantic tools (purchase orders).
"""
from db import execute_query


def register_tools(mcp):
    """Register Purchasing tools."""

    @mcp.tool()
    async def get_purchase_order(business_unit: str, po_id: str) -> dict:
        """
        Get purchase order header (PS_PO_HDR).

        :param business_unit: Purchasing BU
        :param po_id: PO ID
        """
        sql = """
            SELECT
                P.BUSINESS_UNIT,
                P.PO_ID,
                P.VENDOR_ID,
                P.VENDOR_SETID,
                P.PO_DT,
                P.PO_STATUS,
                P.BUYER_ID,
                P.CURRENCY_CD,
                P.TOTAL_PO_AMT,
                P.ORIGIN,
                P.SHIPTO_SETID,
                P.SHIPTO_ID
            FROM PS_PO_HDR P
            WHERE P.BUSINESS_UNIT = :1 AND P.PO_ID = :2
        """
        result = await execute_query(sql, [business_unit.upper(), po_id.upper()])
        if "error" in result:
            return result
        if not result.get("results"):
            return {"error": f"PO '{po_id}' not found for BU '{business_unit}'."}
        row = result["results"][0]
        return {
            "business_unit": row["BUSINESS_UNIT"],
            "po_id": row["PO_ID"],
            "vendor_id": row["VENDOR_ID"],
            "vendor_setid": row["VENDOR_SETID"],
            "po_date": str(row["PO_DT"]) if row["PO_DT"] else None,
            "status": row["PO_STATUS"],
            "buyer_id": row["BUYER_ID"],
            "currency": row["CURRENCY_CD"],
            "total_amt": float(row["TOTAL_PO_AMT"]) if row["TOTAL_PO_AMT"] else None,
        }

    @mcp.tool()
    async def get_po_lines(business_unit: str, po_id: str, limit: int = 200) -> dict:
        """Get PO line details (PS_PO_LINE)."""
        sql = """
            SELECT * FROM PS_PO_LINE L
            WHERE L.BUSINESS_UNIT = :1 AND L.PO_ID = :2
            ORDER BY L.LINE_NBR
            FETCH FIRST :3 ROWS ONLY
        """
        return await execute_query(sql, [business_unit.upper(), po_id.upper(), limit])

    @mcp.tool()
    async def search_purchase_orders(
        business_unit: str,
        vendor_id: str | None = None,
        status: str | None = None,
        limit: int = 50,
    ) -> dict:
        """
        Search recent POs by vendor or status.

        :param business_unit: BU
        :param vendor_id: Optional vendor
        :param status: Optional PO_STATUS (e.g., O, A, C — use get_translate_values)
        :param limit: Max rows
        """
        params = [business_unit.upper()]
        cond = ["P.BUSINESS_UNIT = :1"]
        n = 2
        if vendor_id:
            cond.append(f"P.VENDOR_ID = :{n}")
            params.append(vendor_id.upper())
            n += 1
        if status:
            cond.append(f"P.PO_STATUS = :{n}")
            params.append(status.upper())
            n += 1
        where_sql = " AND ".join(cond)
        sql = f"""
            SELECT P.BUSINESS_UNIT, P.PO_ID, P.VENDOR_ID, P.PO_DT, P.PO_STATUS, P.TOTAL_PO_AMT
            FROM PS_PO_HDR P
            WHERE {where_sql}
            ORDER BY P.PO_DT DESC
            FETCH FIRST :{n} ROWS ONLY
        """
        params.append(limit)
        return await execute_query(sql, params)