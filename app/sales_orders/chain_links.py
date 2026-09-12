"""Document-chain resolvers for the Job Order Slips page: SO -> DR -> SI -> CR.

The sell-side twin of app/purchase_requests/allocation.py's po/rr/ap/cd_links_for_pr_ids.
Each helper answers, for a whole page of Sales Orders in ONE query, "which documents of
this kind exist for each order" as ``{so_id: [(doc_id, number), ...]}``. Never a
per-row property on SalesOrder: the list is exactly where an N+1 would live.

Rules (docs/design/2026-09-12-job-order-chain-columns-design.md):

- a Delivery Receipt counts only while committed (approved/delivered/billed) -- a draft
  has delivered nothing, and naming it would tell the reader goods had left on the
  strength of an unapproved document;
- a Sales Invoice is reached through ``delivery_receipts.sales_invoice_id`` and that
  link ALONE: the app sets it when the DR is billed and clears it when the SI is voided
  or cancelled (sales_invoices.views._unbill_drs), so the link is the truth and an SI
  status filter would only drift from it;
- a Cash Receipt counts unless voided/cancelled -- a voided receipt collected nothing.
"""
from app import db


def _clean_ids(so_ids):
    return [i for i in (so_ids or []) if i is not None]


def _dedup_links(rows):
    """``[(so_id, doc_id, doc_number), ...]`` -> ``{so_id: [(doc_id, number)]}``.

    distinct() is on the whole row, so one document reached through TWO DRs (or two
    SIs) of the same order arrives twice -- dedup on the document itself. Shared by
    the three helpers so they cannot drift apart.
    """
    out = {}
    for so_id, doc_id, doc_number in rows:
        seen = out.setdefault(so_id, [])
        if (doc_id, doc_number) not in seen:
            seen.append((doc_id, doc_number))
    return out


def dr_links_for_so_ids(so_ids):
    """``{so_id: [(dr_id, dr_number), ...]}`` -- committed Delivery Receipts per order."""
    from app.delivery_receipts.models import COMMITTED_STATUSES, DeliveryReceipt
    ids = _clean_ids(so_ids)
    if not ids:
        return {}
    rows = (db.session.query(DeliveryReceipt.sales_order_id,
                             DeliveryReceipt.id, DeliveryReceipt.dr_number)
            .filter(DeliveryReceipt.sales_order_id.in_(ids))
            .filter(DeliveryReceipt.status.in_(COMMITTED_STATUSES))
            .order_by(DeliveryReceipt.dr_number.asc())
            .distinct()
            .all())
    return _dedup_links(rows)


def si_links_for_so_ids(so_ids):
    """``{so_id: [(si_id, invoice_number), ...]}`` -- Sales Invoices that billed the
    order's committed Delivery Receipts."""
    from app.delivery_receipts.models import COMMITTED_STATUSES, DeliveryReceipt
    from app.sales_invoices.models import SalesInvoice
    ids = _clean_ids(so_ids)
    if not ids:
        return {}
    rows = (db.session.query(DeliveryReceipt.sales_order_id,
                             SalesInvoice.id, SalesInvoice.invoice_number)
            .join(SalesInvoice, SalesInvoice.id == DeliveryReceipt.sales_invoice_id)
            .filter(DeliveryReceipt.sales_order_id.in_(ids))
            .filter(DeliveryReceipt.status.in_(COMMITTED_STATUSES))
            .order_by(SalesInvoice.invoice_number.asc())
            .distinct()
            .all())
    return _dedup_links(rows)


def cr_links_for_so_ids(so_ids):
    """``{so_id: [(crv_id, crv_number), ...]}`` -- Cash Receipts applied to the Sales
    Invoices that billed the order's Delivery Receipts; voided/cancelled excluded."""
    from app.cash_receipts.models import CashReceiptVoucher, CRVArLine
    from app.delivery_receipts.models import COMMITTED_STATUSES, DeliveryReceipt
    from app.sales_invoices.models import SalesInvoice
    ids = _clean_ids(so_ids)
    if not ids:
        return {}
    rows = (db.session.query(DeliveryReceipt.sales_order_id,
                             CashReceiptVoucher.id, CashReceiptVoucher.crv_number)
            .join(SalesInvoice, SalesInvoice.id == DeliveryReceipt.sales_invoice_id)
            .join(CRVArLine, CRVArLine.invoice_id == SalesInvoice.id)
            .join(CashReceiptVoucher, CashReceiptVoucher.id == CRVArLine.crv_id)
            .filter(DeliveryReceipt.sales_order_id.in_(ids))
            .filter(DeliveryReceipt.status.in_(COMMITTED_STATUSES))
            .filter(CashReceiptVoucher.status.notin_(('voided', 'cancelled')))
            .order_by(CashReceiptVoucher.crv_number.asc())
            .distinct()
            .all())
    return _dedup_links(rows)
