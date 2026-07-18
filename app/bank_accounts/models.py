"""A branch-scoped label over exactly ONE COA cash/bank GL account (R-04 slice 1)."""
from app import db
from app.utils import ph_now


class BankAccount(db.Model):
    """A branch-scoped label over exactly ONE COA cash/bank GL account (1:1).
    Also holds cash-on-hand entries (bank_* null) -- a Cash & Bank register."""
    __tablename__ = 'bank_accounts'

    id = db.Column(db.Integer, primary_key=True)
    branch_id = db.Column(db.Integer, db.ForeignKey('branches.id'), nullable=False, index=True)
    code = db.Column(db.String(20), nullable=False, index=True)
    name = db.Column(db.String(200), nullable=False)
    # 1:1, globally unique, immutable after creation (edit form never exposes it)
    account_id = db.Column(db.Integer, db.ForeignKey('accounts.id'), nullable=False, unique=True)
    bank_name = db.Column(db.String(200))
    account_number = db.Column(db.String(50))
    account_type = db.Column(db.String(30))            # checking/savings/cash-on-hand
    opening_balance = db.Column(db.Numeric(15, 2), default=0, nullable=False)  # statement anchor; NO JE
    opening_date = db.Column(db.Date)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    created_by = db.Column(db.String(80))
    created_at = db.Column(db.DateTime, default=ph_now, nullable=False)
    updated_at = db.Column(db.DateTime, default=ph_now, onupdate=ph_now, nullable=False)

    account = db.relationship('Account')
    branch = db.relationship('Branch')
