"""Receiving Report views -- goods received against an approved Purchase Order.
Buy-side mirror of app/delivery_receipts/views.py. Approving a RR posts a GRNI accrual
JE (Dr Inventory / Cr GRNI, net of VAT) for tracked-inventory lines via
app.receiving_reports.stock_posting.post_rr_receipt -- a no-op for untracked lines.
The open-qty grid caps received qty at each PO line's OPEN quantity (checked at approve)."""
import json
from datetime import date
from decimal import Decimal, InvalidOperation

from flask import (Blueprint, render_template, redirect, url_for, flash,
                   request, session, abort, jsonify)
from flask_login import login_required, current_user
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import joinedload, selectinload

from app import db
from app.receiving_reports.models import (
    ReceivingReport, ReceivingReportItem, po_line_open_qty, generate_rr_number)
from app.receiving_reports.forms import ReceivingReportForm
from app.receiving_reports.preprinted_layout import (
    COLUMN_LABELS, FIELD_LABELS, get_layout, save_layout)
from app.common.preprinted_base import (
    DATE_FORMATS, FONT_GROUPS, PAPER_LABELS, PAPER_SIZES, TEXT_KEYS)
from app.purchase_orders.models import PurchaseOrder, PurchaseOrderItem
from app.vendors.models import Vendor
from app.settings import AppSettings
from app.audit.utils import log_audit, log_create, log_update, model_to_dict
from app.utils import ph_now
from app.utils.concurrency import claim_version, conflict_message, submitted_version

receiving_reports_bp = Blueprint('receiving_reports', __name__, template_folder='templates')

VALID_RR_STATUSES = {'draft', 'approved', 'billed', 'cancelled'}

# Approved POs are receivable; 'partially_received' too once that transition ships.
RECEIVABLE_PO_STATUSES = ('approved', 'partially_received')


# -- gates ---------------------------------------------------------------------

# Who may build a receipt. Named once so the form's PO-line picker
# (open_lines below) cannot drift from the create/edit views it feeds -- a
# picker that answers to someone who may not save is a data leak with no
# purpose.
RR_EDIT_ROLES = ('staff', 'accountant', 'admin', 'chief_accountant')


def _rr_role_gate():
    if current_user.role not in RR_EDIT_ROLES:
        flash('You do not have permission to manage Receiving Reports.', 'error')
        return redirect(url_for('receiving_reports.list_rr'))
    return None


def _approve_role_gate():
    if not (current_user.has_full_access or current_user.role == 'accountant'):
        flash('Only an approver (accountant/admin) can approve Receiving Reports.', 'error')
        return False
    return True


# -- form context --------------------------------------------------------------

def _active_vendors():
    return Vendor.query.filter_by(is_active=True).order_by(Vendor.name).all()


def _eligible_purchase_orders(branch_id, vendor_id):
    """Approved (or partially-received) POs of *vendor_id*, in this branch, that
    still have at least one line with open qty.

    Returns [] when vendor_id is falsy (None or the picker's 0 "-- Select vendor
    --" sentinel): the create view has no vendor chosen on first load, and there
    is no PO to be eligible against until there is a vendor to scope by. Silently
    falling back to every vendor's receivable POs would defeat the vendor-first
    design this whole task exists for -- see TestNoVendorChosenYet in
    tests/integration/test_rr_vendor_scoping.py.

    The guard is BEHAVIOURALLY REDUNDANT and kept on purpose: `vendor_id == NULL`
    and `vendor_id == 0` match no PurchaseOrder row either, so removing it alone
    changes no answer (removing it does not fail a test -- the filter below is what
    the vendor tests kill). It stays because it skips a pointless query and states
    the rule where a reader meets it, rather than leaving "no vendor yet" to be
    inferred from SQL that happens to return nothing.
    """
    if not vendor_id:
        return []
    pos = (PurchaseOrder.query
           .filter(PurchaseOrder.branch_id == branch_id,
                   PurchaseOrder.vendor_id == vendor_id,
                   PurchaseOrder.status.in_(RECEIVABLE_PO_STATUSES))
           .order_by(PurchaseOrder.order_date.desc(), PurchaseOrder.id.desc()).all())
    return [po for po in pos if any(po_line_open_qty(li) > 0 for li in po.line_items)]


def _po_lines_payload(eligible, exclude_rr_id=None):
    """{po_id: [line dicts]} for the create/edit form's open-qty grid."""
    payload = {}
    for po in eligible:
        rows = []
        for li in po.line_items:
            open_qty = po_line_open_qty(li, exclude_rr_id=exclude_rr_id)
            ordered = Decimal(str(li.quantity or 0))
            rows.append({
                'purchase_order_item_id': li.id,
                'product_code': li.product.code if li.product else '',
                'product_name': (li.product.name if li.product else (li.description or '')),
                'uom': (li.unit_of_measure.code if li.unit_of_measure else (li.uom_text or '')),
                'ordered': float(ordered),
                'received': float(ordered - open_qty),
                'open': float(open_qty),
            })
        payload[po.id] = rows
    return payload


def _existing_lines(rr):
    if not rr:
        return {}
    return {li.purchase_order_item_id: float(li.received_quantity) for li in rr.line_items}


_UNREADABLE_PAYLOAD = ('The received lines could not be read. Please re-enter the '
                       'quantities and save again.')


def _payload_entries(lines_json):
    """Decode the hidden `lines` field into a list of dicts, or raise a ValueError
    written in OUR words.

    The single decoder both `_parse_rr_lines` (the guard) and
    `_submitted_existing_lines` (the bounce-render helper) read the payload
    through, so neither can be handed a shape the other refuses.

    `lines` is raw client JSON, and two of its malformed shapes used to escape as
    Python's own text or as a 500:

    * ``'{not json at all'`` -- json.JSONDecodeError SUBCLASSES ValueError, so it
      landed in the routes' `except ValueError as e: flash(str(e))` and the
      receiver was shown "Expecting property name enclosed in double quotes...".
      Same class as the `int('abc')` leak already refused below.
    * ``'[1, 2, 3]'`` -- a JSON array of non-dicts. `d.get(...)` raised
      AttributeError INSIDE the try (swallowed into a generic flash) and then
      again in `_submitted_existing_lines` OUTSIDE it, for an HTTP 500. A bare
      `except Exception` did not even contain it: it hid the first occurrence and
      let the second escape.

    A non-dict entry is refused in the same shape a non-numeric id already gets
    ("Line N: that purchase order line is not a valid reference."), so one
    malformed row reads the same however it is malformed.
    """
    try:
        items = json.loads(lines_json) if lines_json else []
    except (ValueError, TypeError):
        raise ValueError(_UNREADABLE_PAYLOAD) from None
    if not isinstance(items, list):
        raise ValueError(_UNREADABLE_PAYLOAD)
    for position, d in enumerate(items, start=1):
        if not isinstance(d, dict):
            raise ValueError(
                f'Line {position}: that purchase order line is not a valid reference.')
    return items


def _submitted_existing_lines():
    """Rebuild {purchase_order_item_id: received_qty} from the POSTed hidden JSON (bounced edit).

    A DISPLAY helper: it runs while re-rendering a form that has ALREADY flashed
    its real refusal, so an unreadable payload degrades to "nothing to pre-fill"
    rather than raising a second time and taking the bounce page down with it.
    The rejection itself still happens -- `_payload_entries` raises the same
    ValueError here as it does for the guard; this is the one caller that has
    somewhere better to go than a traceback.
    """
    try:
        items = _payload_entries(request.form.get('lines', '[]'))
    except ValueError:
        return {}
    out = {}
    for d in items:
        poi_id = d.get('purchase_order_item_id')
        if not poi_id:
            continue
        try:
            out[int(poi_id)] = float(d.get('received_quantity') or 0)
        except (TypeError, ValueError):
            continue
    return out


def _render_create(form, eligible):
    """Render the create form, carrying the receiver's own typed quantities back on a
    bounce.

    Moving the ceiling / vendor / branch / status checks to SAVE made
    bounce-with-data the ROUTINE path -- before that the only ValueError create()
    could raise was "Add at least one received line", where there was nothing typed
    to lose. Re-seeding from `{}` would silently empty the whole grid because one
    quantity was mistyped. Mirrors _render_edit.
    """
    existing = _submitted_existing_lines() if request.method == 'POST' else {}
    return render_template('receiving_reports/form.html', form=form, rr=None,
                           eligible=eligible, po_lines=_po_lines_payload(eligible),
                           existing=existing)


def _render_edit(rr, form, eligible):
    existing = (_submitted_existing_lines() if request.method == 'POST'
                else _existing_lines(rr))
    return render_template('receiving_reports/form.html', form=form, rr=rr,
                           eligible=eligible,
                           po_lines=_po_lines_payload(eligible, exclude_rr_id=rr.id),
                           existing=existing)


def _poi_label(poi):
    """How a PO line is named in a refusal message."""
    return (poi.product.name if poi.product else (poi.description or 'this item'))


def _line_prefix(idxs):
    """'Line 3: ' / 'Lines 1, 2: ' -- how a refusal names the submitted lines it blames."""
    return (f'Line{"s" if len(idxs) > 1 else ""} '
            f'{", ".join(str(i) for i in idxs)}: ')


def assert_payload_within_open_qty(pairs, exclude_rr_id=None, vendor_id=None,
                                   branch_id=None):
    """Refuse a SUBMITTED PAYLOAD that receives more of a PO line than remains
    open, or that draws on a purchase order belonging to another vendor, another
    branch, or one that is not receivable -- counting every line of that payload
    TOGETHER.

    *pairs* is an ordered iterable of ``(purchase_order_item_id, qty)``, one per
    submitted line, in submission order. A line's 1-based position in that
    sequence is what the raised message calls "Line N".

    THE CEILING BELONGS TO THE PO LINE, NOT TO A RECEIPT LINE.
    po_line_open_qty() sums the RR lines already COMMITTED IN THE DATABASE
    (approved/billed) and `exclude_rr_id` drops the WHOLE receipt being checked,
    so nothing in the submission being validated counts towards it. Asking the
    question once per submitted line therefore measured every line against the
    FULL open quantity: the same PO line receipted twice in one receipt answered
    "6 <= 10" twice and committed 12 against 10 ordered. Only the payload's
    per-PO-line TOTAL is comparable to the ceiling. This is the same defect class
    as BUG-PR-PO-CEILING-NOT-AGGREGATED-WITHIN-ONE-SUBMISSION -- see
    purchase_requests.allocation.assert_payload_within_open_qty, which this
    mirrors.

    Summed up front and checked ONCE per distinct PO line, rather than by
    threading a running tally through the caller's per-line loop: the message
    then names the PO line that is over-received and EVERY submitted line
    contributing to it, instead of whichever line happened to tip it over. It
    also means nothing is written before the whole submission is known to fit.

    *vendor_id* is the receipt header's vendor and *branch_id* its branch. Every
    line's PO must belong to both, and must itself be receivable
    (RECEIVABLE_PO_STATUSES) -- one receipt covers one vendor, in one branch,
    drawing only on live orders. All three are checked HERE, at save, rather than
    by the form's PO picker: A PICKER FILTER IS NOT ENFORCEMENT -- a raw POST
    bypasses a picker entirely, and with the header `purchase_order_id` column now
    gone (migration rrmulti_0001) nothing else looks at any PO's branch or status
    at all. Either argument left at its None default means there is no value to
    compare against (ReceivingReport.branch_id is nullable, and both are ordinary
    parameters a caller may omit), so there is nothing to enforce.

    The status rule has to live on the LINE, not the header: po_line_open_qty
    ignores PO status entirely, so a cancelled order's lines read as fully open
    forever. That was masked while the form only ever emitted the header PO's own
    lines and the header PO was status-checked in create(); cross-PO lines make it
    reachable.

    Refuses at the FIRST offending PO line in submission order (dicts preserve
    insertion order), so the message is deterministic rather than dependent on
    id ordering.
    """
    totals = {}
    for idx, (poi_id, qty) in enumerate(pairs, start=1):
        slot = totals.setdefault(int(poi_id), [Decimal('0'), []])
        slot[0] += Decimal(str(qty or 0))
        slot[1].append(idx)

    for poi_id, (total, idxs) in totals.items():
        poi = db.session.get(PurchaseOrderItem, poi_id)
        if poi is None:
            raise ValueError(f'Line {idxs[0]}: that purchase order line no longer exists.')
        # PurchaseOrderItem's backref to its header is named 'order', not
        # 'purchase_order' -- see PurchaseOrder.line_items(backref='order').
        po = poi.order
        if po is None:
            raise ValueError(
                f'Line {idxs[0]}: that purchase order line is not attached to a '
                f'purchase order.')
        if vendor_id is not None and po.vendor_id != vendor_id:
            raise ValueError(
                f'{_line_prefix(idxs)}{po.po_number} belongs to {po.vendor_name}. '
                f'A Receiving Report covers one vendor.')
        if branch_id is not None and po.branch_id != branch_id:
            raise ValueError(
                f'{_line_prefix(idxs)}{po.po_number} belongs to another branch. '
                f'A Receiving Report covers one branch.')
        if po.status not in RECEIVABLE_PO_STATUSES:
            raise ValueError(
                f'{_line_prefix(idxs)}{po.po_number} is {po.status} and can no '
                f'longer be received against.')
        open_qty = po_line_open_qty(poi, exclude_rr_id=exclude_rr_id)
        if total > open_qty:
            label = _poi_label(poi)
            if len(idxs) == 1:
                raise ValueError(
                    f'Line {idxs[0]}: only {open_qty} of {label} remain open.')
            raise ValueError(
                f'Lines {", ".join(str(i) for i in idxs)}: only {open_qty} of {label} '
                f'remain open, but these lines receive {total} between them.')
    return None


def _parse_rr_lines(rr, lines_json):
    """Attach RR lines from the hidden JSON: [{purchase_order_item_id, received_quantity}].

    The whole payload is validated BEFORE the first ReceivingReportItem is built,
    so a refusal leaves nothing half-written -- and so the ceiling is measured
    against the payload's per-PO-line total rather than one line at a time. See
    assert_payload_within_open_qty.
    """
    items = _payload_entries(lines_json)
    kept = []
    for position, d in enumerate(items, start=1):
        try:
            qty = Decimal(str(d.get('received_quantity')))
        except (InvalidOperation, TypeError):
            qty = Decimal('0')
        poi_id = d.get('purchase_order_item_id')
        if not poi_id or qty <= 0:
            continue
        try:
            poi_id = int(poi_id)
        except (TypeError, ValueError):
            # The payload is raw client JSON: int('abc') would otherwise escape as
            # a verbatim "invalid literal for int()" flash.
            raise ValueError(
                f'Line {position}: that purchase order line is not a valid reference.'
            ) from None
        kept.append((poi_id, qty))
    if not kept:
        raise ValueError('Add at least one received line.')
    # rr.id is None on the create path (nothing to exclude yet). On edit, excluding
    # this receipt's own rows is belt-and-braces, not load-bearing: po_line_open_qty
    # sums only COMMITTED_STATUSES (approved/billed) and edit() has already refused
    # a non-draft, so the receipt under check is never in that sum. Kept so the
    # guard stays correct if either of those changes.
    assert_payload_within_open_qty(kept, exclude_rr_id=rr.id, vendor_id=rr.vendor_id,
                                   branch_id=rr.branch_id)
    for line_number, (poi_id, qty) in enumerate(kept, start=1):
        poi = db.session.get(PurchaseOrderItem, poi_id)
        rr.line_items.append(ReceivingReportItem(
            line_number=line_number, purchase_order_item_id=poi_id,
            product_id=(poi.product_id if poi else None),
            received_quantity=qty))


def _rr_or_404(id):
    rr = db.get_or_404(ReceivingReport, id)
    if rr.branch_id != session.get('selected_branch_id'):
        abort(404)
    return rr


# -- routes --------------------------------------------------------------------

def _filtered_rr_query(include_ids=False):
    """Build a branch-scoped ReceivingReport query from request filter args.

    Args read: status, vendor, q, date_from, date_to -- and ids when
    include_ids=True (exports only); a valid ids list overrides all other
    filters but stays branch-scoped. Invalid values are ignored.

    Eager-loads the lines -> PO line -> PO chain that `po_number_display` walks. Both callers
    (the list page and the exports) render that column for every row, and the exports are
    unpaginated, so lazy loading here is an N+1 that scales with rows x lines.
    """
    branch_id = session.get('selected_branch_id')
    query = ReceivingReport.query.filter_by(branch_id=branch_id).options(
        selectinload(ReceivingReport.line_items)
        .joinedload(ReceivingReportItem.purchase_order_item)
        .joinedload(PurchaseOrderItem.order))

    if include_ids:
        ids_param = request.args.get('ids', '')
        if ids_param:
            ids = [int(x) for x in ids_param.split(',') if x.strip().isdigit()]
            if ids:
                return query.filter(ReceivingReport.id.in_(ids))

    status_filter = request.args.get('status', 'all')
    if status_filter in VALID_RR_STATUSES:
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
        query = query.filter(db.or_(ReceivingReport.rr_number.ilike(like),
                                    ReceivingReport.vendor_name.ilike(like)))

    date_from = request.args.get('date_from', '')
    if date_from:
        try:
            query = query.filter(ReceivingReport.receipt_date >= date.fromisoformat(date_from))
        except ValueError:
            pass

    date_to = request.args.get('date_to', '')
    if date_to:
        try:
            query = query.filter(ReceivingReport.receipt_date <= date.fromisoformat(date_to))
        except ValueError:
            pass

    return query


@receiving_reports_bp.route('/receiving-reports')
@login_required
def list_rr():
    from app.receiving_reports.utils import compute_rr_summary
    from app.vendors.models import Vendor

    page = request.args.get('page', 1, type=int)
    per_page = 50

    query = _filtered_rr_query().order_by(ReceivingReport.receipt_date.desc(),
                                          ReceivingReport.id.desc())
    pagination = query.paginate(page=page, per_page=per_page, error_out=False)

    branch_id = session.get('selected_branch_id')
    summary = compute_rr_summary(branch_id)
    vendors = Vendor.query.filter_by(is_active=True).order_by(Vendor.name).all()

    return render_template('receiving_reports/list.html',
                           rr_list=pagination.items,
                           pagination=pagination,
                           vendors=vendors,
                           summary=summary,
                           status_filter=request.args.get('status', 'all'),
                           vendor_filter=request.args.get('vendor', 'all'),
                           q=request.args.get('q', ''),
                           date_from=request.args.get('date_from', ''),
                           date_to=request.args.get('date_to', ''))


@receiving_reports_bp.route('/receiving-reports/billable')
@login_required
def billable_rrs():
    """JSON: approved, unbilled RRs for a vendor -- the goods billing path. Auto-gated by the
    receiving_reports module (before_request), so it 404s when the module is off."""
    from app.purchase_billing import billable_rrs_for, ap_billing_consolidate
    branch_id = session.get('selected_branch_id')
    vendor_id = request.args.get('vendor_id', type=int)
    rrs = billable_rrs_for(branch_id, vendor_id) if vendor_id else []
    return jsonify({'consolidate': ap_billing_consolidate(), 'rrs': rrs})


@receiving_reports_bp.route('/receiving-reports/open-lines')
@login_required
def open_lines():
    """JSON: the still-open purchase order lines of *vendor_id*, in the SESSION
    branch -- the data source for the receipt form's "Pull from Purchase Orders"
    picker. Auto-gated by the receiving_reports module (before_request), so it
    404s when the module is off.

    It exists because the picker CANNOT be purely client-side. `po_lines` is
    server-rendered once per GET and is empty until a vendor is chosen (see
    _eligible_purchase_orders), while the vendor is chosen in the browser --
    there is nothing already on the page for the picker to read.

    Branch comes from the session and NEVER from the query string: a
    ?branch_id= parameter would let any signed-in user enumerate another
    branch's orders through a route that looks like a form helper. Vendor is a
    query parameter because the vendor is the user's live choice; scoping by it
    leaks nothing the RR form does not already show.

    `exclude_rr_id` is how the EDIT picker stops counting the receipt being
    edited against its own open quantity. It is validated to a receipt in this
    branch, so a forged id cannot inflate what is offered -- though even that
    would only widen the PICKER: assert_payload_within_open_qty re-measures the
    real ceiling at save and at approve, with the real exclusion.

    Each row carries po_id and po_number on top of _po_lines_payload's fields:
    once one receipt can span several orders, "which PO is this line from?" is a
    per-LINE question, and the payload alone cannot answer it.
    """
    if current_user.role not in RR_EDIT_ROLES:
        return jsonify({'lines': [], 'error': 'not permitted'}), 403
    branch_id = session.get('selected_branch_id')
    vendor_id = request.args.get('vendor_id', type=int)
    exclude_rr_id = request.args.get('exclude_rr_id', type=int)
    if exclude_rr_id:
        rr = db.session.get(ReceivingReport, exclude_rr_id)
        if rr is None or rr.branch_id != branch_id:
            exclude_rr_id = None
    eligible = _eligible_purchase_orders(branch_id, vendor_id)
    payload = _po_lines_payload(eligible, exclude_rr_id=exclude_rr_id)
    lines = []
    for po in eligible:
        for row in payload.get(po.id, []):
            # A PO stays eligible while ANY of its lines is open, so a fully
            # received line of a partly received order still arrives here.
            if row['open'] <= 0:
                continue
            lines.append(dict(row, po_id=po.id, po_number=po.po_number))
    return jsonify({'lines': lines})


@receiving_reports_bp.route('/receiving-reports/create', methods=['GET', 'POST'])
@login_required
def create():
    gate = _rr_role_gate()
    if gate:
        return gate
    branch_id = session.get('selected_branch_id')
    form = ReceivingReportForm()
    form.set_vendor_choices(_active_vendors())
    # The create view has no vendor until the user picks one: on a fresh GET
    # there is nothing submitted yet, so eligible is deliberately []. On a
    # bounced POST, re-scope by whatever vendor was actually submitted so the
    # re-rendered grid still shows that vendor's POs. See _eligible_purchase_orders.
    submitted_vendor_id = (request.form.get('vendor_id', type=int)
                           if request.method == 'POST' else None)
    eligible = _eligible_purchase_orders(branch_id, submitted_vendor_id)

    if form.validate_on_submit():
        rr_number = (form.rr_number.data or '').strip()
        if ReceivingReport.query.filter(ReceivingReport.rr_number == rr_number).first():
            flash('Receiving Report number already exists.', 'error')
            return _render_create(form, eligible)

        vendor = db.session.get(Vendor, form.vendor_id.data)
        if not vendor:
            flash('Selected vendor not found.', 'error')
            return _render_create(form, eligible)
        try:
            rr = ReceivingReport(
                rr_number=rr_number, branch_id=branch_id,
                receipt_date=form.receipt_date.data,
                vendor_id=vendor.id, vendor_name=vendor.name,
                remarks=form.remarks.data or None, status='draft',
                created_by_id=current_user.id)
            _parse_rr_lines(rr, request.form.get('lines', '[]'))
            # No header PO to derive: the receipt's orders live on its lines
            # (rr.purchase_orders), and the header column was dropped in rrmulti_0001.
            db.session.add(rr); db.session.commit()
        except ValueError as e:
            db.session.rollback(); flash(str(e), 'error')
        # Narrow, and only over the WRITE. A bare `except Exception` here hid this
        # task's own IndexError behind "An error occurred creating the Receiving
        # Report."; worse, the audit-log call and the redirect used to sit inside
        # it too, so anything raised AFTER db.session.commit() told the receiver
        # the creation had failed for a receipt that exists. Success work lives in
        # the else: a rollback cannot un-commit, so it must never be reached with
        # the row already written. (IntegrityError is a SQLAlchemyError subclass;
        # named anyway because a duplicate rr_number racing the check above is the
        # one failure a reader should expect to land here.)
        except (SQLAlchemyError, IntegrityError):
            db.session.rollback(); flash('An error occurred creating the Receiving Report.', 'error')
        else:
            log_create(module='receiving_reports', record_id=rr.id,
                       record_identifier=f'{rr.rr_number} - {rr.vendor_name}',
                       new_values=model_to_dict(rr, ['rr_number', 'status', 'receipt_date']))
            flash(f'Receiving Report "{rr.rr_number}" created.', 'success')
            return redirect(url_for('receiving_reports.view', id=rr.id))

    if request.method == 'GET':
        form.rr_number.data = generate_rr_number(branch_id)
        form.receipt_date.data = ph_now().date()
    return _render_create(form, eligible)


@receiving_reports_bp.route('/receiving-reports/<int:id>')
@login_required
def view(id):
    rr = _rr_or_404(id)
    # Read HERE rather than in the template, so the Print button and print_rr()'s
    # own guard read one value.
    return render_template('receiving_reports/detail.html', rr=rr,
                           rr_print_form=AppSettings.get_setting('rr_print_form',
                                                                 'current'))


@receiving_reports_bp.route('/receiving-reports/<int:id>/edit', methods=['GET', 'POST'])
@login_required
def edit(id):
    gate = _rr_role_gate()
    if gate:
        return gate
    rr = _rr_or_404(id)
    if rr.status != 'draft':
        flash('Only a draft Receiving Report can be edited.', 'error')
        return redirect(url_for('receiving_reports.view', id=rr.id))
    branch_id = session.get('selected_branch_id')
    form = ReceivingReportForm(obj=rr)
    form.set_vendor_choices(_active_vendors())
    # The vendor is fixed at create (a snapshot, not re-chosen on edit -- see
    # ReceivingReport.vendor_id), so the picker is scoped by the RECEIPT's own
    # vendor, never by whatever the (possibly disabled) vendor field submits.
    eligible = _eligible_purchase_orders(branch_id, rr.vendor_id)
    # Every PO this receipt already draws on must stay offered even if its open
    # qty is now fully consumed by this RR's own lines (exclude_rr_id in the
    # payload grid handles the quantity; this only keeps the PO itself in the
    # list). rr.purchase_orders is the derived, multi-PO accessor -- the old
    # single rr.purchase_order check missed every PO but the header one.
    for po in rr.purchase_orders:
        if po not in eligible:
            eligible.append(po)

    if form.validate_on_submit():
        old = model_to_dict(rr, ['rr_number', 'status', 'receipt_date'])
        try:
            if not claim_version(ReceivingReport, rr.id, submitted_version()):
                db.session.rollback()
                flash(conflict_message('receiving_reports', rr.id), 'error')
                return _render_edit(rr, form, eligible)
            rr.receipt_date = form.receipt_date.data
            rr.remarks = form.remarks.data or None
            rr.line_items.clear()
            _parse_rr_lines(rr, request.form.get('lines', '[]'))
            # Nothing to re-derive on the header: editing the lines changes which
            # POs this receipt draws on, and rr.purchase_orders reads them from the
            # lines every time (see create()).
            db.session.commit()
        except ValueError as e:
            db.session.rollback(); flash(str(e), 'error')
        except (SQLAlchemyError, IntegrityError):   # see create() for why it is narrow
            db.session.rollback(); flash('An error occurred updating the Receiving Report.', 'error')
        else:
            log_update(module='receiving_reports', record_id=rr.id,
                       record_identifier=f'{rr.rr_number} - {rr.vendor_name}', old_values=old,
                       new_values=model_to_dict(rr, ['rr_number', 'status', 'receipt_date']))
            flash(f'Receiving Report "{rr.rr_number}" updated.', 'success')
            return redirect(url_for('receiving_reports.view', id=rr.id))

    # Unconditional, not GET-only: validate_on_submit() has already run above, so
    # a bounced POST reaches here too with form.vendor_id.data still holding
    # whatever vendor the request posted. The vendor is fixed on this page (see
    # the eligibility comment above and #rrVendorFixedHint in the template) --
    # re-pinning .data to the receipt's own vendor before render is display-only
    # and does not affect what was (or wasn't) saved.
    form.vendor_id.data = rr.vendor_id
    return _render_edit(rr, form, eligible)


# -- lifecycle transitions -----------------------------------------------------

@receiving_reports_bp.route('/receiving-reports/<int:id>/approve', methods=['POST'])
@login_required
def approve(id):
    rr = _rr_or_404(id)
    if not _approve_role_gate():
        return redirect(url_for('receiving_reports.view', id=id))
    if rr.status != 'draft':
        flash('Only a draft Receiving Report can be approved.', 'error')
        return redirect(url_for('receiving_reports.view', id=id))
    # Guard: committing these lines must not exceed each PO line's OPEN qty, and
    # every line's PO must belong to this receipt's vendor and branch and still be
    # receivable. Re-checked here and not only at save: a draft written before this
    # guard existed (or against a PO that has since been received elsewhere, or
    # cancelled since) must not become approvable.
    # Excluding THIS rr from `open` is belt-and-braces, not load-bearing:
    # po_line_open_qty sums only COMMITTED_STATUSES (approved/billed) and this route
    # has already refused a non-draft above, so this receipt cannot be in that sum.
    try:
        assert_payload_within_open_qty(
            [(li.purchase_order_item_id, li.received_quantity) for li in rr.line_items],
            exclude_rr_id=rr.id, vendor_id=rr.vendor_id, branch_id=rr.branch_id)
    except ValueError as e:
        flash(str(e), 'error')
        return redirect(url_for('receiving_reports.view', id=id))
    rr.status = 'approved'
    rr.approved_by_id = current_user.id
    rr.approved_at = ph_now()
    from app.receiving_reports.stock_posting import post_rr_receipt
    from app.posting.control_accounts import ControlAccountError
    try:
        post_rr_receipt(rr, current_user)
    except (ValueError, ControlAccountError) as e:
        db.session.rollback()
        flash(str(e), 'error')
        return redirect(url_for('receiving_reports.view', id=id))
    db.session.commit()
    log_audit(module='receiving_reports', action='approve', record_id=rr.id,
              record_identifier=rr.rr_number, notes='Approved')
    flash(f'Receiving Report "{rr.rr_number}" approved.', 'success')
    return redirect(url_for('receiving_reports.view', id=id))


@receiving_reports_bp.route('/receiving-reports/<int:id>/cancel', methods=['POST'])
@login_required
def cancel(id):
    rr = _rr_or_404(id)
    if not (current_user.has_full_access or current_user.role == 'accountant'):
        flash('Only accountant/admin can cancel a Receiving Report.', 'error')
        return redirect(url_for('receiving_reports.view', id=id))
    if rr.status == 'billed':
        flash('A billed Receiving Report cannot be cancelled.', 'error')
        return redirect(url_for('receiving_reports.view', id=id))
    if rr.status == 'cancelled':
        flash('This Receiving Report is already cancelled.', 'error')
        return redirect(url_for('receiving_reports.view', id=id))
    reason = (request.form.get('cancel_reason') or '').strip()
    if len(reason) < 10:
        flash('A cancellation reason (min 10 chars) is required.', 'error')
        return redirect(url_for('receiving_reports.view', id=id))
    rr.status = 'cancelled'
    rr.cancelled_by_id = current_user.id
    rr.cancelled_at = ph_now()
    rr.cancel_reason = reason
    from app.receiving_reports.stock_posting import reverse_rr_receipt
    try:
        reverse_rr_receipt(rr, current_user)
    except ValueError as e:
        db.session.rollback()
        flash(str(e), 'error')
        return redirect(url_for('receiving_reports.view', id=id))
    db.session.commit()   # cancelling drops it out of COMMITTED_STATUSES -> qty released
    log_audit(module='receiving_reports', action='update', record_id=rr.id,
              record_identifier=rr.rr_number, notes=f'Cancelled: {reason}')
    flash(f'Receiving Report "{rr.rr_number}" cancelled.', 'warning')
    return redirect(url_for('receiving_reports.view', id=id))


# -- print ---------------------------------------------------------------------

@receiving_reports_bp.route('/receiving-reports/<int:id>/print')
@login_required
def print_rr(id):
    """Print a Receiving Report -- the form is chosen by the `rr_print_form` company
    setting (current = standard printable form . preprinted = data-only overlay for
    the client's own pre-printed stationery . hidden = printing disabled). Mirrors
    purchase_orders.print_po.

    There is deliberately NO `rr_print_access` sibling to purchase_orders'. An RR is
    receipt evidence held INTERNALLY -- it never reaches a supplier, so the
    commercial risk that justifies refusing to print a draft purchase order does not
    exist here. `rr_print_form: hidden` is this document's off switch.
    """
    rr = _rr_or_404(id)
    rr_print_form = AppSettings.get_setting('rr_print_form', 'current')
    if rr_print_form == 'hidden':
        flash('Receiving Report printing is not enabled.', 'error')
        return redirect(url_for('receiving_reports.view', id=id))
    company = {'name': AppSettings.get_setting('company_name', ''),
               'address': AppSettings.get_setting('company_address', ''),
               'tin': AppSettings.get_setting('company_tin', '')}
    if rr_print_form == 'preprinted':
        return render_template(
            'receiving_reports/print_preprinted.html', rr=rr, company=company,
            printed_at=ph_now(), layout=get_layout(rr.branch_id),
            can_edit_layout=current_user.has_full_access,
            col_labels=COLUMN_LABELS, font_groups=FONT_GROUPS,
            paper_sizes=PAPER_SIZES, paper_labels=PAPER_LABELS,
            date_formats=DATE_FORMATS, field_labels=FIELD_LABELS,
            signatory_ids=TEXT_KEYS,
            date_labels={k: date(2026, 6, 17).strftime(v) for k, v in DATE_FORMATS.items()})
    return render_template('receiving_reports/print.html', rr=rr, company=company,
                           printed_at=ph_now())


@receiving_reports_bp.route('/receiving-reports/print-layout', methods=['POST'])
@login_required
def save_print_layout():
    """Persist the pre-printed layout JSON (full-access: admin or Chief Accountant).

    Mirrors purchase_orders.save_print_layout: a layout edit changes what prints on
    a client's real, BIR-registered stationery, so it is deliberately narrower than
    the module's edit-level role rule (which admits `staff`)."""
    if not current_user.has_full_access:
        abort(403)
    data = request.get_json(silent=True) or {}
    # The layout is per-branch; the print page requires the selected branch to equal
    # the document's branch, so the session branch is the document's branch.
    clean = save_layout(data, current_user.username, session.get('selected_branch_id'))
    return jsonify(ok=True, layout=clean)


# -- export --------------------------------------------------------------------

_EXPORT_COLUMNS = ['rr_number', 'receipt_date', 'vendor_name', 'po_number_display', 'status']
_EXPORT_HEADERS = ['RR #', 'Receipt Date', 'Vendor', 'PO #', 'Status']


@receiving_reports_bp.route('/receiving-reports/export/excel')
@login_required
def export_excel():
    from app.utils.export import export_to_excel
    rows = _filtered_rr_query(include_ids=True).order_by(ReceivingReport.receipt_date.desc()).all()
    log_audit('receiving_reports', 'export_excel', None, f'{len(rows)} records',
              notes=f'Exported by {current_user.username}; filters: {request.args.to_dict()}')
    timestamp = ph_now().strftime('%Y%m%d_%H%M%S')
    return export_to_excel(data=rows, columns=_EXPORT_COLUMNS, headers=_EXPORT_HEADERS,
                           filename=f'receiving_reports_{timestamp}.xlsx',
                           title='Receiving Reports Report')


@receiving_reports_bp.route('/receiving-reports/export/csv')
@login_required
def export_csv_route():
    from app.utils.export import export_to_csv
    rows = _filtered_rr_query(include_ids=True).order_by(ReceivingReport.receipt_date.desc()).all()
    log_audit('receiving_reports', 'export_csv', None, f'{len(rows)} records',
              notes=f'Exported by {current_user.username}; filters: {request.args.to_dict()}')
    timestamp = ph_now().strftime('%Y%m%d_%H%M%S')
    return export_to_csv(data=rows, columns=_EXPORT_COLUMNS, headers=_EXPORT_HEADERS,
                         filename=f'receiving_reports_{timestamp}.csv')
