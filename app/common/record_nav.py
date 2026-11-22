"""Previous / Next among a module's records (BUG-9; owner, 22 Nov 2026, design A).

His words: "The module's list in its default order, in the current branch, every status. Filters and searches on the
list are ignored. The button greys out at either end."

Each record page includes templates/_record_nav.html, which calls record_nav(module, record). The neighbours come from
one query: the ids of the module's records in the RECORD's branch, in the list's default order. A record page is only
ever shown in its own branch (app/utils/branch_scope.py), so that is "the current branch".

SPECS repeats each list view's default order_by; it cannot import it, because each view builds its order inline with
its filters. tests/integration/test_record_prev_next.py ties the two together: it reads the order off the rendered lists
and off the list views' source, so a list whose default order changes fails there until this table follows.

A record that is not on its module's list gets no buttons at all (record_nav returns None): a journal entry posted by
another document is not a journal voucher.
"""
from importlib import import_module

from flask import url_for
from jinja2 import Undefined
from sqlalchemy.dialects import sqlite

from app import db


class _Spec:
    """One module: its model, its list's default order, the record page's endpoint, and what else scopes its list."""

    def __init__(self, model, order, endpoint, scope=None):
        self._model, self._order, self._endpoint, self._scope = model, order, endpoint, scope

    def model(self):
        module, _, name = self._model.partition(':')
        return getattr(import_module(module), name)

    def order_by(self, model):
        return self._order(model)

    def filters(self, model, record):
        return self._scope(model, record) if self._scope else ()

    def endpoint(self, record):
        return self._endpoint(record) if callable(self._endpoint) else self._endpoint


def _by_date(column):
    """The common list order: the document's date, newest first, then the later entry first."""
    return lambda model: (getattr(model, column).desc(), model.id.desc())


def _newest_first(model):
    return (model.id.desc(),)


def _voucher_types(model, record):
    from app.journals.views import VOUCHER_TYPES
    return (model.entry_type.in_(VOUCHER_TYPES),)


def _same_memo_type(model, record):
    return (model.memo_type == record.memo_type,)


SPECS = {
    # By voucher number AS A NUMBER, highest first (the AP list's order since 2beadb9d).
    'accounts_payable': _Spec('app.accounts_payable.models:AccountsPayable',
                              lambda m: (db.cast(m.ap_number, db.Integer).desc(), m.id.desc()),
                              'accounts_payable.view'),
    'cash_disbursements': _Spec('app.cash_disbursements.models:CashDisbursementVoucher', _by_date('cdv_date'),
                                'cash_disbursements.view'),
    'cash_receipts': _Spec('app.cash_receipts.models:CashReceiptVoucher', _by_date('crv_date'), 'cash_receipts.view'),
    'delivery_receipts': _Spec('app.delivery_receipts.models:DeliveryReceipt', _by_date('delivery_date'),
                               'delivery_receipts.view'),
    # The Journal Voucher list (journals.voucher): voucher-type entries only. Same-date vouchers run in the order
    # they were entered; the list had no tiebreaker of its own until BUG-9 made the one it already showed explicit.
    'journal_entries': _Spec('app.journal_entries.models:JournalEntry',
                             lambda m: (m.entry_date.desc(), m.id.asc()), 'journal_entries.view',
                             scope=_voucher_types),
    'payroll': _Spec('app.payroll.models:PayrollRun', _newest_first, 'payroll.view_run'),
    # Each memo blueprint serves two lists; a memo steps through the list of its own kind.
    'purchase_memos': _Spec('app.purchase_memos.models:PurchaseMemo', _by_date('memo_date'),
                            lambda record: f'purchase_memos.{record.memo_type}_view', scope=_same_memo_type),
    'purchase_orders': _Spec('app.purchase_orders.models:PurchaseOrder', _by_date('order_date'),
                             'purchase_orders.view'),
    'purchase_requests': _Spec('app.purchase_requests.models:PurchaseRequest', _by_date('request_date'),
                               'purchase_requests.view'),
    'quotations': _Spec('app.quotations.models:Quotation', _by_date('quotation_date'), 'quotations.view'),
    'receiving_reports': _Spec('app.receiving_reports.models:ReceivingReport', _by_date('receipt_date'),
                               'receiving_reports.view'),
    'sales_invoices': _Spec('app.sales_invoices.models:SalesInvoice', _by_date('invoice_date'), 'sales_invoices.view'),
    'sales_memos': _Spec('app.sales_memos.models:SalesMemo', _by_date('memo_date'),
                         lambda record: f'sales_memos.{record.memo_type}_view', scope=_same_memo_type),
    'sales_orders': _Spec('app.sales_orders.models:SalesOrder', _by_date('order_date'), 'sales_orders.view'),
    'work_orders': _Spec('app.work_orders.models:WorkOrder', _newest_first, 'work_orders.view'),
}


def order_sql(module):
    """The module's order as SQL text, e.g. 'sales_orders.order_date DESC, sales_orders.id DESC'. For the tests."""
    spec = SPECS[module]
    return ', '.join(str(clause.compile(dialect=sqlite.dialect())) for clause in spec.order_by(spec.model()))


def record_nav(module, record):
    """{'prev_url': ..., 'next_url': ...} for a record page, either being None at that end of the list; or None when
    the record is not on its module's list, so the page shows no buttons."""
    spec = SPECS.get(module)
    # Anything but a saved record of a known module gets no buttons: a template must never fail over these.
    # (An undefined template variable raises on any attribute, so it is turned away by type first.)
    if spec is None or isinstance(record, Undefined) or not isinstance(getattr(record, 'id', None), int):
        return None
    model = spec.model()
    ids = [row[0] for row in (db.session.query(model.id)
                              .filter(model.branch_id == record.branch_id, *spec.filters(model, record))
                              .order_by(*spec.order_by(model)))]
    if record.id not in ids:
        return None
    at = ids.index(record.id)
    endpoint = spec.endpoint(record)
    return {'prev_url': url_for(endpoint, id=ids[at - 1]) if at > 0 else None,
            'next_url': url_for(endpoint, id=ids[at + 1]) if at + 1 < len(ids) else None}
