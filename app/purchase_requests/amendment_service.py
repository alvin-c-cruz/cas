"""Staff amendment-request flow for Purchase Requisitions.

The one rule this module exists to enforce: **staff write only to the request
row; the requisition is changed exclusively by `apply_request`, which runs the
SAME validator and the SAME applier the approver-gated amend route already
uses.** Two appliers would eventually disagree, and the disagreement would be
invisible until it corrupted a document.
"""
from app import db
from app.amendments.service import write_revision
from app.amendments.validation import validate_amendment
from app.purchase_requests.amendment_models import PurchaseRequestAmendmentRequest
from app.purchase_requests.models import PurchaseRequest
from app.utils import ph_now

PENDING = PurchaseRequestAmendmentRequest.STATUS_PENDING


# ----------------------------------------------------------------- queries
def pending_request_for(pr_id):
    """The one pending request for this requisition, or None.

    Read by the convert guard, the PR detail page and the Action Items source,
    so it is the single definition of "has a pending request" -- three separate
    inline queries would drift.
    """
    return (PurchaseRequestAmendmentRequest.query
            .filter_by(purchase_request_id=pr_id, status=PENDING)
            .first())


def pending_request_pr_ids(pr_ids):
    """The subset of `pr_ids` that carry a PENDING amendment request.

    ONE query for the whole page, never one per row: the list paginates at 50, so
    a per-row lookup would put 50 extra round-trips on a full page.
    `test_the_indicator_costs_a_constant_number_of_queries` pins that.

    Only PENDING counts -- an approved or rejected request no longer blocks
    conversion, so it must not keep marking the row.
    """
    ids = [i for i in (pr_ids or []) if i is not None]
    if not ids:
        return set()
    rows = (db.session.query(PurchaseRequestAmendmentRequest.purchase_request_id)
            .filter(PurchaseRequestAmendmentRequest.status == PENDING,
                    PurchaseRequestAmendmentRequest.purchase_request_id.in_(ids))
            .distinct()
            .all())
    return {r[0] for r in rows}


def pending_requests_for_branches(branch_ids):
    """Every pending request in the given branches, newest first.

    Takes a SET of branch ids, not one id: an approver assigned two branches
    must see both, exactly as `get_accessible_branches` scoping works elsewhere.
    """
    if not branch_ids:
        return []
    return (PurchaseRequestAmendmentRequest.query
            .filter(PurchaseRequestAmendmentRequest.status == PENDING,
                    PurchaseRequestAmendmentRequest.branch_id.in_(branch_ids))
            .order_by(PurchaseRequestAmendmentRequest.created_at.desc())
            .all())


# ----------------------------------------------------------------- snapshot
def current_lines(pr):
    """The requisition's lines as the request form's starting point."""
    return [li.to_dict() for li in pr.line_items]


def diff_lines(current, proposed):
    """Rows for the approver's before/after table.

    Matches by the line's own id (`pr_item_id`), never by position: reordering
    or deleting a middle row would otherwise show every following line as
    modified. A proposed row with no id is an ADDED line; a current line whose
    id no longer appears is REMOVED.
    """
    FIELDS = ('product_name', 'description', 'quantity', 'uom_label')

    def _product_name(row):
        """Resolve the product label from whichever key this side carries.

        Stored rows carry product_name; submitted rows carry only product_id. A
        raw-dict comparison therefore reported every proposed row as clearing its
        product -- shown live as `COAL -> —` on a row nobody touched.
        """
        if row.get('product_name'):
            return row['product_name']
        pid = row.get('product_id')
        if pid in (None, '', 'null'):
            return ''
        from app.products.models import Product
        p = db.session.get(Product, int(pid))
        return p.name if p else ''

    def _uom_label(row):
        for key in ('uom_label', 'uom_display'):
            if row.get(key):
                return row[key]
        uid = row.get('unit_of_measure_id') or row.get('uom_id')
        if uid not in (None, '', 'null'):
            from app.units_of_measure.models import UnitOfMeasure
            u = db.session.get(UnitOfMeasure, int(uid))
            if u:
                return u.code
        return row.get('uom_text') or ''

    def norm(row):
        resolved = {
            'product_name': _product_name(row),
            'description': row.get('description'),
            'quantity': row.get('quantity'),
            'uom_label': _uom_label(row),
        }
        out = {}
        for f in FIELDS:
            v = resolved[f]
            if f == 'quantity' and v not in (None, '', 'null'):
                # 1 and 1.00 are the same quantity; comparing their strings is
                # how an untouched line reads as MODIFIED.
                try:
                    v = ('%g' % float(v))
                except (TypeError, ValueError):
                    pass
            out[f] = '' if v is None else str(v).strip()
        return out

    by_id = {}
    for row in current:
        if row.get('id') is not None:
            by_id[str(row['id'])] = row

    rows, seen = [], set()
    for row in proposed:
        raw_id = row.get('pr_item_id') or row.get('id')
        key = str(raw_id) if raw_id not in (None, '') else None
        if key is not None and key in by_id:
            seen.add(key)
            before, after = norm(by_id[key]), norm(row)
            changed = [f for f in FIELDS if before[f] != after[f]]
            rows.append({'kind': 'modified' if changed else 'unchanged',
                         'changed': changed, 'before': before, 'after': after})
        else:
            rows.append({'kind': 'added', 'changed': list(FIELDS),
                         'before': None, 'after': norm(row)})

    for key, row in by_id.items():
        if key not in seen:
            rows.append({'kind': 'removed', 'changed': list(FIELDS),
                         'before': norm(row), 'after': None})
    return rows


def change_count(rows):
    """How many rows actually differ -- the Action Items subtitle reads this."""
    return sum(1 for r in rows if r['kind'] != 'unchanged')


# ----------------------------------------------------------------- mutations
class AmendmentRequestError(ValueError):
    """Refusal a route should flash verbatim."""


def create_request(pr, user, reason, proposed_lines):
    """File a request. Adds to the session; the caller commits.

    Refuses rather than silently no-ops on every precondition, because each one
    is a different fix for the user.
    """
    reason = (reason or '').strip()
    if len(reason) < PurchaseRequestAmendmentRequest.MIN_REASON_LEN:
        raise AmendmentRequestError(
            'Give a reason of at least %d characters -- it becomes the permanent '
            'record of why this approved requisition changed.'
            % PurchaseRequestAmendmentRequest.MIN_REASON_LEN)
    if pr.status not in PurchaseRequest.AMEND_STATUSES:
        raise AmendmentRequestError(
            'A Purchase Requisition with status "%s" cannot be amended.' % pr.status)
    if pr.is_converted():
        po_number = pr.purchase_order.po_number if pr.purchase_order else None
        raise AmendmentRequestError(
            'Purchase Requisition "%s" was already converted to Purchase Order %s. '
            'Amend that order instead.' % (pr.pr_number, po_number or '(unknown)'))
    if pending_request_for(pr.id) is not None:
        raise AmendmentRequestError(
            'This requisition already has an amendment request awaiting review.')

    # Validate the PROPOSAL now, not only at approval: telling the requester
    # immediately is the whole point, and it stops an unapprovable request from
    # sitting in an approver's queue.
    errors = validate_amendment(pr, proposed_lines, 'pr_item_id')
    if errors:
        raise AmendmentRequestError(errors[0])

    req = PurchaseRequestAmendmentRequest(
        purchase_request_id=pr.id,
        branch_id=pr.branch_id,
        requested_by_id=user.id,
        request_reason=reason,
    )
    req.set_proposed({'lines': proposed_lines})
    db.session.add(req)
    return req


def apply_request(req, approver):
    """Approve: apply the proposal to the requisition and append a revision.

    Runs the SAME `validate_amendment` and the SAME `_apply_amended_pr_lines`
    the approver-driven amend route runs -- imported at call time only to avoid
    a views<->service import cycle, not because the coupling is optional.

    Adds to the session; the caller commits. Returns the DocumentRevision.
    """
    from app.purchase_requests.views import _apply_amended_pr_lines

    if not req.is_pending:
        raise AmendmentRequestError(
            'This request has already been %s.' % req.status)

    pr = db.session.get(PurchaseRequest, req.purchase_request_id)
    if pr is None:
        raise AmendmentRequestError('The requisition no longer exists.')
    if pr.is_converted():
        po_number = pr.purchase_order.po_number if pr.purchase_order else None
        raise AmendmentRequestError(
            'Purchase Requisition "%s" was converted to Purchase Order %s while this '
            'request was pending. Amend that order instead.'
            % (pr.pr_number, po_number or '(unknown)'))

    proposed = req.proposed_lines()

    # Re-validate at APPLY time. The proposal was checked when filed, but the
    # requisition can have moved since -- a line consumed, the status changed.
    errors = validate_amendment(pr, proposed, 'pr_item_id')
    if errors:
        raise AmendmentRequestError(errors[0])

    _apply_amended_pr_lines(pr, proposed)
    db.session.flush()

    # Judge the APPLIED RESULT, not the payload -- the same rule the amend route
    # records: re-deriving it from the submission is how the hole survived its
    # first fix on the Purchase Order side.
    if not pr.has_requested_line():
        raise AmendmentRequestError(
            'A Purchase Requisition must keep at least one item with a product or '
            'a description. This amendment would leave none.')

    rev = write_revision(pr, approver.id, reason=req.request_reason)

    req.status = PurchaseRequestAmendmentRequest.STATUS_APPROVED
    req.reviewed_by_id = approver.id
    req.reviewed_at = ph_now()
    req.applied_revision_number = rev.revision_number
    return rev


def reject_request(req, approver, notes=None):
    """Reject: the requisition is left completely untouched."""
    if not req.is_pending:
        raise AmendmentRequestError(
            'This request has already been %s.' % req.status)
    req.status = PurchaseRequestAmendmentRequest.STATUS_REJECTED
    req.reviewed_by_id = approver.id
    req.reviewed_at = ph_now()
    req.review_notes = (notes or '').strip() or None
    return req
