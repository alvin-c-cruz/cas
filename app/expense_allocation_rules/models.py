"""Per-account cost/expense allocation basis (Phase 3b: Income Statement by Product Line).

One rule per P&L account (Selling/Administrative Expense, Other Income/Expense, Income Tax).
An account with no rule defaults to 'none' -> Unallocated (spec-locked explicit default).
"""
from app import db
from app.utils import ph_now


class ExpenseAllocationRule(db.Model):
    __tablename__ = 'expense_allocation_rules'

    id = db.Column(db.Integer, primary_key=True)
    account_id = db.Column(db.Integer, db.ForeignKey('accounts.id'), unique=True, nullable=False)
    basis = db.Column(db.String(20), nullable=False)
    created_at = db.Column(db.DateTime, default=ph_now)
    created_by_id = db.Column(db.Integer, db.ForeignKey('users.id'))

    account = db.relationship('Account', foreign_keys=[account_id])
    created_by = db.relationship('User', foreign_keys=[created_by_id])

    def __repr__(self):
        return f'<ExpenseAllocationRule account={self.account_id} basis={self.basis}>'

    def to_dict(self):
        return {
            'id': self.id, 'account_id': self.account_id,
            'account_code': self.account.code if self.account else None,
            'account_name': self.account.name if self.account else None,
            'basis': self.basis,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }
