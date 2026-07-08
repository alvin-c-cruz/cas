import json

from app import db
from app.utils import ph_now


class VatSettlement(db.Model):
    """Records one company-wide quarterly VAT settlement per (fiscal_year, quarter).

    NOTE: intentionally has NO branch_id. VAT is a per-TIN (company-level) tax filed
    once per quarter across all branches (BIR 2550Q) — a deliberate, documented
    exception to the workspace branch-scoping rule.
    """
    __tablename__ = 'vat_settlements'
    __table_args__ = (db.UniqueConstraint('fiscal_year', 'quarter',
                                          name='uq_vat_settlement_year_quarter'),)

    id = db.Column(db.Integer, primary_key=True)
    fiscal_year = db.Column(db.Integer, nullable=False, index=True)
    quarter = db.Column(db.Integer, nullable=False, index=True)  # 1-4
    status = db.Column(db.String(20), nullable=False, default='settled')  # settled / reversed

    output_vat = db.Column(db.Numeric(15, 2), nullable=False, default=0)
    input_vat = db.Column(db.Numeric(15, 2), nullable=False, default=0)
    prior_carryover = db.Column(db.Numeric(15, 2), nullable=False, default=0)
    net_payable = db.Column(db.Numeric(15, 2), nullable=False, default=0)
    new_carryover = db.Column(db.Numeric(15, 2), nullable=False, default=0)

    settlement_entry_ids = db.Column(db.Text)  # JSON list[int]
    notes = db.Column(db.Text)

    settled_at = db.Column(db.DateTime, nullable=False, default=ph_now)
    settled_by_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    reversed_at = db.Column(db.DateTime)
    reversed_by_id = db.Column(db.Integer, db.ForeignKey('users.id'))

    def get_settlement_entry_ids(self):
        return json.loads(self.settlement_entry_ids) if self.settlement_entry_ids else []

    def set_settlement_entry_ids(self, ids):
        self.settlement_entry_ids = json.dumps(list(ids))

    def __repr__(self):
        return f'<VatSettlement {self.fiscal_year}-Q{self.quarter} {self.status}>'
