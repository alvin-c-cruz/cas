"""Phase 3 -- billing Purchase Orders / Receiving Reports into an Accounts Payable bill.

Buy-side mirror of the SI<-DR billing trio (app/sales_invoices/views.py:_bill_drs/_unbill_drs).
Whole-document billing: a source PO/RR is billed all-or-nothing, gets `accounts_payable_id` set,
and drops out of the "billable" query so it cannot be double-billed.

Two paths (goods vs services):
  * Goods:    PO -> RR(approved) -> bill the RR   (`billable_rrs_for`)
  * Services: PO(approved, no RR) -> bill the PO   (`billable_pos_for`)

The AP module calls `_bill_purchase_sources` (create, before commit) and
`_unbill_purchase_sources` (cancel/void). Both are STRICT no-ops when no source ids are posted, so
a client without the PO/RR modules (e.g. Zhiyuan) hits identical AP behavior.
"""
from app import db

_RECEIVABLE_PO = ('approved', 'partially_received')


def ap_billing_consolidate():
    """Whether one AP bill may consume several POs/RRs. Mirrors si_dr_billing_consolidate."""
    from app.settings import AppSettings
    return AppSettings.get_setting('ap_billing_consolidate', '0') == '1'


def _parse_ids(raw):
    import json
    if isinstance(raw, (list, tuple)):
        seq = raw
    else:
        try:
            seq = json.loads(raw or '[]') or []
        except (ValueError, TypeError):
            return []
    out = []
    for x in seq:
        try:
            out.append(int(x))
        except (ValueError, TypeError):
            continue
    return out


def _bill_purchase_sources(ap, po_ids, rr_ids):
    """Mark each source PO/RR billed + linked to this AP bill. Validates eligibility and enforces
    the consolidate setting. Raises ValueError (caught by AP create -> full rollback) on any problem,
    so a bad pull never half-bills. STRICT no-op when both id lists are empty."""
    po_ids = _parse_ids(po_ids)
    rr_ids = _parse_ids(rr_ids)
    if not po_ids and not rr_ids:
        return
    if not ap_billing_consolidate() and (len(po_ids) + len(rr_ids)) > 1:
        raise ValueError('Consolidated billing is off - bill one Purchase Order or Receiving '
                         'Report per bill. Enable it in Company Settings to bill several at once.')
    from app.purchase_orders.models import PurchaseOrder
    from app.receiving_reports.models import ReceivingReport
    for po_id in po_ids:
        po = db.session.get(PurchaseOrder, po_id)
        if (po is None or po.branch_id != ap.branch_id or po.vendor_id != ap.vendor_id
                or po.status not in _RECEIVABLE_PO or po.accounts_payable_id is not None):
            raise ValueError(f'Purchase Order {po_id} is no longer billable.')
        po.status = 'closed'
        po.accounts_payable_id = ap.id
    for rr_id in rr_ids:
        rr = db.session.get(ReceivingReport, rr_id)
        if (rr is None or rr.branch_id != ap.branch_id or rr.vendor_id != ap.vendor_id
                or rr.status != 'approved' or rr.accounts_payable_id is not None):
            raise ValueError(f'Receiving Report {rr_id} is no longer billable.')
        rr.status = 'billed'
        rr.accounts_payable_id = ap.id


def _unbill_purchase_sources(ap):
    """Revert every PO/RR billed by this AP bill back to 'approved' + unlink (AP cancel/void)."""
    from app.purchase_orders.models import PurchaseOrder
    from app.receiving_reports.models import ReceivingReport
    for po in PurchaseOrder.query.filter_by(accounts_payable_id=ap.id).all():
        po.status = 'approved'
        po.accounts_payable_id = None
    for rr in ReceivingReport.query.filter_by(accounts_payable_id=ap.id).all():
        rr.status = 'approved'
        rr.accounts_payable_id = None


# -- billable queries + AP-line payloads ---------------------------------------

def _po_line_payload(po):
    lines = []
    for li in po.line_items:
        product = li.product
        lines.append({
            'po_item_id': li.id,
            'description': (li.description or (product.name if product else '')),
            'amount': float(li.amount) if li.amount is not None else 0.0,
            'product_id': li.product_id,
            'product_code': product.code if product else None,
            'product_name': product.name if product else None,
            'quantity': float(li.quantity) if li.quantity is not None else None,
            'unit_price': float(li.unit_price) if li.unit_price is not None else None,
            'uom_id': li.unit_of_measure_id,
            'uom_display': (li.unit_of_measure.code if li.unit_of_measure else li.uom_text),
            'vat_category': li.vat_category,
            'vat_rate': float(li.vat_rate) if li.vat_rate is not None else 0.0,
            'account_id': (product.default_account_id if product else None),
        })
    return lines


def billable_pos_for(branch_id, vendor_id):
    """Approved POs for a vendor with NO receiving report (the services/direct path), not yet billed."""
    from app.purchase_orders.models import PurchaseOrder
    from app.receiving_reports.models import ReceivingReport
    pos = (PurchaseOrder.query
           .filter(PurchaseOrder.branch_id == branch_id,
                   PurchaseOrder.vendor_id == vendor_id,
                   PurchaseOrder.status.in_(_RECEIVABLE_PO),
                   PurchaseOrder.accounts_payable_id.is_(None))
           .order_by(PurchaseOrder.order_date.desc(), PurchaseOrder.id.desc()).all())
    out = []
    for po in pos:
        has_rr = (ReceivingReport.query
                  .filter(ReceivingReport.purchase_order_id == po.id,
                          ReceivingReport.status.in_(('approved', 'billed'))).first())
        if has_rr:
            continue          # goods PO -> bill via its RR, not directly
        out.append({'id': po.id, 'po_number': po.po_number,
                    'order_date': po.order_date.isoformat() if po.order_date else None,
                    'lines': _po_line_payload(po)})
    return out


def billable_rrs_for(branch_id, vendor_id):
    """Approved, unbilled RRs for a vendor (the goods path). Each line priced from its PO line."""
    from app.receiving_reports.models import ReceivingReport
    rrs = (ReceivingReport.query
           .filter(ReceivingReport.branch_id == branch_id,
                   ReceivingReport.vendor_id == vendor_id,
                   ReceivingReport.status == 'approved',
                   ReceivingReport.accounts_payable_id.is_(None))
           .order_by(ReceivingReport.receipt_date.desc(), ReceivingReport.id.desc()).all())
    out = []
    for rr in rrs:
        lines = []
        for li in rr.line_items:
            poi = li.purchase_order_item
            product = li.product or (poi.product if poi else None)
            _price = poi.unit_price if (poi and poi.unit_price is not None) else None
            _amt = (float(li.received_quantity * poi.unit_price)
                    if (poi and poi.unit_price is not None and li.received_quantity is not None)
                    else 0.0)
            lines.append({
                'rr_item_id': li.id,
                'po_item_id': (poi.id if poi else None),
                'description': (poi.description if poi else None) or (product.name if product else ''),
                'amount': _amt,
                'product_id': (product.id if product else None),
                'product_code': product.code if product else None,
                'product_name': product.name if product else None,
                'quantity': float(li.received_quantity) if li.received_quantity is not None else 0.0,
                'unit_price': float(poi.unit_price) if (poi and poi.unit_price is not None) else None,
                'uom_id': (poi.unit_of_measure_id if poi else None),
                'uom_display': (poi.unit_of_measure.code if (poi and poi.unit_of_measure)
                                else (poi.uom_text if poi else None)),
                'vat_category': (poi.vat_category if poi else None),
                'vat_rate': float(poi.vat_rate) if (poi and poi.vat_rate is not None) else 0.0,
                'account_id': (product.default_account_id if product else None),
            })
        out.append({'id': rr.id, 'rr_number': rr.rr_number,
                    'receipt_date': rr.receipt_date.isoformat() if rr.receipt_date else None,
                    'purchase_order_number': rr.purchase_order.po_number if rr.purchase_order else None,
                    'lines': lines})
    return out
