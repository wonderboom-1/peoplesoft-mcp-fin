# peoplesoft-mcp-fin

**PeopleSoft Finance MCP Server** — a [Model Context Protocol](https://modelcontextprotocol.io) server for **PeopleSoft Financials (FSCM)**. It encompasses for modules - **GL, AP, AR, Purchasing, and Asset Management** semantics.

What can you do with this MCP Server?
A Model Context Protocol (MCP) server that enables AI assistants to query and understand PeopleSoft FSCM databases.
This server provides semantic tools for Finance, Supply Chain and PeopleTools metadata - allowing natural language questions to be answered with accurate SQL queries.

| This project (`peoplesoft-mcp-fin`) |
|-------------------------------------|
| Ledger, journals, chart of accounts, vendors, vouchers, customers, POs, assets |
| FSCM tables (`PS_LEDGER`, `PS_VCHR_HDR`, `PS_VENDOR`, …) |

## Features


- **Finance-focused tools**: GL summaries, journal header/lines, GL account lookup, vendors, vouchers, customers, billing invoice header, PO header/lines, asset lookup.
- **Schema introspection**: `describe_table`, `list_tables` (with **GL / AP / AR / PO / AM** module filters), translate values, indexes, relationships.
- **PeopleTools tools**: Same metadata stack as the original (records, PeopleCode, SQL definitions, etc.)
- **Direct SQL**: `query_peoplesoft_fin_db`.
- **Resources**: `peoplesoft-fin://schema-guide`, `concepts`, `query-examples`, `peopletools-guide`.

## Prerequisites

- Python 3.11+
- Oracle connectivity to a **PeopleSoft Financials** database (9.x style FSCM tables).
- [uv](https://github.com/astral-sh/uv) (recommended).

## Installation

```bash
cd peoplesoft-mcp-fin
uv sync
```

Dev dependencies (pytest) install by default. Run tests:

```bash
./run_tests.sh
# or: uv run pytest tests/ -v
```

## Configuration

```bash
cp .env.example .env
# Set ORACLE_DSN, ORACLE_USER, ORACLE_PASSWORD
```
Edit .env file and set the parameters with your database credentials and the Azure API foundry key for the LLM

Cursor IDE Integration:
Point Cursor MCP config at this project (see [`.cursor/mcp.json`](.cursor/mcp.json)):

```json
{
  "mcpServers": {
    "peoplesoft-fin": {
      "command": "uv",
      "args": [
        "--directory",
        "/absolute/path/to/peoplesoft-mcp-fin",
        "run",
        "peoplesoft_fin_server.py"
      ]
    }
  }
}
```
Credentials are loaded from .env automatically - no need to include them in the MCP config.


## Run

For the Backend MCP server
```bash
uv run peoplesoft_fin_server.py
# same server (alias): uv run peoplesoft_server.py
```

For the Frontend refer to the 'README' under the 'front-end' folder
```bash
cd front-end
npm install
npm run dev
```

In an **interactive terminal**, the server binds **HTTP** on `127.0.0.1:8765` by default (or the next free port if `8765` is taken—e.g. after **Ctrl+Z**). Open `/` for a short info page; MCP clients use **`/mcp`**. Browsers hitting **`/mcp`** get an HTML hint instead of **406**; POSTs use **JSON response mode** so weak `Accept` headers (e.g. `*/*`) are adjusted automatically. For **Cursor**, stdin is a pipe so **stdio** is used automatically. To force stdio: `PEOPLESOFT_FIN_MCP_TRANSPORT=stdio`.

## Running Tests

```bash
# Set environment variables
export ORACLE_DSN="hostname:port/service_name"
export ORACLE_USER="username"
export ORACLE_PASSWORD="password"

# Run all tests
uv run pytest tests/ -v -s

# Run specific test suite
uv run pytest tests/test_business_questions.py -v -s
uv run pytest tests/test_peopletools_questions.py -v -s
uv run pytest tests/test_import.py -v -s
```

## Example Queries

The MCP enables natural language questions like:

**Business Questions:**
- "How many active Vendors are there?"
- "What is the average invoice value for external vendors by year?"
- "What is the total monetary amount spent for department ID '22222' in 2026?"

**Technical Questions:**
- "What fields does PS_JOURNAL_HDR have?"
- "Where is the DEPTID field used?"
- "Explain effective dating in PeopleSoft"


## Tool overview

### Introspection

| Tool | Description |
|------|-------------|
| `describe_table` | Record fields via PSRECFIELD |
| `list_tables` | Search records; modules: GL, AP, AR, PO, AM, KK, SYSTEM |
| `get_translate_values` | XLAT decode |
| `get_table_indexes` | PSKEYDEFN |
| `get_table_relationships` | Related records by shared keys |

### General Ledger (`tools/gl.py`)

| Tool | Description |
|------|-------------|
| `get_gl_account` | Chart row (PS_GL_ACCOUNT_TBL) |
| `search_gl_accounts` | Search accounts by pattern |
| `get_ledger_account_summary` | Sum by account for BU/ledger/year/period |
| `get_journal_header` / `get_journal_lines` | PS_JRNL_HDR / PS_JRNL_LN |
| `list_open_periods` | PS_OPEN_PERIOD (if present) |

### Accounts Payable (`tools/ap.py`)

| Tool | Description |
|------|-------------|
| `get_vendor` / `search_vendors` | PS_VENDOR |
| `get_voucher_header` / `get_voucher_lines` / `get_voucher_distribution_lines` | PS_VOUCHER, PS_VOUCHER_LINE, PS_DISTRIB_LINE (legacy VCHR_* fallbacks) |
| `list_recent_vouchers` | Recent invoices by BU |

### AR / Billing (`tools/ar.py`)

| Tool | Description |
|------|-------------|
| `get_customer` / `search_customers` | PS_CUSTOMER |
| `get_billing_invoice_header` | PS_BI_HDR |
| `list_customer_items` | PS_ITEM |

### Purchasing (`tools/purchasing.py`)

| Tool | Description |
|------|-------------|
| `get_purchase_order` / `get_po_lines` | PS_PO_HDR / PS_PO_LINE |
| `search_purchase_orders` | PO search by vendor/status |

### Asset Management (`tools/assets.py`)

| Tool | Description |
|------|-------------|
| `get_asset` / `search_assets` | PS_ASSET (BUSINESS_UNIT_AM vs BUSINESS_UNIT fallback) |

### PeopleTools  (`tools/peopletools.py`)

| Tool | Description |
|------|-------------|
| `get_record_definition` | Full record structure with fields and keys |
| `search_records` | Find records by name or description |
| `get_component_structure` | Component pages and navigation |
| `get_page_fields` | Fields on a page with record bindings |
| `get_peoplecode` | Find PeopleCode on records/fields |
| `get_permission_list_details` | Security access for permission lists |
| `get_roles_for_permission_list` | Roles containing a permission list |
| `get_process_definition` | Process Scheduler job definitions |
| `get_application_engine_steps` | AE program structure |
| `get_integration_broker_services` | IB service operations |
| `get_message_definition` | IB message structure |
| `get_query_definition` | PS Query records and fields |
| `get_sql_definition` | Get SQL text by SQLID (views, App Engine, PeopleCode) |
| `search_sql_definitions` | Search SQL objects by text |
| `search_peoplecode` | Search text within PeopleCode |
| `get_field_usage` | Impact analysis - where a field is used |
| `get_translate_field_values` | All XLAT values for a field |
| `explain_peoplesoft_concept` | Explains effective dating, SetID, etc. |

## Available Resources

| Resource URI | Description |
|--------------|-------------|
| `peoplesoft_fin://schema-guide` | Major tables by module |
| `peoplesoft_fin://concepts` | Effective dating, EMPLID, SetID, XLAT |
| `peoplesoft_fin://query-examples-fin` | SQL query patterns |
| `peoplesoft_fin://peopletools-guide` | PeopleTools architecture guide |

## Table / column variance

Financials installs differ by **release, options, and customization**. If a query fails, use `describe_table` and adjust or use `query_peoplesoft_fin_db` with validated SQL.

## Dislaimer

This is experimental code developed as a part of a POC. This code is provided for training and educational purposes only. Use it responsibly. The author assumes no liability for any damages, misuse, or legal consequences arising from its use.

⚠️ Important Note on Database Connections: 
Always use a read-only database connection when configuring access. Supplying connection details to the MCP may expose sensitive financial data to the LLM. Handle credentials with caution and use this integration responsibly.

## License

MIT.
