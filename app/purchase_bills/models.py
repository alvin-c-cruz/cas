"""
Purchase Bill models for supplier invoicing and expense tracking.

Supports:
- Bill header with vendor details
- Line items with expenses/purchases
- VAT input calculation per line
- Withholding tax calculation per bill
- Multiple payment terms
- Bill status tracking
"""
from app import db
from app.utils import ph_now
from decimal import Decimal


class PurchaseBill(db.Model):
    """
    Purchase Bill header model.

    Philippine SME requirements:
    - Bill number (PB-2024-0001 format)
    - Vendor reference (TIN for BIR compliance)
    - Date received and due date
    - VAT input calculation per line
    - Withholding tax calculation on total
    - Total amounts with/without VAT and WT
    """
    __tablename__ = 'purchase_bills'

    id = db.Column(db.Integer, primary_key=True)

    # Branch association
    branch_id = db.Column(db.Integer, db.ForeignKey('branches.id'), nullable=True, index=True)
    branch = db.relationship('Branch', foreign_keys=[branch_id])

    # Bill identification
    bill_number = db.Column(db.String(50), unique=True, nullable=False, index=True)
    bill_date = db.Column(db.Date, nullable=False, index=True)
    due_date = db.Column(db.Date, nullable=False)

    # Vendor reference
    vendor_id = db.Column(db.Integer, db.ForeignKey('vendors.id'), nullable=False, index=True)
    vendor = db.relationship('Vendor', backref='purchase_bills')

    # Vendor details snapshot (for historical accuracy)
    vendor_name = db.Column(db.String(200), nullable=False)
    vendor_tin = db.Column(db.String(20))
    vendor_address = db.Column(db.Text)

    # Vendor's invoice reference
    vendor_invoice_number = db.Column(db.String(100))
    vendor_invoice_date = db.Column(db.Date)

    # Payment terms
    payment_terms = db.Column(db.String(50), default='Net 30')

    # Reference fields
    reference = db.Column(db.String(100))  # PO number, job order, etc.
    notes = db.Column(db.Text)

    # Financial totals (computed from line items)
    subtotal = db.Column(db.Numeric(15, 2), default=0.00, nullable=False)  # VAT-inclusive sum of all line amounts
    vat_amount = db.Column(db.Numeric(15, 2), default=0.00, nullable=False)  # Input VAT
    total_before_wt = db.Column(db.Numeric(15, 2), default=0.00, nullable=False)  # Equals subtotal (VAT extracted from amounts, not added)

    # Withholding tax calculation
    withholding_tax_rate = db.Column(db.Numeric(5, 2), default=0.00, nullable=False)
    withholding_tax_amount = db.Column(db.Numeric(15, 2), default=0.00, nullable=False)

    # Override flags — when True, vat_amount / withholding_tax_amount were manually set
    vat_override = db.Column(db.Boolean, default=False, nullable=False)
    wt_override = db.Column(db.Boolean, default=False, nullable=False)

    # Linked journal entry (posted on save; recreated on edit)
    journal_entry_id = db.Column(db.Integer, db.ForeignKey('journal_entries.id'), nullable=True)
    journal_entry = db.relationship('JournalEntry', foreign_keys=[journal_entry_id])

    # Net payable (Total - WT)
    total_amount = db.Column(db.Numeric(15, 2), default=0.00, nullable=False)

    # Status tracking
    status = db.Column(db.String(20), default='draft', nullable=False, index=True)
    # Statuses: draft, posted, partially_paid, paid, cancelled, voided

    # Payment tracking
    amount_paid = db.Column(db.Numeric(15, 2), default=0.00, nullable=False)
    balance = db.Column(db.Numeric(15, 2), default=0.00, nullable=False)

    # Audit fields
    created_by_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    created_by = db.relationship('User', foreign_keys=[created_by_id], backref='created_purchase_bills')
    posted_by_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    posted_by = db.relationship('User', foreign_keys=[posted_by_id], backref='posted_purchase_bills')

    # Timestamps
    created_at = db.Column(db.DateTime, default=ph_now, nullable=False)
    updated_at = db.Column(db.DateTime, default=ph_now, onupdate=ph_now, nullable=False)
    posted_at = db.Column(db.DateTime)
    cancelled_at = db.Column(db.DateTime)
    voided_at = db.Column(db.DateTime)
    voided_by_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    voided_by = db.relationship('User', foreign_keys=[voided_by_id], backref='voided_purchase_bills')
    void_reason = db.Column(db.String(255))
    cancel_reason = db.Column(db.String(500), nullable=True)

    # Relationship to line items
    # Changed from lazy='dynamic' to lazy='select' to support eager loading (selectinload)
    line_items = db.relationship('PurchaseBillItem', backref='bill', lazy='select',
                                 cascade='all, delete-orphan', order_by='PurchaseBillItem.line_number')

    def __repr__(self):
        return f'<PurchaseBill {self.bill_number}>'

    def calculate_totals(self):
        """Compute bill totals from VAT-inclusive line amounts."""
        self.subtotal = Decimal('0.00')
        auto_vat = Decimal('0.00')
        auto_wt = Decimal('0.00')

        for item in self.line_items:
            self.subtotal += item.line_total
            auto_vat += item.vat_amount
            auto_wt += (item.wt_amount or Decimal('0.00'))

        self.vat_amount = auto_vat
        self.withholding_tax_amount = auto_wt
        self.total_before_wt = self.subtotal   # VAT is extracted from subtotal, not added
        self.total_amount = self.subtotal - self.withholding_tax_amount
        self.balance = self.total_amount - self.amount_paid

    def to_dict(self):
        """Convert bill to dictionary for JSON serialization."""
        return {
            'id': self.id,
            'bill_number': self.bill_number,
            'bill_date': self.bill_date.isoformat() if self.bill_date else None,
            'due_date': self.due_date.isoformat() if self.due_date else None,
            'vendor_id': self.vendor_id,
            'vendor_name': self.vendor_name,
            'vendor_tin': self.vendor_tin,
            'vendor_invoice_number': self.vendor_invoice_number,
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
            'posted_at': self.posted_at.isoformat() if self.posted_at else None
        }


class PurchaseBillItem(db.Model):
    """
    Purchase Bill line item model.

    Each line represents an expense/purchase with:
    - Description and amount (VAT-inclusive)
    - VAT category and calculation
    - Line total
    """
    __tablename__ = 'purchase_bill_items'

    id = db.Column(db.Integer, primary_key=True)

    # Parent bill
    bill_id = db.Column(db.Integer, db.ForeignKey('purchase_bills.id'), nullable=False, index=True)

    # Line ordering
    line_number = db.Column(db.Integer, nullable=False)

    # Item details
    description = db.Column(db.String(500), nullable=False)
    amount = db.Column(db.Numeric(15, 2), default=0.00, nullable=False)

    # VAT information (input VAT)
    vat_category = db.Column(db.String(100))  # Reference to VAT category
    vat_rate = db.Column(db.Numeric(5, 2), default=0.00, nullable=False)  # Snapshot of rate

    # Calculated amounts
    line_total = db.Column(db.Numeric(15, 2), default=0.00, nullable=False)  # equals amount (VAT-inclusive)
    vat_amount = db.Column(db.Numeric(15, 2), default=0.00, nullable=False)  # extracted from amount

    # Account reference (for posting to GL)
    account_id = db.Column(db.Integer, db.ForeignKey('accounts.id'))
    account = db.relationship('Account')

    # Withholding tax (per line, vendor-driven)
    wt_id = db.Column(db.Integer, db.ForeignKey('withholding_tax.id'), nullable=True)
    withholding_tax = db.relationship('WithholdingTax', foreign_keys=[wt_id])
    wt_rate = db.Column(db.Numeric(5, 2), nullable=True)   # snapshot at bill creation time
    wt_amount = db.Column(db.Numeric(15, 2), default=Decimal('0.00'), server_default='0.00', nullable=False)

    def __repr__(self):
        return f'<PurchaseBillItem {self.bill_id}-{self.line_number}>'

    def calculate_amounts(self):
        """Calculate line total, extracted VAT, and WHT on net base (BIR EWT standard)."""
        vat_rate = Decimal(str(self.vat_rate)) if self.vat_rate else Decimal('0')
        if vat_rate > 0:
            net_base = Decimal(str(self.amount)) / (1 + vat_rate / Decimal('100'))
        else:
            net_base = Decimal(str(self.amount))
        self.line_total = Decimal(str(self.amount))
        self.vat_amount = (Decimal(str(self.amount)) - net_base).quantize(Decimal('0.01'), rounding='ROUND_HALF_UP')
        wt_rate = Decimal(str(self.wt_rate)) if self.wt_rate else Decimal('0')
        self.wt_amount = (net_base * wt_rate / Decimal('100')).quantize(Decimal('0.01'), rounding='ROUND_HALF_UP')

    def to_dict(self):
        """Convert line item to dictionary."""
        return {
            'id': self.id,
            'line_number': self.line_number,
            'description': self.description,
            'amount': float(self.amount),
            'vat_category': self.vat_category,
            'vat_rate': float(self.vat_rate),
            'line_total': float(self.line_total),
            'vat_amount': float(self.vat_amount),
            'account_id': self.account_id,
            'wt_id': self.wt_id,
            'wt_rate': float(self.wt_rate) if self.wt_rate is not None else None,
            'wt_amount': float(self.wt_amount),
        }
