"""
Asset Management semantic tools (if AM installed).
"""
from db import execute_query


def register_tools(mcp):
    """Register Asset Management tools."""

    @mcp.tool()
    async def get_asset(business_unit: str, asset_id: str) -> dict:
        """
        Get asset basic info (PS_ASSET) — keys vary; common BUSINESS_UNIT + ASSET_ID.

        :param business_unit: AM business unit
        :param asset_id: Asset ID
        """
        sql = """
            SELECT
                A.BUSINESS_UNIT,
                A.ASSET_ID,
                A.DESCR,
                A.ASSET_STATUS,
                A.ASSET_TYPE,
                A.ACQUISITION_DT,
                A.ACQUISITION_CD,
                A.TAG_NUMBER,
                A.SERIAL_ID,
                A.MANUFACTURER,
                A.MODEL,
                A.PROFILE_ID,
                A.ASSET_CLASS
            FROM PS_ASSET A
            WHERE A.BUSINESS_UNIT = :1 AND A.ASSET_ID = :2
        """
        result = await execute_query(sql, [business_unit.upper(), asset_id.upper()])
        if "error" in result:
            return result
        if not result.get("results"):
            return {"error": f"Asset '{asset_id}' not found for BU '{business_unit}'."}
        row = result["results"][0]
        out = {k: (str(v) if hasattr(v, "isoformat") else v) for k, v in row.items()}
        return {"asset": out}

    @mcp.tool()
    async def search_assets(
        business_unit: str,
        descr_pattern: str | None = None,
        tag_nbr: str | None = None,
        limit: int = 50,
    ) -> dict:
        """Search assets by description or tag."""
        params = [business_unit.upper()]
        cond = ["A.BUSINESS_UNIT = :1"]
        n = 2
        if descr_pattern:
            cond.append(f"UPPER(A.DESCR) LIKE :{n}")
            params.append(f"%{descr_pattern.upper()}%")
            n += 1
        if tag_nbr:
            cond.append(f"A.TAG_NUMBER LIKE :{n}")
            params.append(f"%{tag_nbr.upper()}%")
            n += 1
        where_sql = " AND ".join(cond)
        sql = f"""
            SELECT A.BUSINESS_UNIT, A.ASSET_ID, A.DESCR, A.ASSET_STATUS, A.TAG_NUMBER
            FROM PS_ASSET A
            WHERE {where_sql}
            FETCH FIRST :{n} ROWS ONLY
        """
        params.append(limit)
        return await execute_query(sql, params)
