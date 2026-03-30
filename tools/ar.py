"""
Accounts Receivable / Billing oriented tools (customer, items).
"""
from db import execute_query


def register_tools(mcp):
    """Register AR/Billing tools."""

    @mcp.tool()
    async def get_customer(setid: str, cust_id: str) -> dict:
        """
        Get customer master (PS_CUSTOMER) row.

        :param setid: Customer SetID
        :param cust_id: Customer ID
        """
        sql = """
            SELECT * FROM PS_CUSTOMER C
            WHERE C.SETID = :1 AND C.CUST_ID = :2
            FETCH FIRST 1 ROWS ONLY
        """
        result = await execute_query(sql, [setid.upper(), cust_id.upper()])
        if "error" in result:
            return result
        if not result.get("results"):
            return {"error": f"Customer '{cust_id}' not found for SetID '{setid}'."}
        return {"customer": result["results"][0]}

    @mcp.tool()
    async def search_customers(
        setid: str,
        name_pattern: str | None = None,
        cust_id: str | None = None,
        limit: int = 50,
    ) -> dict:
        """Search customers by name or ID."""
        params: list = [setid.upper()]
        cond = ["C.SETID = :1"]
        n = 2
        if name_pattern:
            cond.append(f"UPPER(C.NAME1) LIKE :{n}")
            params.append(f"%{name_pattern.upper()}%")
            n += 1
        if cust_id:
            cond.append(f"C.CUST_ID LIKE :{n}")
            params.append(f"%{cust_id.upper()}%")
            n += 1
        where_sql = " AND ".join(cond)
        sql = f"""
            SELECT C.SETID, C.CUST_ID, C.NAME1, C.CUST_STATUS
            FROM PS_CUSTOMER C
            WHERE {where_sql}
            ORDER BY C.CUST_ID
            FETCH FIRST :{n} ROWS ONLY
        """
        params.append(limit)
        return await execute_query(sql, params)

    @mcp.tool()
    async def get_billing_invoice_header(business_unit: str, invoice: str) -> dict:
        """
        Get billing invoice header (PS_BI_HDR) if Billing is installed.

        :param business_unit: BI business unit
        :param invoice: Invoice number
        """
        sql = """
            SELECT * FROM PS_BI_HDR B
            WHERE B.BUSINESS_UNIT = :1 AND B.INVOICE = :2
        """
        result = await execute_query(sql, [business_unit.upper(), invoice.upper()])
        if "error" in result:
            return result
        if not result.get("results"):
            return {
                "error": f"Invoice '{invoice}' not found for BU '{business_unit}'. "
                "Confirm Billing module and table names via describe_table('BI_HDR')."
            }
        return {"invoice_header": result["results"][0]}

    @mcp.tool()
    async def list_customer_items(
        business_unit: str,
        cust_id: str,
        limit: int = 50,
    ) -> dict:
        """
        List open/customer items (PS_ITEM) — structure varies; common keys BU + customer + item.

        :param business_unit: AR business unit
        :param cust_id: Customer ID (BI_CUST_ID or CUST_ID per install)
        """
        sql = """
            SELECT I.BUSINESS_UNIT, I.ITEM, I.ITEM_LINE, I.ENTRY_TYPE,
                   I.ENTRY_REASON, I.ENTRY_EVENT, I.ITEM_AMT, I.ENTRY_DT, I.BI_CUST_ID
            FROM PS_ITEM I
            WHERE I.BUSINESS_UNIT = :1 AND I.BI_CUST_ID = :2
            ORDER BY I.ENTRY_DT DESC
            FETCH FIRST :3 ROWS ONLY
        """
        r = await execute_query(sql, [business_unit.upper(), cust_id.upper(), limit])
        if "error" in r and "invalid identifier" in str(r.get("error", "")).lower():
            sql2 = """
                SELECT I.BUSINESS_UNIT, I.ITEM, I.ITEM_LINE, I.ITEM_AMT, I.ENTRY_DT, I.CUST_ID
                FROM PS_ITEM I
                WHERE I.BUSINESS_UNIT = :1 AND I.CUST_ID = :2
                ORDER BY I.ENTRY_DT DESC
                FETCH FIRST :3 ROWS ONLY
            """
            return await execute_query(sql2, [business_unit.upper(), cust_id.upper(), limit])
        return r
