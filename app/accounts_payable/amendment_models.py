"""Edit-level request to attach a missing REQUIRED file to an already-posted AP.

Mirrors PurchaseRequestAmendmentRequest: staff write only to THIS table; the
posted AP itself is touched exclusively by the approver-gated approve path, which
adds an AccountsPayableAttachment. Attachments only — no financial change, ever.
"""
from app import db
from app.utils import ph_now
from app.utils.concurrency import RowVersioned


class AccountsPayableAmendmentRequest(RowVersioned, db.Model):
    __tablename__ = 'ap_amendment_requests'
    __table_args__ = (db.Index('ix_ap_amend_req_pending', 'ap_id', 'status'),)

    STATUS_PENDING = 'pending'
    STATUS_APPROVED = 'approved'
    STATUS_REJECTED = 'rejected'
    STATUS_WITHDRAWN = 'withdrawn'
    MIN_REASON_LEN = 10

    id = db.Column(db.Integer, primary_key=True)
    ap_id = db.Column(db.Integer, db.ForeignKey('accounts_payable.id'), nullable=False, index=True)
    branch_id = db.Column(db.Integer, db.ForeignKey('branches.id'), nullable=False, index=True)
    requested_by_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    reason = db.Column(db.Text, nullable=False)
    # Slot the request fills. Always 'signed_ap' today; column keeps it general.
    kind = db.Column(db.String(40), nullable=False)
    # The file staged with the request (on disk under the request until approve).
    staged_original_filename = db.Column(db.String(255), nullable=False)
    staged_stored_filename = db.Column(db.String(255), nullable=False)
    staged_mime_type = db.Column(db.String(100), nullable=False)
    staged_file_size = db.Column(db.Integer, nullable=False)
    status = db.Column(db.String(20), default=STATUS_PENDING, nullable=False, index=True)
    reviewed_by_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    reviewed_at = db.Column(db.DateTime, nullable=True)
    review_note = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=ph_now, nullable=False)
    updated_at = db.Column(db.DateTime, default=ph_now, onupdate=ph_now, nullable=False)

    ap = db.relationship('AccountsPayable',
                         backref=db.backref('amendment_requests', lazy='dynamic'))
    branch = db.relationship('Branch', foreign_keys=[branch_id])
    requested_by = db.relationship('User', foreign_keys=[requested_by_id])
    reviewed_by = db.relationship('User', foreign_keys=[reviewed_by_id])

    @property
    def is_pending(self):
        return self.status == self.STATUS_PENDING

    def __repr__(self):
        return '<APAmendmentRequest ap=%s status=%s>' % (self.ap_id, self.status)
