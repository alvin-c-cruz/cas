"""Revision read/write service shared by every amendable document.

write_revision touches the session but never commits -- the caller owns the
transaction so a revision and the change that produced it land atomically.
"""
import json

from app import db
from app.amendments.models import DocumentRevision


def latest_revision(document_type, document_id):
    """Highest-numbered revision for a document, or None."""
    return (DocumentRevision.query
            .filter_by(document_type=document_type, document_id=document_id)
            .order_by(DocumentRevision.revision_number.desc())
            .first())


def write_revision(document, user_id, reason=None, authorizing_reference=None):
    """Append the next revision for *document*. Adds to the session; does NOT commit."""
    # Flush first: a line appended but not yet flushed has id None, and the
    # snapshot's line identity depends on that id existing. Default autoflush
    # would usually cover this, which is exactly why it is explicit.
    db.session.flush()

    prev = latest_revision(document.DOCUMENT_TYPE, document.id)
    rev = DocumentRevision(
        document_type=document.DOCUMENT_TYPE,
        document_id=document.id,
        revision_number=0 if prev is None else prev.revision_number + 1,
        snapshot_json=json.dumps(document.build_snapshot()),
        reason=reason,
        authorizing_reference=authorizing_reference,
        amended_by_id=user_id,
        branch_id=getattr(document, 'branch_id', None),
    )
    db.session.add(rev)
    return rev
