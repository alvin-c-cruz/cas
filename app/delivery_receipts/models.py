"""Delivery Receipt -- records deliveries against a confirmed Sales Order.
Operational, NOT accounting: posts no journal entry. Middle link of SO -> DR -> SI.
"""
from decimal import Decimal
from app import db
from app.utils import ph_now
from app.utils.concurrency import RowVersioned

# DR statuses that CONSUME the SO's open quantity (draft & cancelled do not).
COMMITTED_STATUSES = ('approved', 'delivered', 'billed')


class DeliveryReceipt(RowVersioned, db.Model):
    __tablename__ = 'delivery_receipts'

    id = db.Column(db.Integer, primary_key=True)
    branch_id = db.Column(db.Integer, db.ForeignKey('branches.id'), nullable=True, index=True)
    branch = db.relationship('Branch', foreign_keys=[branch_id])

    dr_number = db.Column(db.String(50), unique=True, nullable=False, index=True)
    delivery_date = db.Column(db.Date, nullable=False, index=True)

    sales_order_id = db.Column(db.Integer, db.ForeignKey('sales_orders.id'), nullable=False, index=True)
    sales_order = db.relationship('SalesOrder', foreign_keys=[sales_order_id])

    # Customer snapshot (from the SO at create; no picker).
    customer_id = db.Column(db.Integer, db.ForeignKey('customers.id'), nullable=False, index=True)
    customer_name = db.Column(db.String(200), nullable=False)

    status = db.Column(db.String(20), default='draft', nullable=False, index=True)
    remarks = db.Column(db.Text)

    salesperson_id = db.Column(db.Integer, db.ForeignKey('employees.id'), nullable=True, index=True)
    salesperson = db.relationship('Employee', foreign_keys=[salesperson_id])

    # Billing seam (sub-project #2 fills this); null until billed.
    sales_invoice_id = db.Column(db.Integer, db.ForeignKey('sales_invoices.id'), nullable=True, index=True)

    created_by_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    created_at = db.Column(db.DateTime, default=ph_now, nullable=False)
    updated_at = db.Column(db.DateTime, default=ph_now, onupdate=ph_now, nullable=False)
    approved_by_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    approved_at = db.Column(db.DateTime)
    delivered_by_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    delivered_at = db.Column(db.DateTime)
    cancelled_by_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    cancelled_at = db.Column(db.DateTime)
    cancel_reason = db.Column(db.String(500))

    line_items = db.relationship('DeliveryReceiptItem', backref='delivery_receipt',
                                 lazy='select', cascade='all, delete-orphan',
                                 order_by='DeliveryReceiptItem.line_number')

    def __repr__(self):
        return f'<DeliveryReceipt {self.dr_number} - {self.status}>'

    def to_dict(self):
        return {
            'id': self.id, 'dr_number': self.dr_number, 'status': self.status,
            'delivery_date': self.delivery_date.isoformat() if self.delivery_date else None,
            'sales_order_id': self.sales_order_id,
            'sales_order_number': self.sales_order.so_number if self.sales_order else None,
            'customer_name': self.customer_name,
            'salesperson_id': self.salesperson_id,
            'salesperson_name': self.salesperson.full_name if self.salesperson else None,
        }


class DeliveryReceiptItem(db.Model):
    __tablename__ = 'delivery_receipt_items'

    id = db.Column(db.Integer, primary_key=True)
    delivery_receipt_id = db.Column(db.Integer, db.ForeignKey('delivery_receipts.id'),
                                    nullable=False, index=True)
    line_number = db.Column(db.Integer, nullable=False)
    sales_order_item_id = db.Column(db.Integer, db.ForeignKey('sales_order_items.id'),
                                    nullable=False, index=True)
    sales_order_item = db.relationship('SalesOrderItem', foreign_keys=[sales_order_item_id])
    product_id = db.Column(db.Integer, db.ForeignKey('products.id'), nullable=True)  # snapshot for print
    product = db.relationship('Product', foreign_keys=[product_id])
    delivered_quantity = db.Column(db.Numeric(15, 4), nullable=False)

    # The `qty_fmt` filter (app.utils.format_line_qty) duck-types a line item on
    # `quantity` / `unit_of_measure` / `uom_text`. A DR line's quantity is the
    # DELIVERED quantity, and its UoM belongs to the SO line it delivers against.
    @property
    def quantity(self):
        return self.delivered_quantity

    @property
    def unit_of_measure(self):
        soi = self.sales_order_item
        return soi.unit_of_measure if soi else None

    @property
    def uom_text(self):
        soi = self.sales_order_item
        return soi.uom_text if soi else None

    def to_dict(self):
        soi = self.sales_order_item
        return {
            'id': self.id, 'line_number': self.line_number,
            'sales_order_item_id': self.sales_order_item_id,
            'delivered_quantity': float(self.delivered_quantity) if self.delivered_quantity is not None else 0.0,
            'ordered_quantity': float(soi.quantity) if (soi and soi.quantity is not None) else None,
            'product_code': soi.product.code if (soi and soi.product) else (self.product.code if self.product else None),
            'product_name': soi.product.name if (soi and soi.product) else (self.product.name if self.product else None),
            'uom': (soi.unit_of_measure.code if (soi and soi.unit_of_measure) else (soi.uom_text if soi else None)),
            'unit_price': float(soi.unit_price) if (soi and soi.unit_price is not None) else None,
        }


def so_line_open_qty(so_item, exclude_dr_id=None):
    """Ordered qty of an SO line minus the qty already committed by non-cancelled,
    non-draft DR lines (statuses in COMMITTED_STATUSES). Pass exclude_dr_id to leave
    a specific DR out of the sum (used when re-checking the DR being approved)."""
    ordered = Decimal(str(so_item.quantity or 0))
    q = (db.session.query(db.func.coalesce(db.func.sum(DeliveryReceiptItem.delivered_quantity), 0))
         .join(DeliveryReceipt, DeliveryReceiptItem.delivery_receipt_id == DeliveryReceipt.id)
         .filter(DeliveryReceiptItem.sales_order_item_id == so_item.id)
         .filter(DeliveryReceipt.status.in_(COMMITTED_STATUSES)))
    if exclude_dr_id is not None:
        q = q.filter(DeliveryReceipt.id != exclude_dr_id)
    committed = Decimal(str(q.scalar() or 0))
    return ordered - committed


def generate_dr_number(branch_id=None):
    """Next DR-YYYY-MM-#### for the current PH month.

    The sequence is global per month (not per branch), mirroring generate_so_number --
    dr_number is a globally unique column. branch_id is accepted for call-site symmetry.
    """
    today = ph_now().date()
    prefix = f"DR-{today.year:04d}-{today.month:02d}-"
    rows = (DeliveryReceipt.query
            .filter(DeliveryReceipt.dr_number.like(prefix + '%'))
            .with_entities(DeliveryReceipt.dr_number).all())
    nums = []
    for (n,) in rows:
        tail = n.rsplit('-', 1)[-1]
        if tail.isdigit():
            nums.append(int(tail))
    return f"{prefix}{(max(nums) + 1) if nums else 1:04d}"


def post_delivery_je(dr):
    """R-03 seam: on-delivery inventory-relief / COGS journal entry. Inert now (no-op)."""
    return None
