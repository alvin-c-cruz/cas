# APV Demo Data — Design Spec

## Goal

Seed 30 AP voucher entries spanning April–June 2026 via the browser UI (Playwright automation). Purpose: client demos and UI/UX testing.

## Constraints

- Use existing 9 vendors from `seed_minimal` (no new vendors).
- Create through the live app at `http://127.0.0.1:5000` — exercises the actual forms.
- Admin account (`admin` / `admin123`) performs all actions.
- `partially_paid` and `paid` statuses are skipped — receipts module is under construction.
- The 2 leftover Run 2 bills (AP-2026-06-0001 cancelled, AP-2026-06-0002 voided) remain; new bills continue the sequence starting at AP-2026-04-0001 (bills are backdated to April/May/June).

## Status Mix

| Status | Count |
|--------|-------|
| Posted (outstanding) | 22 |
| Draft | 4 |
| Cancelled | 2 |
| Voided | 2 |
| **Total** | **30** |

## Vendor Reference

| Code | Name | VAT | WHT |
|------|------|-----|-----|
| MOS | Mega Office Supplies Co. | V12DG (12%) | WC158 (1%) |
| VND001 | MOS Trading Corp | V12DG (12%) | WC158 (1%) |
| VND002 | Sunshine Property Mgmt | V12DG (12%) | WC100 (5%) |
| VND003 | TechServe IT Solutions | V12SV (12%) | WC160 (2%) |
| VND004 | ABC Law and Associates | V12SV (12%) | WC160 (2%) |
| VND005 | Green Power Electric Co | VEX (0%) | None |
| VND006 | PhilPost Courier | INV (0%) | None |
| VND007 | ZeroExport Trading | V0 (0%) | None |
| VND008 | Capitol Office Supply | V12DG (12%) | WC158 (1%) |

## The 30 Bills

All bills: `branch_id = Main Branch`, `payment_terms = Net 30`, single line item per bill, `due_date = bill_date + 30 days`.

### April 2026

| # | Bill Date | Due Date | Vendor | Description | Amount | Ref | Status |
|---|-----------|----------|--------|-------------|--------|-----|--------|
| 1 | 2026-04-01 | 2026-05-01 | VND002 | Office rent - April 2026 | ₱45,000 | PO-APR-001 | Posted |
| 2 | 2026-04-05 | 2026-05-05 | VND005 | Electricity - April 2026 | ₱8,500 | PO-APR-002 | Posted |
| 3 | 2026-04-08 | 2026-05-08 | MOS | Office supplies restock | ₱12,300 | PO-APR-003 | Posted |
| 4 | 2026-04-10 | 2026-05-10 | VND003 | Quarterly IT maintenance | ₱35,000 | PO-APR-004 | Posted |
| 5 | 2026-04-12 | 2026-05-12 | VND006 | Document delivery services | ₱2,800 | PO-APR-005 | Posted |
| 6 | 2026-04-15 | 2026-05-15 | VND004 | Legal retainer fee - April | ₱25,000 | PO-APR-006 | Posted |
| 7 | 2026-04-18 | 2026-05-18 | VND001 | Paper and printing supplies | ₱6,750 | PO-APR-007 | Posted |
| 8 | 2026-04-22 | 2026-05-22 | VND003 | Software license renewal | ₱18,000 | PO-APR-008 | Posted |
| 9 | 2026-04-25 | 2026-05-25 | VND008 | Toner cartridges and accessories | ₱9,200 | PO-APR-009 | **Draft** |
| 10 | 2026-04-28 | 2026-05-28 | VND007 | Export packaging materials | ₱5,500 | PO-APR-010 | **Voided** (reason: "Wrong vendor — reissued under correct vendor") |

### May 2026

| # | Bill Date | Due Date | Vendor | Description | Amount | Ref | Status |
|---|-----------|----------|--------|-------------|--------|-----|--------|
| 11 | 2026-05-01 | 2026-05-31 | VND002 | Office rent - May 2026 | ₱45,000 | PO-MAY-001 | Posted |
| 12 | 2026-05-05 | 2026-06-04 | VND005 | Electricity - May 2026 | ₱9,200 | PO-MAY-002 | Posted |
| 13 | 2026-05-07 | 2026-06-06 | MOS | Stationery and office supplies | ₱7,800 | PO-MAY-003 | Posted |
| 14 | 2026-05-10 | 2026-06-09 | VND004 | Contract review services | ₱15,000 | PO-MAY-004 | Posted |
| 15 | 2026-05-12 | 2026-06-11 | VND006 | Courier and delivery | ₱3,100 | PO-MAY-005 | Posted |
| 16 | 2026-05-15 | 2026-06-14 | VND003 | Network infrastructure repair | ₱28,500 | PO-MAY-006 | Posted |
| 17 | 2026-05-18 | 2026-06-17 | VND001 | Printer paper bulk order | ₱11,200 | PO-MAY-007 | **Cancelled** (reason: "Cancelled for testing purposes - duplicate order") |
| 18 | 2026-05-20 | 2026-06-19 | VND008 | Filing cabinets (2 units) | ₱22,000 | PO-MAY-008 | Posted |
| 19 | 2026-05-22 | 2026-06-21 | VND007 | Shipping and packaging materials | ₱4,300 | PO-MAY-009 | **Draft** |
| 20 | 2026-05-28 | 2026-06-27 | VND002 | Parking fee adjustment - May | ₱5,000 | PO-MAY-010 | **Voided** (reason: "Incorrect amount — reissued with correct figure") |

### June 2026

| # | Bill Date | Due Date | Vendor | Description | Amount | Ref | Status |
|---|-----------|----------|--------|-------------|--------|-----|--------|
| 21 | 2026-06-01 | 2026-07-01 | VND002 | Office rent - June 2026 | ₱45,000 | PO-JUN-001 | Posted |
| 22 | 2026-06-05 | 2026-07-05 | VND005 | Electricity - June 2026 | ₱10,100 | PO-JUN-002 | Posted |
| 23 | 2026-06-07 | 2026-07-07 | MOS | Office supplies - June restock | ₱14,500 | PO-JUN-003 | Posted |
| 24 | 2026-06-10 | 2026-07-10 | VND003 | Server maintenance and updates | ₱42,000 | PO-JUN-004 | Posted |
| 25 | 2026-06-12 | 2026-07-12 | VND004 | Legal and compliance review | ₱30,000 | PO-JUN-005 | Posted |
| 26 | 2026-06-14 | 2026-07-14 | VND006 | Courier services - June | ₱2,500 | PO-JUN-006 | Posted |
| 27 | 2026-06-16 | 2026-07-16 | VND001 | Office stationery order | ₱8,900 | PO-JUN-007 | **Cancelled** (reason: "Cancelled for testing purposes - wrong items ordered") |
| 28 | 2026-06-18 | 2026-07-18 | VND008 | Office chairs (5 units) | ₱35,000 | PO-JUN-008 | Posted |
| 29 | 2026-06-20 | 2026-07-20 | VND003 | IT consulting - Q2 review | ₱55,000 | PO-JUN-009 | **Draft** |
| 30 | 2026-06-25 | 2026-07-25 | VND007 | Export materials - June batch | ₱6,800 | PO-JUN-010 | **Draft** |

## Execution Approach

**Actor:** Admin user via Playwright MCP browser automation.

**Per-bill workflow:**
1. Navigate to `/purchase-bills/create`
2. Select vendor → set bill_date, due_date, reference
3. Set line item: description, amount, VAT category (from vendor default), account (first available expense leaf), WHT (from vendor default)
4. Click Save Draft → verify redirect to detail page
5. **If Posted:** click Post APV trigger → confirm in modal
6. **If Voided:** click Void APV trigger → enter void reason → confirm
7. **If Cancelled:** click Post APV first → then Cancel APV trigger → enter cancel reason → confirm

**Expense account:** Use the first available leaf account under Operating Expenses (60101).

**Vendor invoice numbers:** Omitted (left blank) for simplicity — these are internal POs.

## Expected Dashboard State After Seeding

- Outstanding payables: 22 posted bills totalling ≈ ₱530,450
- AP Aging: spread across April (overdue), May (overdue/current), June (current)
- List view: 30 entries with varied statuses, filterable by status

## Out of Scope

- Multiple line items per bill (single line item keeps automation tractable)
- Vendor invoice numbers (left blank)
- Attachments
- Payment entries (receipts module under construction)
