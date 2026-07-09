"""Normalized reader over every VAT-bearing document line.

Four tables carry VAT: sales_invoice_items, crv_revenue_lines (sales side) and
accounts_payable_items, cdv_expense_lines (purchase side). compute_vat_position()
nets GL account balances, which include all four -- so any report that reads only
two will diverge from the settlement the moment a CRV or CDV books VAT.

Every VAT report folds over this one stream. A fifth source is one edit here,
not four edits scattered across bir.py.

Pure-read. Returns plain namedtuples, never ORM objects, so callers may cache
results without DetachedInstanceError exposure.
"""
from collections import namedtuple
from decimal import Decimal

from sqlalchemy.orm import selectinload

from app import db
from app.accounts_payable.models import AccountsPayable
from app.cash_disbursements.models import CashDisbursementVoucher
from app.cash_receipts.models import CashReceiptVoucher
from app.sales_invoices.models import SalesInvoice
from app.vat_categories.models import PURCHASE_NATURES

UNCLASSIFIED = 'unclassified'

SALES_BUCKET_BY_NATURE = {
    'regular': 'vatable',
    'zero_export': 'zero_rated',
    'zero_other': 'zero_rated',
    'exempt': 'exempt',
    'government': 'government',
    UNCLASSIFIED: UNCLASSIFIED,
}

PURCHASE_BUCKET_BY_NATURE = {n: n for n in PURCHASE_NATURES}
PURCHASE_BUCKET_BY_NATURE[UNCLASSIFIED] = UNCLASSIFIED

# Copied verbatim from bir.py:40 / bir.py:113 -- do not diverge.
SI_STATUSES = ('posted', 'paid', 'partially_paid')
AP_STATUSES = ('posted', 'paid', 'partially_paid')

VatLine = namedtuple('VatLine', [
    'side', 'source', 'doc_id', 'doc_no', 'doc_date',
    'partner_id', 'partner_name', 'partner_tin',
    'nature', 'base', 'vat_amount',
])


def _d(x):
    return Decimal(str(x or 0))


def _emit(side, source, doc_id, doc_no, doc_date, pid, pname, ptin, line):
    vat = _d(line.vat_amount)
    return VatLine(
        side=side, source=source, doc_id=doc_id, doc_no=doc_no, doc_date=doc_date,
        partner_id=pid, partner_name=pname, partner_tin=ptin or '',
        nature=line.vat_nature or UNCLASSIFIED,
        base=_d(line.amount) - vat,
        vat_amount=vat,
    )


def _sales(date_from, date_to, branch_id):
    out = []

    q = db.session.query(SalesInvoice).options(
        selectinload(SalesInvoice.line_items)).filter(
        SalesInvoice.invoice_date >= date_from,
        SalesInvoice.invoice_date <= date_to,
        SalesInvoice.status.in_(SI_STATUSES))
    if branch_id:
        q = q.filter(SalesInvoice.branch_id == branch_id)
    for inv in q.all():
        for line in inv.line_items:
            out.append(_emit('sales', 'sales_invoice', inv.id, inv.invoice_number,
                             inv.invoice_date, inv.customer_id, inv.customer_name,
                             inv.customer_tin, line))

    q = db.session.query(CashReceiptVoucher).options(
        selectinload(CashReceiptVoucher.revenue_lines)).filter(
        CashReceiptVoucher.crv_date >= date_from,
        CashReceiptVoucher.crv_date <= date_to,
        CashReceiptVoucher.status == 'posted')
    if branch_id:
        q = q.filter(CashReceiptVoucher.branch_id == branch_id)
    for crv in q.all():
        for line in crv.revenue_lines:
            out.append(_emit('sales', 'cash_receipt', crv.id, crv.crv_number,
                             crv.crv_date, crv.customer_id, crv.customer_name,
                             crv.customer_tin, line))
    return out


def _purchases(date_from, date_to, branch_id):
    out = []

    q = db.session.query(AccountsPayable).options(
        selectinload(AccountsPayable.line_items)).filter(
        AccountsPayable.ap_date >= date_from,
        AccountsPayable.ap_date <= date_to,
        AccountsPayable.status.in_(AP_STATUSES))
    if branch_id:
        q = q.filter(AccountsPayable.branch_id == branch_id)
    for bill in q.all():
        for line in bill.line_items:
            out.append(_emit('purchases', 'accounts_payable', bill.id,
                             bill.vendor_invoice_number, bill.ap_date,
                             bill.vendor_id, bill.vendor_name, bill.vendor_tin, line))

    q = db.session.query(CashDisbursementVoucher).options(
        selectinload(CashDisbursementVoucher.expense_lines)).filter(
        CashDisbursementVoucher.cdv_date >= date_from,
        CashDisbursementVoucher.cdv_date <= date_to,
        CashDisbursementVoucher.status == 'posted')
    if branch_id:
        q = q.filter(CashDisbursementVoucher.branch_id == branch_id)
    for cdv in q.all():
        for line in cdv.expense_lines:
            out.append(_emit('purchases', 'cash_disbursement', cdv.id, cdv.cdv_number,
                             cdv.cdv_date, cdv.vendor_id, cdv.vendor_name,
                             cdv.vendor_tin, line))
    return out


def vat_lines(date_from, date_to, side, branch_id=None):
    """Every VAT-bearing posted line in [date_from, date_to], both ends inclusive.

    side: 'sales' or 'purchases'. branch_id=None means company-wide (per-TIN),
    which is what BIR VAT filing requires; SLS/SLP pass a branch.
    """
    if side == 'sales':
        return _sales(date_from, date_to, branch_id)
    if side == 'purchases':
        return _purchases(date_from, date_to, branch_id)
    raise ValueError(f"vat_lines(): side must be 'sales' or 'purchases', got {side!r}")
