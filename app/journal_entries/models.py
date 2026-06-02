"""
Journal Entry models for manual general ledger adjustments.

Supports:
- Journal entry header with reference
- Journal entry lines with debits and credits
- Automatic balancing validation
- Period-end adjustments
- Reversing entries
"""
from app import db
from app.utils import ph_now
from decimal import Decimal


class JournalEntry(db.Model):
    """
    Journal Entry header model.

    Accounting requirements:
    - Journal entry numbering (JE-2024-0001)
    - Entry date and period
    - Reference and description
    - Balanced debits and credits validation
    - Reversing entry support
    """
    __tablename__ = 'journal_entries'

    id = db.Column(db.Integer, primary_key=True)

    # Entry identification
    entry_number = db.Column(db.String(50), unique=True, nullable=False, index=True)
    entry_date = db.Column(db.Date, nullable=False, index=True)

    # Description and reference
    description = db.Column(db.String(500), nullable=False)
    reference = db.Column(db.String(100))

    # Entry type: 'adjustment', 'closing', 'opening', 'reversal', 'reclassification'
    entry_type = db.Column(db.String(20), default='adjustment', nullable=False)

    # Reversing entry support
    is_reversing = db.Column(db.Boolean, default=False, nullable=False)
    reversal_date = db.Column(db.Date)  # Date when this entry should be reversed

    # Totals (must balance)
    total_debit = db.Column(db.Numeric(15, 2), default=0.00, nullable=False)
    total_credit = db.Column(db.Numeric(15, 2), default=0.00, nullable=False)

    # Balance check
    is_balanced = db.Column(db.Boolean, default=False, nullable=False)

    # Status: 'draft', 'posted', 'reversed', 'cancelled'
    status = db.Column(db.String(20), default='draft', nullable=False, index=True)

    # Link to reversed entry (if this is a reversing entry)
    reversed_entry_id = db.Column(db.Integer, db.ForeignKey('journal_entries.id'))
    reversed_by_id = db.Column(db.Integer, db.ForeignKey('journal_entries.id'))

    # Audit fields
    created_by_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    created_by = db.relationship('User', foreign_keys=[created_by_id], backref='created_journal_entries')
    posted_by_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    posted_by = db.relationship('User', foreign_keys=[posted_by_id], backref='posted_journal_entries')

    # Timestamps
    created_at = db.Column(db.DateTime, default=ph_now, nullable=False)
    updated_at = db.Column(db.DateTime, default=ph_now, onupdate=ph_now, nullable=False)
    posted_at = db.Column(db.DateTime)
    cancelled_at = db.Column(db.DateTime)

    # Relationship to lines
    lines = db.relationship('JournalEntryLine', backref='entry', lazy='dynamic',
                           cascade='all, delete-orphan', order_by='JournalEntryLine.line_number')

    def __repr__(self):
        return f'<JournalEntry {self.entry_number}>'

    def calculate_totals(self):
        """Calculate total debits and credits from lines."""
        self.total_debit = Decimal('0.00')
        self.total_credit = Decimal('0.00')

        for line in self.lines:
            self.total_debit += line.debit_amount
            self.total_credit += line.credit_amount

        # Check if balanced
        self.is_balanced = (self.total_debit == self.total_credit)

    def to_dict(self):
        """Convert journal entry to dictionary."""
        return {
            'id': self.id,
            'entry_number': self.entry_number,
            'entry_date': self.entry_date.isoformat() if self.entry_date else None,
            'description': self.description,
            'reference': self.reference,
            'entry_type': self.entry_type,
            'is_reversing': self.is_reversing,
            'total_debit': float(self.total_debit),
            'total_credit': float(self.total_credit),
            'is_balanced': self.is_balanced,
            'status': self.status,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'posted_at': self.posted_at.isoformat() if self.posted_at else None
        }


class JournalEntryLine(db.Model):
    """
    Journal Entry line model.

    Each line represents a debit or credit to an account.
    """
    __tablename__ = 'journal_entry_lines'

    id = db.Column(db.Integer, primary_key=True)

    # Parent entry
    entry_id = db.Column(db.Integer, db.ForeignKey('journal_entries.id'), nullable=False, index=True)

    # Line ordering
    line_number = db.Column(db.Integer, nullable=False)

    # Account reference (required)
    account_id = db.Column(db.Integer, db.ForeignKey('accounts.id'), nullable=False)
    account = db.relationship('Account')

    # Description for this line
    description = db.Column(db.String(500))

    # Debit or Credit (one must be zero)
    debit_amount = db.Column(db.Numeric(15, 2), default=0.00, nullable=False)
    credit_amount = db.Column(db.Numeric(15, 2), default=0.00, nullable=False)

    def __repr__(self):
        return f'<JournalEntryLine {self.entry_id}-{self.line_number}>'

    def to_dict(self):
        """Convert line to dictionary."""
        return {
            'id': self.id,
            'line_number': self.line_number,
            'account_id': self.account_id,
            'account_code': self.account.code if self.account else None,
            'account_name': self.account.name if self.account else None,
            'description': self.description,
            'debit_amount': float(self.debit_amount),
            'credit_amount': float(self.credit_amount)
        }
