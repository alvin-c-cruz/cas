"""Sales Order — a customer's committed order. Operational, NOT accounting:
posts no journal entry, has no GL account/WHT/payment. Mirrors SalesInvoice minus accounting."""
from decimal import Decimal, ROUND_HALF_UP
from app import db
from app.utils import ph_now


class SalesOrder(db.Model):
    __tablename__ = 'sales_orders'

    id = db.Column(db.Integer, primary_key=True)
    branch_id = db.Column(db.Integer, db.ForeignKey('branches.id'), nullable=True, index=True)
    branch = db.relationship('Branch', foreign_keys=[branch_id])

    so_number = db.Column(db.String(50), unique=True, nullable=False, index=True)
    order_date = db.Column(db.Date, nullable=False, index=True)
    expected_delivery_date = db.Column(db.Date, nullable=True)

    customer_id = db.Column(db.Integer, db.ForeignKey('customers.id'), nullable=False, index=True)
    customer = db.relationship('Customer')
    customer_name = db.Column(db.String(200), nullable=False)
    customer_tin = db.Column(db.String(20))
    customer_address = db.Column(db.Text)
    customer_po_number = db.Column(db.String(100))
    customer_po_date = db.Column(db.Date)

    payment_terms = db.Column(db.String(50), default='Net 30')
    reference = db.Column(db.String(100))
    notes = db.Column(db.Text, nullable=False, default='')

    subtotal = db.Column(db.Numeric(15, 2), default=0.00, nullable=False)
    vat_amount = db.Column(db.Numeric(15, 2), default=0.00, nullable=False)
    vat_override = db.Column(db.Boolean, default=False, nullable=False)
    total_amount = db.Column(db.Numeric(15, 2), default=0.00, nullable=False)

    status = db.Column(db.String(20), default='draft', nullable=False, index=True)

    # Forward-compat hook for P-60 (billing); null until billed.
    sales_invoice_id = db.Column(db.Integer, db.ForeignKey('sales_invoices.id'), nullable=True)

    salesperson_id = db.Column(db.Integer, db.ForeignKey('employees.id'), nullable=True, index=True)
    salesperson = db.relationship('Employee', foreign_keys=[salesperson_id])
    created_by_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    created_at = db.Column(db.DateTime, default=ph_now, nullable=False)
    updated_at = db.Column(db.DateTime, default=ph_now, onupdate=ph_now, nullable=False)
    confirmed_by_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    confirmed_at = db.Column(db.DateTime)
    cancelled_by_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    cancelled_at = db.Column(db.DateTime)
    cancel_reason = db.Column(db.String(500), nullable=True)

    line_items = db.relationship('SalesOrderItem', backref='order', lazy='select',
                                 cascade='all, delete-orphan', order_by='SalesOrderItem.line_number')

    def calculate_totals(self):
        self.subtotal = sum((Decimal(str(li.amount or 0)) for li in self.line_items), Decimal('0.00'))
        self.vat_amount = sum((Decimal(str(li.vat_amount or 0)) for li in self.line_items), Decimal('0.00'))
        self.total_amount = self.subtotal   # no WHT on an SO

    def to_dict(self):
        return {'id': self.id, 'so_number': self.so_number,
                'order_date': self.order_date.isoformat() if self.order_date else None,
                'customer_name': self.customer_name, 'status': self.status,
                'salesperson_id': self.salesperson_id,
                'salesperson_name': self.salesperson.full_name if self.salesperson else None,
                'total_amount': float(self.total_amount) if self.total_amount is not None else 0.0}


class SalesOrderItem(db.Model):
    __tablename__ = 'sales_order_items'

    id = db.Column(db.Integer, primary_key=True)
    sales_order_id = db.Column(db.Integer, db.ForeignKey('sales_orders.id'), nullable=False, index=True)
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
        """Extract VAT from VAT-inclusive amount. Mirrors SalesInvoiceItem minus account/WHT."""
        # Derived amount when itemized (VAT-inclusive): amount = qty × unit_price.
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
            'amount': float(self.amount) if self.amount is not None else 0.0,
            'quantity': float(self.quantity) if self.quantity is not None else None,
            'unit_price': float(self.unit_price) if self.unit_price is not None else None,
            'uom_text': self.uom_text, 'unit_of_measure_id': self.unit_of_measure_id,
            'uom_code': self.unit_of_measure.code if self.unit_of_measure else None,
            'uom_name': self.unit_of_measure.name if self.unit_of_measure else None,
            'uom_display': (self.unit_of_measure.code if self.unit_of_measure else self.uom_text),
            'product_id': self.product_id,
            'product_code': self.product.code if self.product else None,
            'product_name': self.product.name if self.product else None,
            'vat_category': self.vat_category,
            'vat_rate': float(self.vat_rate) if self.vat_rate is not None else 0.0,
        }


def copy_salesperson(src, dst):
    """Carry the salesperson down the SO->DR->SI chain (future cascade hook)."""
    dst.salesperson_id = src.salesperson_id
