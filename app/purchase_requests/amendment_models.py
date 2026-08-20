"""Staff-initiated amendment request for an already-approved Purchase Requisition.

WHY THIS EXISTS. `purchase_requests.amend` is gated on `_approve_gate()`, not on
the edit rule, and deliberately so: its own comment records that gating an
amendment on the edit rule shipped a Critical on the Purchase Order side, where a
staff user who could not approve a PO could rewrite an approved one. So staff
must never gain a write path onto an approved requisition.

This model is the seam that lets them ASK without letting them WRITE. Staff write
only to this table; the requisition itself is touched exclusively by the existing
approver-gated apply path, which still appends a DocumentRevision. It mirrors
`PermissionChangeRequest` -- the established request/approve precedent in this
codebase -- rather than inventing a second shape.

The proposal is stored as JSON rather than as child rows because it is a
*proposal*, not document state: it is written once, read for the diff, applied or
discarded, and never queried per line. `DocumentRevision.snapshot_json` makes the
same call for the same reason.
"""
import json

from app import db
from app.utils import ph_now
from app.utils.concurrency import RowVersioned


class PurchaseRequestAmendmentRequest(RowVersioned, db.Model):
    """One staff request to amend one approved requisition.

    RowVersioned because approve/reject are the classic lost-update pair: two
    approvers opening the same request and acting a moment apart would otherwise
    both apply it, producing two revisions from one request.
    """
    __tablename__ = 'pr_amendment_requests'
    __table_args__ = (
        db.Index('ix_pr_amend_req_pending', 'purchase_request_id', 'status'),
    )

    STATUS_PENDING = 'pending'
    STATUS_APPROVED = 'approved'
    STATUS_REJECTED = 'rejected'
    STATUS_WITHDRAWN = 'withdrawn'

    #: The reason must survive onto the revision record, where the shared
    #: amendment service requires >= 10 characters. Enforced in the form and the
    #: service, not the column, so the message is a field error rather than a 500.
    MIN_REASON_LEN = 10

    id = db.Column(db.Integer, primary_key=True)

    purchase_request_id = db.Column(db.Integer, db.ForeignKey('purchase_requests.id'),
                                    nullable=False, index=True)

    # Branch-scoped from day one (memory branch-scoping-rule). A request list
    # without this repeats the exact hole three separate fixes closed on
    # 2026-08-20 -- see BUG-BRANCH-SCOPED-MASTERS-EDIT-NOT-BRANCH-FILTERED.
    branch_id = db.Column(db.Integer, db.ForeignKey('branches.id'),
                          nullable=False, index=True)

    requested_by_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    request_reason = db.Column(db.Text, nullable=False)

    #: The proposed header + lines, in the same shape `_apply_amended_pr_lines`
    #: already consumes, so the approve path can hand it to the SAME applier the
    #: approver-driven amend route uses. Two appliers would eventually disagree.
    proposed_json = db.Column(db.Text, nullable=False)

    status = db.Column(db.String(20), default=STATUS_PENDING, nullable=False, index=True)

    reviewed_by_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    reviewed_at = db.Column(db.DateTime, nullable=True)
    review_notes = db.Column(db.Text, nullable=True)

    #: Which revision this became, once applied. Null while pending/rejected.
    applied_revision_number = db.Column(db.Integer, nullable=True)

    created_at = db.Column(db.DateTime, default=ph_now, nullable=False)

    purchase_request = db.relationship('PurchaseRequest',
                                       backref=db.backref('amendment_requests',
                                                          lazy='dynamic'))
    branch = db.relationship('Branch', foreign_keys=[branch_id])
    requested_by = db.relationship('User', foreign_keys=[requested_by_id])
    reviewed_by = db.relationship('User', foreign_keys=[reviewed_by_id])

    # ------------------------------------------------------------------
    def get_proposed(self):
        """The proposed payload as a dict; {} when unreadable.

        Never raises: a malformed row must render as "nothing proposed" in the
        review screen rather than 500 the approver's Action Items.
        """
        try:
            value = json.loads(self.proposed_json or '{}')
        except ValueError:
            return {}
        return value if isinstance(value, dict) else {}

    def set_proposed(self, payload):
        self.proposed_json = json.dumps(payload)

    def proposed_lines(self):
        lines = self.get_proposed().get('lines')
        return lines if isinstance(lines, list) else []

    @property
    def is_pending(self):
        return self.status == self.STATUS_PENDING

    def __repr__(self):
        return ('<PurchaseRequestAmendmentRequest pr=%s status=%s>'
                % (self.purchase_request_id, self.status))
