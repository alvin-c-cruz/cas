"""Quotation — a product-priced pre-sale offer. Front of the O2C chain (Quote -> SO -> DR -> SI).
Operational, NOT accounting (posts no JE). vat_treatment is Quotation-only; the SO it creates on
accept is always VAT-inclusive."""
from decimal import Decimal, ROUND_HALF_UP
from app import db
from app.utils import ph_now

VAT_TREATMENTS = ('inclusive', 'exclusive', 'zero_rated')
STANDARD_VAT_RATE = Decimal('12')


class Quotation(db.Model):
    __tablename__ = 'quotations'

    id = db.Column(db.Integer, primary_key=True)
    branch_id = db.Column(db.Integer, db.ForeignKey('branches.id'), nullable=True, index=True)
    branch = db.relationship('Branch', foreign_keys=[branch_id])

    quotation_number = db.Column(db.String(50), unique=True, nullable=False, index=True)
    quotation_date = db.Column(db.Date, nullable=False, index=True)
    valid_until = db.Column(db.Date, nullable=True)

    customer_id = db.Column(db.Integer, db.ForeignKey('customers.id'), nullable=False, index=True)
    customer = db.relationship('Customer')
    customer_name = db.Column(db.String(200), nullable=False)
    customer_tin = db.Column(db.String(20))
    customer_address = db.Column(db.Text)

    payment_terms = db.Column(db.String(50), default='Net 30')
    reference = db.Column(db.String(100))
    notes = db.Column(db.Text, nullable=False, default='')
    vat_treatment = db.Column(db.String(10), default='inclusive', nullable=False)

    status = db.Column(db.String(20), default='draft', nullable=False, index=True)

    salesperson_id = db.Column(db.Integer, db.ForeignKey('employees.id'), nullable=True, index=True)
    salesperson = db.relationship('Employee', foreign_keys=[salesperson_id])
    sales_order_id = db.Column(db.Integer, db.ForeignKey('sales_orders.id'), nullable=True, index=True)
    sales_order = db.relationship('SalesOrder', foreign_keys=[sales_order_id])

    subtotal = db.Column(db.Numeric(15, 2), default=0.00, nullable=False)
    vat_amount = db.Column(db.Numeric(15, 2), default=0.00, nullable=False)
    total_amount = db.Column(db.Numeric(15, 2), default=0.00, nullable=False)

    created_by_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    created_at = db.Column(db.DateTime, default=ph_now, nullable=False)
    updated_at = db.Column(db.DateTime, default=ph_now, onupdate=ph_now, nullable=False)
    sent_by_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    sent_at = db.Column(db.DateTime)
    accepted_by_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    accepted_at = db.Column(db.DateTime)
    rejected_by_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    rejected_at = db.Column(db.DateTime)
    reject_reason = db.Column(db.String(500))
    cancelled_by_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    cancelled_at = db.Column(db.DateTime)
    cancel_reason = db.Column(db.String(500))

    line_items = db.relationship('QuotationItem', backref='quotation', lazy='select',
                                 cascade='all, delete-orphan', order_by='QuotationItem.line_number')

    @property
    def is_expired(self):
        return (self.status == 'sent' and self.valid_until is not None
                and self.valid_until < ph_now().date())

    def calculate_totals(self):
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
        return {
            'id': self.id, 'quotation_number': self.quotation_number, 'status': self.status,
            'vat_treatment': self.vat_treatment, 'is_expired': self.is_expired,
            'valid_until': self.valid_until.isoformat() if self.valid_until else None,
            'customer_name': self.customer_name,
            'salesperson_id': self.salesperson_id,
            'salesperson_name': self.salesperson.full_name if self.salesperson else None,
            'sales_order_id': self.sales_order_id,
            'sales_order_number': self.sales_order.so_number if self.sales_order_id and getattr(self, 'sales_order', None) else None,
            'total_amount': float(self.total_amount) if self.total_amount is not None else 0.0,
        }


class QuotationItem(db.Model):
    __tablename__ = 'quotation_items'

    id = db.Column(db.Integer, primary_key=True)
    quotation_id = db.Column(db.Integer, db.ForeignKey('quotations.id'), nullable=False, index=True)
    line_number = db.Column(db.Integer, nullable=False)
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

    def calculate_amounts(self):
        """Amount = qty x unit_price when both set; extract line VAT (inclusive) for the
        inclusive-treatment summary. Mirror SalesOrderItem."""
        if self.quantity is not None and self.unit_price is not None:
            q = Decimal(str(self.quantity)); up = Decimal(str(self.unit_price))
            if q > 0 and up > 0:
                self.amount = (q * up).quantize(Decimal('0.01'), ROUND_HALF_UP)
        amt = Decimal(str(self.amount or 0))
        rate = Decimal(str(self.vat_rate or 0))
        if rate > 0:
            net = (amt / (1 + rate / 100)).quantize(Decimal('0.01'), ROUND_HALF_UP)
            self.vat_amount = amt - net
        else:
            self.vat_amount = Decimal('0.00')
        self.line_total = amt

    def to_dict(self):
        return {
            'id': self.id, 'line_number': self.line_number,
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
        }


def generate_quotation_number(branch_id):
    """Next QTN-YYYY-MM-#### for the current PH month (mirror generate_so_number)."""
    today = ph_now().date()
    prefix = f"QTN-{today.year:04d}-{today.month:02d}-"
    rows = (Quotation.query.filter(Quotation.quotation_number.like(prefix + '%'))
            .with_entities(Quotation.quotation_number).all())
    nums = []
    for (n,) in rows:
        tail = n.rsplit('-', 1)[-1]
        if tail.isdigit():
            nums.append(int(tail))
    return f"{prefix}{(max(nums) + 1) if nums else 1:04d}"
