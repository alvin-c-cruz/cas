"""How a purchase order finished -- a label derived on every read, never stored (GCD-5).

Owner, 13 Nov 2026: "it should show Paid if closed by CV, and Received if closed by RR"; then the
letters "GCD-5.1 A, 5.2 B, 5.3 A, 5.4 A" (work order 2026-11-13-po-status-paid-or-received).

The stored ``PurchaseOrder.status`` and every rule that reads it (receive, amend, cancel, bill)
are untouched: this module only names, for the screens, how far the order has got. A PO is
``closed`` in the database only when an AP voucher billed the PO itself; receiving it in full, or
settling its receipts by a cash voucher (``purchase_billing.settle_rr_by_cdv``), leaves it
``approved``. The label reads the PO's **committed receipts** -- RRs in approved or billed status
(``COMMITTED_STATUSES``), the same set that consumes a line's open quantity -- and the first
rule that matches wins, so no two labels overlap:

  1. stored draft / cancelled                       -> as stored
  2. stored closed (an APV billed the PO itself)    -> Closed
  3. no committed receipt                           -> as stored (Submitted / Approved)
  4. some received, not fully                       -> Partly received          (5.4 A)
  5. fully received, every receipt paid by a CDV    -> Paid
  6. fully received, every receipt finished, some by APV and some by CDV -> Closed (5.3 A)
  7. fully received, anything else -- every receipt billed by APV (5.2 B), or one not yet
     billed or paid                                 -> Received

"Fully received" is ``po_line_open_qty`` <= 0 on every line ordered with a quantity above zero;
an over-receipt counts as received.
"""
from collections import defaultdict
from decimal import Decimal

from app import db

#: Label key -> the words on the screen.
LABELS = {
    'draft': 'Draft',
    'submitted': 'Submitted',
    'approved': 'Approved',
    'partly_received': 'Partly received',
    'received': 'Received',
    'paid': 'Paid',
    'closed': 'Closed',
    'cancelled': 'Cancelled',
}

#: Label key -> the existing badge class in style.css (no new CSS).
BADGES = {
    'draft': 'draft',
    'submitted': 'submitted',
    'approved': 'approved',
    'partly_received': 'partially-received',
    'received': 'converted',
    'paid': 'paid',
    'closed': 'closed',
    'cancelled': 'cancelled',
}

#: Old list-filter values that bookmarked links may still carry.
FILTER_ALIASES = {'partially_received': 'partly_received'}

_AS_STORED = ('draft', 'cancelled')


def label_for(key):
    return LABELS.get(key, (key or '').replace('_', ' ').capitalize())


def badge_for(key):
    return BADGES.get(key, 'draft')


def _finished_by(rr_status, accounts_payable_id, settled_cdv_id):
    """'cdv' / 'apv' for a finished (billed) receipt, None for one not yet billed or paid."""
    if rr_status != 'billed':
        return None
    if settled_cdv_id is not None:
        return 'cdv'
    if accounts_payable_id is not None:
        return 'apv'
    return None


def _decide(stored, fully_received, finishes):
    """The rule table. *finishes*: one entry per committed receipt, 'cdv' / 'apv' / None."""
    if stored in _AS_STORED:
        return stored
    if stored == 'closed':
        return 'closed'
    if not finishes:
        # A stored 'partially_received' is inert (nothing assigns it); read it as approved.
        return stored if stored in ('submitted', 'approved') else 'approved'
    if not fully_received:
        return 'partly_received'
    if all(f == 'cdv' for f in finishes):
        return 'paid'
    if all(f is not None for f in finishes) and 'cdv' in finishes and 'apv' in finishes:
        return 'closed'
    return 'received'      # every receipt by APV (5.2 B), or one not yet billed or paid


def progress_keys(pos):
    """{po.id: label key} for many orders in three queries (the list page, exports)."""
    from app.purchase_orders.models import PurchaseOrderItem
    from app.receiving_reports.models import (COMMITTED_STATUSES, ReceivingReport,
                                              ReceivingReportItem)

    pos = list(pos)
    keys = {}
    live = [po for po in pos if po.status not in _AS_STORED and po.status != 'closed']
    for po in pos:
        if po.status in _AS_STORED or po.status == 'closed':
            keys[po.id] = _decide(po.status, False, [])
    if not live:
        return keys
    ids = [po.id for po in live]

    ordered = defaultdict(dict)          # po_id -> {item_id: ordered qty}, lines with qty > 0
    for item_id, po_id, qty in (db.session.query(PurchaseOrderItem.id,
                                                 PurchaseOrderItem.purchase_order_id,
                                                 PurchaseOrderItem.quantity)
                                .filter(PurchaseOrderItem.purchase_order_id.in_(ids))):
        q = Decimal(str(qty or 0))
        if q > 0:
            ordered[po_id][item_id] = q

    received = defaultdict(Decimal)      # item_id -> qty on committed receipts
    finishes = defaultdict(dict)         # po_id -> {rr_id: 'cdv' / 'apv' / None}
    rows = (db.session.query(PurchaseOrderItem.purchase_order_id,
                             ReceivingReportItem.purchase_order_item_id,
                             ReceivingReportItem.received_quantity,
                             ReceivingReport.id, ReceivingReport.status,
                             ReceivingReport.accounts_payable_id,
                             ReceivingReport.settled_cdv_id)
            .join(ReceivingReport, ReceivingReportItem.receiving_report_id == ReceivingReport.id)
            .join(PurchaseOrderItem,
                  ReceivingReportItem.purchase_order_item_id == PurchaseOrderItem.id)
            .filter(PurchaseOrderItem.purchase_order_id.in_(ids))
            .filter(ReceivingReport.status.in_(COMMITTED_STATUSES)))
    for po_id, item_id, qty, rr_id, rr_status, ap_id, cdv_id in rows:
        received[item_id] += Decimal(str(qty or 0))
        finishes[po_id][rr_id] = _finished_by(rr_status, ap_id, cdv_id)

    for po in live:
        fully = all(received[item_id] >= q for item_id, q in ordered[po.id].items())
        keys[po.id] = _decide(po.status, fully, list(finishes[po.id].values()))
    return keys


def progress_key(po):
    """The label key of one order (the detail page)."""
    return progress_keys([po])[po.id]


def receipts_for(po):
    """The PO's committed receipts, oldest first, each with how it finished.

    [{'rr': ReceivingReport, 'finished_by': 'cdv' / 'apv' / None,
      'document': CDV or APV number / None, 'document_id': its id / None}, ...]
    """
    from app.accounts_payable.models import AccountsPayable
    from app.cash_disbursements.models import CashDisbursementVoucher
    from app.purchase_orders.models import PurchaseOrderItem
    from app.receiving_reports.models import (COMMITTED_STATUSES, ReceivingReport,
                                              ReceivingReportItem)

    rrs = (ReceivingReport.query
           .join(ReceivingReportItem, ReceivingReportItem.receiving_report_id == ReceivingReport.id)
           .join(PurchaseOrderItem,
                 ReceivingReportItem.purchase_order_item_id == PurchaseOrderItem.id)
           .filter(PurchaseOrderItem.purchase_order_id == po.id)
           .filter(ReceivingReport.status.in_(COMMITTED_STATUSES))
           .distinct()
           .order_by(ReceivingReport.receipt_date, ReceivingReport.rr_number)
           .all())
    out = []
    for rr in rrs:
        how = _finished_by(rr.status, rr.accounts_payable_id, rr.settled_cdv_id)
        document = document_id = None
        if how == 'cdv':
            cdv = db.session.get(CashDisbursementVoucher, rr.settled_cdv_id)
            document, document_id = (cdv.cdv_number if cdv else None), rr.settled_cdv_id
        elif how == 'apv':
            ap = db.session.get(AccountsPayable, rr.accounts_payable_id)
            document, document_id = (ap.ap_number if ap else None), rr.accounts_payable_id
        out.append({'rr': rr, 'finished_by': how, 'document': document,
                    'document_id': document_id})
    return out
