"""Purchase Request views -- a thin requisition that converts to a draft PO on approval.
Mirror of app/quotations/views.py. Operational only: posts NO journal entry."""
import json
from datetime import date
from decimal import Decimal, InvalidOperation

from flask import (Blueprint, render_template, redirect, url_for, flash,
                   request, session, abort, current_app)
from flask_login import login_required, current_user

from sqlalchemy.orm import joinedload

from app import db
from app.purchase_requests.models import (
    PurchaseRequest, PurchaseRequestItem, generate_pr_number)
from app.purchase_requests.forms import PurchaseRequestForm, PurchaseRequestAmendForm
from app.amendments.models import DocumentRevision
from app.amendments.service import write_revision
from app.amendments.validation import validate_amendment
from app.users.models import User
from app.settings import AppSettings
from app.audit.utils import log_audit, log_create, log_update, model_to_dict
from app.errors.utils import log_exception
from app.utils import ph_now
from app.utils.cache_helpers import get_active_units, get_active_products
from app.utils.concurrency import claim_version, conflict_message, submitted_version

purchase_requests_bp = Blueprint('purchase_requests', __name__, template_folder='templates')

VALID_PR_STATUSES = {'draft', 'submitted', 'approved', 'rejected', 'converted', 'cancelled'}


# -- gates ---------------------------------------------------------------------

def _pr_role_gate():
    if current_user.role not in ['staff', 'accountant', 'admin', 'chief_accountant']:
        flash('You do not have permission to manage Purchase Requests.', 'error')
        return redirect(url_for('purchase_requests.list_pr'))
    return None


def _approve_gate():
    if not (current_user.has_full_access or current_user.role == 'accountant'):
        flash('Only an approver (accountant/admin) can approve Purchase Requests.', 'error')
        return False
    return True


def _get_pr_or_404(id):
    pr = db.get_or_404(PurchaseRequest, id)
    if pr.branch_id != session.get('selected_branch_id'):
        abort(404)
    return pr


def _common_form_ctx():
    return {
        'units': [u.to_dict() for u in get_active_units()],
        'products': [p.to_dict() for p in get_active_products()],
    }


def _pr_int(v):
    try:
        return int(v) if v and str(v).strip() not in ('', 'null') else None
    except (ValueError, TypeError):
        return None


def _pr_dec(v):
    try:
        return Decimal(str(v)) if v not in (None, '', 'null') else None
    except (InvalidOperation, TypeError):
        return None


def _pr_line_fields(d):
    """The five submitted values a requisition line carries, coerced.

    Shared by the rebuild parser (create / draft edit) and the in-place applier
    (amend) so the two can never disagree about how a submitted row is read --
    the drift that let the equivalent hole survive on the Purchase Order side.
    Returns (product_id, description, quantity, uom_id, uom_text).
    """
    return (
        _pr_int(d.get('product_id')),
        (d.get('description') or '').strip() or None,
        _pr_dec(d.get('quantity')),
        _pr_int(d.get('uom_id')),
        (d.get('uom_text') or None),
    )


def _apply_amended_pr_lines(pr, items):
    """Update this requisition's lines IN PLACE from the already-parsed submission.

    Takes the PARSED list, not a JSON string: the amend route parses once and
    hands the same object to the validator and to this function.

    WHY IN PLACE, when a rebuild strands nothing here. PO and SO must preserve
    line ids because a rebuild orphans ReceivingReportItem.purchase_order_item_id
    (and the SO delivery equivalents) with SQLite FK enforcement off. **PR has no
    such child** -- nothing declares a purchase_request_item_id, and conversion
    COPIES lines into a draft PO rather than pointing at them. The reason is
    narrower: PurchaseRequestItem.id is what lines two revision snapshots up row
    by row. `_parse_and_attach_pr_lines` appends fresh rows, so a rebuild would
    renumber every line on every amendment and leave Rev 0 and Rev 1 sharing no
    identity even for rows nobody touched.

    SECURITY: the lookup is scoped to THIS requisition's own line_items. A
    pr_item_id belonging to a DIFFERENT PR is never resolved against a global
    query, so it cannot rewrite another requisition's row -- it falls through to
    "not found" and becomes a new line here. Slice 2's review demonstrated the
    global-lookup version live on the PO side, rewriting another order's line and
    emptying the target.
    """
    items = items or []
    existing = {item.id: item for item in pr.line_items}
    seen = set()
    kept = 0

    for idx, d in enumerate(items, start=1):
        product_id, description, qty, uom_id, uom_text = _pr_line_fields(d)
        if product_id is None and description is None and qty is None:
            continue  # blank trailing line
        if product_id is None and description is None:
            raise ValueError(f'Line {idx}: enter a product or a description.')

        item = existing.get(_pr_int(d.get('pr_item_id')))
        if item is None:
            item = PurchaseRequestItem(purchase_request_id=pr.id)
            pr.line_items.append(item)
        else:
            seen.add(item.id)

        kept += 1
        item.line_number = kept
        item.product_id = product_id
        item.description = description
        item.quantity = qty
        item.unit_of_measure_id = uom_id
        item.uom_text = uom_text

    # NO minimum-line rule here, deliberately. This function APPLIES; the amend
    # route JUDGES the applied result with pr.has_requested_line() (task 1's
    # predicate, which is also what the create/edit parser's own rule restates).
    # Enforcing it in both places is the drift that let the same hole survive its
    # first fix on the Purchase Order side: the rule was closed by hand in one
    # spot and left open in the other, with a control test that only exercised
    # the closed one. One rule, one place, judged on the RESULT.

    # Iterate the PRE-LOOP snapshot, never the live collection: a row appended
    # above may have been assigned an id by an autoflush, and it was never added
    # to `seen`, so sweeping the live collection would delete the line the user
    # just added.
    for item_id, item in existing.items():
        if item_id not in seen:
            pr.line_items.remove(item)
            db.session.delete(item)


def _parse_and_attach_pr_lines(pr, lines_json):
    """Attach requisition lines. A line needs a Product OR a free-text description; no pricing.

    REBUILD path -- create and draft edit only. The amend route uses
    _apply_amended_pr_lines, which preserves line ids.
    """
    _int, _dec = _pr_int, _pr_dec

    items = json.loads(lines_json) if lines_json else []
    kept = 0
    for idx, d in enumerate(items, start=1):
        product_id, description, qty, uom_id, uom_text = _pr_line_fields(d)
        if product_id is None and description is None and qty is None:
            continue  # blank line
        if product_id is None and description is None:
            raise ValueError(f'Line {idx}: enter a product or a description.')
        kept += 1
        pr.line_items.append(PurchaseRequestItem(
            line_number=kept, product_id=product_id, description=description,
            quantity=qty, unit_of_measure_id=uom_id, uom_text=uom_text))
    if kept == 0:
        raise ValueError('Add at least one requested item.')


# -- routes --------------------------------------------------------------------

def _filtered_pr_query(include_ids=False):
    """Build a branch-scoped PurchaseRequest query from request filter args.

    Args read: status, q, date_from, date_to -- and ids when include_ids=True
    (exports only); a valid ids list overrides all other filters but stays
    branch-scoped. Invalid values are ignored.
    """
    branch_id = session.get('selected_branch_id')
    query = PurchaseRequest.query.filter_by(branch_id=branch_id)

    if include_ids:
        ids_param = request.args.get('ids', '')
        if ids_param:
            ids = [int(x) for x in ids_param.split(',') if x.strip().isdigit()]
            if ids:
                return query.filter(PurchaseRequest.id.in_(ids))

    status_filter = request.args.get('status', 'all')
    if status_filter in VALID_PR_STATUSES:
        query = query.filter_by(status=status_filter)

    q = request.args.get('q', '').strip()
    if q:
        like = f'%{q}%'
        query = query.filter(db.or_(PurchaseRequest.pr_number.ilike(like),
                                    PurchaseRequest.reason.ilike(like)))

    date_from = request.args.get('date_from', '')
    if date_from:
        try:
            query = query.filter(PurchaseRequest.request_date >= date.fromisoformat(date_from))
        except ValueError:
            pass

    date_to = request.args.get('date_to', '')
    if date_to:
        try:
            query = query.filter(PurchaseRequest.request_date <= date.fromisoformat(date_to))
        except ValueError:
            pass

    return query


@purchase_requests_bp.route('/purchase-requests')
@login_required
def list_pr():
    from app.purchase_requests.utils import compute_pr_summary

    page = request.args.get('page', 1, type=int)
    per_page = 50

    query = _filtered_pr_query().order_by(PurchaseRequest.request_date.desc(),
                                          PurchaseRequest.id.desc())
    pagination = query.paginate(page=page, per_page=per_page, error_out=False)

    branch_id = session.get('selected_branch_id')
    summary = compute_pr_summary(branch_id)

    return render_template('purchase_requests/list.html',
                           pr_list=pagination.items,
                           pagination=pagination,
                           summary=summary,
                           status_filter=request.args.get('status', 'all'),
                           q=request.args.get('q', ''),
                           date_from=request.args.get('date_from', ''),
                           date_to=request.args.get('date_to', ''))


@purchase_requests_bp.route('/purchase-requests/create', methods=['GET', 'POST'])
@login_required
def create():
    gate = _pr_role_gate()
    if gate:
        return gate
    form = PurchaseRequestForm()
    if form.validate_on_submit():
        pr_number = (form.pr_number.data or '').strip()
        if PurchaseRequest.query.filter(PurchaseRequest.pr_number == pr_number).first():
            flash('Purchase Request number already exists.', 'error')
            return render_template('purchase_requests/form.html', form=form, pr=None,
                                   line_items=[], **_common_form_ctx())
        try:
            pr = PurchaseRequest(
                branch_id=session.get('selected_branch_id'),
                pr_number=pr_number,
                request_date=form.request_date.data,
                reason=form.reason.data or None,
                status='draft', created_by_id=current_user.id)
            _parse_and_attach_pr_lines(pr, request.form.get('line_items', '[]'))
            db.session.add(pr); db.session.commit()
            log_create(module='purchase_requests', record_id=pr.id,
                       record_identifier=pr.pr_number,
                       new_values=model_to_dict(pr, ['pr_number', 'request_date', 'status']))
            flash(f'Purchase Request "{pr.pr_number}" created.', 'success')
            return redirect(url_for('purchase_requests.view', id=pr.id))
        except ValueError as e:
            db.session.rollback(); flash(str(e), 'error')
            return render_template('purchase_requests/form.html', form=form, pr=None,
                                   line_items=[], **_common_form_ctx())
        except Exception as e:
            db.session.rollback()
            current_app.logger.error('Error creating purchase request', exc_info=True)
            log_exception(e, severity='ERROR', module='purchase_requests.create')
            flash('An error occurred creating the Purchase Request.', 'error')

    if request.method == 'GET':
        form.pr_number.data = generate_pr_number()
        form.request_date.data = ph_now().date()
    return render_template('purchase_requests/form.html', form=form, pr=None,
                           line_items=[], **_common_form_ctx())


def _revision_panel_rows(pr):
    """Rows for the detail page's revision-history panel, newest first.

    ONE query, and one `joinedload` rather than a lazy `amended_by` per row --
    a relationship access behind a Jinja expression would render an identical
    page while paying a query per revision, invisible to anyone reading the view.

    `document_type` is part of the filter, not decoration: `document_id` is a
    plain Integer pointing at eight different tables, so PR id 1 and Purchase
    Order id 1 are the same number and only the type separates them.

    Flattened to plain dicts so the template cannot reach a relationship at all.
    """
    revisions = (DocumentRevision.query
                 .options(joinedload(DocumentRevision.amended_by))
                 .filter_by(document_type=PurchaseRequest.DOCUMENT_TYPE,
                            document_id=pr.id)
                 .order_by(DocumentRevision.revision_number.desc())
                 .all())
    return [{
        'number': r.revision_number,
        # Already Philippine local time: amended_at defaults to ph_now() and is
        # stored on a naive DateTime column, so the offset is dropped on the way
        # in. Formatting is left to the template's strftime -- passing it through
        # format_ph_datetime() would treat this naive PH value as UTC and shift
        # it forward eight hours.
        'amended_at': r.amended_at,
        'amended_by': r.amended_by.username if r.amended_by else None,
        'reason': r.reason,
    } for r in revisions]


@purchase_requests_bp.route('/purchase-requests/<int:id>')
@login_required
def view(id):
    pr = _get_pr_or_404(id)
    created_by_user = db.session.get(User, pr.created_by_id) if pr.created_by_id else None
    return render_template('purchase_requests/detail.html', pr=pr,
                           created_by_user=created_by_user,
                           revisions=_revision_panel_rows(pr))


@purchase_requests_bp.route('/purchase-requests/<int:id>/edit', methods=['GET', 'POST'])
@login_required
def edit(id):
    gate = _pr_role_gate()
    if gate:
        return gate
    pr = _get_pr_or_404(id)
    if pr.status != 'draft':
        flash('Only a draft Purchase Request can be edited.', 'error')
        return redirect(url_for('purchase_requests.view', id=id))
    form = PurchaseRequestForm(obj=pr)
    restore = ([li.to_dict() for li in pr.line_items] if request.method == 'GET'
               else json.loads(request.form.get('line_items', '[]') or '[]'))

    if form.validate_on_submit():
        old = model_to_dict(pr, ['pr_number', 'request_date', 'status'])
        try:
            if not claim_version(PurchaseRequest, pr.id, submitted_version()):
                db.session.rollback()
                flash(conflict_message('purchase_requests', pr.id), 'error')
                return render_template('purchase_requests/form.html', form=form, pr=pr,
                                       line_items=restore, **_common_form_ctx())
            pr.request_date = form.request_date.data
            pr.reason = form.reason.data or None
            pr.line_items.clear()
            _parse_and_attach_pr_lines(pr, request.form.get('line_items', '[]'))
            db.session.commit()
            log_update(module='purchase_requests', record_id=pr.id, record_identifier=pr.pr_number,
                       old_values=old, new_values=model_to_dict(pr, ['pr_number', 'request_date', 'status']))
            flash(f'Purchase Request "{pr.pr_number}" updated.', 'success')
            return redirect(url_for('purchase_requests.view', id=pr.id))
        except ValueError as e:
            db.session.rollback(); flash(str(e), 'error')
        except Exception as e:
            db.session.rollback()
            log_exception(e, severity='ERROR', module='purchase_requests.edit')
            flash('An error occurred updating the Purchase Request.', 'error')
    return render_template('purchase_requests/form.html', form=form, pr=pr,
                           line_items=restore, **_common_form_ctx())


@purchase_requests_bp.route('/purchase-requests/<int:id>/amend', methods=['GET', 'POST'])
@login_required
def amend(id):
    """Post-approval amendment. The PR keeps its status and number; every save
    appends a DocumentRevision."""
    pr = _get_pr_or_404(id)

    # APPROVE-level gate, NOT _pr_role_gate(). _pr_role_gate admits `staff`
    # (it guards create/edit); _approve_gate does not. An amendment rewrites an
    # already-approved requisition, so it is gated on who may approve one --
    # gating it on the edit rule is exactly the Critical shipped on the Purchase
    # Order side, where a staff user who could not approve a PO could rewrite an
    # approved one.
    if not _approve_gate():
        return redirect(url_for('purchase_requests.view', id=id))

    if pr.status == 'draft':
        flash('A draft Purchase Request is edited, not amended.', 'error')
        return redirect(url_for('purchase_requests.edit', id=id))
    if pr.is_converted():
        # Name the PO. A bare "cannot be amended" leaves the user nowhere to go;
        # the actionable fact is WHICH order this requisition became, since that
        # is the document they must change instead.
        po_number = pr.purchase_order.po_number if pr.purchase_order else None
        flash('Purchase Request "%s" was already converted to Purchase Order %s. '
              'Amend that order instead.'
              % (pr.pr_number, po_number or '(unknown)'), 'error')
        return redirect(url_for('purchase_requests.view', id=id))
    if pr.status not in PurchaseRequest.AMEND_STATUSES:
        flash('A Purchase Request with status "%s" cannot be amended.' % pr.status, 'error')
        return redirect(url_for('purchase_requests.view', id=id))

    form = PurchaseRequestAmendForm(obj=pr)

    # Parse the payload ONCE and hand the parsed list to both the validator and
    # the applier, so the two can never disagree about what was submitted.
    #   * ABSENT key: `.get('line_items', '[]')` cannot tell "the hidden field
    #     never reached the server" from "the user deleted every row" -- that
    #     conflation has already shipped in this codebase.
    #   * UNPARSEABLE or NOT A LIST: json.loads raises, or iterating a scalar
    #     does, either way a 500 where the contract promises messages.
    submitted_lines = []
    line_items_error = None
    if request.method == 'POST':
        if 'line_items' not in request.form:
            line_items_error = ('The line items did not reach the server. '
                                'Reload the page and try again.')
        else:
            try:
                submitted_lines = json.loads(request.form.get('line_items') or '[]')
            except ValueError:  # json.JSONDecodeError subclasses ValueError
                line_items_error = ('The line items could not be read. '
                                    'Reload the page and try again.')
            else:
                if not isinstance(submitted_lines, list):
                    line_items_error = ('The line items could not be read. '
                                        'Reload the page and try again.')
                    submitted_lines = []

    # On a refusal re-render the RAW submission so the user keeps their edits --
    # except when that submission is the thing being refused, where the stored
    # lines are the only usable starting point.
    restore = ([li.to_dict() for li in pr.line_items]
               if request.method == 'GET' or line_items_error else submitted_lines)

    def _render():
        return render_template('purchase_requests/form.html', form=form, pr=pr,
                               amend_mode=True, line_items=restore,
                               **_common_form_ctx())

    if line_items_error:
        flash(line_items_error, 'error')
        return _render()

    if form.validate_on_submit():
        # Validate BEFORE claiming the version: claim_version's conditional
        # UPDATE bumps row_version as a side effect, so claiming first would
        # leave a pending write behind on a refusal that only re-renders.
        errors = validate_amendment(pr, submitted_lines, 'pr_item_id')
        if errors:
            for message in errors:
                flash(message, 'error')
            return _render()

        old = model_to_dict(pr, ['pr_number', 'request_date', 'reason', 'status'])
        try:
            if not claim_version(PurchaseRequest, pr.id, submitted_version()):
                db.session.rollback()
                flash(conflict_message('purchase_requests', pr.id), 'error')
                return _render()

            # pr_number is deliberately NOT reassigned -- an amendment revises a
            # requisition, it does not renumber it. request_date and reason are
            # ordinary editable fields and must not be silently discarded.
            pr.request_date = form.request_date.data
            pr.reason = form.reason.data or None

            _apply_amended_pr_lines(pr, submitted_lines)
            db.session.flush()

            # Judge the APPLIED RESULT, not the payload. Re-deriving the rule
            # from the submission is how the same hole survived its first fix on
            # the Purchase Order side. Raising routes this through the ValueError
            # handler below, whose rollback undoes both the line changes and
            # claim_version's row_version bump.
            if not pr.has_requested_line():
                raise ValueError(
                    'A Purchase Request must keep at least one item with a '
                    'product or a description. This amendment would leave none.')

            rev = write_revision(pr, current_user.id,
                                 reason=(form.amend_reason.data or '').strip())
            db.session.commit()

            # action='amend', not 'update': the audit log is where an auditor
            # separates "somebody edited a draft" from "somebody rewrote an
            # approved requisition". conflict_message() reads both.
            log_audit(module='purchase_requests', action='amend', record_id=pr.id,
                      record_identifier=pr.pr_number, old_values=old,
                      new_values=model_to_dict(
                          pr, ['pr_number', 'request_date', 'reason', 'status']),
                      notes='Amended to Rev %s' % rev.revision_number)
            flash('Purchase Request "%s" amended (Rev %s).'
                  % (pr.pr_number, rev.revision_number), 'success')
            return redirect(url_for('purchase_requests.view', id=pr.id))

        except ValueError as e:
            db.session.rollback()
            flash(str(e), 'error')
            return _render()
        except Exception as e:
            db.session.rollback()
            log_exception(e, severity='ERROR', module='purchase_requests.amend')
            flash('An error occurred while saving the amendment. Please try again.', 'error')

    elif request.method == 'POST':
        # A WTForms field-level failure (amend_reason too short) only populates
        # form.<field>.errors, and this template does not render per-field errors
        # -- without this the refusal reason vanishes and the response is an
        # indistinguishable 200.
        for field_errors in form.errors.values():
            for message in field_errors:
                flash(message, 'error')

    return _render()


# -- lifecycle -----------------------------------------------------------------

@purchase_requests_bp.route('/purchase-requests/<int:id>/submit', methods=['POST'])
@login_required
def submit(id):
    pr = _get_pr_or_404(id)
    gate = _pr_role_gate()
    if gate:
        return gate
    if pr.status != 'draft':
        flash('Only a draft Purchase Request can be submitted.', 'error')
        return redirect(url_for('purchase_requests.view', id=id))
    pr.status = 'submitted'
    pr.submitted_by_id = current_user.id
    pr.submitted_at = ph_now()
    db.session.commit()
    log_audit(module='purchase_requests', action='update', record_id=pr.id,
              record_identifier=pr.pr_number, notes='Submitted')
    flash(f'Purchase Request "{pr.pr_number}" submitted for approval.', 'success')
    return redirect(url_for('purchase_requests.view', id=id))


@purchase_requests_bp.route('/purchase-requests/<int:id>/approve', methods=['POST'])
@login_required
def approve(id):
    pr = _get_pr_or_404(id)
    if not _approve_gate():
        return redirect(url_for('purchase_requests.view', id=id))
    if pr.status != 'submitted':
        flash('Only a submitted Purchase Request can be approved.', 'error')
        return redirect(url_for('purchase_requests.view', id=id))
    pr.status = 'approved'
    pr.approved_by_id = current_user.id
    pr.approved_at = ph_now()
    # Rev 0 -- the baseline every later amendment is measured against. Written
    # AFTER the status assignment so the snapshot records the PR as approved, and
    # inside the same transaction so approval and baseline land atomically.
    # baseline=True claims revision slot 0; it is the only call in this module
    # that may, and an amendment finding no baseline starts at Rev 1 rather than
    # occupying the slot (see app/amendments/service.py::write_revision).
    write_revision(pr, current_user.id, baseline=True)
    db.session.commit()
    log_audit(module='purchase_requests', action='approve', record_id=pr.id,
              record_identifier=pr.pr_number, notes='Approved')
    flash(f'Purchase Request "{pr.pr_number}" approved. Convert it to a Purchase Order.', 'success')
    return redirect(url_for('purchase_requests.view', id=id))


@purchase_requests_bp.route('/purchase-requests/<int:id>/reject', methods=['POST'])
@login_required
def reject(id):
    pr = _get_pr_or_404(id)
    if not _approve_gate():
        return redirect(url_for('purchase_requests.view', id=id))
    if pr.status != 'submitted':
        flash('Only a submitted Purchase Request can be rejected.', 'error')
        return redirect(url_for('purchase_requests.view', id=id))
    reason = (request.form.get('reject_reason') or '').strip()
    if len(reason) < 10:
        flash('A rejection reason (min 10 chars) is required.', 'error')
        return redirect(url_for('purchase_requests.view', id=id))
    pr.status = 'rejected'
    pr.rejected_by_id = current_user.id
    pr.rejected_at = ph_now()
    pr.reject_reason = reason
    db.session.commit()
    log_audit(module='purchase_requests', action='update', record_id=pr.id,
              record_identifier=pr.pr_number, notes=f'Rejected: {reason}')
    flash(f'Purchase Request "{pr.pr_number}" rejected.', 'warning')
    return redirect(url_for('purchase_requests.view', id=id))


@purchase_requests_bp.route('/purchase-requests/<int:id>/cancel', methods=['POST'])
@login_required
def cancel(id):
    pr = _get_pr_or_404(id)
    if not _approve_gate():
        return redirect(url_for('purchase_requests.view', id=id))
    if pr.status in ('converted', 'cancelled', 'rejected'):
        flash('This Purchase Request can no longer be cancelled.', 'error')
        return redirect(url_for('purchase_requests.view', id=id))
    reason = (request.form.get('cancel_reason') or '').strip()
    if len(reason) < 10:
        flash('A cancellation reason (min 10 chars) is required.', 'error')
        return redirect(url_for('purchase_requests.view', id=id))
    pr.status = 'cancelled'
    pr.cancelled_by_id = current_user.id
    pr.cancelled_at = ph_now()
    pr.cancel_reason = reason
    db.session.commit()
    log_audit(module='purchase_requests', action='update', record_id=pr.id,
              record_identifier=pr.pr_number, notes=f'Cancelled: {reason}')
    flash(f'Purchase Request "{pr.pr_number}" cancelled.', 'warning')
    return redirect(url_for('purchase_requests.view', id=id))


@purchase_requests_bp.route('/purchase-requests/<int:id>/convert', methods=['POST'])
@login_required
def convert(id):
    """Approved PR -> a NEW draft Purchase Order (buyer adds vendor + prices).
    Mirror of quotations.accept -> draft SO."""
    pr = _get_pr_or_404(id)
    if not _approve_gate():
        return redirect(url_for('purchase_requests.view', id=id))
    if pr.status != 'approved':
        flash('Only an approved Purchase Request can be converted to a Purchase Order.', 'error')
        return redirect(url_for('purchase_requests.view', id=id))
    # Import inside the function to avoid an import cycle at module load.
    from app.purchase_orders.models import PurchaseOrder, PurchaseOrderItem, generate_po_number
    try:
        po = PurchaseOrder(
            po_number=generate_po_number(), branch_id=pr.branch_id,
            order_date=ph_now().date(), status='draft', vat_treatment='inclusive',
            notes='', purchase_request_id=pr.id, created_by_id=current_user.id)
        for li in pr.line_items:
            po.line_items.append(PurchaseOrderItem(
                line_number=li.line_number, product_id=li.product_id,
                description=li.description, quantity=li.quantity,
                unit_of_measure_id=li.unit_of_measure_id, uom_text=li.uom_text,
                unit_price=None, amount=Decimal('0'), vat_rate=Decimal('0')))
        po.calculate_totals()
        db.session.add(po); db.session.flush()      # get po.id
        pr.status = 'converted'
        pr.purchase_order_id = po.id
        db.session.commit()
        log_audit(module='purchase_requests', action='convert', record_id=pr.id,
                  record_identifier=pr.pr_number, notes=f'Converted -> {po.po_number}')
        flash(f'Purchase Request "{pr.pr_number}" converted to draft Purchase Order '
              f'"{po.po_number}". Add the vendor and prices.', 'success')
        return redirect(url_for('purchase_orders.view', id=po.id))
    except Exception as e:
        db.session.rollback()
        log_exception(e, severity='ERROR', module='purchase_requests.convert')
        flash('An error occurred converting the Purchase Request.', 'error')
        return redirect(url_for('purchase_requests.view', id=id))


@purchase_requests_bp.route('/purchase-requests/<int:id>/print')
@login_required
def print_pr(id):
    pr = _get_pr_or_404(id)
    company = {'name': AppSettings.get_setting('company_name', ''),
               'address': AppSettings.get_setting('company_address', ''),
               'tin': AppSettings.get_setting('company_tin', '')}
    return render_template('purchase_requests/print.html', pr=pr, company=company,
                           printed_at=ph_now())


# -- export routes -----------------------------------------------------------------

_EXPORT_COLUMNS = ['pr_number', 'request_date', 'reason', 'purchase_order.po_number', 'status']
_EXPORT_HEADERS = ['PR #', 'Request Date', 'Reason', 'Converted PO #', 'Status']


@purchase_requests_bp.route('/purchase-requests/export/excel')
@login_required
def export_excel():
    from app.utils.export import export_to_excel
    rows = _filtered_pr_query(include_ids=True).order_by(PurchaseRequest.request_date.desc()).all()
    log_audit('purchase_requests', 'export_excel', None, f'{len(rows)} records',
              notes=f'Exported by {current_user.username}; filters: {request.args.to_dict()}')
    timestamp = ph_now().strftime('%Y%m%d_%H%M%S')
    return export_to_excel(data=rows, columns=_EXPORT_COLUMNS, headers=_EXPORT_HEADERS,
                           filename=f'purchase_requests_{timestamp}.xlsx',
                           title='Purchase Requests Report')


@purchase_requests_bp.route('/purchase-requests/export/csv')
@login_required
def export_csv_route():
    from app.utils.export import export_to_csv
    rows = _filtered_pr_query(include_ids=True).order_by(PurchaseRequest.request_date.desc()).all()
    log_audit('purchase_requests', 'export_csv', None, f'{len(rows)} records',
              notes=f'Exported by {current_user.username}; filters: {request.args.to_dict()}')
    timestamp = ph_now().strftime('%Y%m%d_%H%M%S')
    return export_to_csv(data=rows, columns=_EXPORT_COLUMNS, headers=_EXPORT_HEADERS,
                         filename=f'purchase_requests_{timestamp}.csv')
