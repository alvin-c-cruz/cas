"""
Sales Invoice models for customer billing and revenue tracking.

Supports:
- Invoice header with customer details
- Line items with products/services
- VAT-inclusive amounts (VAT is extracted, not added)
- WHT on the invoice (customer deducts on payment; booked as Creditable WHT Receivable)
- Journal entry link (created on save, promoted on post)
- Invoice status tracking
"""
from app import db
from app.utils import ph_now
from decimal import Decimal


class SalesInvoice(db.Model):
    """
    Sales Invoice header model.

    Philippine SME requirements:
    - Invoice number (SI-2026-MM-NNNN format)
    - Customer reference (TIN for BIR compliance)
    - Date issued and due date
    - VAT-inclusive line items (VAT extracted, not added)
    - WHT receivable tracking (customer deducts WHT on payment)
    - Total amounts before and after WHT
    - Journal entry linked via journal_entry_id FK
    """
    __tablename__ = 'sales_invoices'

    id = db.Column(db.Integer, primary_key=True)

    # Branch association
    branch_id = db.Column(db.Integer, db.ForeignKey('branches.id'), nullable=True, index=True)
    branch = db.relationship('Branch', foreign_keys=[branch_id])

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

    # Customer PO / reference
    customer_po_number = db.Column(db.String(100))
    customer_po_date = db.Column(db.Date)

    # Payment terms
    payment_terms = db.Column(db.String(50), default='Net 30')

    # Reference fields
    reference = db.Column(db.String(100))
    notes = db.Column(db.Text, nullable=False, default='')

    # Financial totals (computed from line items)
    # subtotal = VAT-inclusive sum of all line amounts
    subtotal = db.Column(db.Numeric(15, 2), default=0.00, nullable=False)
    # vat_amount = output VAT extracted from subtotal
    vat_amount = db.Column(db.Numeric(15, 2), default=0.00, nullable=False)
    # total_before_wt = equals subtotal (VAT extracted, not added)
    total_before_wt = db.Column(db.Numeric(15, 2), default=0.00, nullable=False)

    # Withholding tax (customer deducts on payment)
    withholding_tax_amount = db.Column(db.Numeric(15, 2), default=0.00, nullable=False)

    # Override flags — when True, vat_amount / withholding_tax_amount were manually set
    vat_override = db.Column(db.Boolean, default=False, nullable=False)
    wt_override = db.Column(db.Boolean, default=False, nullable=False)

    # Net receivable (subtotal - WHT)
    total_amount = db.Column(db.Numeric(15, 2), default=0.00, nullable=False)

    # Linked journal entry (created on save; promoted on post)
    journal_entry_id = db.Column(db.Integer, db.ForeignKey('journal_entries.id'), nullable=True)
    journal_entry = db.relationship('JournalEntry', foreign_keys=[journal_entry_id])

    # Status tracking
    # Statuses: draft, posted, partially_paid, paid, cancelled, voided
    status = db.Column(db.String(20), default='draft', nullable=False, index=True)

    # Payment tracking
    amount_paid = db.Column(db.Numeric(15, 2), default=0.00, nullable=False)
    balance = db.Column(db.Numeric(15, 2), default=0.00, nullable=False)

    # Audit fields
    created_by_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    created_by = db.relationship('User', foreign_keys=[created_by_id], backref='created_sales_invoices')
    posted_by_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    posted_by = db.relationship('User', foreign_keys=[posted_by_id], backref='posted_sales_invoices')
    voided_by_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    voided_by = db.relationship('User', foreign_keys=[voided_by_id], backref='voided_sales_invoices')

    # Timestamps
    created_at = db.Column(db.DateTime, default=ph_now, nullable=False)
    updated_at = db.Column(db.DateTime, default=ph_now, onupdate=ph_now, nullable=False)
    posted_at = db.Column(db.DateTime)
    cancelled_at = db.Column(db.DateTime)
    sent_at = db.Column(db.DateTime)
    sent_by_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    sent_by = db.relationship('User', foreign_keys=[sent_by_id], backref='sent_sales_invoices')
    voided_at = db.Column(db.DateTime)
    void_reason = db.Column(db.String(255))
    cancel_reason = db.Column(db.String(500), nullable=True)

    # Relationships to line items and attachments
    line_items = db.relationship('SalesInvoiceItem', backref='invoice', lazy='select',
                                 cascade='all, delete-orphan', order_by='SalesInvoiceItem.line_number')
    attachments = db.relationship('SalesInvoiceAttachment', backref='invoice', lazy='select',
                                  cascade='all, delete-orphan', order_by='SalesInvoiceAttachment.uploaded_at')

    def __repr__(self):
        return f'<SalesInvoice {self.invoice_number}>'

    def calculate_totals(self):
        subtotal = Decimal('0.00')
        auto_vat = Decimal('0.00')
        auto_wt = Decimal('0.00')
        for item in self.line_items:
            subtotal += Decimal(str(item.line_total))
            auto_vat += Decimal(str(item.vat_amount or 0))
            auto_wt += Decimal(str(item.wt_amount or 0))
        self.subtotal = subtotal
        if not self.vat_override:
            self.vat_amount = auto_vat
        if not self.wt_override:
            self.withholding_tax_amount = auto_wt
        self.total_before_wt = self.subtotal
        self.total_amount = self.subtotal - Decimal(str(self.withholding_tax_amount))
        self.balance = self.total_amount - Decimal(str(self.amount_paid))

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
            'customer_po_number': self.customer_po_number,
            'payment_terms': self.payment_terms,
            'reference': self.reference,
            'subtotal': float(self.subtotal),
            'vat_amount': float(self.vat_amount),
            'total_before_wt': float(self.total_before_wt),
            'withholding_tax_amount': float(self.withholding_tax_amount),
            'total_amount': float(self.total_amount),
            'amount_paid': float(self.amount_paid),
            'balance': float(self.balance),
            'status': self.status,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'posted_at': self.posted_at.isoformat() if self.posted_at else None,
        }


class SalesInvoiceItem(db.Model):
    __tablename__ = 'sales_invoice_items'

    id = db.Column(db.Integer, primary_key=True)
    invoice_id = db.Column(db.Integer, db.ForeignKey('sales_invoices.id'), nullable=False, index=True)
    line_number = db.Column(db.Integer, nullable=False)
    description = db.Column(db.String(500), nullable=False)
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

    account_id = db.Column(db.Integer, db.ForeignKey('accounts.id'))
    account = db.relationship('Account')

    wt_id = db.Column(db.Integer, db.ForeignKey('withholding_tax.id'), nullable=True)
    withholding_tax = db.relationship('WithholdingTax', foreign_keys=[wt_id])
    wt_rate = db.Column(db.Numeric(5, 2), nullable=True)
    wt_amount = db.Column(db.Numeric(15, 2), default=Decimal('0.00'), nullable=False)

    def __repr__(self):
        return f'<SalesInvoiceItem {self.invoice_id}-{self.line_number}>'

    def calculate_amounts(self):
        """Extract VAT from VAT-inclusive amount; compute WHT on net base."""
        # Derived amount when itemized: amount = qty × unit_price (VAT-inclusive).
        if self.quantity is not None and self.unit_price is not None:
            q = Decimal(str(self.quantity)); up = Decimal(str(self.unit_price))
            if q > 0 and up > 0:
                self.amount = (q * up).quantize(Decimal('0.01'), rounding='ROUND_HALF_UP')
        vat_rate = Decimal(str(self.vat_rate)) if self.vat_rate else Decimal('0')
        amount = Decimal(str(self.amount)) if self.amount else Decimal('0')
        if vat_rate > 0:
            net_base = amount / (1 + vat_rate / Decimal('100'))
        else:
            net_base = amount
        self.line_total = amount
        self.vat_amount = (amount - net_base).quantize(
            Decimal('0.01'), rounding='ROUND_HALF_UP')
        # WHT base is Net of VAT = Gross - rounded VAT (owner formula, RIC books),
        # NOT the unrounded Gross/1.12 — the two differ by a centavo on residual lines.
        net_of_vat = amount - self.vat_amount
        wt_rate = Decimal(str(self.wt_rate)) if self.wt_rate else Decimal('0')
        self.wt_amount = (net_of_vat * wt_rate / Decimal('100')).quantize(
            Decimal('0.01'), rounding='ROUND_HALF_UP')

    def to_dict(self):
        return {
            'id': self.id,
            'line_number': self.line_number,
            'description': self.description,
            'amount': float(self.amount),
            'quantity': float(self.quantity) if self.quantity is not None else None,
            'unit_price': float(self.unit_price) if self.unit_price is not None else None,
            'uom_text': self.uom_text,
            'unit_of_measure_id': self.unit_of_measure_id,
            'uom_code': self.unit_of_measure.code if self.unit_of_measure else None,
            'uom_name': self.unit_of_measure.name if self.unit_of_measure else None,
            'uom_display': (self.unit_of_measure.code if self.unit_of_measure else self.uom_text),
            'product_id': self.product_id,
            'product_code': self.product.code if self.product else None,
            'product_name': self.product.name if self.product else None,
            'vat_category': self.vat_category,
            'vat_rate': float(self.vat_rate),
            'line_total': float(self.line_total),
            'vat_amount': float(self.vat_amount),
            'account_id': self.account_id,
            'wt_id': self.wt_id,
            'wt_rate': float(self.wt_rate) if self.wt_rate is not None else None,
            'wt_amount': float(self.wt_amount),
        }


class SalesInvoiceAttachment(db.Model):
    __tablename__ = 'sales_invoice_attachments'

    id = db.Column(db.Integer, primary_key=True)
    invoice_id = db.Column(db.Integer, db.ForeignKey('sales_invoices.id'),
                           nullable=False, index=True)
    original_filename = db.Column(db.String(255), nullable=False)
    stored_filename = db.Column(db.String(255), nullable=False, unique=True)
    mime_type = db.Column(db.String(100), nullable=False)
    file_size = db.Column(db.Integer, nullable=False)
    uploaded_by_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    uploaded_by = db.relationship('User', foreign_keys=[uploaded_by_id],
                                  backref='uploaded_invoice_attachments')
    uploaded_at = db.Column(db.DateTime, default=ph_now, nullable=False)

    def __repr__(self):
        return f'<SalesInvoiceAttachment {self.original_filename} invoice={self.invoice_id}>'

    @property
    def is_image(self):
        return self.mime_type.startswith('image/')

    @property
    def file_size_human(self):
        if self.file_size < 1024:
            return f'{self.file_size} B'
        if self.file_size < 1024 * 1024:
            return f'{self.file_size / 1024:.1f} KB'
        return f'{self.file_size / (1024 * 1024):.1f} MB'
