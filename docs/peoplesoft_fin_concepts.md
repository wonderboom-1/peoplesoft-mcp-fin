# PeopleSoft Financials — Concepts

## Business Unit (BU)

Financial transactions are scoped by **Business Unit** — different BUs for GL, AP, AR, PO, etc. may apply depending on setup (e.g., same BU or separate).

## SetID

**SetID** controls tablesets for shared setup data:

- **GL**: Chart of accounts (`PS_GL_ACCOUNT_TBL`) is SetID + Account + effective date.
- **AP**: Vendors (`PS_VENDOR`) are SetID + Vendor ID + effective date.
- **AR**: Customers (`PS_CUSTOMER`) are SetID + Customer ID + effective date.

## Ledger & fiscal calendar

- **Ledger** (e.g., `ACTUALS`) identifies a ledger within a BU.
- **Fiscal year** and **accounting period** partition posted amounts in `PS_LEDGER`.
- Open/close status may be tracked in `PS_FIN_OPEN_PERIOD` (if used).

## Vouchers (AP)

Typical lifecycle: entry → approval → post. Status fields (e.g., `POST_STATUS_AP`, `ENTRY_STATUS`) are often translate fields — use `get_translate_values`.

## Journals (GL)

**Journal ID** + **Business Unit** identify a journal in `PS_JRNL_HEADER` / `PS_JRNL_LN`.

## Effective dating

Setup tables (account, vendor, customer) use **EFFDT** / **EFF_STATUS**. Tools in this MCP use “current row” patterns (`MAX(EFFDT) <= SYSDATE`).

## Customization

Field and record names can differ by **PeopleTools version** and **customizations**. Always confirm with `describe_table` and `get_record_definition`.
