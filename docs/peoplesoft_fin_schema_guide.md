# PeopleSoft Financials — Schema Guide (FSCM-oriented)

Use **`describe_table`** and **`list_tables(module='...')`** for your exact install.

## General Ledger (GL)

| Table | Description | Typical keys |
|-------|-------------|--------------|
| PS_LEDGER | Posted ledger balances / activity | BU, LEDGER, ACCOUNT, FISCAL_YEAR, ACCOUNTING_PERIOD, … |
| PS_JRNL_HEADER | Journal header | BUSINESS_UNIT, JOURNAL_ID |
| PS_JRNL_LN | Journal lines (metadata record: JRNL_LINE) | BUSINESS_UNIT, JOURNAL_ID, JOURNAL_LINE |
| PS_GL_ACCOUNT_TBL | Chart of accounts | SETID, ACCOUNT, EFFDT |
| PS_FIN_OPEN_PERIOD | Open periods (if used) | BUSINESS_UNIT, LEDGER_GROUP, FISCAL_YEAR, ACCOUNTING_PERIOD |

## Currency / Exchange Rates

| Table | Description | Typical keys |
|-------|-------------|--------------|
| PS_RT_RATE_TBL | Cross-currency exchange rates (effective-dated) | RT_RATE_INDEX, FROM_CUR, TO_CUR, RT_TYPE, EFFDT |

Conversion formula: `amount * RATE_MULT / RATE_DIV`. Common RT_TYPE values: CURR, SPOT, AVGMO, AVGYR, CRRNT. Default RT_RATE_INDEX is `MARKET`.

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

## PeopleTools System Tables

### Record/Field Metadata
| Table | Description | Key Fields |
|-------|-------------|------------|
| PSRECDEFN | Record definitions | RECNAME |
| PSRECFIELD | Fields in records | RECNAME, FIELDNAME |
| PSDBFIELD | Field properties | FIELDNAME |
| PSKEYDEFN | Index/key definitions | RECNAME, INDEXID, FIELDNAME |
| PSINDEXDEFN | Index properties | RECNAME, INDEXID |

### PeopleCode
| Table | Description | Key Fields |
|-------|-------------|------------|
| PSPCMPROG | PeopleCode metadata | OBJECTVALUE1, OBJECTVALUE2, OBJECTVALUE3 |
| PSPCMTXT | PeopleCode source (CLOB) | OBJECTVALUE1, OBJECTVALUE2, OBJECTVALUE3 |
| PSPCMNAME | PeopleCode references | (various) |

### Pages & Components
| Table | Description | Key Fields |
|-------|-------------|------------|
| PSPNLDEFN | Page definitions | PNLNAME |
| PSPNLFIELD | Fields on pages | PNLNAME, FIELDNUM |
| PSPNLGRPDEFN | Component definitions | PNLGRPNAME, MARKET |
| PSPNLGROUP | Pages in components | PNLGRPNAME, PNLNAME |
| PSMENUDEFN | Menu definitions | MENUNAME |
| PSMENUITEM | Menu items | MENUNAME, BARNAME, ITEMNAME |

### Security
| Table | Description | Key Fields |
|-------|-------------|------------|
| PSOPRDEFN | User definitions | OPRID |
| PSROLEDEFN | Role definitions | ROLENAME |
| PSROLEUSER | User-role mapping | ROLEUSER, ROLENAME |
| PSROLECLASS | Role-permission mapping | ROLENAME, CLASSID |
| PSCLASSDEFN | Permission list definitions | CLASSID |
| PSAUTHITEM | Component authorization | CLASSID, MENUNAME, BARITEMNAME |

### Translate Values
| Table | Description | Key Fields |
|-------|-------------|------------|
| PSXLATDEFN | Translate field definitions | FIELDNAME |
| PSXLATITEM | Translate values | FIELDNAME, FIELDVALUE, EFFDT |
| PSXLATITEMLANG | Translated descriptions | FIELDNAME, FIELDVALUE, LANGUAGE_CD |

### Application Engine
| Table | Description | Key Fields |
|-------|-------------|------------|
| PSAEAPPLDEFN | AE program definitions | AE_APPLID |
| PSAESECTDEFN | AE section definitions | AE_APPLID, AE_SECTION |
| PSAESTEPDEFN | AE step definitions | AE_APPLID, AE_SECTION, AE_STEP |
| PSAESQLDEFN | AE SQL definitions | AE_APPLID, AE_SECTION, AE_STEP |
| PSAESTEPMSGDEFN | AE PeopleCode | AE_APPLID, AE_SECTION, AE_STEP |

### Process Scheduler
| Table | Description | Key Fields |
|-------|-------------|------------|
| PS_PRCSDEFN | Process definitions | PRCSTYPE, PRCSNAME |
| PSPRCSRQST | Process requests | PRCSINSTANCE |
| PS_PRCSRUNCNTL | Run control records | OPRID, RUN_CNTL_ID |
| PSPRCSPARMS | Process parameters | PRCSINSTANCE |

### Integration Broker
| Table | Description | Key Fields |
|-------|-------------|------------|
| PSOPERATION | Service operations | IB_OPERATIONNAME |
| PSMSGDEFN | Message definitions | MSGNAME, VERSION |
| PSMSGPARTDEFN | Message parts | MSGNAME, PARTNAME |
| PSMSGROUT | Message routing | IB_OPERATIONNAME |
| PSNODE | Node definitions | MSGNODENAME |

### Query Manager
| Table | Description | Key Fields |
|-------|-------------|------------|
| PSQRYDEFN | Query definitions | QRYNAME |
| PSQRYRECORD | Query records | QRYNAME, RECNAME |
| PSQRYFIELD | Query fields | QRYNAME, FIELDNUM |
| PSQRYCRITERIA | Query criteria | QRYNAME, CRITERIANUM |
| PSQRYACCLST | Query access | QRYNAME, CLASSID |
