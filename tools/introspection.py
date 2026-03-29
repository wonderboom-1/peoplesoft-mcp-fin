"""
Schema introspection tools for PeopleSoft Finance MCP.
"""
from db import execute_query, execute_query_with_limit


def register_tools(mcp):
    """Register all introspection tools with the MCP server."""

    @mcp.tool()
    async def describe_table(table_name: str) -> dict:
        """
        Get the structure of a PeopleSoft table/record including all fields,
        types, lengths, and descriptions. Use FIRST before writing finance SQL.

        :param table_name: Record name (e.g., 'LEDGER', 'VENDOR', 'VCHR_HDR', 'JRNL_HDR').
        :return: List of fields with properties
        """
        clean_name = table_name.upper().replace("PS_", "")

        sql = """
            SELECT
                RF.FIELDNAME,
                RF.FIELDNUM,
                DF.FIELDTYPE,
                DF.LENGTH,
                DF.DECIMALPOS,
                DBMS_LOB.SUBSTR(DF.DESCRLONG, 4000, 1) AS DESCRIPTION,
                CASE WHEN RF.USEEDIT LIKE '%K%' THEN 'Y' ELSE 'N' END AS IS_KEY,
                CASE WHEN RF.USEEDIT LIKE '%R%' THEN 'Y' ELSE 'N' END AS IS_REQUIRED,
                CASE WHEN DF.FIELDTYPE = 1 THEN 'XLAT' ELSE NULL END AS HAS_TRANSLATE
            FROM PSRECFIELD RF
            JOIN PSDBFIELD DF ON RF.FIELDNAME = DF.FIELDNAME
            WHERE RF.RECNAME = :1
            ORDER BY RF.FIELDNUM
        """

        result = await execute_query(sql, [clean_name])

        if "error" in result:
            return result

        if not result.get("results"):
            return {
                "error": f"Table '{table_name}' not found. Try list_tables() to search for tables."
            }

        field_type_map = {
            0: "CHARACTER",
            1: "LONG_CHARACTER",
            2: "NUMBER",
            3: "SIGNED_NUMBER",
            4: "DATE",
            5: "TIME",
            6: "DATETIME",
            8: "IMAGE",
            9: "IMAGE_REF",
        }

        fields = []
        for row in result["results"]:
            fields.append(
                {
                    "field_name": row["FIELDNAME"],
                    "position": row["FIELDNUM"],
                    "type": field_type_map.get(row["FIELDTYPE"], f"UNKNOWN({row['FIELDTYPE']})"),
                    "length": row["LENGTH"],
                    "decimals": row["DECIMALPOS"] if row["DECIMALPOS"] else None,
                    "description": row["DESCRIPTION"],
                    "is_key": row["IS_KEY"] == "Y",
                    "is_required": row["IS_REQUIRED"] == "Y",
                    "has_translate_values": row["FIELDTYPE"] == 1
                    or row["HAS_TRANSLATE"] == "XLAT",
                }
            )

        return {
            "table_name": f"PS_{clean_name}",
            "record_name": clean_name,
            "field_count": len(fields),
            "fields": fields,
        }

    @mcp.tool()
    async def list_tables(
        pattern: str | None = None,
        module: str | None = None,
        limit: int = 50,
    ) -> dict:
        """
        Search for PeopleSoft tables/records by name pattern or finance module.

        :param pattern: Optional pattern (e.g., 'LEDGER', 'VCHR', 'VENDOR', 'PO_HDR').
        :param module: Optional filter:
            - 'GL' or 'GENERAL_LEDGER': Ledger, journal, chart of accounts
            - 'AP' or 'PAYABLES': Voucher, vendor, payment
            - 'AR' or 'RECEIVABLES' or 'BILLING': Customer, item, BI
            - 'PO' or 'PURCHASING': Purchase order, requisition
            - 'AM' or 'ASSETS': Asset management
            - 'KK' or 'COMMITMENT': Commitment control (if installed)
            - 'SYSTEM': PeopleTools metadata-style names (no underscore in pattern)
        :param limit: Max results (default 50)
        :return: Matching tables with descriptions
        """
        conditions = ["R.RECTYPE = 0"]
        params = []

        if pattern:
            clean_pattern = pattern.upper().replace("PS_", "").replace("*", "%").replace("?", "_")
            if "%" not in clean_pattern:
                clean_pattern = f"%{clean_pattern}%"
            conditions.append("R.RECNAME LIKE :1")
            params.append(clean_pattern)

        if module:
            mu = module.upper()
            if mu in ("GL", "GENERAL_LEDGER"):
                conditions.append(
                    """
                    (R.RECNAME LIKE 'LEDGER%' OR R.RECNAME LIKE 'JRNL%'
                     OR R.RECNAME LIKE 'GL\\_%' ESCAPE '\\'
                     OR R.RECNAME LIKE 'TREE\\_NODE%' ESCAPE '\\'
                     OR R.RECNAME LIKE 'OPEN\\_PERIOD%' ESCAPE '\\')
                    """
                )
            elif mu in ("AP", "PAYABLES"):
                conditions.append(
                    """
                    (R.RECNAME LIKE 'VCHR%' OR R.RECNAME LIKE 'VENDOR%'
                     OR R.RECNAME LIKE 'PYMNT%' OR R.RECNAME LIKE 'PAYMENT%'
                     OR R.RECNAME LIKE 'AP\\_%' ESCAPE '\\')
                    """
                )
            elif mu in ("AR", "RECEIVABLES", "BILLING"):
                conditions.append(
                    """
                    (R.RECNAME LIKE 'CUSTOMER%' OR R.RECNAME LIKE 'CUST\\_%' ESCAPE '\\'
                     OR R.RECNAME LIKE 'ITEM%' OR R.RECNAME LIKE 'BI\\_%' ESCAPE '\\'
                     OR R.RECNAME LIKE 'AR\\_%' ESCAPE '\\')
                    """
                )
            elif mu in ("PO", "PURCHASING"):
                conditions.append(
                    """
                    (R.RECNAME LIKE 'PO\\_%' ESCAPE '\\'
                     OR R.RECNAME LIKE 'REQ\\_%' ESCAPE '\\'
                     OR R.RECNAME LIKE 'PURCH%')
                    """
                )
            elif mu in ("AM", "ASSETS"):
                conditions.append(
                    """
                    (R.RECNAME LIKE 'ASSET%' OR R.RECNAME LIKE 'BOOK%'
                     OR R.RECNAME LIKE 'AM\\_%' ESCAPE '\\')
                    """
                )
            elif mu in ("KK", "COMMITMENT"):
                conditions.append("R.RECNAME LIKE 'KK\\_%' ESCAPE '\\'")
            elif mu == "SYSTEM":
                conditions.append("R.RECNAME NOT LIKE '%\\_%' ESCAPE '\\'")

        where_clause = " AND ".join(conditions)

        sql = f"""
            SELECT
                R.RECNAME,
                R.RECDESCR,
                R.PARENTRECNAME,
                (SELECT COUNT(*) FROM PSRECFIELD RF WHERE RF.RECNAME = R.RECNAME) AS FIELD_COUNT
            FROM PSRECDEFN R
            WHERE {where_clause}
            ORDER BY R.RECNAME
            FETCH FIRST :limit ROWS ONLY
        """
        params.append(limit)

        result = await execute_query(sql, params)

        if "error" in result:
            return result

        tables = []
        for row in result["results"]:
            tables.append(
                {
                    "record_name": row["RECNAME"],
                    "table_name": f"PS_{row['RECNAME']}",
                    "description": row["RECDESCR"],
                    "parent_record": row["PARENTRECNAME"] if row["PARENTRECNAME"] else None,
                    "field_count": row["FIELD_COUNT"],
                }
            )

        return {"count": len(tables), "tables": tables}

    @mcp.tool()
    async def get_translate_values(field_name: str) -> dict:
        """
        Decode translate (XLAT) values for a field (e.g., voucher status, dist status).

        :param field_name: Field name (e.g., 'POST_STATUS_AP', 'PYMNT_METHOD')
        :return: Code values with descriptions
        """
        clean_name = field_name.upper()

        sql = """
            SELECT
                X.FIELDVALUE,
                X.XLATSHORTNAME,
                X.XLATLONGNAME,
                X.EFF_STATUS,
                X.EFFDT
            FROM PSXLATITEM X
            WHERE X.FIELDNAME = :1
            AND X.EFFDT = (
                SELECT MAX(X2.EFFDT)
                FROM PSXLATITEM X2
                WHERE X2.FIELDNAME = X.FIELDNAME
                AND X2.FIELDVALUE = X.FIELDVALUE
                AND X2.EFFDT <= SYSDATE
            )
            ORDER BY X.FIELDVALUE
        """

        result = await execute_query(sql, [clean_name])

        if "error" in result:
            return result

        if not result.get("results"):
            return {
                "field_name": clean_name,
                "message": f"No translate values found for '{clean_name}'.",
                "values": [],
            }

        values = []
        for row in result["results"]:
            values.append(
                {
                    "code": row["FIELDVALUE"],
                    "short_name": row["XLATSHORTNAME"],
                    "long_name": row["XLATLONGNAME"],
                    "active": row["EFF_STATUS"] == "A",
                }
            )

        return {"field_name": clean_name, "value_count": len(values), "values": values}

    @mcp.tool()
    async def get_table_indexes(table_name: str) -> dict:
        """Get index keys for a PeopleSoft finance table."""
        clean_name = table_name.upper().replace("PS_", "")

        sql = """
            SELECT
                K.INDEXID,
                K.KEYPOSN,
                K.FIELDNAME,
                CASE K.INDEXID
                    WHEN '_' THEN 'PRIMARY'
                    WHEN 'A' THEN 'ALTERNATE_A'
                    WHEN 'B' THEN 'ALTERNATE_B'
                    WHEN 'C' THEN 'ALTERNATE_C'
                    ELSE 'INDEX_' || K.INDEXID
                END AS INDEX_TYPE
            FROM PSKEYDEFN K
            WHERE K.RECNAME = :1
            ORDER BY K.INDEXID, K.KEYPOSN
        """

        result = await execute_query(sql, [clean_name])

        if "error" in result:
            return result

        if not result.get("results"):
            return {"error": f"No indexes found for table '{table_name}'."}

        indexes = {}
        for row in result["results"]:
            idx_id = row["INDEXID"]
            if idx_id not in indexes:
                indexes[idx_id] = {
                    "index_id": idx_id,
                    "index_type": row["INDEX_TYPE"],
                    "fields": [],
                }
            indexes[idx_id]["fields"].append(
                {"position": row["KEYPOSN"], "field_name": row["FIELDNAME"]}
            )

        primary_keys = []
        if "_" in indexes:
            primary_keys = [f["field_name"] for f in indexes["_"]["fields"]]

        return {
            "table_name": f"PS_{clean_name}",
            "record_name": clean_name,
            "primary_key_fields": primary_keys,
            "indexes": list(indexes.values()),
        }

    @mcp.tool()
    async def get_table_relationships(table_name: str) -> dict:
        """Find tables sharing key fields with the given record (join discovery)."""
        clean_name = table_name.upper().replace("PS_", "")

        key_sql = """
            SELECT K.FIELDNAME
            FROM PSKEYDEFN K
            WHERE K.RECNAME = :1 AND K.INDEXID = '_'
            ORDER BY K.KEYPOSN
        """

        key_result = await execute_query(key_sql, [clean_name])

        if "error" in key_result:
            return key_result

        if not key_result.get("results"):
            return {"error": f"Table '{table_name}' not found or has no primary key."}

        key_fields = [r["FIELDNAME"] for r in key_result["results"]]
        if not key_fields:
            return {"message": "No key fields found for this table."}

        placeholders = ", ".join([f":{i + 1}" for i in range(len(key_fields))])

        related_sql = f"""
            SELECT DISTINCT
                RF.RECNAME,
                RD.RECDESCR,
                COUNT(*) AS SHARED_KEY_COUNT
            FROM PSRECFIELD RF
            JOIN PSRECDEFN RD ON RF.RECNAME = RD.RECNAME
            WHERE RF.FIELDNAME IN ({placeholders})
            AND RF.RECNAME != :rec_name
            AND RD.RECTYPE = 0
            GROUP BY RF.RECNAME, RD.RECDESCR
            HAVING COUNT(*) >= 1
            ORDER BY COUNT(*) DESC, RF.RECNAME
            FETCH FIRST 30 ROWS ONLY
        """

        params = key_fields + [clean_name]
        related_result = await execute_query(related_sql, params)

        if "error" in related_result:
            return related_result

        related_tables = []
        for row in related_result["results"]:
            related_tables.append(
                {
                    "record_name": row["RECNAME"],
                    "table_name": f"PS_{row['RECNAME']}",
                    "description": row["RECDESCR"],
                    "shared_key_fields": row["SHARED_KEY_COUNT"],
                    "relationship_strength": "strong"
                    if row["SHARED_KEY_COUNT"] >= len(key_fields)
                    else "partial",
                }
            )

        return {
            "source_table": f"PS_{clean_name}",
            "key_fields": key_fields,
            "related_table_count": len(related_tables),
            "related_tables": related_tables,
        }
