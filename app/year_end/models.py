import json
from decimal import Decimal

from app import db
from app.utils import ph_now


class FiscalYearClose(db.Model):
    """Records one year-end close per (fiscal_year, branch). Reopen flips status."""
    __tablename__ = 'fiscal_year_closes'
    __table_args__ = (db.UniqueConstraint('fiscal_year', 'branch_id',
                                          name='uq_fyc_year_branch'),)

    id = db.Column(db.Integer, primary_key=True)
    fiscal_year = db.Column(db.Integer, nullable=False, index=True)
    branch_id = db.Column(db.Integer, db.ForeignKey('branches.id'),
                          nullable=False, index=True)
    status = db.Column(db.String(20), nullable=False, default='closed')
    net_income = db.Column(db.Numeric(15, 2), nullable=False, default=0)
    closing_entry_ids = db.Column(db.Text)  # JSON list[int]

    closed_at = db.Column(db.DateTime, nullable=False, default=ph_now)
    closed_by_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    reopened_at = db.Column(db.DateTime)
    reopened_by_id = db.Column(db.Integer, db.ForeignKey('users.id'))

    branch = db.relationship('Branch', foreign_keys=[branch_id])

    def get_closing_entry_ids(self):
        return json.loads(self.closing_entry_ids) if self.closing_entry_ids else []

    def set_closing_entry_ids(self, ids):
        self.closing_entry_ids = json.dumps(list(ids))

    def __repr__(self):
        return f'<FiscalYearClose {self.fiscal_year}/{self.branch_id} {self.status}>'
