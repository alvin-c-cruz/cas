"""Purchase Request -- a thin internal requisition. Front of the buy-side chain
(PR -> PO -> RR -> Bill). Mirror of Quotation on the sell side. Operational, NOT accounting:
posts no journal entry.

A requisition records WHAT is needed (product / UoM / qty / description) and WHY (reason) --
NO vendor and NO price. On approval it converts into a *draft* Purchase Order where the buyer
adds the vendor and prices (mirror of quotations.accept -> draft SO)."""
from app import db
from app.utils import ph_now
from app.utils.concurrency import RowVersioned


class PurchaseRequest(RowVersioned, db.Model):
    __tablename__ = 'purchase_requests'

    id = db.Column(db.Integer, primary_key=True)
    branch_id = db.Column(db.Integer, db.ForeignKey('branches.id'), nullable=True, index=True)
    branch = db.relationship('Branch', foreign_keys=[branch_id])

    pr_number = db.Column(db.String(50), unique=True, nullable=False, index=True)
    request_date = db.Column(db.Date, nullable=False, index=True)
    reason = db.Column(db.Text)

    status = db.Column(db.String(20), default='draft', nullable=False, index=True)

    # Forward-link to the PO created on convert (this IS a real ORM FK, mirroring
    # Quotation.sales_order_id). The reverse edge PurchaseOrder.purchase_request_id is a bare
    # Integer, so only this side declares the FK -- no metadata cycle.
    purchase_order_id = db.Column(db.Integer, db.ForeignKey('purchase_orders.id'),
                                  nullable=True, index=True)
    purchase_order = db.relationship('PurchaseOrder', foreign_keys=[purchase_order_id])

    created_by_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    created_at = db.Column(db.DateTime, default=ph_now, nullable=False)
    updated_at = db.Column(db.DateTime, default=ph_now, onupdate=ph_now, nullable=False)
    submitted_by_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    submitted_at = db.Column(db.DateTime)
    approved_by_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    approved_at = db.Column(db.DateTime)
    rejected_by_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    rejected_at = db.Column(db.DateTime)
    reject_reason = db.Column(db.String(500))
    cancelled_by_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    cancelled_at = db.Column(db.DateTime)
    cancel_reason = db.Column(db.String(500))

    line_items = db.relationship('PurchaseRequestItem', backref='purchase_request',
                                 lazy='select', cascade='all, delete-orphan',
                                 order_by='PurchaseRequestItem.line_number')

    def to_dict(self):
        return {'id': self.id, 'pr_number': self.pr_number, 'status': self.status,
                'request_date': self.request_date.isoformat() if self.request_date else None,
                'purchase_order_id': self.purchase_order_id,
                'purchase_order_number': self.purchase_order.po_number if self.purchase_order else None}


class PurchaseRequestItem(db.Model):
    __tablename__ = 'purchase_request_items'

    id = db.Column(db.Integer, primary_key=True)
    purchase_request_id = db.Column(db.Integer, db.ForeignKey('purchase_requests.id'),
                                    nullable=False, index=True)
    line_number = db.Column(db.Integer, nullable=False)
    description = db.Column(db.String(255), nullable=True)
    quantity = db.Column(db.Numeric(15, 4), nullable=True)
    uom_text = db.Column(db.String(20), nullable=True)
    unit_of_measure_id = db.Column(db.Integer, db.ForeignKey('units_of_measure.id'), nullable=True)
    product_id = db.Column(db.Integer, db.ForeignKey('products.id'), nullable=True)
    unit_of_measure = db.relationship('UnitOfMeasure')
    product = db.relationship('Product')
    # NO price / amount / vat -- the buyer supplies pricing at PO conversion.

    def to_dict(self):
        return {
            'id': self.id, 'line_number': self.line_number,
            'description': self.description,
            'quantity': float(self.quantity) if self.quantity is not None else None,
            'uom_text': self.uom_text, 'unit_of_measure_id': self.unit_of_measure_id,
            'uom_display': (self.unit_of_measure.code if self.unit_of_measure else self.uom_text),
            'product_id': self.product_id,
            'product_code': self.product.code if self.product else None,
            'product_name': self.product.name if self.product else None,
        }


def generate_pr_number(branch_id=None):
    """Next PR-YYYY-MM-#### for the current PH month (global per month; mirror generate_dr_number)."""
    today = ph_now().date()
    prefix = f"PR-{today.year:04d}-{today.month:02d}-"
    rows = (PurchaseRequest.query
            .filter(PurchaseRequest.pr_number.like(prefix + '%'))
            .with_entities(PurchaseRequest.pr_number).all())
    nums = []
    for (n,) in rows:
        tail = n.rsplit('-', 1)[-1]
        if tail.isdigit():
            nums.append(int(tail))
    return f"{prefix}{(max(nums) + 1) if nums else 1:04d}"
