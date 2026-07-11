"""Register of BIR 2307 certificates received from customers (payee side).

CRUD only; branch-scoped and audit-logged. The SAWT and reconciliation that read
this register live in service.py + the reports routes below.
"""
from datetime import datetime
from functools import wraps
from flask import (Blueprint, render_template, redirect, url_for, flash, request)
from flask_login import login_required, current_user

from app import db
from app.withholding_certificates.models import WithholdingCertificateReceived
from app.withholding_certificates.forms import WithholdingCertificateReceivedForm
from app.withholding_certificates.service import get_sawt, reconcile_sawt
from app.audit.utils import log_create, log_update, log_delete, model_to_dict
from app.users.utils import get_accessible_branches
from app.utils import ph_now
from app.utils.bir_books import get_company_identity
from app.utils.export import export_to_excel
from app.reports.bir import get_quarter_name

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


def _period_args():
    year = request.args.get('year', datetime.now().year, type=int)
    quarter = request.args.get('quarter', (datetime.now().month - 1) // 3 + 1, type=int)
    return year, quarter


@withholding_certificates_bp.route('/withholding-certificates/sawt')
@login_required
@accountant_or_admin_required
def sawt():
    """SAWT (Summary Alphalist of Withholding Taxes) -- rendered from the register."""
    year, quarter = _period_args()
    data = get_sawt(year, quarter)
    return render_template('withholding_certificates/sawt.html', data=data, year=year,
                           quarter=quarter, quarter_name=get_quarter_name(quarter),
                           company=get_company_identity())


@withholding_certificates_bp.route('/withholding-certificates/sawt/export/excel')
@login_required
@accountant_or_admin_required
def sawt_export_excel():
    year, quarter = _period_args()
    data = get_sawt(year, quarter)
    rows = [{'customer_tin': r['customer_tin'], 'customer_name': r['customer_name'],
             'atc_code': r['atc_code'], 'income_payment': f"{r['income_payment']:.2f}",
             'tax_withheld': f"{r['tax_withheld']:.2f}"} for r in data['rows']]
    cols = ['customer_tin', 'customer_name', 'atc_code', 'income_payment', 'tax_withheld']
    headers = ['TIN', 'Payor (Customer)', 'ATC', 'Income Payment', 'Tax Withheld']
    return export_to_excel(rows, cols, headers, f'SAWT_{year}_Q{quarter}.xlsx',
                           f'SAWT - {get_quarter_name(quarter)} {year}')


@withholding_certificates_bp.route('/withholding-certificates/reconciliation')
@login_required
@accountant_or_admin_required
def reconciliation():
    """Diff booked payee WHT against the certificates-received register."""
    year, quarter = _period_args()
    data = reconcile_sawt(year, quarter)
    return render_template('withholding_certificates/reconciliation.html', data=data,
                           year=year, quarter=quarter, quarter_name=get_quarter_name(quarter),
                           company=get_company_identity())
