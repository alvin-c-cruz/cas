"""Purchase Order views -- create/edit/list/view + lifecycle. Buy-side mirror of
app/sales_orders/views.py. Operational module only: posts NO journal entry, has NO GL
account, NO WHT, NO payment. The Bill (Accounts Payable) is the first document that hits
the ledger. Lines accept a Product (goods) OR a free-text description (services)."""
import json
from datetime import date
from decimal import Decimal, InvalidOperation

from flask import (Blueprint, render_template, redirect, url_for, flash,
                   request, session, abort, current_app, jsonify)
from flask_login import login_required, current_user
from sqlalchemy.orm import joinedload

from app import db
from app.purchase_orders.models import (
    PurchaseOrder, PurchaseOrderItem, next_po_number_for, next_po_signatories_for,
    group_lines_by_description)
from app.purchase_orders.forms import PurchaseOrderForm, PurchaseOrderAmendForm
from app.purchase_orders.preprinted_layout import (
    COLUMN_LABELS, FIELD_LABELS, get_layout, save_layout)
from app.common.preprinted_base import (
    DATE_FORMATS, FONT_GROUPS, PAPER_LABELS, PAPER_SIZES, TEXT_KEYS)
from app.vendors.models import Vendor
from app.users.models import User
from app.settings import AppSettings
from app.amendments.models import DocumentRevision
from app.amendments.service import write_revision
from app.amendments.validation import validate_amendment
from app.audit.utils import log_audit, log_create, log_update, model_to_dict
from app.errors.utils import log_exception
from app.utils import ph_now
from app.utils.cache_helpers import get_active_units, get_active_products, get_vat_categories
from app.utils.concurrency import claim_version, conflict_message, submitted_version

purchase_orders_bp = Blueprint('purchase_orders', __name__, template_folder='templates')

VALID_PO_STATUSES = {'draft', 'submitted', 'approved', 'partially_received',
                     'closed', 'cancelled'}


# ── line-item helpers ────────────────────────────────────────────────────────

def _po_line_dec(v):
    try:
        return Decimal(str(v)) if v not in (None, '', 'null') else None
    except (InvalidOperation, TypeError):
        return None


def _po_line_int(v):
    try:
        return int(v) if v and str(v).strip() not in ('', 'null') else None
    except (ValueError, TypeError):
        return None


def _po_line_is_blank(d):
    """True for a blank trailing line -- a row the user never filled in.

    Extracted so the up-front allocation pre-pass and the per-line coercion skip
    exactly the same rows. Two spellings of "blank" would let a line the pre-pass
    ignored still be saved (or the reverse), which is the whole class of bug the
    pre-pass exists to close.
    """
    amount = Decimal(str(d.get('amount', '0') or '0'))
    return (_po_line_int(d.get('product_id')) is None
            and not (d.get('description') or '').strip()
            and (amount is None or amount == 0)
            and _po_line_dec(d.get('quantity')) is None
            and _po_line_dec(d.get('unit_price')) is None)


def _assert_payload_allocations(items, exclude_po_id=None):
    """Weigh the WHOLE submitted line array against the requisition ceilings,
    before a single row is touched.

    Called by BOTH line paths at their top, so no write path can reach the
    database without it -- _assign_po_line_fields is the only place a line is
    coerced, and these two functions are its only callers.

    Why here and not per line: the ceiling belongs to the REQUISITION line, and
    one payload may name one requisition line on several of its own rows. The
    per-line check inside _assign_po_line_fields measures each row against a sum
    over PO lines already in the DATABASE, so it cannot see its own siblings --
    the same requisition line pulled twice into one order passed twice and
    doubled it. See assert_payload_within_open_qty.

    Deliberately does NOT re-judge the two per-line refusals (unknown id, wrong
    branch): _assign_po_line_fields owns those messages, and re-deriving them
    here would be a second spelling of a rule. An unknown id is skipped and
    refused by name a moment later; a wrong-branch line forms its own group (a
    different requisition line, hence a different id) so counting it can only add
    a refusal to a line that is being refused anyway.
    """
    from app.purchase_requests.models import PurchaseRequestItem
    from app.purchase_requests.allocation import (assert_no_pending_amendment,
                                                  assert_payload_within_open_qty)
    allocations = []
    for idx, d in enumerate(items or [], start=1):
        if not isinstance(d, dict) or _po_line_is_blank(d):
            continue
        src_id = _po_line_int(d.get('source_pr_item_id'))
        if src_id is None:
            continue
        pr_item = db.session.get(PurchaseRequestItem, src_id)
        if pr_item is None:
            continue
        allocations.append((pr_item, _po_line_dec(d.get('quantity')), idx))
    # Refuse an amendment-blocked requisition BEFORE the quantity maths: the
    # quantities are irrelevant if the requisition may not be ordered at all,
    # and checking first gives the accurate refusal rather than a confusing
    # over-quantity message.
    assert_no_pending_amendment(allocations)
    assert_payload_within_open_qty(allocations, exclude_po_id=exclude_po_id)


def _assign_po_line_fields(item, d, idx, branch_id=None, exclude_po_id=None):
    """Coerce one submitted line dict onto *item*. A line needs a Product (goods)
    OR a free-text description (services).

    Shared by BOTH line paths -- _parse_and_attach_po_lines (draft edit,
    rebuild-from-scratch) and _apply_amended_po_lines (post-approval amend,
    update in place) -- so the coercion rules live in exactly one place. Does NOT
    touch line_number (each caller assigns it once it knows how many non-blank
    lines it has kept) or received_quantity/billed_quantity (not form fields).

    *idx* is the line's 1-based position in the SUBMITTED array, used only in the
    raised ValueError's message. Returns False (leaving *item* untouched) for a
    blank trailing line; True otherwise.
    """
    vat_rate = _po_line_dec(d.get('vat_rate')) or Decimal('0.00')
    product_id = _po_line_int(d.get('product_id'))
    description = (d.get('description') or '').strip() or None
    amount = Decimal(str(d.get('amount', '0') or '0'))
    qty = _po_line_dec(d.get('quantity'))
    price = _po_line_dec(d.get('unit_price'))
    if _po_line_is_blank(d):
        return False  # skip a blank trailing line
    if product_id is None and description is None:
        raise ValueError(f'Line {idx}: enter a product or a description.')

    item.description = description
    item.quantity = qty
    item.unit_price = price
    item.uom_text = (d.get('uom_text') or None)
    item.unit_of_measure_id = _po_line_int(d.get('uom_id'))
    item.product_id = product_id
    item.amount = amount
    item.vat_category = d.get('vat_category') or None
    item.vat_rate = vat_rate

    # Requisition allocation. The id is validated HERE rather than trusted from
    # the payload: the picker filters by branch and by open quantity, and a
    # POST bypasses both.
    src_id = _po_line_int(d.get('source_pr_item_id'))
    if src_id is None:
        item.source_pr_item_id = None
    else:
        # Do NOT clear item.source_pr_item_id first. On the amend path the row
        # is already persistent, and the ceiling query below AUTOFLUSHES -- a
        # pre-emptive None would be written out, dropping this line from its own
        # SUM and neutering the check by accident. Assign only after it passes.
        from app.purchase_requests.models import PurchaseRequestItem, PurchaseRequest
        from app.purchase_requests.allocation import assert_within_open_qty
        pr_item = db.session.get(PurchaseRequestItem, src_id)
        if pr_item is None:
            raise ValueError(f'Line {idx}: the requisition line no longer exists.')
        pr = db.session.get(PurchaseRequest, pr_item.purchase_request_id)
        if pr is None or (branch_id is not None and pr.branch_id != branch_id):
            raise ValueError(f'Line {idx}: that requisition line belongs to another branch.')
        # The ROW's own contract. The SUBMISSION's ceiling is enforced by
        # _assert_payload_allocations, which both callers run before any row is
        # touched -- this one cannot see its siblings and so cannot be the guard
        # for a multi-line payload. Kept because this helper is the single place
        # a line is coerced and must not silently assume its caller pre-screened;
        # both call the same implementation, so there is one rule, not two.
        assert_within_open_qty(pr_item, qty, idx, exclude_po_id=exclude_po_id)
        item.source_pr_item_id = src_id

    item.calculate_amounts()
    return True


def _refresh_source_requisitions(po):
    """Recompute the status of every requisition this PO draws from.

    Called after any write that can change what is ordered -- create, edit,
    amend and cancel. Idempotent, so calling it twice is harmless and calling
    it on a PO with no requisition lines does nothing.
    """
    from app.purchase_requests.models import PurchaseRequest, PurchaseRequestItem
    from app.purchase_requests.allocation import recompute_pr_status
    ids = {li.source_pr_item_id for li in po.line_items if li.source_pr_item_id}
    if not ids:
        return
    pr_ids = {row.purchase_request_id for row in
              PurchaseRequestItem.query.filter(PurchaseRequestItem.id.in_(ids)).all()}
    for pr in PurchaseRequest.query.filter(PurchaseRequest.id.in_(pr_ids)).all():
        recompute_pr_status(pr)


def _parse_and_attach_po_lines(po, lines_json, branch_id=None, exclude_po_id=None):
    """Parse hidden-JSON line array and attach PurchaseOrderItem objects to *po*.
    A line needs a Product (goods) OR a free-text description (services)."""
    items = json.loads(lines_json) if lines_json else []
    # Whole-payload allocation ceiling FIRST, before any line is attached.
    _assert_payload_allocations(items, exclude_po_id=exclude_po_id)
    kept = 0
    for idx, d in enumerate(items, start=1):
        li = PurchaseOrderItem()
        if not _assign_po_line_fields(li, d, idx, branch_id=branch_id,
                                      exclude_po_id=exclude_po_id):
            continue  # skip a blank trailing line
        kept += 1
        li.line_number = kept
        po.line_items.append(li)


def _apply_amended_po_lines(po, items, branch_id=None, exclude_po_id=None):
    """Update this PO's lines IN PLACE from the ALREADY-PARSED submitted array.

    Takes the parsed list, not the raw JSON string, so the route parses the
    submission exactly once -- the same object it handed validate_amendment.
    Re-parsing here would let the two see different bytes if anything in between
    ever touched request.form, and it would put a json.loads (a 500 on malformed
    input) back inside the write path the route has already screened.

    Unlike _parse_and_attach_po_lines (which the draft edit path uses after a
    wholesale DELETE of every row), this preserves PurchaseOrderItem.id for every
    line the user kept. That id is load-bearing twice over:

      * it is the identity two revision snapshots are lined up by, so a rebuild
        would make every amendment look like "all lines removed, all lines added";
      * ReceivingReportItem.purchase_order_item_id points at it. SQLite FK
        enforcement is OFF app-wide, so a rebuild does not error -- it silently
        strands every existing RR line, and the next po_line_open_qty() on one
        dereferences None and 500s, unrecoverable through the UI.

    A submitted line carries `po_item_id` when it came from an existing row and
    null when the user added it in this amendment -- the SAME key
    validate_amendment() parses on. Validation must mirror application: any
    existing row whose id is absent from the submission was removed by the user
    and is deleted here, which is exactly the case validate_amendment refuses
    when that line has receipts or references against it.

    SECURITY: the lookup is scoped to THIS order's own po.line_items -- a
    po_item_id belonging to a DIFFERENT Purchase Order is never resolved through
    a global query, so it cannot rewrite another order's row. It falls through to
    "not found" and creates a new line on this order instead.
    """
    items = items or []
    # Whole-payload allocation ceiling FIRST, before any row is updated, added
    # or deleted. On THIS path it is the only check that can see a duplicated
    # requisition line at all: exclude_po_id takes the order's own committed
    # lines out of the ceiling (it must -- see the route), so the per-line check
    # measures each submitted row against an ordered total this order does not
    # appear in.
    _assert_payload_allocations(items, exclude_po_id=exclude_po_id)
    existing = {item.id: item for item in po.line_items}
    seen = set()
    kept = 0

    for idx, d in enumerate(items, start=1):
        item_id = _po_line_int(d.get('po_item_id'))
        item = existing.get(item_id) if item_id is not None else None
        is_new = item is None
        if is_new:
            item = PurchaseOrderItem(purchase_order_id=po.id)

        if not _assign_po_line_fields(item, d, idx, branch_id=branch_id,
                                      exclude_po_id=exclude_po_id):
            # For an EXISTING item this `continue` leaves it out of `seen`, so
            # the sync loop below deletes it -- an implicit "blank an existing
            # row to remove it" path. It is unreachable in practice only because
            # a blank submission also blanks quantity, and validate_amendment's
            # per-row parse refuses a missing/unreadable quantity before this
            # function is ever called. The two parsers must keep matching.
            continue  # blank trailing line -- do not attach/keep it
        kept += 1
        item.line_number = kept

        if is_new:
            db.session.add(item)
            po.line_items.append(item)
        else:
            seen.add(item.id)

    # Iterate the PRE-LOOP `existing` snapshot, never the live collection: a row
    # appended above can be autoflushed (and so assigned an id) mid-loop, and its
    # id was never added to `seen`, so a sweep over the LIVE collection would
    # target the line the user just added. Today that does not fail silently --
    # db.session.delete() on the freshly-appended instance raises
    # InvalidRequestError ("is not persisted"), which the route's generic handler
    # turns into a lost amendment behind a generic error flash. Loud, but still a
    # lost amendment, and only an accident of instance state away from the silent
    # deletion it would otherwise be.
    for item_id, item in existing.items():
        if item_id not in seen:
            po.line_items.remove(item)
            db.session.delete(item)


# ── role gate + helpers ───────────────────────────────────────────────────────

def _role_gate():
    """EDIT-level rule: who may create or edit a DRAFT Purchase Order."""
    if current_user.role not in ['staff', 'accountant', 'admin', 'chief_accountant']:
        flash('You do not have permission to perform this action.', 'error')
        return redirect(url_for('purchase_orders.list_po'))
    return None


def _has_approve_level_role():
    """APPROVE-level rule: who may change a Purchase Order that is already approved.

    Strictly narrower than _role_gate() -- `staff` is admitted there and refused
    here. Shared by approve(), cancel() and amend() so the three cannot drift:
    an amendment rewrites quantities and totals on an approved document, so
    gating it on the edit-level rule would let a staff user who cannot approve a
    PO rewrite one the moment somebody else did (10 -> 10000, 50.00 ->
    5,000,000.00, revision recorded in their name). An approval control that can
    be bypassed by amending one second later is not a control.

    Predicate, not a gate: each caller keeps its own message and redirect.
    """
    return current_user.role == 'accountant' or current_user.has_full_access


def _get_po_or_404(id):
    po = db.get_or_404(PurchaseOrder, id)
    if po.branch_id != session.get('selected_branch_id'):
        abort(404)
    return po


def _revision_panel_rows(po):
    """Rows for the detail page's revision-history panel, newest first.

    ONE query, and one `joinedload` rather than a lazy `amended_by` per row --
    `latest_revision()` per revision (or a bare relationship access in the
    template) would render an identical page while paying a query per revision.
    `tests/integration/test_po_revision_panel.py` measures this by counting the
    SQL the request actually executes, at 1 and at 6 revisions.

    `document_type` is part of the filter, not decoration: `document_id` is a
    plain Integer pointing at eight different tables, so PO id 1 and Sales Order
    id 1 are the same number and only the type separates them.

    Flattened to plain dicts here rather than handed to the template as ORM rows
    so the template cannot reach a relationship (and therefore a query) behind a
    Jinja expression, where it would be invisible to anyone reading this view.
    """
    revisions = (DocumentRevision.query
                 .options(joinedload(DocumentRevision.amended_by))
                 .filter_by(document_type=po.DOCUMENT_TYPE, document_id=po.id)
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
        'authorizing_reference': r.authorizing_reference,
    } for r in revisions]


def _active_vendors():
    return Vendor.query.filter_by(is_active=True).order_by(Vendor.name).all()


def _common_form_ctx():
    return {
        'units': [u.to_dict() for u in get_active_units()],
        'products': [p.to_dict() for p in get_active_products()],
        'vat_categories': [v.to_dict() for v in get_vat_categories()],
    }


# ── routes ───────────────────────────────────────────────────────────────────

def _filtered_po_query(include_ids=False):
    """Build a branch-scoped PurchaseOrder query from request filter args.

    Args read: status, vendor, q, date_from, date_to -- and ids when
    include_ids=True (exports only); a valid ids list overrides all other
    filters but stays branch-scoped. Invalid values are ignored.
    """
    branch_id = session.get('selected_branch_id')
    query = PurchaseOrder.query.filter_by(branch_id=branch_id)

    if include_ids:
        ids_param = request.args.get('ids', '')
        if ids_param:
            ids = [int(x) for x in ids_param.split(',') if x.strip().isdigit()]
            if ids:
                return query.filter(PurchaseOrder.id.in_(ids))

    status_filter = request.args.get('status', 'all')
    if status_filter in VALID_PO_STATUSES:
        query = query.filter_by(status=status_filter)

    vendor_filter = request.args.get('vendor', 'all')
    if vendor_filter != 'all':
        try:
            query = query.filter_by(vendor_id=int(vendor_filter))
        except ValueError:
            pass

    q_text = request.args.get('q', '').strip()
    if q_text:
        like = f'%{q_text}%'
        query = query.filter(db.or_(PurchaseOrder.po_number.ilike(like),
                                    PurchaseOrder.vendor_name.ilike(like)))

    date_from = request.args.get('date_from', '')
    if date_from:
        try:
            query = query.filter(PurchaseOrder.order_date >= date.fromisoformat(date_from))
        except ValueError:
            pass

    date_to = request.args.get('date_to', '')
    if date_to:
        try:
            query = query.filter(PurchaseOrder.order_date <= date.fromisoformat(date_to))
        except ValueError:
            pass

    return query


@purchase_orders_bp.route('/purchase-orders')
@login_required
def list_po():
    from app.purchase_orders.utils import compute_po_summary
    from app.vendors.models import Vendor

    page = request.args.get('page', 1, type=int)
    per_page = 50

    query = _filtered_po_query().order_by(PurchaseOrder.order_date.desc(),
                                          PurchaseOrder.id.desc())
    pagination = query.paginate(page=page, per_page=per_page, error_out=False)

    branch_id = session.get('selected_branch_id')
    summary = compute_po_summary(branch_id)
    vendors = Vendor.query.filter_by(is_active=True).order_by(Vendor.name).all()

    return render_template('purchase_orders/list.html',
                           po_list=pagination.items,
                           pagination=pagination,
                           vendors=vendors,
                           summary=summary,
                           status_filter=request.args.get('status', 'all'),
                           vendor_filter=request.args.get('vendor', 'all'),
                           q=request.args.get('q', ''),
                           date_from=request.args.get('date_from', ''),
                           date_to=request.args.get('date_to', ''))


@purchase_orders_bp.route('/purchase-orders/billable')
@login_required
def billable_pos():
    """JSON: approved, unbilled, RR-less POs for a vendor -- the services/direct billing path.
    Auto-gated by the purchase_orders module (before_request), so it 404s when the module is off.
    Data source for the AP form's billing picker."""
    from app.purchase_billing import billable_pos_for, ap_billing_consolidate
    branch_id = session.get('selected_branch_id')
    vendor_id = request.args.get('vendor_id', type=int)
    pos = billable_pos_for(branch_id, vendor_id) if vendor_id else []
    return jsonify({'consolidate': ap_billing_consolidate(), 'pos': pos})


@purchase_orders_bp.route('/purchase-orders/create', methods=['GET', 'POST'])
@login_required
def create():
    gate = _role_gate()
    if gate:
        return gate

    form = PurchaseOrderForm()
    vendors = _active_vendors()
    form.set_vendor_choices(vendors)

    if form.validate_on_submit():
        po_number = (form.po_number.data or '').strip()

        if PurchaseOrder.query.filter(PurchaseOrder.po_number == po_number).first():
            flash('Purchase Order number already exists.', 'error')
            return render_template('purchase_orders/form.html', form=form, po=None,
                                   line_items=[], vendors=vendors, **_common_form_ctx())

        vendor = db.session.get(Vendor, form.vendor_id.data)
        if not vendor:
            flash('Selected vendor not found.', 'error')
            return render_template('purchase_orders/form.html', form=form, po=None,
                                   line_items=[], vendors=vendors, **_common_form_ctx())

        try:
            po = PurchaseOrder(
                branch_id=session.get('selected_branch_id'),
                po_number=po_number,
                order_date=form.order_date.data,
                expected_date=form.expected_date.data or None,
                vendor_id=vendor.id,
                vendor_name=vendor.name,
                vendor_tin=vendor.tin,
                vendor_address=vendor.address,
                vat_treatment=form.vat_treatment.data,
                payment_terms=form.payment_terms.data,
                reference=form.reference.data or None,
                purpose=form.purpose.data or None,
                notes=form.notes.data or '',
                prepared_by=(form.prepared_by.data or '').strip() or None,
                checked_by=(form.checked_by.data or '').strip() or None,
                approved_by=(form.approved_by.data or '').strip() or None,
                status='draft',
                created_by_id=current_user.id,
            )
            _parse_and_attach_po_lines(po, request.form.get('line_items', '[]'),
                                       branch_id=session.get('selected_branch_id'))
            po.calculate_totals()
            db.session.add(po)
            # Flush before recomputing: the requisition's open quantity is a SUM
            # over PO lines in the DATABASE, so pending lines must be there for
            # this order to count towards it.
            db.session.flush()
            _refresh_source_requisitions(po)
            db.session.commit()

            log_create(
                module='purchase_orders',
                record_id=po.id,
                record_identifier=f'{po.po_number} - {po.vendor_name}',
                new_values=model_to_dict(po, [
                    'po_number', 'order_date', 'vendor_name',
                    'subtotal', 'vat_amount', 'total_amount', 'status']),
            )
            flash(f'Purchase Order "{po.po_number}" created successfully!', 'success')
            return redirect(url_for('purchase_orders.list_po'))

        except ValueError as e:
            db.session.rollback()
            flash(str(e), 'error')
            return render_template('purchase_orders/form.html', form=form, po=None,
                                   line_items=[], vendors=vendors, **_common_form_ctx())
        except Exception as e:
            db.session.rollback()
            current_app.logger.error('Error creating purchase order', exc_info=True)
            log_exception(e, severity='ERROR', module='purchase_orders.create')
            flash('An error occurred while entering the Purchase Order. Please try again.', 'error')

    if request.method == 'GET':
        # A SUGGESTION off this purchaser's own pre-printed pad -- the two pads'
        # ranges never overlap, so a global next-number points into the other
        # purchaser's range. The user may still overwrite it.
        form.po_number.data = next_po_number_for(current_user.id,
                                                 session.get('selected_branch_id'))
        form.order_date.data = ph_now().date()
        # Signatories carry forward off the SAME pad -- this purchaser's own last
        # order, not a company-wide setting, which would hand one purchaser the
        # other's people. A suggestion, editable per order.
        for field, value in next_po_signatories_for(current_user.id).items():
            getattr(form, field).data = value

    return render_template('purchase_orders/form.html', form=form, po=None,
                           line_items=[], vendors=vendors, **_common_form_ctx())


@purchase_orders_bp.route('/purchase-orders/<int:id>')
@login_required
def view(id):
    po = _get_po_or_404(id)
    created_by_user = (db.session.get(User, po.created_by_id) if po.created_by_id else None)
    approved_by_user = (db.session.get(User, po.approved_by_id) if po.approved_by_id else None)
    cancelled_by_user = (db.session.get(User, po.cancelled_by_id) if po.cancelled_by_id else None)
    return render_template('purchase_orders/detail.html', po=po,
                           created_by_user=created_by_user,
                           approved_by_user=approved_by_user,
                           cancelled_by_user=cancelled_by_user,
                           # Both settings the Print button is gated on, read HERE
                           # rather than in the template, so the button and
                           # print_po()'s own guards read the same two values.
                           po_print_form=AppSettings.get_setting('po_print_form', 'current'),
                           po_print_access=AppSettings.get_setting('po_print_access',
                                                                   'approved_only'),
                           revisions=_revision_panel_rows(po))


@purchase_orders_bp.route('/purchase-orders/<int:id>/edit', methods=['GET', 'POST'])
@login_required
def edit(id):
    gate = _role_gate()
    if gate:
        return gate

    po = _get_po_or_404(id)
    if po.status != 'draft':
        flash('Only draft Purchase Orders can be edited.', 'error')
        return redirect(url_for('purchase_orders.view', id=id))

    form = PurchaseOrderForm(obj=po)
    vendors = _active_vendors()
    form.set_vendor_choices(vendors)

    restore_items = ([li.to_dict() for li in po.line_items]
                     if request.method == 'GET'
                     else json.loads(request.form.get('line_items', '[]') or '[]'))

    if form.validate_on_submit():
        po_number = (form.po_number.data or '').strip()
        if PurchaseOrder.query.filter(PurchaseOrder.po_number == po_number,
                                      PurchaseOrder.id != po.id).first():
            flash('Purchase Order number already exists.', 'error')
            return render_template('purchase_orders/form.html', form=form, po=po,
                                   line_items=restore_items, vendors=vendors, **_common_form_ctx())

        vendor = db.session.get(Vendor, form.vendor_id.data)
        if not vendor:
            flash('Selected vendor not found.', 'error')
            return render_template('purchase_orders/form.html', form=form, po=po,
                                   line_items=restore_items, vendors=vendors, **_common_form_ctx())

        try:
            old_values = model_to_dict(po, [
                'po_number', 'order_date', 'vendor_name',
                'subtotal', 'vat_amount', 'total_amount', 'status'])

            # Lost-update guard: the first write, before the line teardown below.
            if not claim_version(PurchaseOrder, po.id, submitted_version()):
                db.session.rollback()
                flash(conflict_message('purchase_orders', po.id), 'error')
                return render_template('purchase_orders/form.html', form=form, po=po,
                                       line_items=restore_items, vendors=vendors, **_common_form_ctx())

            po.po_number = po_number
            po.order_date = form.order_date.data
            po.expected_date = form.expected_date.data or None
            po.vendor_id = vendor.id
            po.vendor_name = vendor.name
            po.vendor_tin = vendor.tin
            po.vendor_address = vendor.address
            po.vat_treatment = form.vat_treatment.data
            po.payment_terms = form.payment_terms.data
            po.reference = form.reference.data or None
            po.purpose = form.purpose.data or None
            po.notes = form.notes.data or ''
            for _sig in PurchaseOrderForm.SIGNATORY_FIELDS:
                setattr(po, _sig, (getattr(form, _sig).data or '').strip() or None)

            db.session.execute(db.delete(PurchaseOrderItem)
                               .where(PurchaseOrderItem.purchase_order_id == po.id))
            # exclude_po_id: without it this order's own lines count against
            # itself and an unchanged save fails the ceiling check.
            _parse_and_attach_po_lines(po, request.form.get('line_items', '[]'),
                                       branch_id=session.get('selected_branch_id'),
                                       exclude_po_id=po.id)
            db.session.flush()
            db.session.expire(po, ['line_items'])
            po.calculate_totals()
            _refresh_source_requisitions(po)
            db.session.commit()

            log_update(
                module='purchase_orders',
                record_id=po.id,
                record_identifier=f'{po.po_number} - {po.vendor_name}',
                old_values=old_values,
                new_values=model_to_dict(po, [
                    'po_number', 'order_date', 'vendor_name',
                    'subtotal', 'vat_amount', 'total_amount', 'status']))
            flash(f'Purchase Order "{po.po_number}" updated successfully!', 'success')
            return redirect(url_for('purchase_orders.view', id=po.id))

        except ValueError as e:
            db.session.rollback()
            flash(str(e), 'error')
            return render_template('purchase_orders/form.html', form=form, po=po,
                                   line_items=restore_items, vendors=vendors, **_common_form_ctx())
        except Exception as e:
            db.session.rollback()
            current_app.logger.error('Error updating purchase order', exc_info=True)
            log_exception(e, severity='ERROR', module='purchase_orders.edit')
            flash('An error occurred while saving the Purchase Order. Please try again.', 'error')

    return render_template('purchase_orders/form.html', form=form, po=po,
                           line_items=restore_items, vendors=vendors, **_common_form_ctx())


@purchase_orders_bp.route('/purchase-orders/<int:id>/amend', methods=['GET', 'POST'])
@login_required
def amend(id):
    """Post-approval amendment. Mirrors edit(), but the PO keeps its status and
    every save appends a DocumentRevision."""
    # APPROVE-level gate, deliberately NOT _role_gate(). See
    # _has_approve_level_role(): amending rewrites an already-approved document,
    # so it is gated on who may approve, not on who may edit a draft. The message
    # and redirect stay _role_gate()'s -- only the admitted set is narrower.
    if not _has_approve_level_role():
        flash('You do not have permission to perform this action.', 'error')
        return redirect(url_for('purchase_orders.list_po'))

    po = _get_po_or_404(id)
    if po.status == 'draft':
        flash('A draft Purchase Order is edited, not amended.', 'error')
        return redirect(url_for('purchase_orders.edit', id=id))
    if po.status not in PurchaseOrder.AMEND_STATUSES:
        flash(f'A Purchase Order with status "{po.status}" cannot be amended.', 'error')
        return redirect(url_for('purchase_orders.view', id=id))

    form = PurchaseOrderAmendForm(obj=po)
    vendors = _active_vendors()
    form.set_vendor_choices(vendors)

    # Parse the submitted line array ONCE, here, and refuse the three shapes that
    # must never reach the applier:
    #
    #  * key ABSENT. `request.form.get('line_items', '[]')` cannot tell "the
    #    field never arrived" from "the user deleted every line", so a POST that
    #    dropped the hidden input -- the BUG-DR-EDIT-FALSE-CONFLICT class, which
    #    has already shipped in this codebase once -- reads as a full clear-out
    #    and leaves an APPROVED PO with zero lines and a 0.00 total, a state
    #    approve() itself refuses, reported as a success.
    #  * not JSON. json.loads raises out of the view (an unhandled 500), which
    #    contradicts app/amendments/validation.py's contract that a crafted POST
    #    produces messages, not a 500 -- the crafted POST never reaches it.
    #  * valid JSON that is not an ARRAY. `123`, `true` and `1.5` parse fine and
    #    then raised TypeError inside parse_submission -- and validate_amendment
    #    is called below, OUTSIDE the try, so that was a 500 too. `"x"` and
    #    `{"a": 1}` are iterable and produced one bogus message per character or
    #    key, and `null` reached the applier as `items or []` and emptied the
    #    order. json.loads produces a list for every submission this form can
    #    make; anything else is crafted.
    #
    # An EXPLICIT '[]' is deliberately NOT refused here: it is a real submission
    # (the user removed every row) and belongs to validate_amendment, which judges
    # it per line, and then to has_approvable_line(), which judges the RESULT.
    #
    # (edit() and sales_orders.amend() share the same holes; fixing them is a
    # separate change and deliberately out of scope here.)
    stored_items = [li.to_dict() for li in po.line_items]
    submitted_lines = []
    line_items_error = None
    unreadable = ('The line items could not be read. '
                  'Reload the page and try again.')
    if request.method == 'POST':
        if 'line_items' not in request.form:
            line_items_error = ('The line items did not reach the server. '
                                'Reload the page and try again.')
        else:
            try:
                submitted_lines = json.loads(request.form.get('line_items') or '[]')
            except ValueError:  # json.JSONDecodeError subclasses ValueError
                line_items_error = unreadable
            else:
                if not isinstance(submitted_lines, list):
                    submitted_lines = []
                    line_items_error = unreadable

    # On a refusal the form re-renders the RAW submission so the user does not
    # lose their edits -- except when that submission is the thing being refused,
    # where the stored lines are the only usable starting point.
    restore_items = (stored_items if request.method == 'GET' or line_items_error
                     else submitted_lines)

    def _render():
        return render_template('purchase_orders/form.html', form=form, po=po,
                               amend_mode=True, line_items=restore_items,
                               vendors=vendors, **_common_form_ctx())

    if line_items_error:
        flash(line_items_error, 'error')
        return _render()

    if form.validate_on_submit():
        # Validate BEFORE claiming the version. claim_version's conditional
        # UPDATE increments row_version as a side effect, so claiming first would
        # leave a pending write behind on a refusal that then just re-renders.
        errors = validate_amendment(po, submitted_lines, 'po_item_id')
        if errors:
            for message in errors:
                flash(message, 'error')
            return _render()

        vendor = db.session.get(Vendor, form.vendor_id.data)
        if not vendor:
            flash('Selected vendor not found.', 'error')
            return _render()

        try:
            if not claim_version(PurchaseOrder, po.id, submitted_version()):
                db.session.rollback()
                flash(conflict_message('purchase_orders', po.id), 'error')
                return _render()

            old_values = model_to_dict(po, [
                'po_number', 'order_date', 'vendor_name',
                'subtotal', 'vat_amount', 'total_amount', 'status'])

            # po_number is deliberately NOT reassigned (an amendment revises an
            # order, it does not renumber it) -- but order_date is an ordinary
            # editable field and must not be silently discarded.
            po.order_date = form.order_date.data
            po.expected_date = form.expected_date.data or None
            po.vendor_id = vendor.id
            po.vendor_name = vendor.name
            po.vendor_tin = vendor.tin
            po.vendor_address = vendor.address
            po.vat_treatment = form.vat_treatment.data
            po.payment_terms = form.payment_terms.data
            po.reference = form.reference.data or None
            po.purpose = form.purpose.data or None
            po.notes = form.notes.data or ''
            for _sig in PurchaseOrderForm.SIGNATORY_FIELDS:
                setattr(po, _sig, (getattr(form, _sig).data or '').strip() or None)

            # UPDATE IN PLACE -- do NOT delete-and-rebuild the way edit() does.
            # See _apply_amended_po_lines: a rebuild strands every
            # ReceivingReportItem.purchase_order_item_id, silently.
            # exclude_po_id is genuinely load-bearing HERE, unlike on edit():
            # this path updates in place, so without it the order's own lines
            # count against the requisition ceiling and any amendment of a
            # fully-pulled line is refused.
            _apply_amended_po_lines(po, submitted_lines, branch_id=po.branch_id,
                                    exclude_po_id=po.id)
            db.session.flush()
            db.session.expire(po, ['line_items'])
            po.calculate_totals()

            # An amendment may not leave the order in a shape approve() would
            # have refused. Checked on the RESULT, through approve()'s own
            # predicate, rather than by re-deriving the rule from the submitted
            # payload: the payload is a list of dicts and the rule is about
            # PurchaseOrderItem rows, and a second hand-written spelling of a
            # rule is exactly what let this hole through the first time.
            # Raising routes it through the ValueError handler below, whose
            # rollback undoes both the line changes and claim_version's version
            # bump, leaving the PO byte-identical.
            if not po.has_approvable_line():
                raise ValueError(
                    'A Purchase Order must keep at least one line with a unit '
                    'price and an amount. This amendment would leave none.')

            _refresh_source_requisitions(po)

            rev = write_revision(po, current_user.id,
                                 reason=(form.amend_reason.data or '').strip())
            db.session.commit()

            # action='amend', not 'update': the audit log is where an auditor
            # separates "somebody edited a draft" from "somebody rewrote an
            # APPROVED document", and 'update' collapses the two. conflict_message()
            # reads both actions, so the lost-update message still names an
            # amender.
            log_audit(
                module='purchase_orders',
                action='amend',
                record_id=po.id,
                record_identifier=f'{po.po_number} - {po.vendor_name}',
                old_values=old_values,
                new_values=model_to_dict(po, [
                    'po_number', 'order_date', 'vendor_name',
                    'subtotal', 'vat_amount', 'total_amount', 'status']),
                notes=f'Amended to Rev {rev.revision_number}')

            flash(f'Purchase Order "{po.po_number}" amended '
                  f'(Rev {rev.revision_number}).', 'success')
            return redirect(url_for('purchase_orders.view', id=po.id))

        except ValueError as e:
            db.session.rollback()
            flash(str(e), 'error')
            return _render()
        except Exception as e:
            db.session.rollback()
            current_app.logger.error('Error amending purchase order', exc_info=True)
            log_exception(e, severity='ERROR', module='purchase_orders.amend')
            flash('An error occurred while saving the amendment. Please try again.', 'error')

    elif request.method == 'POST':
        # validate_on_submit() failed on a real submission. A WTForms field-level
        # error (e.g. amend_reason's Length) only populates form.<field>.errors,
        # and form.html does not render per-field errors for amend_reason -- so
        # without this the refusal reason vanishes and the response is a plain
        # 200 indistinguishable from a success.
        for field_errors in form.errors.values():
            for message in field_errors:
                flash(message, 'error')

    return _render()


@purchase_orders_bp.route('/purchase-orders/<int:id>/submit', methods=['POST'])
@login_required
def submit(id):
    """draft -> submitted. Mirrors purchase_requests.submit.

    Gated on the EDIT-level rule (_role_gate), not the approve-level one: the
    whole point is that a staff purchaser -- who may build an order but may not
    approve it -- has a way to hand it on. Before this, she could raise a draft
    and then move it nowhere.
    """
    po = _get_po_or_404(id)
    gate = _role_gate()
    if gate:
        return gate
    if po.status != 'draft':
        flash('Only a draft Purchase Order can be submitted.', 'error')
        return redirect(url_for('purchase_orders.view', id=id))
    if po.vendor_id is None:
        flash('Set a vendor before submitting this Purchase Order.', 'error')
        return redirect(url_for('purchase_orders.view', id=id))
    po.status = 'submitted'
    po.submitted_by_id = current_user.id
    po.submitted_at = ph_now()
    db.session.commit()
    # action='submit', not 'update': the audit log's Actions filter is built from
    # the DISTINCT actions present, so a lifecycle event logged as a generic
    # update is unfilterable and reads as an ordinary edit.
    log_audit(module='purchase_orders', action='submit', record_id=po.id,
              record_identifier=po.po_number, notes='Submitted')
    flash(f'Purchase Order "{po.po_number}" submitted for approval.', 'success')
    return redirect(url_for('purchase_orders.view', id=id))


@purchase_orders_bp.route('/purchase-orders/<int:id>/approve', methods=['POST'])
@login_required
def approve(id):
    """Draft or submitted -> approved. No journal entry -- a PO posts nothing."""
    po = _get_po_or_404(id)
    if not _has_approve_level_role():
        flash('You do not have permission to approve Purchase Orders.', 'error')
        return redirect(url_for('purchase_orders.view', id=id))
    # 'draft' is still accepted alongside 'submitted': an approver who raises an
    # order herself should not have to submit it to herself first, which is how
    # the requisition already behaves. The submit step exists so a STAFF
    # purchaser has a way forward, not to add a hop for someone who never needed
    # one.
    if po.status not in ('draft', 'submitted'):
        flash('Only draft or submitted Purchase Orders can be approved.', 'error')
        return redirect(url_for('purchase_orders.view', id=id))
    if po.vendor_id is None:
        flash('Set a vendor before approving this Purchase Order.', 'error')
        return redirect(url_for('purchase_orders.view', id=id))
    # The same predicate amend() enforces on its RESULT -- see
    # PurchaseOrder.has_approvable_line. Extracted, not reworded: an amendment
    # must not be able to undo this check one second after it passed.
    if not po.has_approvable_line():
        flash('Set a unit price on at least one line before approving this Purchase Order.', 'error')
        return redirect(url_for('purchase_orders.view', id=id))

    old_values = model_to_dict(po, ['status'])
    po.status = 'approved'
    po.approved_by_id = current_user.id
    po.approved_at = ph_now()
    # Rev 0 -- the baseline every later amendment is measured against. Written
    # AFTER the status change so the snapshot records the PO as approved, and
    # inside the same transaction so approval and baseline land atomically.
    # baseline=True claims revision slot 0; it is the only call in the app that
    # may, and an amendment that finds no baseline starts at Rev 1 rather than
    # occupying the slot (see write_revision).
    write_revision(po, current_user.id, baseline=True)
    db.session.commit()

    log_update(module='purchase_orders', record_id=po.id, record_identifier=po.po_number,
               old_values=old_values, new_values=model_to_dict(po, ['status']), notes='Approved')
    flash(f'Purchase Order "{po.po_number}" has been approved.', 'success')
    return redirect(url_for('purchase_orders.view', id=id))


@purchase_orders_bp.route('/purchase-orders/<int:id>/cancel', methods=['POST'])
@login_required
def cancel(id):
    """Non-terminal PO -> cancelled. Captures a reason from the custom modal form."""
    po = _get_po_or_404(id)
    if not _has_approve_level_role():
        flash('You do not have permission to cancel Purchase Orders.', 'error')
        return redirect(url_for('purchase_orders.view', id=id))
    if po.accounts_payable_id is not None:
        flash('A billed Purchase Order cannot be cancelled. Void the bill first.', 'error')
        return redirect(url_for('purchase_orders.view', id=id))
    if po.status in ('cancelled', 'closed'):
        flash('This Purchase Order has already been cancelled or closed.', 'error')
        return redirect(url_for('purchase_orders.view', id=id))

    cancel_reason = request.form.get('cancel_reason', '').strip()
    if len(cancel_reason) < 10:
        flash('Please provide a cancellation reason (at least 10 characters).', 'error')
        return redirect(url_for('purchase_orders.view', id=id))

    old_values = model_to_dict(po, ['status'])
    po.status = 'cancelled'
    po.cancelled_by_id = current_user.id
    po.cancelled_at = ph_now()
    po.cancel_reason = cancel_reason
    # The lines are still attached, so this reopens every requisition line the
    # cancelled order was holding -- no restore step, the sum simply stops
    # counting a cancelled PO.
    db.session.flush()
    _refresh_source_requisitions(po)
    db.session.commit()

    log_update(module='purchase_orders', record_id=po.id, record_identifier=po.po_number,
               old_values=old_values, new_values=model_to_dict(po, ['status']),
               notes=f'Cancelled: {cancel_reason}')
    flash(f'Purchase Order "{po.po_number}" has been cancelled.', 'success')
    return redirect(url_for('purchase_orders.view', id=id))


@purchase_orders_bp.route('/purchase-orders/<int:id>/print')
@login_required
def print_po(id):
    """Print a Purchase Order -- the form is chosen by the `po_print_form` company
    setting (current = standard printable form . preprinted = data-only overlay for
    the client's own pre-printed stationery . hidden = printing disabled). Mirrors
    sales_orders.print_so."""
    po = _get_po_or_404(id)
    po_print_form = AppSettings.get_setting('po_print_form', 'current')
    if po_print_form == 'hidden':
        flash('Purchase Order printing is not enabled.', 'error')
        return redirect(url_for('purchase_orders.view', id=id))
    # Enforced HERE, not only by hiding the button -- a direct GET bypasses the
    # template entirely.
    #
    # A CANCELLED purchase order is NEVER printable, at any setting: neither print
    # surface shows status (print.html carries no status text and the overlay is
    # data-only by design), so a printed cancelled PO is indistinguishable on paper
    # from a live order at the supplier's end. Every sibling excludes cancelled in
    # BOTH branches of its gate -- sales_invoices/detail.html:110-111,
    # accounts_payable/detail.html:112-113, cash_disbursements/detail.html:77-78.
    if po.status == 'cancelled':
        flash('A cancelled Purchase Order cannot be printed.', 'error')
        return redirect(url_for('purchase_orders.view', id=id))
    # DRAFT is the only status po_print_access governs, and the check is DEFAULT-DENY:
    # the exemption needs an exact 'draft_and_approved' match, so an unrecognised or
    # stale stored value (e.g. a 'posted_only' left by the shared PRINT_ACCESS_CHOICES)
    # refuses rather than opens. Matches sales_invoices/views.py:1401-1403 and
    # cash_disbursements/views.py:1354-1355.
    po_print_access = AppSettings.get_setting('po_print_access', 'approved_only')
    if po.status == 'draft' and po_print_access != 'draft_and_approved':
        flash('A draft Purchase Order cannot be printed. Approve it first.', 'error')
        return redirect(url_for('purchase_orders.view', id=id))
    company = {
        'name': AppSettings.get_setting('company_name', ''),
        'address': AppSettings.get_setting('company_address', ''),
        'tin': AppSettings.get_setting('company_tin', ''),
    }
    if po_print_form == 'preprinted':
        return render_template(
            'purchase_orders/print_preprinted.html', po=po, company=company,
            printed_at=ph_now(), layout=get_layout(po.branch_id),
            can_edit_layout=current_user.has_full_access,
            col_labels=COLUMN_LABELS, font_groups=FONT_GROUPS,
            paper_sizes=PAPER_SIZES, paper_labels=PAPER_LABELS,
            date_formats=DATE_FORMATS, field_labels=FIELD_LABELS,
            signatory_ids=TEXT_KEYS,
            date_labels={k: date(2026, 6, 17).strftime(v) for k, v in DATE_FORMATS.items()})
    return render_template('purchase_orders/print.html', po=po, company=company,
                           printed_at=ph_now(),
                           line_groups=group_lines_by_description(po.line_items))


@purchase_orders_bp.route('/purchase-orders/print-layout', methods=['POST'])
@login_required
def save_print_layout():
    """Persist the pre-printed layout JSON (full-access: admin or Chief Accountant).

    Mirrors sales_orders.save_print_layout: a layout edit changes what prints on a
    client's real, BIR-registered stationery, so it is deliberately narrower than
    the module's edit-level role rule."""
    if not current_user.has_full_access:
        abort(403)
    data = request.get_json(silent=True) or {}
    # The layout is per-branch; the print page requires the selected branch to equal
    # the document's branch, so the session branch is the document's branch.
    clean = save_layout(data, current_user.username, session.get('selected_branch_id'))
    return jsonify(ok=True, layout=clean)


# ── export routes ────────────────────────────────────────────────────────────

_EXPORT_COLUMNS = ['po_number', 'order_date', 'vendor_name', 'vendor_tin', 'subtotal',
                   'vat_amount', 'total_amount', 'status']
_EXPORT_HEADERS = ['PO #', 'Order Date', 'Vendor', 'TIN', 'Subtotal', 'VAT', 'Total', 'Status']


@purchase_orders_bp.route('/purchase-orders/export/excel')
@login_required
def export_excel():
    from app.utils.export import export_to_excel
    rows = _filtered_po_query(include_ids=True).order_by(PurchaseOrder.order_date.desc()).all()
    log_audit('purchase_orders', 'export_excel', None, f'{len(rows)} records',
              notes=f'Exported by {current_user.username}; filters: {request.args.to_dict()}')
    timestamp = ph_now().strftime('%Y%m%d_%H%M%S')
    return export_to_excel(data=rows, columns=_EXPORT_COLUMNS, headers=_EXPORT_HEADERS,
                           filename=f'purchase_orders_{timestamp}.xlsx',
                           title='Purchase Orders Report')


@purchase_orders_bp.route('/purchase-orders/export/csv')
@login_required
def export_csv_route():
    from app.utils.export import export_to_csv
    rows = _filtered_po_query(include_ids=True).order_by(PurchaseOrder.order_date.desc()).all()
    log_audit('purchase_orders', 'export_csv', None, f'{len(rows)} records',
              notes=f'Exported by {current_user.username}; filters: {request.args.to_dict()}')
    timestamp = ph_now().strftime('%Y%m%d_%H%M%S')
    return export_to_csv(data=rows, columns=_EXPORT_COLUMNS, headers=_EXPORT_HEADERS,
                         filename=f'purchase_orders_{timestamp}.csv')
