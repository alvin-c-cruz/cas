"""Bank reconciliation against a Slice-1 BankAccount (R-04 slice 3). GL-account-
centric: the set of book items is every JournalEntryLine on the account's GL
account for its branch -- no per-source special-casing, and it automatically
picks up Bank Transfers (slice 2) once that ships, with zero code change here."""
from app import db
from app.utils import ph_now
from app.utils.concurrency import RowVersioned


class BankReconciliation(RowVersioned, db.Model):
    __tablename__ = 'bank_reconciliations'

    id = db.Column(db.Integer, primary_key=True)
    bank_account_id = db.Column(db.Integer, db.ForeignKey('bank_accounts.id'), nullable=False, index=True)
    bank_account = db.relationship('BankAccount')

    statement_date = db.Column(db.Date, nullable=False)
    statement_ending_balance = db.Column(db.Numeric(15, 2), nullable=False)
    beginning_balance = db.Column(db.Numeric(15, 2), nullable=False)
    status = db.Column(db.String(20), nullable=False, default='draft', server_default='draft')

    # Snapshot totals -- set ONCE at completion, never live-recomputed after.
    book_balance = db.Column(db.Numeric(15, 2), nullable=True)
    cleared_debits = db.Column(db.Numeric(15, 2), nullable=True)
    cleared_credits = db.Column(db.Numeric(15, 2), nullable=True)
    outstanding_deposits = db.Column(db.Numeric(15, 2), nullable=True)
    outstanding_checks = db.Column(db.Numeric(15, 2), nullable=True)
    adjusted_balance = db.Column(db.Numeric(15, 2), nullable=True)

    reconciled_by_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    reconciled_by = db.relationship('User', foreign_keys=[reconciled_by_id])
    reconciled_at = db.Column(db.DateTime, nullable=True)

    created_at = db.Column(db.DateTime, default=ph_now, nullable=False)
    updated_at = db.Column(db.DateTime, default=ph_now, onupdate=ph_now, nullable=False)

    items = db.relationship('ReconciliationItem', backref='reconciliation', lazy='dynamic',
                            cascade='all, delete-orphan')


class ReconciliationItem(db.Model):
    """Module-owned clearing state. Does NOT modify JournalEntryLine -- zero
    regression blast radius on the core ledger."""
    __tablename__ = 'reconciliation_items'

    id = db.Column(db.Integer, primary_key=True)
    reconciliation_id = db.Column(db.Integer, db.ForeignKey('bank_reconciliations.id'),
                                  nullable=False, index=True)
    je_line_id = db.Column(db.Integer, db.ForeignKey('journal_entry_lines.id'),
                           nullable=False, unique=True, index=True)
    cleared_at = db.Column(db.DateTime, default=ph_now, nullable=False)

    je_line = db.relationship('JournalEntryLine')
