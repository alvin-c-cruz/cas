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
        """Compute invoice totals from VAT-inclusive line amounts.

        When line_items exist, aggregates from them.
        When no line items exist (e.g. manual or round-trip), uses existing
        subtotal/vat_amount/withholding_tax_amount to recompute derived fields.
        """
        if self.line_items:
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

        self.total_before_wt = Decimal(str(self.subtotal))   # VAT is extracted from subtotal, not added
        self.total_amount = Decimal(str(self.subtotal)) - Decimal(str(self.withholding_tax_amount))
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


# Stubs — full implementation in Task 4
class SalesInvoiceItem(db.Model):
    __tablename__ = 'sales_invoice_items'
    id = db.Column(db.Integer, primary_key=True)
    invoice_id = db.Column(db.Integer, db.ForeignKey('sales_invoices.id'), nullable=False)
    line_number = db.Column(db.Integer, nullable=False)
    description = db.Column(db.String(500), nullable=False)
    amount = db.Column(db.Numeric(15, 2), default=0.00, nullable=False)
    quantity = db.Column(db.Numeric(15, 4), default=1.0000, nullable=False)
    unit_price = db.Column(db.Numeric(15, 2), default=0.00, nullable=False)
    vat_category = db.Column(db.String(100))
    vat_rate = db.Column(db.Numeric(5, 2), default=0.00, nullable=False)
    line_total = db.Column(db.Numeric(15, 2), default=0.00, nullable=False)
    vat_amount = db.Column(db.Numeric(15, 2), default=0.00, nullable=False)
    account_id = db.Column(db.Integer, db.ForeignKey('accounts.id'))
    account = db.relationship('Account')
    wt_id = db.Column(db.Integer, db.ForeignKey('withholding_tax.id'), nullable=True)
    wt_rate = db.Column(db.Numeric(5, 2), nullable=True)
    wt_amount = db.Column(db.Numeric(15, 2), default=Decimal('0.00'), nullable=False)

    def calculate_amounts(self):
        pass

    def to_dict(self):
        return {}


class SalesInvoiceAttachment(db.Model):
    __tablename__ = 'sales_invoice_attachments'
    id = db.Column(db.Integer, primary_key=True)
    invoice_id = db.Column(db.Integer, db.ForeignKey('sales_invoices.id'), nullable=False)
    original_filename = db.Column(db.String(255), nullable=False)
    stored_filename = db.Column(db.String(255), nullable=False, unique=True)
    mime_type = db.Column(db.String(100), nullable=False)
    file_size = db.Column(db.Integer, nullable=False)
    uploaded_by_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    uploaded_by = db.relationship('User', foreign_keys=[uploaded_by_id],
                                  backref='uploaded_invoice_attachments')
    uploaded_at = db.Column(db.DateTime, default=ph_now, nullable=False)
