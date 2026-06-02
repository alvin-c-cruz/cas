"""
Sales Invoice models for customer billing and revenue tracking.

Supports:
- Invoice header with customer details
- Line items with products/services
- VAT calculation per line
- Multiple payment terms
- Invoice status tracking
"""
from app import db
from app.utils import ph_now
from decimal import Decimal


class SalesInvoice(db.Model):
    """
    Sales Invoice header model.

    Philippine SME requirements:
    - Invoice number (SI-2024-0001 format)
    - Customer reference (TIN for BIR compliance)
    - Date issued and due date
    - VAT calculation per line
    - Total amounts with/without VAT
    """
    __tablename__ = 'sales_invoices'

    id = db.Column(db.Integer, primary_key=True)

    # Invoice identification
    invoice_number = db.Column(db.String(50), unique=True, nullable=False, index=True)
    invoice_date = db.Column(db.Date, nullable=False, index=True)
    due_date = db.Column(db.Date, nullable=False)

    # Customer reference
    customer_id = db.Column(db.Integer, db.ForeignKey('customers.id'), nullable=False, index=True)
    customer = db.relationship('Customer', backref='sales_invoices')

    # Customer details snapshot (for historical accuracy)
    customer_name = db.Column(db.String(200), nullable=False)
    customer_tin = db.Column(db.String(20))
    customer_address = db.Column(db.Text)

    # Payment terms
    payment_terms = db.Column(db.String(50), default='Net 30')

    # Reference fields
    reference = db.Column(db.String(100))  # PO number, job order, etc.
    notes = db.Column(db.Text)

    # Financial totals (computed from line items)
    subtotal = db.Column(db.Numeric(15, 2), default=0.00, nullable=False)  # Before VAT
    vat_amount = db.Column(db.Numeric(15, 2), default=0.00, nullable=False)
    total_amount = db.Column(db.Numeric(15, 2), default=0.00, nullable=False)  # Including VAT

    # Status tracking
    status = db.Column(db.String(20), default='draft', nullable=False, index=True)
    # Statuses: draft, posted, paid, partially_paid, cancelled

    # Payment tracking
    amount_paid = db.Column(db.Numeric(15, 2), default=0.00, nullable=False)
    balance = db.Column(db.Numeric(15, 2), default=0.00, nullable=False)

    # Audit fields
    created_by_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    created_by = db.relationship('User', foreign_keys=[created_by_id], backref='created_sales_invoices')
    posted_by_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    posted_by = db.relationship('User', foreign_keys=[posted_by_id], backref='posted_sales_invoices')

    # Timestamps
    created_at = db.Column(db.DateTime, default=ph_now, nullable=False)
    updated_at = db.Column(db.DateTime, default=ph_now, onupdate=ph_now, nullable=False)
    posted_at = db.Column(db.DateTime)
    cancelled_at = db.Column(db.DateTime)

    # Relationship to line items
    line_items = db.relationship('SalesInvoiceItem', backref='invoice', lazy='dynamic',
                                 cascade='all, delete-orphan', order_by='SalesInvoiceItem.line_number')

    def __repr__(self):
        return f'<SalesInvoice {self.invoice_number}>'

    def calculate_totals(self):
        """Calculate invoice totals from line items."""
        self.subtotal = Decimal('0.00')
        self.vat_amount = Decimal('0.00')

        for item in self.line_items:
            self.subtotal += item.line_total
            self.vat_amount += item.vat_amount

        self.total_amount = self.subtotal + self.vat_amount
        self.balance = self.total_amount - self.amount_paid

    def to_dict(self):
        """Convert invoice to dictionary for JSON serialization."""
        return {
            'id': self.id,
            'invoice_number': self.invoice_number,
            'invoice_date': self.invoice_date.isoformat() if self.invoice_date else None,
            'due_date': self.due_date.isoformat() if self.due_date else None,
            'customer_id': self.customer_id,
            'customer_name': self.customer_name,
            'customer_tin': self.customer_tin,
            'payment_terms': self.payment_terms,
            'reference': self.reference,
            'subtotal': float(self.subtotal),
            'vat_amount': float(self.vat_amount),
            'total_amount': float(self.total_amount),
            'amount_paid': float(self.amount_paid),
            'balance': float(self.balance),
            'status': self.status,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'posted_at': self.posted_at.isoformat() if self.posted_at else None
        }


class SalesInvoiceItem(db.Model):
    """
    Sales Invoice line item model.

    Each line represents a product/service sold with:
    - Description and quantity
    - Unit price
    - VAT category and calculation
    - Line total
    """
    __tablename__ = 'sales_invoice_items'

    id = db.Column(db.Integer, primary_key=True)

    # Parent invoice
    invoice_id = db.Column(db.Integer, db.ForeignKey('sales_invoices.id'), nullable=False, index=True)

    # Line ordering
    line_number = db.Column(db.Integer, nullable=False)

    # Item details
    description = db.Column(db.String(500), nullable=False)
    quantity = db.Column(db.Numeric(15, 4), default=1.0000, nullable=False)
    unit_price = db.Column(db.Numeric(15, 2), default=0.00, nullable=False)

    # VAT information
    vat_category = db.Column(db.String(100))  # Reference to VAT category
    vat_rate = db.Column(db.Numeric(5, 2), default=0.00, nullable=False)  # Snapshot of rate

    # Calculated amounts
    line_total = db.Column(db.Numeric(15, 2), default=0.00, nullable=False)  # qty * price
    vat_amount = db.Column(db.Numeric(15, 2), default=0.00, nullable=False)  # line_total * vat_rate / 100

    # Account reference (for posting to GL)
    account_id = db.Column(db.Integer, db.ForeignKey('accounts.id'))
    account = db.relationship('Account')

    def __repr__(self):
        return f'<SalesInvoiceItem {self.invoice_id}-{self.line_number}>'

    def calculate_amounts(self):
        """Calculate line totals and VAT amount."""
        self.line_total = Decimal(str(self.quantity)) * Decimal(str(self.unit_price))
        self.vat_amount = self.line_total * Decimal(str(self.vat_rate)) / Decimal('100')

    def to_dict(self):
        """Convert line item to dictionary."""
        return {
            'id': self.id,
            'line_number': self.line_number,
            'description': self.description,
            'quantity': float(self.quantity),
            'unit_price': float(self.unit_price),
            'vat_category': self.vat_category,
            'vat_rate': float(self.vat_rate),
            'line_total': float(self.line_total),
            'vat_amount': float(self.vat_amount),
            'account_id': self.account_id
        }
