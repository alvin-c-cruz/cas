"""Posting-fidelity invariant: every posted JE's legs must tie to its document header.

`Dr == Cr` proves nothing. Each of the four posting documents books a residual leg
(cash for CDV/CRV, the first expense/revenue line for AP/SI) that silently absorbs any
per-leg error and leaves the entry balanced. Two live money bugs shipped behind exactly
that: the CRV WHT override (backlog 83) and the AP pure-override empty-bucket gap.

So this suite asserts the NON-PLUG legs against the header totals, across
{SI, AP, CDV, CRV} x {none, vat_override, wt_override, both} = 16 cells:

  1. WHT legs sum   == header WHT total   (on the correct side)
  2. VAT legs sum   == header VAT total
  3. counterparty leg (AR / AP / cash) == header total_amount
  4. income/expense leg == subtotal - header VAT

(3) and (4) together pin BOTH plug locations: CDV/CRV absorb into cash, AP/SI absorb
into the first expense/revenue line. An error can hide in neither.

Multi-bucket splitting (per-ATC WHT, per-category VAT) is covered by
test_ap_wht_buckets.py / test_cdv_wht_buckets.py and the VAT-bucket suites; each cell
here deliberately uses ONE VAT category and ONE ATC so the bucket sums degenerate to
the header comparison.

Fixture trap: SI/CDV/CRV `calculate_totals()` honors the override flags, so overrides
are applied and totals re-derived. **AP's ignores them entirely** and always overwrites
from the lines (accounts_payable/models.py:130), so for AP the override fields are set
AFTER calculate_totals() and total_amount is recomputed by hand -- mirroring
`_apply_ap_overrides` (accounts_payable/views.py).
"""
from datetime import date
from decimal import Decimal

import pytest

from app import db
from app.accounts.models import Account
from app.accounts_payable.models import AccountsPayable, AccountsPayableItem
from app.cash_disbursements.models import CashDisbursementVoucher, CDVExpenseLine
from app.cash_receipts.models import CashReceiptVoucher, CRVRevenueLine
from app.customers.models import Customer
from app.sales_invoices.models import SalesInvoice, SalesInvoiceItem
from app.sales_vat_categories.models import SalesVATCategory
from app.vat_categories.models import VATCategory
from app.vendors.models import Vendor
from app.withholding_tax.models import WithholdingTax

# Marked for all four documents so a change to ANY posting view selects this suite
# through /guard's marker-based e2e/module gate.
pytestmark = [
    pytest.mark.integration,
    pytest.mark.sales_invoices,
    pytest.mark.accounts_payable,
    pytest.mark.cash_disbursements,
    pytest.mark.cash_receipts,
]

# One VAT-inclusive line, everywhere.
GROSS = Decimal('1120.00')
VAT = Decimal('120.00')       # 12% extracted from GROSS
NET = Decimal('1000.00')      # GROSS - VAT
WHT = Decimal('100.00')       # 10% of NET

VAT_OVERRIDE = Decimal('130.00')
WHT_OVERRIDE = Decimal('75.00')

OVERRIDE_MODES = ['none', 'vat_override', 'wt_override', 'both']
DOCUMENTS = ['si', 'ap', 'cdv', 'crv']

# Distinct codes so a leg can be identified by account.
AR, CWT, AP_TRADE, WHT_PAYABLE = '10201', '10212', '20101', '20301'
OUTPUT_VAT, INPUT_VAT = '20201', '10501'
CASH, REVENUE, EXPENSE = '1001', '4001', '5001'


def _acct(code, name, account_type='Asset', normal_balance='Debit'):
    a = Account(code=code, name=name, account_type=account_type,
                classification='Current', normal_balance=normal_balance, is_active=True)
    db.session.add(a)
    db.session.flush()
    return a


def _expected(mode):
    """(header VAT, header WHT) for an override mode."""
    return (
        VAT_OVERRIDE if mode in ('vat_override', 'both') else VAT,
        WHT_OVERRIDE if mode in ('wt_override', 'both') else WHT,
    )


def _legs(je):
    """{account_code: (debit, credit)} for the posted entry."""
    out = {}
    for line in je.lines:
        d, c = out.get(line.account.code, (Decimal('0.00'), Decimal('0.00')))
        out[line.account.code] = (d + line.debit_amount, c + line.credit_amount)
    return out


# --- per-document builders -------------------------------------------------------
#
# Each returns (posted_je, header_vat, header_wht, header_total_amount).


def _build_si(branch, user, mode):
    from app.sales_invoices.views import _post_invoice_je

    _acct(AR, 'Accounts Receivable - Trade')
    _acct(CWT, 'Creditable Withholding Tax')
    out_vat = _acct(OUTPUT_VAT, 'Output VAT', 'Liability', 'Credit')
    revenue = _acct(REVENUE, 'Sales Revenue', 'Income', 'Credit')
    from tests.conftest import assign_control_accounts
    assign_control_accounts(db.session)
    db.session.add(SalesVATCategory(code='V12', name='VATable 12%', rate=Decimal('12.00'),
                                    transaction_nature='regular',
                                    output_vat_account_id=out_vat.id, is_active=True))
    wht = WithholdingTax(code='WC158', name='WC158', rate=Decimal('10.00'), is_active=True)
    db.session.add(wht)
    customer = Customer(code='CINV', name='Invariant Customer', is_active=True)
    db.session.add(customer)
    db.session.flush()

    inv = SalesInvoice(
        branch_id=branch.id, invoice_number='SI-INV-0001', invoice_date=date(2099, 1, 5),
        due_date=date(2099, 2, 5), customer_id=customer.id, customer_name=customer.name,
        notes='', status='draft', created_by_id=user.id,
        subtotal=Decimal('0.00'), vat_amount=Decimal('0.00'),
        total_before_wt=Decimal('0.00'), withholding_tax_amount=Decimal('0.00'),
        total_amount=Decimal('0.00'), amount_paid=Decimal('0.00'), balance=Decimal('0.00'),
    )
    db.session.add(inv)
    db.session.flush()
    db.session.add(SalesInvoiceItem(
        invoice_id=inv.id, line_number=1, description='Service',
        amount=GROSS, line_total=GROSS, vat_category='V12', vat_rate=Decimal('12.00'),
        vat_amount=VAT, account_id=revenue.id, wt_id=wht.id, wt_amount=WHT))
    db.session.flush()
    db.session.refresh(inv)

    exp_vat, exp_wht = _expected(mode)
    inv.vat_override = mode in ('vat_override', 'both')
    inv.wt_override = mode in ('wt_override', 'both')
    inv.vat_amount = exp_vat
    inv.withholding_tax_amount = exp_wht
    inv.calculate_totals()          # honors the flags; re-derives total_amount
    db.session.flush()

    je = _post_invoice_je(inv, user.id)
    db.session.flush()
    return je, inv.vat_amount, inv.withholding_tax_amount, inv.total_amount


def _build_ap(branch, user, mode):
    from app.accounts_payable.views import _post_ap_je

    _acct(AP_TRADE, 'Accounts Payable - Trade', 'Liability', 'Credit')
    _acct(WHT_PAYABLE, 'WHT Payable - Expanded', 'Liability', 'Credit')
    in_vat = _acct(INPUT_VAT, 'Input VAT')
    expense = _acct(EXPENSE, 'Operating Expense', 'Expense', 'Debit')
    db.session.add(VATCategory(code='V12P', name='Input 12%', rate=Decimal('12.00'),
                               input_vat_account_id=in_vat.id, is_active=True))
    wht = WithholdingTax(code='WC158', name='WC158', rate=Decimal('10.00'), is_active=True)
    db.session.add(wht)
    vendor = Vendor(code='VINV', name='Invariant Vendor', is_active=True)
    db.session.add(vendor)
    db.session.flush()

    ap = AccountsPayable(
        branch_id=branch.id, ap_number='AP-INV-0001', ap_date=date(2099, 1, 5),
        due_date=date(2099, 2, 5), vendor_id=vendor.id, vendor_name=vendor.name,
        notes='', status='draft', created_by_id=user.id,
        subtotal=Decimal('0.00'), vat_amount=Decimal('0.00'),
        total_before_wt=Decimal('0.00'), withholding_tax_amount=Decimal('0.00'),
        total_amount=Decimal('0.00'), amount_paid=Decimal('0.00'), balance=Decimal('0.00'),
    )
    db.session.add(ap)
    db.session.flush()
    db.session.add(AccountsPayableItem(
        ap_id=ap.id, line_number=1, description='Service',
        amount=GROSS, line_total=GROSS, vat_category='V12P', vat_rate=Decimal('12.00'),
        vat_amount=VAT, account_id=expense.id, wt_id=wht.id, wt_amount=WHT))
    db.session.flush()
    db.session.refresh(ap)

    ap.calculate_totals()           # IGNORES the override flags -- overwrites from lines
    exp_vat, exp_wht = _expected(mode)
    ap.vat_override = mode in ('vat_override', 'both')
    ap.wt_override = mode in ('wt_override', 'both')
    ap.vat_amount = exp_vat         # ...so apply overrides AFTER, like _apply_ap_overrides
    ap.withholding_tax_amount = exp_wht
    ap.total_amount = ap.subtotal - exp_wht
    ap.balance = ap.total_amount
    db.session.flush()

    je = _post_ap_je(ap, user.id)
    db.session.flush()
    return je, ap.vat_amount, ap.withholding_tax_amount, ap.total_amount


def _build_cdv(branch, user, mode):
    from app.cash_disbursements.views import _post_cdv_je

    _acct(AP_TRADE, 'Accounts Payable - Trade', 'Liability', 'Credit')
    _acct(WHT_PAYABLE, 'WHT Payable - Expanded', 'Liability', 'Credit')
    in_vat = _acct(INPUT_VAT, 'Input VAT')
    cash = _acct(CASH, 'Cash on Hand')
    expense = _acct(EXPENSE, 'Operating Expense', 'Expense', 'Debit')
    db.session.add(VATCategory(code='V12P', name='Input 12%', rate=Decimal('12.00'),
                               input_vat_account_id=in_vat.id, is_active=True))
    wht = WithholdingTax(code='WC158', name='WC158', rate=Decimal('10.00'), is_active=True)
    db.session.add(wht)
    vendor = Vendor(code='VINV', name='Invariant Vendor', is_active=True)
    db.session.add(vendor)
    db.session.flush()

    cdv = CashDisbursementVoucher(
        branch_id=branch.id, cdv_number='CD-INV-0001', cdv_date=date(2099, 1, 5),
        vendor_id=vendor.id, vendor_name=vendor.name, payment_method='cash',
        cash_account_id=cash.id, notes='', status='draft',
        total_ap_applied=Decimal('0.00'), total_expense=Decimal('0.00'),
        total_vat=Decimal('0.00'), total_wt=Decimal('0.00'), total_amount=Decimal('0.00'),
    )
    db.session.add(cdv)
    db.session.flush()
    db.session.add(CDVExpenseLine(
        cdv_id=cdv.id, line_number=1, description='Service',
        amount=GROSS, line_total=GROSS, vat_category='V12P', vat_rate=Decimal('12.00'),
        vat_amount=VAT, account_id=expense.id, wt_id=wht.id, wt_amount=WHT))
    db.session.flush()
    db.session.refresh(cdv)

    exp_vat, exp_wht = _expected(mode)
    cdv.vat_override = mode in ('vat_override', 'both')
    cdv.wt_override = mode in ('wt_override', 'both')
    cdv.total_vat = exp_vat
    cdv.total_wt = exp_wht
    cdv.calculate_totals()          # honors the flags
    db.session.flush()

    je = _post_cdv_je(cdv, user.id)
    db.session.flush()
    return je, cdv.total_vat, cdv.total_wt, cdv.total_amount


def _build_crv(branch, user, mode):
    from app.cash_receipts.views import _post_crv_je

    _acct(AR, 'Accounts Receivable - Trade')
    _acct(CWT, 'Creditable Withholding Tax')
    out_vat = _acct(OUTPUT_VAT, 'Output VAT', 'Liability', 'Credit')
    cash = _acct(CASH, 'Cash on Hand')
    revenue = _acct(REVENUE, 'Sales Revenue', 'Income', 'Credit')
    from tests.conftest import assign_control_accounts
    assign_control_accounts(db.session)
    db.session.add(SalesVATCategory(code='V12', name='VATable 12%', rate=Decimal('12.00'),
                                    transaction_nature='regular',
                                    output_vat_account_id=out_vat.id, is_active=True))
    wht = WithholdingTax(code='WC158', name='WC158', rate=Decimal('10.00'), is_active=True)
    db.session.add(wht)
    customer = Customer(code='CINV', name='Invariant Customer', is_active=True)
    db.session.add(customer)
    db.session.flush()

    crv = CashReceiptVoucher(
        branch_id=branch.id, crv_number='CR-INV-0001', crv_date=date(2099, 1, 5),
        customer_id=customer.id, customer_name=customer.name, payment_method='cash',
        cash_account_id=cash.id, notes='', status='draft',
        total_ar_applied=Decimal('0.00'), total_revenue=Decimal('0.00'),
        total_vat=Decimal('0.00'), total_wt=Decimal('0.00'), total_amount=Decimal('0.00'),
    )
    db.session.add(crv)
    db.session.flush()
    db.session.add(CRVRevenueLine(
        crv_id=crv.id, line_number=1, description='Service',
        amount=GROSS, line_total=GROSS, vat_category='V12', vat_rate=Decimal('12.00'),
        vat_amount=VAT, account_id=revenue.id, wt_id=wht.id, wt_amount=WHT))
    db.session.flush()
    db.session.refresh(crv)

    exp_vat, exp_wht = _expected(mode)
    crv.vat_override = mode in ('vat_override', 'both')
    crv.wt_override = mode in ('wt_override', 'both')
    crv.total_vat = exp_vat
    crv.total_wt = exp_wht
    crv.calculate_totals()          # honors the flags
    db.session.flush()

    je = _post_crv_je(crv, user.id)
    db.session.flush()
    return je, crv.total_vat, crv.total_wt, crv.total_amount


# doc -> (builder, wht account code, wht side, vat account code, vat side,
#         counterparty code, counterparty side, income/expense code, ie side)
SPEC = {
    'si':  (_build_si,  CWT, 'debit',  OUTPUT_VAT, 'credit',
            AR, 'debit', REVENUE, 'credit'),
    'ap':  (_build_ap,  WHT_PAYABLE, 'credit', INPUT_VAT, 'debit',
            AP_TRADE, 'credit', EXPENSE, 'debit'),
    'cdv': (_build_cdv, WHT_PAYABLE, 'credit', INPUT_VAT, 'debit',
            CASH, 'credit', EXPENSE, 'debit'),
    'crv': (_build_crv, CWT, 'debit', OUTPUT_VAT, 'credit',
            CASH, 'debit', REVENUE, 'credit'),
}


def _side(legs, code, side):
    debit, credit = legs.get(code, (Decimal('0.00'), Decimal('0.00')))
    return debit if side == 'debit' else credit


@pytest.mark.parametrize('mode', OVERRIDE_MODES)
@pytest.mark.parametrize('doc', DOCUMENTS)
def test_posted_je_legs_tie_to_document_header(doc, mode, db_session, admin_user, main_branch):
    build, wht_code, wht_side, vat_code, vat_side, cp_code, cp_side, ie_code, ie_side = SPEC[doc]

    je, header_vat, header_wht, header_total = build(main_branch, admin_user, mode)
    legs = _legs(je)

    assert _side(legs, wht_code, wht_side) == header_wht, (
        f'{doc}/{mode}: WHT leg on {wht_code} != header WHT {header_wht}')

    assert _side(legs, vat_code, vat_side) == header_vat, (
        f'{doc}/{mode}: VAT leg on {vat_code} != header VAT {header_vat}')

    assert _side(legs, cp_code, cp_side) == header_total, (
        f'{doc}/{mode}: counterparty leg on {cp_code} != header total_amount {header_total}')

    assert _side(legs, ie_code, ie_side) == GROSS - header_vat, (
        f'{doc}/{mode}: income/expense leg on {ie_code} != subtotal - header VAT')

    assert je.is_balanced, f'{doc}/{mode}: JE does not balance'
