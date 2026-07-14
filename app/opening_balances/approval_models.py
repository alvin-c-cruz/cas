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

    @staticmethod
    def accountant_ca_count():
        """Active users whose role is accountant or chief_accountant. Admin is NOT
        counted here -- the owner's matrix keys off the accountant/CA population."""
        from app.users.models import User
        return User.query.filter(
            User.role.in_(['accountant', 'chief_accountant']),
            User.is_active == True,  # noqa: E712
        ).count()

    def auto_approves(self):
        """True when this request applies immediately with no pending state:
        - the requester is the SOLE active accountant/CA (count == 1), or
        - there are ZERO accountants/CAs and the requester is an admin (solo-admin
          escape hatch so a lone-admin instance isn't permanently locked out).
        Everyone else -> pending (nobody self-approves, incl. admin, when a peer exists)."""
        from app.users.models import User
        requester = User.query.filter_by(username=self.requested_by).first()
        if requester is None or not requester.is_active:
            return False
        count = self.accountant_ca_count()
        if requester.role in ('accountant', 'chief_accountant') and count == 1:
            return True
        if count == 0 and requester.role == 'admin':
            return True
        return False

    def can_be_approved_by(self, username):
        """A pending request may be approved by any OTHER active accountant, CA, or
        admin -- never the requester. (Diverges from AccountChangeRequest, where
        full-access can self-approve.)"""
        from app.users.models import User
        reviewer = User.query.filter_by(username=username).first()
        if reviewer is None or not reviewer.is_active:
            return False
        if reviewer.role not in ('accountant', 'chief_accountant', 'admin'):
            return False
        return username != self.requested_by
