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

quotations_bp = Blueprint('quotations', __name__, template_folder='templates')

VALID_QUOTATION_STATUSES = {'draft', 'sent', 'accepted', 'rejected', 'cancelled'}


# -- line-item helper ----------------------------------------------------------

def _parse_and_attach_quote_lines(q, lines_json):
    """Parse the hidden-JSON line array and attach QuotationItem objects to *q*.
    Mirrors sales_orders._parse_and_attach_so_lines, but a quote may itemize freely
    (no product-required guard)."""
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
    for d in items:
        vat_rate = _dec(d.get('vat_rate')) or Decimal('0.00')
        product_id = _int(d.get('product_id'))
        amount = Decimal(str(d.get('amount', '0') or '0'))
        qty = _dec(d.get('quantity'))
        price = _dec(d.get('unit_price'))
        is_empty = (product_id is None and (amount is None or amount == 0)
                    and qty is None and price is None)
        if is_empty:
            continue  # skip a blank trailing line
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
