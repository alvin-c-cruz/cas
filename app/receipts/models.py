"""
Receipt models for cash and bank transactions.

Supports:
- Customer receipts (collections)
- Vendor payments (disbursements)
- Cash and bank transactions
- Check tracking
- Receipt numbering
"""
from app import db
from app.utils import ph_now
from decimal import Decimal


class Receipt(db.Model):
    """
    Receipt model for cash and bank transactions.

    Philippine SME requirements:
    - Receipt/Payment numbering (CR-2024-0001, CP-2024-0001)
    - Payment method tracking (Cash, Check, Bank Transfer)
    - Check number and date tracking
    - Bank account reference
    - Transaction type (receipt from customer, payment to vendor)
    """
    __tablename__ = 'receipts'

    id = db.Column(db.Integer, primary_key=True)

    # Branch association
    branch_id = db.Column(db.Integer, db.ForeignKey('branches.id'), nullable=True, index=True)
    branch = db.relationship('Branch', foreign_keys=[branch_id])

    # Receipt identification
    receipt_number = db.Column(db.String(50), unique=True, nullable=False, index=True)
    receipt_date = db.Column(db.Date, nullable=False, index=True)

    # Transaction type: 'collection' (from customer) or 'payment' (to vendor)
    transaction_type = db.Column(db.String(20), nullable=False, index=True)

    # Customer reference (for collections)
    customer_id = db.Column(db.Integer, db.ForeignKey('customers.id'))
    customer = db.relationship('Customer', backref='receipts')
    customer_name = db.Column(db.String(200))  # Snapshot

    # Vendor reference (for payments)
    vendor_id = db.Column(db.Integer, db.ForeignKey('vendors.id'))
    vendor = db.relationship('Vendor', backref='payments')
    vendor_name = db.Column(db.String(200))  # Snapshot

    # Payment method: 'cash', 'check', 'bank_transfer', 'online'
    payment_method = db.Column(db.String(20), nullable=False)

    # Check details (if payment method is 'check')
    check_number = db.Column(db.String(50))
    check_date = db.Column(db.Date)
    check_bank = db.Column(db.String(100))

    # Bank account reference
    bank_account = db.Column(db.String(100))  # e.g., "BDO Savings - 1234"

    # Amount
    amount = db.Column(db.Numeric(15, 2), nullable=False)

    # Reference and notes
    reference = db.Column(db.String(100))  # OR number, invoice reference, etc.
    notes = db.Column(db.Text)

    # Status: 'draft', 'posted', 'cleared', 'bounced' (for checks), 'cancelled'
    status = db.Column(db.String(20), default='draft', nullable=False, index=True)

    # Account reference (Cash/Bank account for posting to GL)
    account_id = db.Column(db.Integer, db.ForeignKey('accounts.id'))
    account = db.relationship('Account')

    # Audit fields
    created_by_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    created_by = db.relationship('User', foreign_keys=[created_by_id], backref='created_receipts')
    posted_by_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    posted_by = db.relationship('User', foreign_keys=[posted_by_id], backref='posted_receipts')

    # Timestamps
    created_at = db.Column(db.DateTime, default=ph_now, nullable=False)
    updated_at = db.Column(db.DateTime, default=ph_now, onupdate=ph_now, nullable=False)
    posted_at = db.Column(db.DateTime)
    cleared_at = db.Column(db.DateTime)  # When check cleared
    cancelled_at = db.Column(db.DateTime)

    def __repr__(self):
        return f'<Receipt {self.receipt_number}>'

    def to_dict(self):
        """Convert receipt to dictionary for JSON serialization."""
        return {
            'id': self.id,
            'receipt_number': self.receipt_number,
            'receipt_date': self.receipt_date.isoformat() if self.receipt_date else None,
            'transaction_type': self.transaction_type,
            'customer_name': self.customer_name,
            'vendor_name': self.vendor_name,
            'payment_method': self.payment_method,
            'check_number': self.check_number,
            'check_date': self.check_date.isoformat() if self.check_date else None,
            'bank_account': self.bank_account,
            'amount': float(self.amount),
            'reference': self.reference,
            'status': self.status,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'posted_at': self.posted_at.isoformat() if self.posted_at else None
        }
