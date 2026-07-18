"""Budget entry model (R-09 Slice 1).

A BudgetLine is one planned amount for one account, in one branch, for one
calendar month of a fiscal year. Flat matrix of values, not a document with its
own lifecycle -- no header table. See
docs/superpowers/specs/2026-07-19-budgeting-entry-r09-slice1-design.md.
"""
from app import db
from app.utils import ph_now


class BudgetLine(db.Model):
    __tablename__ = 'budget_lines'

    id = db.Column(db.Integer, primary_key=True)
    branch_id = db.Column(db.Integer, db.ForeignKey('branches.id'), nullable=False, index=True)
    account_id = db.Column(db.Integer, db.ForeignKey('accounts.id'), nullable=False, index=True)
    fiscal_year = db.Column(db.Integer, nullable=False, index=True)
    month = db.Column(db.Integer, nullable=False)
    amount = db.Column(db.Numeric(15, 2), default=0, nullable=False)
    updated_by_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    created_at = db.Column(db.DateTime, default=ph_now, nullable=False)
    updated_at = db.Column(db.DateTime, default=ph_now, onupdate=ph_now, nullable=False)

    branch = db.relationship('Branch')
    account = db.relationship('Account')
    updated_by = db.relationship('User', foreign_keys=[updated_by_id])

    __table_args__ = (
        db.UniqueConstraint('branch_id', 'account_id', 'fiscal_year', 'month',
                             name='uq_budget_line_branch_account_year_month'),
    )

    def __repr__(self):
        return (f'<BudgetLine branch={self.branch_id} account={self.account_id} '
                f'{self.fiscal_year}-{self.month:02d}={self.amount}>')
