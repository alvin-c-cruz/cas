"""A purchase order's paper trail for the PO list: RR #, AP #, CD # (RCPT A, owner 17 Nov 2026: his RR-3 idea "maybe
something similar to the PR list page"; work order 2026-11-13-rr-received-without-po-link).

Mirrors the PR list's link helpers (purchase_requests/allocation.py rr/ap/cd_links_for_pr_ids): one query per column
for the whole page, never per row, each answering {po_id: [(doc_id, doc_number), ...]} in number order.
- RR #: COMMITTED receiving reports (approved or billed) against the order's lines -- a draft or submitted receipt has
  received nothing.
- AP #: the AP voucher that billed the order itself (services route), and those that billed its committed receipts.
- CD #: the CDVs that paid those AP vouchers, and those that settled its receipts outside AP (rrsettle_0001).
"""
from app import db


def _dedup(rows):
    out = {}
    for po_id, doc_id, number in rows:
        seen = out.setdefault(po_id, [])
        if (doc_id, number) not in seen:
            seen.append((doc_id, number))
    for po_id in out:
        out[po_id].sort(key=lambda d: d[1] or '')
    return out


def chain_links_for_po_ids(po_ids):
    """(rr_links, ap_links, cd_links) for the given orders."""
    from app.accounts_payable.models import AccountsPayable
    from app.cash_disbursements.models import CashDisbursementVoucher as CDV, CDVApLine
    from app.purchase_orders.models import PurchaseOrder, PurchaseOrderItem
    from app.receiving_reports.models import COMMITTED_STATUSES, ReceivingReport, ReceivingReportItem

    ids = [i for i in (po_ids or []) if i is not None]
    if not ids:
        return {}, {}, {}

    def receipts():
        return (db.session.query(PurchaseOrderItem.purchase_order_id, ReceivingReport)
                .join(ReceivingReportItem, ReceivingReportItem.purchase_order_item_id == PurchaseOrderItem.id)
                .join(ReceivingReport, ReceivingReport.id == ReceivingReportItem.receiving_report_id)
                .filter(PurchaseOrderItem.purchase_order_id.in_(ids),
                        ReceivingReport.status.in_(COMMITTED_STATUSES)))

    rr_rows, ap_rows, cd_rows = [], [], []
    rr_ap_ids = {}            # ap_id -> set(po_id)
    for po_id, rr in receipts().distinct():
        rr_rows.append((po_id, rr.id, rr.rr_number))
        if rr.accounts_payable_id:
            rr_ap_ids.setdefault(rr.accounts_payable_id, set()).add(po_id)
        if rr.settled_cdv_id:
            cdv = db.session.get(CDV, rr.settled_cdv_id)
            if cdv is not None:
                cd_rows.append((po_id, cdv.id, cdv.cdv_number))

    ap_po = dict(rr_ap_ids)
    for po in PurchaseOrder.query.filter(PurchaseOrder.id.in_(ids), PurchaseOrder.accounts_payable_id.isnot(None)):
        ap_po.setdefault(po.accounts_payable_id, set()).add(po.id)
    if ap_po:
        for ap in AccountsPayable.query.filter(AccountsPayable.id.in_(list(ap_po))):
            for po_id in ap_po[ap.id]:
                ap_rows.append((po_id, ap.id, ap.ap_number))
        paid = (db.session.query(CDVApLine.ap_id, CDV.id, CDV.cdv_number)
                .join(CDV, CDV.id == CDVApLine.cdv_id)
                .filter(CDVApLine.ap_id.in_(list(ap_po)), CDV.status.notin_(('voided', 'cancelled'))))
        for ap_id, cdv_id, number in paid:
            for po_id in ap_po[ap_id]:
                cd_rows.append((po_id, cdv_id, number))
    return _dedup(rr_rows), _dedup(ap_rows), _dedup(cd_rows)
