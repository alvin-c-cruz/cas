"""Purchase Order — a committed order to a vendor. Buy-side mirror of SalesOrder.
Operational, NOT accounting: posts no journal entry, has no GL account/WHT/payment.
The Bill (Accounts Payable) is the first document in the chain that hits the ledger.

vat_treatment mirrors Quotation (inclusive / exclusive / zero_rated). Two seams are created
here but stay inert until later phases: `purchase_request_id` (Phase 4 PR->PO conversion) and
`accounts_payable_id` (Phase 3 billing). Line-level `received_quantity` / `billed_quantity` are
written by the Receiving Report (Phase 2) and the AP picker (Phase 3) respectively."""
from decimal import Decimal, ROUND_HALF_UP
from app import db
from app.utils import ph_now
from app.utils.concurrency import RowVersioned

VAT_TREATMENTS = ('inclusive', 'exclusive', 'zero_rated')
STANDARD_VAT_RATE = Decimal('12')


class PurchaseOrder(RowVersioned, db.Model):
    __tablename__ = 'purchase_orders'

    id = db.Column(db.Integer, primary_key=True)
    branch_id = db.Column(db.Integer, db.ForeignKey('branches.id'), nullable=True, index=True)
    branch = db.relationship('Branch', foreign_keys=[branch_id])

    po_number = db.Column(db.String(50), unique=True, nullable=False, index=True)
    order_date = db.Column(db.Date, nullable=True, index=True)
    expected_date = db.Column(db.Date, nullable=True)

    vendor_id = db.Column(db.Integer, db.ForeignKey('vendors.id'), nullable=True, index=True)
    vendor = db.relationship('Vendor')
    vendor_name = db.Column(db.String(200))
    vendor_tin = db.Column(db.String(30))
    vendor_address = db.Column(db.String(300))

    payment_terms = db.Column(db.String(50), default='Net 30')
    reference = db.Column(db.String(100))
    notes = db.Column(db.Text, nullable=False, default='')
    vat_treatment = db.Column(db.String(10), default='inclusive', nullable=False)

    status = db.Column(db.String(20), default='draft', nullable=False, index=True)

    # Chain link: the Purchase Request this PO was created from on convert (null for directly-entered
    # POs). Plain Integer (no ORM FK) on purpose -- the reverse edge PurchaseRequest.purchase_order_id
    # forms the pair; declaring an FK both ways creates a metadata cycle SQLAlchemy can't sort for
    # create_all/drop_all. Mirrors SalesOrder.quotation_id (migration 29500ade76f8). Inert until Phase 4.
    purchase_request_id = db.Column(db.Integer, nullable=True, index=True)

    # Billing seam (Phase 3): set when a Bill is cut against this PO (services path). Null until billed.
    accounts_payable_id = db.Column(db.Integer, db.ForeignKey('accounts_payable.id'), nullable=True)

    subtotal = db.Column(db.Numeric(15, 2), default=0.00, nullable=False)
    vat_amount = db.Column(db.Numeric(15, 2), default=0.00, nullable=False)
    vat_override = db.Column(db.Boolean, default=False, nullable=False)
    total_amount = db.Column(db.Numeric(15, 2), default=0.00, nullable=False)

    created_by_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    created_at = db.Column(db.DateTime, default=ph_now, nullable=False)
    updated_at = db.Column(db.DateTime, default=ph_now, onupdate=ph_now, nullable=False)
    approved_by_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    approved_at = db.Column(db.DateTime)
    cancelled_by_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    cancelled_at = db.Column(db.DateTime)
    cancel_reason = db.Column(db.String(500), nullable=True)

    line_items = db.relationship('PurchaseOrderItem', backref='order', lazy='select',
                                 cascade='all, delete-orphan',
                                 order_by='PurchaseOrderItem.line_number')

    def calculate_totals(self):
        """Header totals branch on vat_treatment (mirror Quotation.calculate_totals)."""
        gross = sum((Decimal(str(li.amount or 0)) for li in self.line_items), Decimal('0.00'))
        if self.vat_treatment == 'exclusive':
            self.subtotal = gross                                 # net
            self.vat_amount = (gross * STANDARD_VAT_RATE / 100).quantize(Decimal('0.01'), ROUND_HALF_UP)
            self.total_amount = self.subtotal + self.vat_amount
        elif self.vat_treatment == 'zero_rated':
            self.subtotal = gross
            self.vat_amount = Decimal('0.00')
            self.total_amount = gross
        else:  # inclusive
            self.subtotal = gross
            self.vat_amount = sum((Decimal(str(li.vat_amount or 0)) for li in self.line_items),
                                  Decimal('0.00'))
            self.total_amount = gross

    def to_dict(self):
        return {'id': self.id, 'po_number': self.po_number,
                'order_date': self.order_date.isoformat() if self.order_date else None,
                'vendor_name': self.vendor_name, 'status': self.status,
                'vat_treatment': self.vat_treatment,
                'total_amount': float(self.total_amount) if self.total_amount is not None else 0.0}


class PurchaseOrderItem(db.Model):
    __tablename__ = 'purchase_order_items'

    id = db.Column(db.Integer, primary_key=True)
    purchase_order_id = db.Column(db.Integer, db.ForeignKey('purchase_orders.id'),
                                  nullable=False, index=True)
    line_number = db.Column(db.Integer, nullable=False)
    description = db.Column(db.String(255), nullable=True)   # free-text (service lines w/o a product)
    amount = db.Column(db.Numeric(15, 2), default=0.00, nullable=False)
    quantity = db.Column(db.Numeric(15, 4), nullable=True)
    unit_price = db.Column(db.Numeric(15, 2), nullable=True)
    uom_text = db.Column(db.String(20), nullable=True)
    unit_of_measure_id = db.Column(db.Integer, db.ForeignKey('units_of_measure.id'), nullable=True)
    product_id = db.Column(db.Integer, db.ForeignKey('products.id'), nullable=True)
    unit_of_measure = db.relationship('UnitOfMeasure')
    product = db.relationship('Product')
    vat_category = db.Column(db.String(100))
    vat_rate = db.Column(db.Numeric(5, 2), default=0.00, nullable=False)
    line_total = db.Column(db.Numeric(15, 2), default=0.00, nullable=False)
    vat_amount = db.Column(db.Numeric(15, 2), default=0.00, nullable=False)

    # Fulfilment tracking: received_quantity written by the Receiving Report (Phase 2),
    # billed_quantity written by the AP billing picker (Phase 3). Both default 0.
    received_quantity = db.Column(db.Numeric(15, 4), default=0)
    billed_quantity = db.Column(db.Numeric(15, 4), default=0)

    def calculate_amounts(self):
        """Extract VAT from VAT-inclusive amount. Mirrors SalesOrderItem/QuotationItem."""
        if self.quantity is not None and self.unit_price is not None:
            q = Decimal(str(self.quantity)); up = Decimal(str(self.unit_price))
            if q > 0 and up > 0:
                self.amount = (q * up).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        amt = Decimal(str(self.amount or 0))
        rate = Decimal(str(self.vat_rate or 0))
        if rate > 0:
            net = (amt / (1 + rate / 100)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
            self.vat_amount = amt - net
        else:
            self.vat_amount = Decimal('0.00')
        self.line_total = amt

    def to_dict(self):
        return {
            'id': self.id, 'line_number': self.line_number,
            'description': self.description,
            'amount': float(self.amount) if self.amount is not None else 0.0,
            'quantity': float(self.quantity) if self.quantity is not None else None,
            'unit_price': float(self.unit_price) if self.unit_price is not None else None,
            'uom_text': self.uom_text, 'unit_of_measure_id': self.unit_of_measure_id,
            'uom_display': (self.unit_of_measure.code if self.unit_of_measure else self.uom_text),
            'product_id': self.product_id,
            'product_code': self.product.code if self.product else None,
            'product_name': self.product.name if self.product else None,
            'vat_category': self.vat_category,
            'vat_rate': float(self.vat_rate) if self.vat_rate is not None else 0.0,
            'received_quantity': float(self.received_quantity) if self.received_quantity is not None else 0.0,
            'billed_quantity': float(self.billed_quantity) if self.billed_quantity is not None else 0.0,
        }


def generate_po_number():
    """Next PO-YYYY-MM-#### for the current PH month (mirror generate_so_number)."""
    today = ph_now().date()
    prefix = f"PO-{today.year:04d}-{today.month:02d}-"
    rows = (PurchaseOrder.query
            .filter(PurchaseOrder.po_number.like(prefix + '%'))
            .with_entities(PurchaseOrder.po_number).all())
    nums = []
    for (n,) in rows:
        tail = n.rsplit('-', 1)[-1]
        if tail.isdigit():
            nums.append(int(tail))
    return f"{prefix}{(max(nums) + 1) if nums else 1:04d}"
