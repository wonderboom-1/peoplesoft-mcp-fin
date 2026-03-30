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
# Clone the repository
git clone https://github.com/wonderboom-1/peoplesoft-mcp-fin.git
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

### Schema Introspection (`tools/introspection.py`) — 5 tools

| Tool | Parameters | Description |
|------|-----------|-------------|
| `describe_table` | **table_name** | Get table structure (fields, types, lengths, keys); falls back to ALL_TAB_COLUMNS for PeopleTools system tables |
| `list_tables` | pattern?, module?, limit? | Search records by name pattern or finance module (GL, AP, AR, PO, AM, KK, SYSTEM) |
| `get_translate_values` | **field_name** | Decode XLAT translate values for a field (e.g. VENDOR_STATUS) |
| `get_table_indexes` | **table_name** | Get index/key definitions from PSKEYDEFN |
| `get_table_relationships` | **table_name** | Find related tables sharing key fields (join discovery) |

### General Ledger (`tools/gl.py`) — 6 tools

| Tool | Parameters | Description |
|------|-----------|-------------|
| `get_gl_account` | **setid**, **account** | Get chart-of-accounts row, effective-dated (PS_GL_ACCOUNT_TBL) |
| `search_gl_accounts` | **setid**, pattern?, account_type?, limit? | Search GL accounts by description or account number |
| `get_ledger_account_summary` | **business_unit**, **ledger**, **fiscal_year**, **accounting_period**, account_pattern?, limit? | Summarize posted ledger balances by account (PS_LEDGER) |
| `get_journal_header` | **business_unit**, **journal_id** | Get journal header (PS_JRNL_HEADER) |
| `get_journal_lines` | **business_unit**, **journal_id**, limit? | Get journal lines (PS_JRNL_LN) |
| `list_open_periods` | **business_unit**, ledger_group? | List open GL periods (PS_FIN_OPEN_PERIOD with PS_CAL_DETP_TBL fallback) |

### Accounts Payable (`tools/ap.py`) — 6 tools

| Tool | Parameters | Description |
|------|-----------|-------------|
| `get_vendor` | **setid**, **vendor_id** | Get vendor master row (PS_VENDOR) |
| `search_vendors` | **setid**, name_pattern?, vendor_id?, limit? | Search vendors by name or ID |
| `get_voucher_header` | **business_unit**, **voucher_id** | Get voucher header (PS_VOUCHER; legacy VCHR_HDR fallback) |
| `get_voucher_lines` | **business_unit**, **voucher_id**, limit? | Get voucher lines (PS_VOUCHER_LINE) |
| `get_voucher_distribution_lines` | **business_unit**, **voucher_id**, limit? | Get distribution/accounting lines (PS_DISTRIB_LINE) |
| `list_recent_vouchers` | **business_unit**, vendor_id?, days?, limit? | List recent vouchers by invoice date |

### Accounts Receivable (`tools/ar.py`) — 4 tools

| Tool | Parameters | Description |
|------|-----------|-------------|
| `get_customer` | **setid**, **cust_id** | Get customer master row (PS_CUSTOMER) |
| `search_customers` | **setid**, name_pattern?, cust_id?, limit? | Search customers by name or ID |
| `get_billing_invoice_header` | **business_unit**, **invoice** | Get billing invoice header (PS_BI_HDR) |
| `list_customer_items` | **business_unit**, **cust_id**, limit? | List open customer items (PS_ITEM) |

### Purchasing (`tools/purchasing.py`) — 3 tools

| Tool | Parameters | Description |
|------|-----------|-------------|
| `get_purchase_order` | **business_unit**, **po_id** | Get PO header (PS_PO_HDR) |
| `get_po_lines` | **business_unit**, **po_id**, limit? | Get PO line details (PS_PO_LINE) |
| `search_purchase_orders` | **business_unit**, vendor_id?, status?, limit? | Search recent POs by vendor or status |

### Asset Management (`tools/assets.py`) — 2 tools

| Tool | Parameters | Description |
|------|-----------|-------------|
| `get_asset` | **business_unit**, **asset_id** | Get asset info (PS_ASSET; BUSINESS_UNIT_AM fallback) |
| `search_assets` | **business_unit**, descr_pattern?, tag_nbr?, limit? | Search assets by description or tag number |

### Financial Performance (`tools/performance.py`) — 6 tools

| Tool | Parameters | Description |
|------|-----------|-------------|
| `get_budget_vs_actual` | **business_unit**, **fiscal_year**, ledger_actuals?, ledger_budget?, account?, accounting_period?, limit? | Compare budget vs actuals ledger by account (PS_LEDGER) |
| `search_budget_exceptions` | **business_unit**, **fiscal_year**, threshold_pct?, ledger_actuals?, ledger_budget?, limit? | Find accounts exceeding a budget % threshold |
| `get_commitment_control_budget` | **business_unit**, **ledger_group**, **fiscal_year**, account?, limit? | Query KK budget balances (PS_LEDGER_KK) |
| `check_budget_status` | **business_unit**, **ledger_group**, **fiscal_year**, account?, limit? | Summarize KK available balance and consumed % |
| `get_period_close_status` | **business_unit**, **fiscal_year**, accounting_period? | Period open/close status across ledger groups (PS_FIN_OPEN_PERIOD) |
| `get_journal_posting_summary` | **business_unit**, **fiscal_year**, accounting_period? | Count posted vs unposted journals for period-end monitoring |

### Currency (`tools/currency.py`) — 2 tools

| Tool | Parameters | Description |
|------|-----------|-------------|
| `get_exchange_rate` | **from_currency**, **to_currency**, effective_date?, rt_type?, rt_rate_index? | Look up effective-dated exchange rate from PS_RT_RATE_TBL |
| `convert_amount` | **amount**, **from_currency**, **to_currency**, effective_date?, rt_type?, rt_rate_index? | Convert monetary amount between currencies using PS_RT_RATE_TBL rates |

### PeopleTools Metadata (`tools/peopletools.py`) — 18 tools

| Tool | Parameters | Description |
|------|-----------|-------------|
| `get_record_definition` | **record_name** | Get record definition from PSRECDEFN |
| `search_records` | **search_term**, record_type?, limit? | Search record definitions by name or description |
| `get_component_structure` | **component_name**, market? | Get component structure from PSPNLGRPDEFN |
| `get_component_pages` | **component_name**, market? | Get pages within a component (PSPNLGROUP) |
| `get_page_fields` | **page_name** | Get fields on a page (PSPNLFIELD) |
| `get_page_field_bindings` | **page_name** | Get field-to-record bindings on a page |
| `get_peoplecode` | **record_name**, **field_name**, **event** | Get PeopleCode source from PSPCMTXT (chunked CLOB read) |
| `get_permission_list_details` | **permission_list** | Get permission list details (PSCLASSDEFN + PSAUTHITEM) |
| `get_roles_for_permission_list` | **permission_list** | Find all roles containing a permission list (PSROLECLASS) |
| `get_process_definition` | process_name?, process_type? | Get process scheduler definitions (PS_PRCSDEFN) |
| `get_application_engine_steps` | **ae_program** | Get AE program sections and steps (PSAESTEPDEFN) |
| `get_integration_broker_services` | service_name? | Get IB service operations (PSOPERATION) |
| `get_message_definition` | **message_name** | Get message definition (PSMSGDEFN) |
| `get_query_definition` | **query_name** | Get PS Query definition (PSQRYDEFN) |
| `get_sql_definition` | **sql_id** | Get SQL object text from PSSQLTEXTDEFN (chunked CLOB read) |
| `search_sql_definitions` | **search_pattern**, limit? | Search SQL definitions by text pattern |
| `search_peoplecode` | **search_text**, limit? | Search PeopleCode source text across all programs |
| `get_field_usage` | **field_name**, limit? | Find all records that use a specific field |
| `get_translate_field_values` | **field_name** | Get translate values for a field (PSXLATITEM) |
| `explain_peoplesoft_concept` | **concept** | Explain a PeopleTools concept (static knowledge, no DB query) |

### Raw SQL (`peoplesoft_fin_server.py`) — 1 tool

| Tool | Parameters | Description |
|------|-----------|-------------|
| `query_peoplesoft_fin_db` | **sql_query**, parameters? | Execute arbitrary read-only SQL with pre/post-validation and auto-recovery |

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
