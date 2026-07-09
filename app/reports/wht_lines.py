"""Normalized reader over every withholding-bearing document line.

Payor side (we withheld from a vendor): accounts_payable_items + cdv_expense_lines
  -> BIR 2307 issued, 1601-EQ QAP.
Payee side (a customer withheld from us): sales_invoice_items + crv_revenue_lines
  -> SAWT reconciliation against the certificates-received register.

Today's get_alphalist_of_payees() reads accounts_payable_items only, so a vendor
paid by cash disbursement is invisible to the QAP. This module closes that.

tax_type filtering is by QUERY, not convention: final tax is not creditable and
must never reach a 2307, a QAP, or a SAWT.

Pure-read. Returns plain namedtuples, never ORM objects, so callers may cache
results without DetachedInstanceError exposure.
"""
from collections import namedtuple
from decimal import Decimal

from app import db
from app.accounts_payable.models import AccountsPayable, AccountsPayableItem
from app.cash_disbursements.models import CashDisbursementVoucher, CDVExpenseLine
from app.cash_receipts.models import CashReceiptVoucher, CRVRevenueLine
from app.sales_invoices.models import SalesInvoice, SalesInvoiceItem
from app.reports.vat_lines import AP_STATUSES, SI_STATUSES

WhtLine = namedtuple('WhtLine', [
    'side', 'source', 'doc_no', 'doc_date',
    'partner_id', 'partner_name', 'partner_tin',
    'atc_code', 'atc_rate', 'tax_type',
    'income_payment', 'tax_withheld',
])


def _d(x):
    return Decimal(str(x or 0))


def _emit(side, source, doc_no, doc_date, pid, pname, ptin, line):
    wt = line.withholding_tax
    return WhtLine(
        side=side, source=source, doc_no=doc_no, doc_date=doc_date,
        partner_id=pid, partner_name=pname, partner_tin=ptin or '',
        atc_code=wt.code, atc_rate=_d(line.wt_rate), tax_type=wt.tax_type,
        income_payment=_d(line.amount) - _d(line.vat_amount),
        tax_withheld=_d(line.wt_amount),
    )


def _collect(header_model, line_attr, date_col, status_filter, doc_no_attr,
             partner_id_attr, partner_name_attr, partner_tin_attr,
             side, source, date_from, date_to, branch_id):
    q = db.session.query(header_model).filter(
        date_col >= date_from, date_col <= date_to, status_filter)
    if branch_id:
        q = q.filter(header_model.branch_id == branch_id)
    out = []
    for doc in q.all():
        for line in getattr(doc, line_attr):
            if line.wt_id is None:
                continue
            out.append(_emit(side, source, getattr(doc, doc_no_attr),
                             getattr(doc, date_col.key),
                             getattr(doc, partner_id_attr),
                             getattr(doc, partner_name_attr),
                             getattr(doc, partner_tin_attr), line))
    return out


def wht_lines(date_from, date_to, side, tax_type=None, branch_id=None):
    """Every withholding-bearing posted line in [date_from, date_to], inclusive.

    side='payor' -> AP + CDV (vendor).  side='payee' -> SI + CRV (customer).
    tax_type=None returns both regimes; pass 'expanded' for creditable surfaces.
    """
    if side == 'payor':
        rows = (
            _collect(AccountsPayable, 'line_items', AccountsPayable.ap_date,
                     AccountsPayable.status.in_(AP_STATUSES),
                     'vendor_invoice_number', 'vendor_id', 'vendor_name', 'vendor_tin',
                     side, 'accounts_payable', date_from, date_to, branch_id)
            + _collect(CashDisbursementVoucher, 'expense_lines',
                       CashDisbursementVoucher.cdv_date,
                       CashDisbursementVoucher.status == 'posted',
                       'cdv_number', 'vendor_id', 'vendor_name', 'vendor_tin',
                       side, 'cash_disbursement', date_from, date_to, branch_id)
        )
    elif side == 'payee':
        rows = (
            _collect(SalesInvoice, 'line_items', SalesInvoice.invoice_date,
                     SalesInvoice.status.in_(SI_STATUSES),
                     'invoice_number', 'customer_id', 'customer_name', 'customer_tin',
                     side, 'sales_invoice', date_from, date_to, branch_id)
            + _collect(CashReceiptVoucher, 'revenue_lines',
                       CashReceiptVoucher.crv_date,
                       CashReceiptVoucher.status == 'posted',
                       'crv_number', 'customer_id', 'customer_name', 'customer_tin',
                       side, 'cash_receipt', date_from, date_to, branch_id)
        )
    else:
        raise ValueError(f"wht_lines(): side must be 'payor' or 'payee', got {side!r}")

    if tax_type is not None:
        rows = [r for r in rows if r.tax_type == tax_type]
    return rows
