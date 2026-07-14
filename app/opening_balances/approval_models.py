"""Opening-Balance change-request model (governed approval after period close).

Mirrors app/accounts/approval_models.py::AccountChangeRequest, but the approval
matrix (Task 3) DELIBERATELY differs: full-access users do NOT self-approve when a
peer accountant/CA exists. Do not "fix" it to match the COA precedent.
"""
import json
from app import db
from app.utils import ph_now


class OpeningBalanceChangeRequest(db.Model):
    __tablename__ = 'opening_balance_change_requests'

    id = db.Column(db.Integer, primary_key=True)
    # Bare Integer, no inline ForeignKey -- SQLite batch add_column can't emit an
    # unnamed FK, and app-wide FK enforcement is off anyway.
    branch_id = db.Column(db.Integer, nullable=True, index=True)

    # JSON snapshot of the proposed opening entry: {'cutover_date': 'YYYY-MM-DD',
    # 'lines': [{'account_id': int, 'debit': str, 'credit': str}, ...]}
    change_data = db.Column(db.Text, nullable=False)

    requested_by = db.Column(db.String(100), nullable=False)
    requested_at = db.Column(db.DateTime, default=ph_now, nullable=False)

    status = db.Column(db.String(20), default='pending', nullable=False)

    reviewed_by = db.Column(db.String(100))
    reviewed_at = db.Column(db.DateTime)
    rejection_reason = db.Column(db.Text)
    request_reason = db.Column(db.Text, nullable=True)

    def __repr__(self):
        return f'<OpeningBalanceChangeRequest {self.status} by {self.requested_by}>'

    def get_change_data(self):
        return json.loads(self.change_data) if self.change_data else {}

    def set_change_data(self, data):
        self.change_data = json.dumps(data)

    def to_dict(self):
        return {
            'id': self.id,
            'branch_id': self.branch_id,
            'change_data': self.get_change_data(),
            'requested_by': self.requested_by,
            'requested_at': self.requested_at.isoformat() if self.requested_at else None,
            'status': self.status,
            'reviewed_by': self.reviewed_by,
            'reviewed_at': self.reviewed_at.isoformat() if self.reviewed_at else None,
            'rejection_reason': self.rejection_reason,
            'request_reason': self.request_reason,
        }
