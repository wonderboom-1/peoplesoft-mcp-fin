# PeopleSoft Financials — Schema Guide (FSCM-oriented)

Use **`describe_table`** and **`list_tables(module='...')`** for your exact install.

## General Ledger (GL)

| Table | Description | Typical keys |
|-------|-------------|--------------|
| PS_LEDGER | Posted ledger balances / activity | BU, LEDGER, ACCOUNT, FISCAL_YEAR, ACCOUNTING_PERIOD, … |
| PS_JRNL_HDR | Journal header (metadata record: JRNL_HEADER) | BUSINESS_UNIT, JOURNAL_ID |
| PS_JRNL_LN | Journal lines (metadata record: JRNL_LINE) | BUSINESS_UNIT, JOURNAL_ID, JOURNAL_LINE |
| PS_GL_ACCOUNT_TBL | Chart of accounts | SETID, ACCOUNT, EFFDT |
| PS_OPEN_PERIOD | Open periods (if used) | BUSINESS_UNIT, LEDGER_GROUP, FISCAL_YEAR, ACCOUNTING_PERIOD |

## Accounts Payable (AP)

| Table | Description | Typical keys |
|-------|-------------|--------------|
| PS_VENDOR | Vendor master | SETID, VENDOR_ID (eff-dating varies) |
| PS_VOUCHER | Voucher header | BUSINESS_UNIT, VOUCHER_ID |
| PS_VOUCHER_LINE | Voucher line (invoice / expense) | BUSINESS_UNIT, VOUCHER_ID, VOUCHER_LINE_NUM |
| PS_DISTRIB_LINE | Distribution (GL) lines — child of voucher line | BUSINESS_UNIT, VOUCHER_ID, VOUCHER_LINE_NUM, DISTRIB_LINE_NUM |
| PS_VCHR_HDR / PS_VCHR_LINE / PS_VCHR_DIST_LN | Legacy names on some installs | Same logical keys |
| PS_PAYMENT_TBL / payment views | Payments | Varies by release |

## Accounts Receivable / Billing

| Table | Description | Typical keys |
|-------|-------------|--------------|
| PS_CUSTOMER | Customer master | SETID, CUST_ID, EFFDT |
| PS_ITEM | AR items / activity | BUSINESS_UNIT, ITEM, … |
| PS_BI_HDR | Billing invoice header | BUSINESS_UNIT, INVOICE |

## Purchasing

| Table | Description | Typical keys |
|-------|-------------|--------------|
| PS_PO_HDR | Purchase order header | BUSINESS_UNIT, PO_ID |
| PS_PO_LINE | PO lines | BUSINESS_UNIT, PO_ID, LINE_NBR |

## Asset Management

| Table | Description | Typical keys |
|-------|-------------|--------------|
| PS_ASSET | Asset master | BUSINESS_UNIT_AM (or BUSINESS_UNIT), ASSET_ID |

## PeopleTools (all modules)

| Table | Use |
|-------|-----|
| PSRECFIELD / PSRECDEFN | Record layout |
| PSKEYDEFN | Keys and indexes |
| PSXLATITEM | Translate values |
