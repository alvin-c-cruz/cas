"""Stock Adjustments blueprint (R-03 slice 2a-i).

The Stock Adjustment document: draft create/edit with a multi-line editor, a
view page with Approve/Void actions, and print. Approve posts stock movements +
a balanced JE (via the Task 6 service); Void reverses both.
"""
import json
from decimal import Decimal, InvalidOperation

from flask import (Blueprint, render_template, redirect, url_for, flash,
                   request, session, current_app, abort)
from flask_login import login_required, current_user

from app import db
from app.users.module_access import module_enabled

stock_adjustments_bp = Blueprint('stock_adjustments', __name__,
                                 url_prefix='/stock-adjustments',
                                 template_folder='templates')

_WRITE_ROLES = ('accountant', 'chief_accountant', 'admin')


def _guard():
    if not module_enabled('stock_adjustments'):
        flash('The Stock Adjustments module is not enabled.', 'error')
        return redirect(url_for('dashboard.index'))
    return None


def _can_manage():
    return current_user.role in _WRITE_ROLES


def _tracked_products():
    from app.products.models import Product
    return (Product.query.filter_by(is_active=True, track_inventory=True)
            .order_by(Product.code).all())


def _product_options(products):
    """Plain-dict product list for the line editor's product picker."""
    return [{'id': p.id, 'code': p.code, 'name': p.name} for p in products]


def _render_form(form, products, adj):
    return render_template('stock_adjustments/form.html', form=form, adj=adj,
                           product_options=_product_options(products))


def _parse_lines(raw_json, valid_product_ids):
    """Build StockAdjustmentLine rows from the posted `lines` JSON. Raises
    ValueError on an empty payload or an untracked/unknown product."""
    from app.stock_adjustments.models import StockAdjustmentLine
    items = json.loads(raw_json or '[]')
    built = []
    for raw in items:
        try:
            pid = int(raw['product_id'])
            qty = Decimal(str(raw['quantity_delta']))
        except (KeyError, TypeError, ValueError, InvalidOperation):
            raise ValueError('A stock adjustment line is missing a product or quantity.')
        if qty == 0:
            raise ValueError('A stock adjustment line quantity cannot be zero.')
        if pid not in valid_product_ids:
            raise ValueError('A line references a product that is not inventory-tracked.')
        unit_cost = raw.get('unit_cost')
        if qty > 0 and (unit_cost is None or str(unit_cost).strip() == ''):
            raise ValueError('A positive (stock-in) line requires a unit cost.')
        built.append(StockAdjustmentLine(
            product_id=pid,
            quantity_delta=qty,
            unit_cost=(Decimal(str(unit_cost)) if unit_cost not in (None, '') else None),
            note=(raw.get('note') or None)))
    if not built:
        raise ValueError('Add at least one line.')
    return built


def _adj_or_404(id):
    """Fetch a StockAdjustment by id, scoped to the user's ACCESSIBLE branches
    (same set the list route uses via get_accessible_branches) -- not just the
    single currently-SELECTED branch. Matches the app/fixed_assets/views.py
    convention: the list does the access-scoping, detail/edit/approve/void
    fetch by id and 404 only when the record falls outside that access set."""
    from app.stock_adjustments.models import StockAdjustment
    from app.users.utils import get_accessible_branches
    adj = db.get_or_404(StockAdjustment, id)
    accessible_ids = {b.id for b in get_accessible_branches(current_user)}
    if adj.branch_id not in accessible_ids:
        abort(404)
    return adj


@stock_adjustments_bp.route('/')
@login_required
def index():
    blocked = _guard()
    if blocked:
        return blocked
    from app.stock_adjustments.models import StockAdjustment
    from app.users.utils import get_accessible_branches
    branch_ids = [b.id for b in get_accessible_branches(current_user)]
    adjustments = (StockAdjustment.query.filter(StockAdjustment.branch_id.in_(branch_ids))
                   .order_by(StockAdjustment.id.desc()).all())
    return render_template('stock_adjustments/list.html', adjustments=adjustments,
                           can_manage=_can_manage())


@stock_adjustments_bp.route('/create', methods=['GET', 'POST'])
@login_required
def create():
    blocked = _guard()
    if blocked:
        return blocked
    if not _can_manage():
        flash('You do not have permission to enter stock adjustments.', 'error')
        return redirect(url_for('stock_adjustments.index'))
    from app.stock_adjustments.forms import StockAdjustmentForm
    from app.stock_adjustments.models import StockAdjustment
    from app.stock_adjustments.numbering import generate_sa_number
    from app.utils.concurrency import commit_with_renumber_retry
    from app.audit.utils import log_create

    form = StockAdjustmentForm()
    products = _tracked_products()
    if form.validate_on_submit():
        valid_ids = {p.id for p in products}
        try:
            lines = _parse_lines(form.lines.data, valid_ids)
        except ValueError as e:
            flash(str(e), 'error')
            return _render_form(form, products, None)
        adj = StockAdjustment(sa_number=generate_sa_number(),
                              branch_id=session.get('selected_branch_id'),
                              adjustment_date=form.adjustment_date.data,
                              reason_type=form.reason_type.data,
                              notes=form.notes.data or None,
                              status='draft', created_by_id=current_user.id)
        for li in lines:
            adj.lines.append(li)
        db.session.add(adj)
        commit_with_renumber_retry(adj, 'sa_number', generate_sa_number)
        log_create(module='stock_adjustments', record_id=adj.id,
                   record_identifier=adj.sa_number,
                   new_values={'sa_number': adj.sa_number, 'reason_type': adj.reason_type,
                               'lines': len(adj.lines)})
        flash(f'Stock Adjustment {adj.sa_number} saved as draft.', 'success')
        return redirect(url_for('stock_adjustments.view', id=adj.id))
    return _render_form(form, products, None)


@stock_adjustments_bp.route('/<int:id>/edit', methods=['GET', 'POST'])
@login_required
def edit(id):
    blocked = _guard()
    if blocked:
        return blocked
    if not _can_manage():
        flash('You do not have permission to edit stock adjustments.', 'error')
        return redirect(url_for('stock_adjustments.index'))
    from app.stock_adjustments.forms import StockAdjustmentForm
    from app.stock_adjustments.models import StockAdjustment
    from app.utils.concurrency import claim_version, submitted_version, conflict_message
    from app.audit.utils import log_update

    adj = _adj_or_404(id)
    if adj.status != 'draft':
        flash('Only a draft Stock Adjustment can be edited.', 'error')
        return redirect(url_for('stock_adjustments.view', id=adj.id))

    products = _tracked_products()
    form = StockAdjustmentForm(obj=adj)
    if form.validate_on_submit():
        valid_ids = {p.id for p in products}
        try:
            lines = _parse_lines(form.lines.data, valid_ids)
        except ValueError as e:
            flash(str(e), 'error')
            return _render_form(form, products, adj)
        # Optimistic-lock claim FIRST, before any line teardown.
        if not claim_version(StockAdjustment, adj.id, submitted_version()):
            db.session.rollback()
            flash(conflict_message('stock_adjustments', adj.id), 'error')
            return redirect(url_for('stock_adjustments.edit', id=adj.id))
        adj.adjustment_date = form.adjustment_date.data
        adj.reason_type = form.reason_type.data
        adj.notes = form.notes.data or None
        adj.lines.clear()
        for li in lines:
            adj.lines.append(li)
        db.session.commit()
        log_update(module='stock_adjustments', record_id=adj.id,
                   record_identifier=adj.sa_number,
                   old_values={}, new_values={'reason_type': adj.reason_type,
                                              'lines': len(adj.lines)})
        flash(f'Stock Adjustment {adj.sa_number} updated.', 'success')
        return redirect(url_for('stock_adjustments.view', id=adj.id))

    if request.method == 'GET':
        form.lines.data = json.dumps([
            {'product_id': li.product_id,
             'quantity_delta': str(li.quantity_delta),
             'unit_cost': (str(li.unit_cost) if li.unit_cost is not None else ''),
             'note': li.note or ''} for li in adj.lines])
    return _render_form(form, products, adj)


@stock_adjustments_bp.route('/<int:id>')
@login_required
def view(id):
    blocked = _guard()
    if blocked:
        return blocked
    adj = _adj_or_404(id)
    return render_template('stock_adjustments/view.html', adj=adj, can_manage=_can_manage())


@stock_adjustments_bp.route('/<int:id>/print')
@login_required
def print_adjustment(id):
    blocked = _guard()
    if blocked:
        return blocked
    from app.settings import AppSettings
    from app.utils import ph_now
    adj = _adj_or_404(id)
    company = {'name': AppSettings.get_setting('company_name', ''),
               'address': AppSettings.get_setting('company_address', ''),
               'tin': AppSettings.get_setting('company_tin', '')}
    return render_template('stock_adjustments/print.html', adj=adj, company=company,
                           printed_at=ph_now())


@stock_adjustments_bp.route('/<int:id>/approve', methods=['POST'])
@login_required
def approve(id):
    blocked = _guard()
    if blocked:
        return blocked
    from app.stock_adjustments.service import approve_adjustment
    from app.posting.control_accounts import ControlAccountError
    from app.audit.utils import log_audit

    adj = _adj_or_404(id)
    view_url = url_for('stock_adjustments.view', id=adj.id)
    if not _can_manage():
        flash('You do not have permission to approve stock adjustments.', 'error')
        return redirect(view_url)
    if adj.status != 'draft':
        flash('Only a draft Stock Adjustment can be approved.', 'error')
        return redirect(view_url)
    try:
        approve_adjustment(adj, current_user)
        db.session.commit()
        log_audit(module='stock_adjustments', action='approve', record_id=adj.id,
                  record_identifier=adj.sa_number, notes='Approved and posted')
        flash(f'Stock Adjustment {adj.sa_number} approved and posted.', 'success')
        warnings = getattr(adj, '_negative_warnings', None) or []
        if warnings:
            flash('Posted, but these products went to a negative on-hand balance: '
                  + ', '.join(warnings) + '.', 'warning')
    except (ValueError, ControlAccountError) as e:
        db.session.rollback()
        flash(str(e), 'error')
    except Exception:
        db.session.rollback()
        current_app.logger.error('Error approving Stock Adjustment', exc_info=True)
        flash('An error occurred while approving the Stock Adjustment.', 'error')
    return redirect(view_url)


@stock_adjustments_bp.route('/<int:id>/void', methods=['POST'])
@login_required
def void(id):
    blocked = _guard()
    if blocked:
        return blocked
    from app.stock_adjustments.service import void_adjustment
    from app.posting.control_accounts import ControlAccountError
    from app.audit.utils import log_audit

    adj = _adj_or_404(id)
    view_url = url_for('stock_adjustments.view', id=adj.id)
    if not _can_manage():
        flash('You do not have permission to void stock adjustments.', 'error')
        return redirect(view_url)
    if adj.status != 'posted':
        flash('Only a posted Stock Adjustment can be voided.', 'error')
        return redirect(view_url)
    try:
        void_adjustment(adj, current_user)
        db.session.commit()
        log_audit(module='stock_adjustments', action='void', record_id=adj.id,
                  record_identifier=adj.sa_number, notes='Voided')
        flash(f'Stock Adjustment {adj.sa_number} voided.', 'warning')
    except (ValueError, ControlAccountError) as e:
        db.session.rollback()
        flash(str(e), 'error')
    except Exception:
        db.session.rollback()
        current_app.logger.error('Error voiding Stock Adjustment', exc_info=True)
        flash('An error occurred while voiding the Stock Adjustment.', 'error')
    return redirect(view_url)
