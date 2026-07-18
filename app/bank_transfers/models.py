"""A first-class document moving money between two of a client's own BankAccounts
(R-04 slice 2). Intra-branch = one immediate JE; inter-branch = a two-step
initiate/confirm flow through a Due-from/Due-to clearing pair."""
from app import db
from app.utils import ph_now
from app.utils.concurrency import RowVersioned

VALID_STATUSES = ('draft', 'in_transit', 'completed', 'rejected', 'cancelled')


class BankTransfer(RowVersioned, db.Model):
    __tablename__ = 'bank_transfers'

    id = db.Column(db.Integer, primary_key=True)
    transfer_number = db.Column(db.String(50), unique=True, index=True, nullable=False)

    from_bank_account_id = db.Column(db.Integer, db.ForeignKey('bank_accounts.id'), nullable=False)
    to_bank_account_id = db.Column(db.Integer, db.ForeignKey('bank_accounts.id'), nullable=False)
    from_bank_account = db.relationship('BankAccount', foreign_keys=[from_bank_account_id])
    to_bank_account = db.relationship('BankAccount', foreign_keys=[to_bank_account_id])

    from_branch_id = db.Column(db.Integer, db.ForeignKey('branches.id'), nullable=False, index=True)
    to_branch_id = db.Column(db.Integer, db.ForeignKey('branches.id'), nullable=False, index=True)
    is_inter_branch = db.Column(db.Boolean, nullable=False)

    amount = db.Column(db.Numeric(15, 2), nullable=False)
    transfer_date = db.Column(db.Date, nullable=False)
    memo = db.Column(db.Text, nullable=True)

    status = db.Column(db.String(20), nullable=False, default='draft', server_default='draft', index=True)

    sender_je_id = db.Column(db.Integer, db.ForeignKey('journal_entries.id'), nullable=True)
    receiver_je_id = db.Column(db.Integer, db.ForeignKey('journal_entries.id'), nullable=True)
    reversal_je_id = db.Column(db.Integer, db.ForeignKey('journal_entries.id'), nullable=True)

    created_by_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    initiated_by_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    initiated_at = db.Column(db.DateTime, nullable=True)
    confirmed_by_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    confirmed_at = db.Column(db.DateTime, nullable=True)
    rejected_by_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    rejected_at = db.Column(db.DateTime, nullable=True)
    cancelled_by_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    cancelled_at = db.Column(db.DateTime, nullable=True)

    created_at = db.Column(db.DateTime, default=ph_now, nullable=False)
    updated_at = db.Column(db.DateTime, default=ph_now, onupdate=ph_now, nullable=False)
