"""
Currency conversion tools backed by PS_RT_RATE_TBL.

PS_RT_RATE_TBL stores effective-dated cross-currency exchange rates.
Converted amount = source_amount * RATE_MULT / RATE_DIV.
"""
from db import execute_query


def register_tools(mcp):
    """Register currency conversion tools."""

    async def _fetch_rate(
        from_currency: str,
        to_currency: str,
        effective_date: str | None,
        rt_type: str,
        rt_rate_index: str,
    ) -> dict:
        """Shared helper: look up the best effective-dated rate row."""
        # oracledb maps binds by ORDER OF FIRST APPEARANCE in the SQL,
        # so params list must match the order binds appear in the query.
        date_expr = "TO_DATE(:5, 'YYYY-MM-DD')" if effective_date else "SYSDATE"
        params: list = [
            rt_rate_index.upper(),
            from_currency.upper(),
            to_currency.upper(),
            rt_type.upper(),
        ]
        if effective_date:
            params.append(effective_date)

        sql = f"""
            SELECT R.RT_RATE_INDEX, R.FROM_CUR, R.TO_CUR,
                   R.RT_TYPE, R.EFFDT, R.RATE_MULT, R.RATE_DIV
            FROM PS_RT_RATE_TBL R
            WHERE R.RT_RATE_INDEX = :1
              AND R.FROM_CUR = :2
              AND R.TO_CUR = :3
              AND R.RT_TYPE = :4
              AND R.EFFDT = (
                  SELECT MAX(R2.EFFDT)
                  FROM PS_RT_RATE_TBL R2
                  WHERE R2.RT_RATE_INDEX = R.RT_RATE_INDEX
                    AND R2.FROM_CUR = R.FROM_CUR
                    AND R2.TO_CUR = R.TO_CUR
                    AND R2.RT_TYPE = R.RT_TYPE
                    AND R2.EFFDT <= {date_expr}
              )
        """
        result = await execute_query(sql, params)
        if "error" in result:
            return result
        if not result.get("results"):
            return {
                "error": (
                    f"No exchange rate found for {from_currency.upper()} -> "
                    f"{to_currency.upper()} (index={rt_rate_index.upper()}, "
                    f"type={rt_type.upper()}, date={effective_date or 'today'}). "
                    "Try a different RT_TYPE (CURR, SPOT, AVGMO, AVGYR, CRRNT) "
                    "or RT_RATE_INDEX."
                )
            }
        row = result["results"][0]
        rate_mult = float(row["RATE_MULT"])
        rate_div = float(row["RATE_DIV"]) if row["RATE_DIV"] else 1.0
        return {
            "from_cur": row["FROM_CUR"],
            "to_cur": row["TO_CUR"],
            "rt_rate_index": row["RT_RATE_INDEX"],
            "rt_type": row["RT_TYPE"],
            "effdt": str(row["EFFDT"]) if row["EFFDT"] else None,
            "rate_mult": rate_mult,
            "rate_div": rate_div,
            "effective_rate": rate_mult / rate_div if rate_div else None,
        }

    @mcp.tool()
    async def get_exchange_rate(
        from_currency: str,
        to_currency: str,
        effective_date: str | None = None,
        rt_type: str = "CURR",
        rt_rate_index: str = "MARKET",
    ) -> dict:
        """
        Look up the effective-dated exchange rate between two currencies
        from PS_RT_RATE_TBL.

        Converted amount = source_amount * RATE_MULT / RATE_DIV.

        :param from_currency: Source currency code (e.g. USD, EUR, GBP)
        :param to_currency: Target currency code
        :param effective_date: Date string YYYY-MM-DD; defaults to today
        :param rt_type: Rate type — CURR, SPOT, AVGMO, AVGYR, CRRNT
        :param rt_rate_index: Rate index — typically MARKET
        """
        return await _fetch_rate(
            from_currency, to_currency, effective_date, rt_type, rt_rate_index
        )

    @mcp.tool()
    async def convert_amount(
        amount: float,
        from_currency: str,
        to_currency: str,
        effective_date: str | None = None,
        rt_type: str = "CURR",
        rt_rate_index: str = "MARKET",
    ) -> dict:
        """
        Convert a monetary amount from one currency to another using the
        effective-dated rate in PS_RT_RATE_TBL.

        :param amount: Source amount to convert
        :param from_currency: Source currency code (e.g. USD)
        :param to_currency: Target currency code (e.g. EUR)
        :param effective_date: Date string YYYY-MM-DD; defaults to today
        :param rt_type: Rate type — CURR, SPOT, AVGMO, AVGYR, CRRNT
        :param rt_rate_index: Rate index — typically MARKET
        """
        rate = await _fetch_rate(
            from_currency, to_currency, effective_date, rt_type, rt_rate_index
        )
        if "error" in rate:
            return rate
        converted = amount * rate["rate_mult"] / rate["rate_div"]
        return {
            "original_amount": amount,
            "from_currency": rate["from_cur"],
            "to_currency": rate["to_cur"],
            "converted_amount": round(converted, 4),
            "rate_mult": rate["rate_mult"],
            "rate_div": rate["rate_div"],
            "effective_rate": rate["effective_rate"],
            "effdt": rate["effdt"],
            "rt_type": rate["rt_type"],
            "rt_rate_index": rate["rt_rate_index"],
        }
