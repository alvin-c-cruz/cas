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


def write_revision(document, user_id, reason=None, authorizing_reference=None,
                   baseline=False):
    """Append the next revision for *document*. Adds to the session; does NOT commit.

    `baseline=True` marks the ONE revision that records the document as it was
    approved -- Rev 0, written by the approve/confirm route and by nothing else.
    Every other call records a change made after that point and is numbered from
    1 up.

    REVISION 0 IS A SLOT, NOT "whoever wrote first". It used to be handed to the
    first writer (`0 if prev is None else prev + 1`), so amending a document that
    has no baseline put POST-CHANGE state in the baseline slot, gave that row an
    amendment reason, and shifted every later number by one -- a revision history
    that documents the corruption instead of preventing it. No Purchase Order
    reaches that state today (docrev_0002 backfills every `approved_at IS NOT
    NULL` row), but this service is document-agnostic and each remaining document
    type brings its own backfill predicate; the Sales Order one already admits in
    its docstring that it skips orders confirmed and later closed or cancelled.

    When there is no baseline the slot is left EMPTY and the amendment takes Rev
    1. Refusing the write instead would deny a real business action over a data
    condition the user can neither see nor repair, for a state that is latent
    today; leaving the slot empty states the true thing -- no capture of the
    approved document exists -- keeps `revision_number` meaning "the Nth change
    after the baseline", and stays repairable, since a later backfill can insert
    Rev 0 without renumbering anything. The detail panel reads exactly this: it
    captions Rev 0 (and only Rev 0) as the original approved order, so an absent
    Rev 0 makes no claim at all.
    """
    # A baseline is not a change: it has no reason, and the panel keys on exactly
    # that ("a reason means an amendment"). Passing one would render a Rev 0 as an
    # amendment numbered zero -- the same lie by a different route.
    if baseline and reason is not None:
        raise ValueError('a baseline revision records what was approved, not a '
                         'change -- it cannot carry a reason')

    # Flush first: a line appended but not yet flushed has id None, and the
    # snapshot's line identity depends on that id existing. Default autoflush
    # would usually cover this, which is exactly why it is explicit.
    db.session.flush()

    prev = latest_revision(document.DOCUMENT_TYPE, document.id)
    if prev is not None:
        revision_number = prev.revision_number + 1
    else:
        revision_number = 0 if baseline else 1
    rev = DocumentRevision(
        document_type=document.DOCUMENT_TYPE,
        document_id=document.id,
        revision_number=revision_number,
        snapshot_json=json.dumps(document.build_snapshot()),
        reason=reason,
        authorizing_reference=authorizing_reference,
        amended_by_id=user_id,
        branch_id=getattr(document, 'branch_id', None),
    )
    db.session.add(rev)
    return rev
