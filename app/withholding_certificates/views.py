"""Register of BIR 2307 certificates received from customers (payee side).

CRUD only; branch-scoped and audit-logged. The SAWT and reconciliation that read
this register live in service.py + the reports routes below.
"""
from functools import wraps
from flask import (Blueprint, render_template, redirect, url_for, flash, request)
from flask_login import login_required, current_user

from app import db
from app.withholding_certificates.models import WithholdingCertificateReceived
from app.withholding_certificates.forms import WithholdingCertificateReceivedForm
from app.audit.utils import log_create, log_update, log_delete, model_to_dict, get_changes
from app.users.utils import get_accessible_branches
from app.utils import ph_now

withholding_certificates_bp = Blueprint(
    'withholding_certificates', __name__, template_folder='templates')

_FIELDS = ['branch_id', 'customer_id', 'certificate_number', 'date_received',
           'period_from', 'period_to', 'wt_id', 'income_payment', 'tax_withheld', 'notes']


def accountant_or_admin_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not current_user.is_authenticated:
            return redirect(url_for('users.login'))
        if current_user.role not in ['accountant', 'admin', 'chief_accountant']:
            flash('You do not have permission to perform this action.', 'error')
            return redirect(url_for('dashboard.index'))
        return f(*args, **kwargs)
    return wrapper


def _set_choices(form):
    from app.customers.models import Customer
    from app.withholding_tax.models import WithholdingTax
    branches = get_accessible_branches(current_user)
    form.branch_id.choices = [(b.id, f'{b.code} - {b.name}') for b in branches]
    customers = Customer.query.filter_by(is_active=True).order_by(Customer.name).all()
    form.customer_id.choices = [(c.id, f'{c.name}') for c in customers]
    # Only creditable (expanded) codes belong on a 2307 received.
    codes = (WithholdingTax.query.filter_by(is_active=True, tax_type='expanded')
             .order_by(WithholdingTax.code).all())
    form.wt_id.choices = [(w.id, f'{w.code}: {w.name}') for w in codes]


def _apply(form, rec):
    rec.branch_id = form.branch_id.data
    rec.customer_id = form.customer_id.data
    rec.certificate_number = form.certificate_number.data
    rec.date_received = form.date_received.data
    rec.period_from = form.period_from.data
    rec.period_to = form.period_to.data
    rec.wt_id = form.wt_id.data
    rec.income_payment = form.income_payment.data
    rec.tax_withheld = form.tax_withheld.data
    rec.notes = form.notes.data or None


def _accessible_branch_ids():
    return [b.id for b in get_accessible_branches(current_user)]


@withholding_certificates_bp.route('/withholding-certificates')
@login_required
@accountant_or_admin_required
def list_certificates():
    q = WithholdingCertificateReceived.query
    if not current_user.has_full_access:
        q = q.filter(WithholdingCertificateReceived.branch_id.in_(_accessible_branch_ids()))
    certs = q.order_by(WithholdingCertificateReceived.date_received.desc()).all()
    return render_template('withholding_certificates/list.html', certificates=certs)


@withholding_certificates_bp.route('/withholding-certificates/create', methods=['GET', 'POST'])
@login_required
@accountant_or_admin_required
def create_certificate():
    form = WithholdingCertificateReceivedForm()
    _set_choices(form)
    if form.validate_on_submit():
        rec = WithholdingCertificateReceived()
        _apply(form, rec)
        rec.created_by = current_user.username
        rec.updated_by = current_user.username
        db.session.add(rec)
        db.session.commit()
        log_create('withholding_certificates', rec.id, rec.certificate_number,
                   model_to_dict(rec, _FIELDS))
        flash('Certificate recorded.', 'success')
        return redirect(url_for('withholding_certificates.list_certificates'))
    return render_template('withholding_certificates/form.html', form=form, certificate=None)


@withholding_certificates_bp.route('/withholding-certificates/<int:cert_id>/edit',
                                   methods=['GET', 'POST'])
@login_required
@accountant_or_admin_required
def edit_certificate(cert_id):
    rec = db.get_or_404(WithholdingCertificateReceived, cert_id)
    form = WithholdingCertificateReceivedForm(obj=rec)
    _set_choices(form)
    if form.validate_on_submit():
        old = model_to_dict(rec, _FIELDS)
        _apply(form, rec)
        rec.updated_by = current_user.username
        rec.updated_at = ph_now()
        db.session.commit()
        log_update('withholding_certificates', rec.id, rec.certificate_number,
                   old, model_to_dict(rec, _FIELDS))
        flash('Certificate updated.', 'success')
        return redirect(url_for('withholding_certificates.list_certificates'))
    return render_template('withholding_certificates/form.html', form=form, certificate=rec)


@withholding_certificates_bp.route('/withholding-certificates/<int:cert_id>/delete',
                                   methods=['POST'])
@login_required
@accountant_or_admin_required
def delete_certificate(cert_id):
    rec = db.get_or_404(WithholdingCertificateReceived, cert_id)
    old = model_to_dict(rec, _FIELDS)
    number = rec.certificate_number
    db.session.delete(rec)
    db.session.commit()
    log_delete('withholding_certificates', cert_id, number, old)
    flash('Certificate deleted.', 'success')
    return redirect(url_for('withholding_certificates.list_certificates'))
