"""Quotation views -- a product-priced pre-sale offer; front of the O2C chain
(Quotation -> SO -> DR -> SI). Operational only: posts NO journal entry.
Mirrors sales_orders.views with a header vat_treatment and a validity-period lifecycle."""
import json
from datetime import date
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from flask import (Blueprint, render_template, redirect, url_for, flash,
                   request, session, abort, current_app)
from flask_login import login_required, current_user

from app import db
from app.quotations.models import Quotation, QuotationItem, generate_quotation_number
from app.quotations.forms import QuotationForm
from app.sales_orders.models import copy_salesperson
from app.customers.models import Customer
from app.customers.views import build_customer_quick_add_form
from app.withholding_tax.models import WithholdingTax
from app.users.models import User
from app.audit.utils import log_audit, log_create, log_update, model_to_dict
from app.errors.utils import log_exception
from app.utils import ph_now
from app.utils.cache_helpers import get_active_units, get_active_products, get_sales_vat_categories
from app.utils.concurrency import claim_version, conflict_message, submitted_version

quotations_bp = Blueprint('quotations', __name__, template_folder='templates')

VALID_QUOTATION_STATUSES = {'draft', 'sent', 'accepted', 'rejected', 'cancelled'}


# -- line-item helper ----------------------------------------------------------

def _parse_and_attach_quote_lines(q, lines_json):
    """Parse the hidden-JSON line array and attach QuotationItem objects to *q*.
    Mirrors sales_orders._parse_and_attach_so_lines, including its product-required
    guard: a QuotationItem has no description column, so a product-less line would
    identify nothing (BUG-QUOTE-LINE-NO-PRODUCT-UOM) and would propagate a null
    product down the Quote->SO->DR chain on accept."""
    def _dec(v):
        try:
            return Decimal(str(v)) if v not in (None, '', 'null') else None
        except (InvalidOperation, TypeError):
            return None

    def _int(v):
        try:
            return int(v) if v and str(v).strip() not in ('', 'null') else None
        except (ValueError, TypeError):
            return None

    items = json.loads(lines_json) if lines_json else []
    kept = 0
    for idx, d in enumerate(items, start=1):
        vat_rate = _dec(d.get('vat_rate')) or Decimal('0.00')
        product_id = _int(d.get('product_id'))
        amount = Decimal(str(d.get('amount', '0') or '0'))
        qty = _dec(d.get('quantity'))
        price = _dec(d.get('unit_price'))
        is_empty = (product_id is None and (amount is None or amount == 0)
                    and qty is None and price is None)
        if is_empty:
            continue  # skip a blank trailing line
        if product_id is None:
            raise ValueError(f'Line {idx}: select a product.')
        kept += 1
        li = QuotationItem(
            line_number=kept,
            quantity=qty,
            unit_price=price,
            uom_text=(d.get('uom_text') or None),
            unit_of_measure_id=_int(d.get('uom_id')),
            product_id=product_id,
            amount=amount,
            vat_category=d.get('vat_category') or None,
            vat_rate=vat_rate,
        )
        li.calculate_amounts()
        q.line_items.append(li)


# -- gates / context -----------------------------------------------------------

def _role_gate():
    """Returns a redirect if the current user may not write quotations, else None."""
    if current_user.role not in ['staff', 'accountant', 'admin', 'chief_accountant']:
        flash('You do not have permission to perform this action.', 'error')
        return redirect(url_for('quotations.list'))
    return None


def _salesperson_choices(branch_id):
    from app.sales_orders.views import _salesperson_choices as so_choices
    return so_choices(branch_id)


def _common_form_ctx():
    customers = Customer.query.filter_by(is_active=True).order_by(Customer.name).all()
    return {
        'units': [u.to_dict() for u in get_active_units()],
        'products': [p.to_dict() for p in get_active_products()],
        'vat_categories': [v.to_dict() for v in get_sales_vat_categories()],
        'customers': customers,
        'customer_quick_add_form': build_customer_quick_add_form(),
        'customer_quick_add_whts': WithholdingTax.query.filter_by(is_active=True)
                                   .order_by(WithholdingTax.code).all(),
    }


# -- routes --------------------------------------------------------------------

@quotations_bp.route('/quotations')
@login_required
def list():
    branch_id = session.get('selected_branch_id')
    query = Quotation.query.filter_by(branch_id=branch_id)
    status_filter = request.args.get('status', 'all')
    if status_filter in VALID_QUOTATION_STATUSES:
        query = query.filter_by(status=status_filter)
    quotes = query.order_by(Quotation.quotation_date.desc(), Quotation.id.desc()).all()
    return render_template('quotations/list.html', quotes=quotes,
                           status_filter=status_filter)


@quotations_bp.route('/quotations/create', methods=['GET', 'POST'])
@login_required
def create():
    gate = _role_gate()
    if gate:
        return gate

    form = QuotationForm()
    form.salesperson_id.choices = _salesperson_choices(session.get('selected_branch_id'))

    if form.validate_on_submit():
        try:
            customer_id = int(form.customer_id.data)
        except (ValueError, TypeError):
            flash('Invalid customer.', 'error')
            return render_template('quotations/form.html', form=form, quote=None,
                                   line_items=[], **_common_form_ctx())

        cust = db.session.get(Customer, customer_id)
        if not cust:
            flash('Selected customer not found.', 'error')
            return render_template('quotations/form.html', form=form, quote=None,
                                   line_items=[], **_common_form_ctx())

        try:
            branch_id = session.get('selected_branch_id')
            q = Quotation(
                branch_id=branch_id,
                quotation_number=generate_quotation_number(branch_id),
                quotation_date=form.quotation_date.data,
                valid_until=form.valid_until.data or None,
                customer_id=cust.id,
                customer_name=cust.name,
                customer_tin=cust.tin,
                customer_address=cust.address,
                payment_terms=form.payment_terms.data,
                reference=form.reference.data or None,
                vat_treatment=form.vat_treatment.data,
                salesperson_id=(form.salesperson_id.data or None),
                notes=form.notes.data or '',
                status='draft',
                created_by_id=current_user.id,
            )
            _parse_and_attach_quote_lines(q, request.form.get('lines', '[]'))
            q.calculate_totals()
            db.session.add(q)
            db.session.commit()

            log_create(
                module='quotations',
                record_id=q.id,
                record_identifier=f'{q.quotation_number} - {q.customer_name}',
                new_values=model_to_dict(q, [
                    'quotation_number', 'quotation_date', 'customer_name', 'vat_treatment',
                    'subtotal', 'vat_amount', 'total_amount', 'status'])
            )
            flash(f'Quotation "{q.quotation_number}" created successfully!', 'success')
            return redirect(url_for('quotations.view', id=q.id))

        except ValueError as e:
            db.session.rollback()
            flash(str(e), 'error')
            return render_template('quotations/form.html', form=form, quote=None,
                                   line_items=[], **_common_form_ctx())
        except Exception as e:
            db.session.rollback()
            current_app.logger.error('Error creating quotation', exc_info=True)
            log_exception(e, severity='ERROR', module='quotations.create')
            flash('An error occurred while entering the Quotation. Please try again.', 'error')

    if request.method == 'GET':
        form.quotation_date.data = ph_now().date()

    return render_template('quotations/form.html', form=form, quote=None,
                           line_items=[], **_common_form_ctx())


@quotations_bp.route('/quotations/<int:id>/edit', methods=['GET', 'POST'])
@login_required
def edit(id):
    gate = _role_gate()
    if gate:
        return gate

    q = db.get_or_404(Quotation, id)
    if q.branch_id != session.get('selected_branch_id'):
        abort(404)
    if q.status != 'draft':
        flash('Only draft quotations can be edited.', 'error')
        return redirect(url_for('quotations.view', id=id))

    form = QuotationForm(obj=q)
    form.salesperson_id.choices = _salesperson_choices(session.get('selected_branch_id'))

    restore_items = ([item.to_dict() for item in q.line_items]
                     if request.method == 'GET'
                     else json.loads(request.form.get('lines', '[]') or '[]'))

    if form.validate_on_submit():
        try:
            customer_id = int(form.customer_id.data)
        except (ValueError, TypeError):
            flash('Invalid customer.', 'error')
            return render_template('quotations/form.html', form=form, quote=q,
                                   line_items=restore_items, **_common_form_ctx())

        cust = db.session.get(Customer, customer_id)
        if not cust:
            flash('Selected customer not found.', 'error')
            return render_template('quotations/form.html', form=form, quote=q,
                                   line_items=restore_items, **_common_form_ctx())

        try:
            old_values = model_to_dict(q, [
                'quotation_date', 'customer_name', 'vat_treatment',
                'subtotal', 'vat_amount', 'total_amount', 'status'])

            # Lost-update guard: the first write, before the line teardown below.
            if not claim_version(Quotation, q.id, submitted_version()):
                db.session.rollback()
                flash(conflict_message('quotations', q.id), 'error')
                return render_template('quotations/form.html', form=form, quote=q,
                                       line_items=restore_items, **_common_form_ctx())

            q.quotation_date = form.quotation_date.data
            q.valid_until = form.valid_until.data or None
            q.customer_id = cust.id
            q.customer_name = cust.name
            q.customer_tin = cust.tin
            q.customer_address = cust.address
            q.payment_terms = form.payment_terms.data
            q.reference = form.reference.data or None
            q.vat_treatment = form.vat_treatment.data
            q.salesperson_id = form.salesperson_id.data or None
            q.notes = form.notes.data or ''

            db.session.execute(db.delete(QuotationItem).where(QuotationItem.quotation_id == q.id))
            _parse_and_attach_quote_lines(q, request.form.get('lines', '[]'))
            db.session.flush()
            db.session.expire(q, ['line_items'])
            q.calculate_totals()
            db.session.commit()

            log_update(
                module='quotations',
                record_id=q.id,
                record_identifier=f'{q.quotation_number} - {q.customer_name}',
                old_values=old_values,
                new_values=model_to_dict(q, [
                    'quotation_date', 'customer_name', 'vat_treatment',
                    'subtotal', 'vat_amount', 'total_amount', 'status'])
            )
            flash(f'Quotation "{q.quotation_number}" updated successfully!', 'success')
            return redirect(url_for('quotations.view', id=q.id))

        except ValueError as e:
            db.session.rollback()
            flash(str(e), 'error')
            return render_template('quotations/form.html', form=form, quote=q,
                                   line_items=restore_items, **_common_form_ctx())
        except Exception as e:
            db.session.rollback()
            current_app.logger.error('Error updating quotation', exc_info=True)
            log_exception(e, severity='ERROR', module='quotations.edit')
            flash('An error occurred while saving the Quotation. Please try again.', 'error')

    return render_template('quotations/form.html', form=form, quote=q,
                           line_items=restore_items, **_common_form_ctx())


@quotations_bp.route('/quotations/<int:id>')
@login_required
def view(id):
    """Read-only detail view for a Quotation."""
    q = db.get_or_404(Quotation, id)
    if q.branch_id != session.get('selected_branch_id'):
        abort(404)
    created_by_user = db.session.get(User, q.created_by_id) if q.created_by_id else None
    return render_template('quotations/detail.html', quote=q,
                           created_by_user=created_by_user)


@quotations_bp.route('/quotations/<int:id>/print')
@login_required
def print_quote(id):
    """Standard printable quotation (Subtotal / VAT / Total per the quote's VAT treatment)."""
    from app.settings import AppSettings
    q = db.get_or_404(Quotation, id)
    if q.branch_id != session.get('selected_branch_id'):
        abort(404)
    company = {
        'name': AppSettings.get_setting('company_name', ''),
        'address': AppSettings.get_setting('company_address', ''),
        'tin': AppSettings.get_setting('company_tin', ''),
    }
    treatment_labels = {'inclusive': 'VAT-Inclusive', 'exclusive': 'VAT-Exclusive',
                        'zero_rated': 'Zero-Rated'}
    return render_template('quotations/print.html', quote=q, company=company,
                           printed_at=ph_now(),
                           treatment_label=treatment_labels.get(q.vat_treatment, q.vat_treatment))


# -- lifecycle transitions -----------------------------------------------------

def _quote_admin_gate():
    """Accept/reject/cancel are approver actions (accountant/admin)."""
    if not (current_user.has_full_access or current_user.role == 'accountant'):
        flash('Only accountant/admin can perform this action.', 'error')
        return False
    return True


@quotations_bp.route('/quotations/<int:id>/send', methods=['POST'])
@login_required
def send(id):
    q = db.get_or_404(Quotation, id)
    if q.branch_id != session.get('selected_branch_id'):
        abort(404)
    if current_user.role not in ['staff', 'accountant', 'admin', 'chief_accountant']:
        flash('You do not have permission to perform this action.', 'error')
        return redirect(url_for('quotations.view', id=id))
    if q.status != 'draft':
        flash('Only a draft quotation can be sent.', 'error')
        return redirect(url_for('quotations.view', id=id))
    q.status = 'sent'; q.sent_by_id = current_user.id; q.sent_at = ph_now()
    db.session.commit()
    log_audit(module='quotations', action='update', record_id=q.id,
              record_identifier=q.quotation_number, notes='Sent')
    flash(f'Quotation "{q.quotation_number}" sent.', 'success')
    return redirect(url_for('quotations.view', id=id))


@quotations_bp.route('/quotations/<int:id>/accept', methods=['POST'])
@login_required
def accept(id):
    q = db.get_or_404(Quotation, id)
    if q.branch_id != session.get('selected_branch_id'):
        abort(404)
    if not _quote_admin_gate():
        return redirect(url_for('quotations.view', id=id))
    if q.status != 'sent':
        flash('Only a sent quotation can be accepted.', 'error')
        return redirect(url_for('quotations.view', id=id))
    if q.is_expired:
        flash('This quotation has expired and can no longer be accepted.', 'error')
        return redirect(url_for('quotations.view', id=id))
    from app.sales_orders.models import SalesOrder, SalesOrderItem
    from app.sales_orders.views import generate_so_number
    try:
        so = SalesOrder(so_number=generate_so_number(), branch_id=q.branch_id,
                        order_date=ph_now().date(), customer_id=q.customer_id,
                        customer_name=q.customer_name, customer_tin=q.customer_tin,
                        customer_address=q.customer_address, payment_terms=q.payment_terms,
                        reference=q.reference, notes=q.notes or '', status='draft',
                        quotation_id=q.id, created_by_id=current_user.id)
        copy_salesperson(q, so)
        for qi in q.line_items:
            up = qi.unit_price
            vat_cat, vat_rate = qi.vat_category, qi.vat_rate
            if q.vat_treatment == 'exclusive' and up is not None:
                up = (Decimal(str(up)) * Decimal('1.12')).quantize(Decimal('0.01'), ROUND_HALF_UP)
                vat_cat, vat_rate = 'V12', Decimal('12')
            elif q.vat_treatment == 'zero_rated':
                vat_cat, vat_rate = 'V0', Decimal('0')
            si = SalesOrderItem(line_number=qi.line_number, product_id=qi.product_id,
                                quantity=qi.quantity, unit_price=up, uom_text=qi.uom_text,
                                unit_of_measure_id=qi.unit_of_measure_id,
                                amount=(Decimal(str(up)) * Decimal(str(qi.quantity))
                                        ).quantize(Decimal('0.01'), ROUND_HALF_UP)
                                        if (up is not None and qi.quantity is not None) else qi.amount,
                                vat_category=vat_cat, vat_rate=vat_rate)
            si.calculate_amounts()
            so.line_items.append(si)
        so.calculate_totals()
        db.session.add(so); db.session.flush()
        q.status = 'accepted'; q.accepted_by_id = current_user.id; q.accepted_at = ph_now()
        q.sales_order_id = so.id
        db.session.commit()
        log_audit(module='quotations', action='accept', record_id=q.id,
                  record_identifier=q.quotation_number, notes=f'Accepted -> {so.so_number}')
        flash(f'Quotation accepted. Sales Order "{so.so_number}" created (draft).', 'success')
        return redirect(url_for('sales_orders.view', id=so.id))
    except Exception as e:
        db.session.rollback()
        current_app.logger.error('Error accepting quotation', exc_info=True)
        log_exception(e, severity='ERROR', module='quotations.accept')
        flash('An error occurred creating the Sales Order from this quotation.', 'error')
        return redirect(url_for('quotations.view', id=id))


@quotations_bp.route('/quotations/<int:id>/reject', methods=['POST'])
@login_required
def reject(id):
    q = db.get_or_404(Quotation, id)
    if q.branch_id != session.get('selected_branch_id'):
        abort(404)
    if not _quote_admin_gate():
        return redirect(url_for('quotations.view', id=id))
    if q.status != 'sent':
        flash('Only a sent quotation can be rejected.', 'error')
        return redirect(url_for('quotations.view', id=id))
    reason = (request.form.get('reject_reason') or '').strip()
    if len(reason) < 10:
        flash('A rejection reason (min 10 chars) is required.', 'error')
        return redirect(url_for('quotations.view', id=id))
    q.status = 'rejected'; q.rejected_by_id = current_user.id; q.rejected_at = ph_now()
    q.reject_reason = reason
    db.session.commit()
    log_audit(module='quotations', action='update', record_id=q.id,
              record_identifier=q.quotation_number, notes=f'Rejected: {reason}')
    flash(f'Quotation "{q.quotation_number}" rejected.', 'warning')
    return redirect(url_for('quotations.view', id=id))


@quotations_bp.route('/quotations/<int:id>/cancel', methods=['POST'])
@login_required
def cancel(id):
    q = db.get_or_404(Quotation, id)
    if q.branch_id != session.get('selected_branch_id'):
        abort(404)
    if not _quote_admin_gate():
        return redirect(url_for('quotations.view', id=id))
    if q.status in ('accepted', 'cancelled'):
        flash('This quotation can no longer be cancelled.', 'error')
        return redirect(url_for('quotations.view', id=id))
    reason = (request.form.get('cancel_reason') or '').strip()
    if len(reason) < 10:
        flash('A cancellation reason (min 10 chars) is required.', 'error')
        return redirect(url_for('quotations.view', id=id))
    q.status = 'cancelled'; q.cancelled_by_id = current_user.id; q.cancelled_at = ph_now()
    q.cancel_reason = reason
    db.session.commit()
    log_audit(module='quotations', action='update', record_id=q.id,
              record_identifier=q.quotation_number, notes=f'Cancelled: {reason}')
    flash(f'Quotation "{q.quotation_number}" cancelled.', 'warning')
    return redirect(url_for('quotations.view', id=id))
