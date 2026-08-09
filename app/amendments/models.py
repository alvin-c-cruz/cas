"""Append-only revision log shared by every amendable document.

One row per revision, holding a full JSON snapshot of the document as of that
revision. Rev 0 is the document as originally approved.

Deliberately does NOT extend RowVersioned: rows are never updated or deleted, so
there is no lost-update to guard against. Mirrors SalesOrderRevision's choice.
"""
from app import db
from app.utils import ph_now


class DocumentRevision(db.Model):
    __tablename__ = 'document_revisions'
    __table_args__ = (
        db.UniqueConstraint('document_type', 'document_id', 'revision_number',
                            name='uq_document_revision_number'),
        db.Index('ix_document_revisions_doc', 'document_type', 'document_id'),
    )

    id = db.Column(db.Integer, primary_key=True)

    # Matches the module's audit `module` name, e.g. 'purchase_orders'.
    document_type = db.Column(db.String(40), nullable=False)

    # PLAIN Integer, no ORM FK: this column points at eight different tables, a
    # shape no ForeignKey can express. Mirrors SalesOrder.quotation_id's reasoning.
    document_id = db.Column(db.Integer, nullable=False)

    # 0-based. Rev 0 == the document as originally approved.
    revision_number = db.Column(db.Integer, nullable=False)

    snapshot_json = db.Column(db.Text, nullable=False)

    # Required (>=10 chars) for N >= 1; null on Rev 0. Enforced in the service
    # (slice 2), not the column, because Rev 0 legitimately has none.
    reason = db.Column(db.String(500), nullable=True)

    authorizing_reference = db.Column(db.String(100), nullable=True)

    amended_by_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    amended_by = db.relationship('User', foreign_keys=[amended_by_id])
    amended_at = db.Column(db.DateTime, default=ph_now, nullable=False)

    branch_id = db.Column(db.Integer, db.ForeignKey('branches.id'), nullable=True, index=True)

    def __repr__(self):
        return (f'<DocumentRevision {self.document_type}={self.document_id} '
                f'rev={self.revision_number}>')
