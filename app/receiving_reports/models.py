"""Receiving Report -- records goods received against an approved Purchase Order.
Buy-side mirror of DeliveryReceipt. Operational, NOT accounting: posts no journal entry in v1.

The RR is a control document -- it caps how much a Bill can charge (bill-what-you-received) and
records receipt. It is NOT a GRNI accrual today, but two seams keep that door open without a model
rebuild: `journal_entry_id` (a future accrual JE) and `accounts_payable_id` (the billing link,
Phase 3). Middle link of PO -> RR -> Bill.
"""
from decimal import Decimal
from app import db
from app.utils import ph_now
from app.utils.concurrency import RowVersioned

# RR statuses that CONSUME the PO's open quantity (draft & cancelled do not).
# No 'delivered' step on the buy-side (that is a sell-side concept), so: approved + billed.
COMMITTED_STATUSES = ('approved', 'billed')


class ReceivingReport(RowVersioned, db.Model):
    __tablename__ = 'receiving_reports'

    id = db.Column(db.Integer, primary_key=True)
    branch_id = db.Column(db.Integer, db.ForeignKey('branches.id'), nullable=True, index=True)
    branch = db.relationship('Branch', foreign_keys=[branch_id])

    rr_number = db.Column(db.String(50), unique=True, nullable=False, index=True)
    receipt_date = db.Column(db.Date, nullable=False, index=True)

    purchase_order_id = db.Column(db.Integer, db.ForeignKey('purchase_orders.id'),
                                  nullable=False, index=True)
    purchase_order = db.relationship('PurchaseOrder', foreign_keys=[purchase_order_id])

    # Vendor snapshot (from the PO at create; no picker).
    vendor_id = db.Column(db.Integer, db.ForeignKey('vendors.id'), nullable=True, index=True)
    vendor_name = db.Column(db.String(200), nullable=False)

    status = db.Column(db.String(20), default='draft', nullable=False, index=True)
    remarks = db.Column(db.Text)

    # Billing seam (Phase 3): set when a Bill is cut against this RR. Null until billed.
    accounts_payable_id = db.Column(db.Integer, db.ForeignKey('accounts_payable.id'),
                                    nullable=True, index=True)
    # Accrual seam (deferred): a future GRNI / period-end reversing JE attaches here. Inert in v1.
    journal_entry_id = db.Column(db.Integer, db.ForeignKey('journal_entries.id'), nullable=True)

    created_by_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    created_at = db.Column(db.DateTime, default=ph_now, nullable=False)
    updated_at = db.Column(db.DateTime, default=ph_now, onupdate=ph_now, nullable=False)
    approved_by_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    approved_at = db.Column(db.DateTime)
    cancelled_by_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    cancelled_at = db.Column(db.DateTime)
    cancel_reason = db.Column(db.String(500))

    line_items = db.relationship('ReceivingReportItem', backref='receiving_report',
                                 lazy='select', cascade='all, delete-orphan',
                                 order_by='ReceivingReportItem.line_number')

    def __repr__(self):
        return f'<ReceivingReport {self.rr_number} - {self.status}>'

    def to_dict(self):
        return {
            'id': self.id, 'rr_number': self.rr_number, 'status': self.status,
            'receipt_date': self.receipt_date.isoformat() if self.receipt_date else None,
            'purchase_order_id': self.purchase_order_id,
            'purchase_order_number': self.purchase_order.po_number if self.purchase_order else None,
            'vendor_name': self.vendor_name,
        }


class ReceivingReportItem(db.Model):
    __tablename__ = 'receiving_report_items'

    id = db.Column(db.Integer, primary_key=True)
    receiving_report_id = db.Column(db.Integer, db.ForeignKey('receiving_reports.id'),
                                    nullable=False, index=True)
    line_number = db.Column(db.Integer, nullable=False)
    purchase_order_item_id = db.Column(db.Integer, db.ForeignKey('purchase_order_items.id'),
                                       nullable=False, index=True)
    purchase_order_item = db.relationship('PurchaseOrderItem',
                                          foreign_keys=[purchase_order_item_id])
    product_id = db.Column(db.Integer, db.ForeignKey('products.id'), nullable=True)  # snapshot for print
    product = db.relationship('Product', foreign_keys=[product_id])
    received_quantity = db.Column(db.Numeric(15, 4), nullable=False)

    # R-03 slice 2a-ii: points at the StockMovement this line's receipt posted
    # (tracked products only -- NULL for an untracked line or a not-yet-approved RR).
    stock_movement_id = db.Column(db.Integer, db.ForeignKey('stock_movements.id'), nullable=True)
    stock_movement = db.relationship('StockMovement')

    # A RR line's quantity is the RECEIVED quantity; UoM/price belong to the PO line it receives.
    @property
    def quantity(self):
        return self.received_quantity

    @property
    def unit_of_measure(self):
        poi = self.purchase_order_item
        return poi.unit_of_measure if poi else None

    @property
    def uom_text(self):
        poi = self.purchase_order_item
        return poi.uom_text if poi else None

    def to_dict(self):
        poi = self.purchase_order_item
        return {
            'id': self.id, 'line_number': self.line_number,
            'purchase_order_item_id': self.purchase_order_item_id,
            'received_quantity': float(self.received_quantity) if self.received_quantity is not None else 0.0,
            'ordered_quantity': float(poi.quantity) if (poi and poi.quantity is not None) else None,
            'description': (poi.description if poi else None),
            'product_code': (poi.product.code if (poi and poi.product) else (self.product.code if self.product else None)),
            'product_name': (poi.product.name if (poi and poi.product) else (self.product.name if self.product else None)),
            'uom': (poi.unit_of_measure.code if (poi and poi.unit_of_measure) else (poi.uom_text if poi else None)),
            'unit_price': float(poi.unit_price) if (poi and poi.unit_price is not None) else None,
        }


def po_line_open_qty(po_item, exclude_rr_id=None):
    """Ordered qty of a PO line minus the qty already received by non-cancelled, non-draft RR
    lines (statuses in COMMITTED_STATUSES). Pass exclude_rr_id to leave a specific RR out of the
    sum (used when re-checking the RR being approved)."""
    ordered = Decimal(str(po_item.quantity or 0))
    q = (db.session.query(db.func.coalesce(db.func.sum(ReceivingReportItem.received_quantity), 0))
         .join(ReceivingReport, ReceivingReportItem.receiving_report_id == ReceivingReport.id)
         .filter(ReceivingReportItem.purchase_order_item_id == po_item.id)
         .filter(ReceivingReport.status.in_(COMMITTED_STATUSES)))
    if exclude_rr_id is not None:
        q = q.filter(ReceivingReport.id != exclude_rr_id)
    received = Decimal(str(q.scalar() or 0))
    return ordered - received


def generate_rr_number(branch_id=None):
    """Next RR-YYYY-MM-#### for the current PH month (global per month; mirror generate_dr_number)."""
    today = ph_now().date()
    prefix = f"RR-{today.year:04d}-{today.month:02d}-"
    rows = (ReceivingReport.query
            .filter(ReceivingReport.rr_number.like(prefix + '%'))
            .with_entities(ReceivingReport.rr_number).all())
    nums = []
    for (n,) in rows:
        tail = n.rsplit('-', 1)[-1]
        if tail.isdigit():
            nums.append(int(tail))
    return f"{prefix}{(max(nums) + 1) if nums else 1:04d}"
