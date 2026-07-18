"""Depreciation run lifecycle (R-05 Slice 2): new-run preview/confirm-post,
list, reverse."""
from decimal import Decimal, InvalidOperation
from flask import Blueprint, render_template, redirect, url_for, request, flash
from flask_login import login_required, current_user
from app import db
from app.fixed_asset_depreciation.forms import DepreciationRunPeriodForm, ReversalForm
from app.fixed_asset_depreciation.models import DepreciationRun
from app.fixed_asset_depreciation.service import (
    compute_depreciation_preview, post_depreciation_run, reverse_depreciation_run,
)
from app.users.utils import get_accessible_branches

fixed_asset_depreciation_bp = Blueprint('fixed_asset_depreciation', __name__,
                                        template_folder='templates')


def _parse_report_params():
    from datetime import datetime
    branch_id = request.args.get('branch_id', type=int)
    as_of_str = request.args.get('as_of')
    as_of_date = (datetime.strptime(as_of_str, '%Y-%m-%d').date() if as_of_str
                 else datetime.today().date())
    return branch_id, as_of_date


def _accountant_or_admin_required(f):
    from functools import wraps
    @wraps(f)
    def decorated(*args, **kwargs):
        if not (current_user.role == 'accountant' or current_user.has_full_access):
            flash('Only Accountants and Administrators can run depreciation.', 'error')
            return redirect(url_for('fixed_asset_depreciation.list_runs'))
        return f(*args, **kwargs)
    return decorated


@fixed_asset_depreciation_bp.route('/fixed-asset-depreciation/new', methods=['GET', 'POST'])
@login_required
@_accountant_or_admin_required
def new_run():
    form = DepreciationRunPeriodForm()
    form.branch_id.choices = [(b.id, b.name) for b in get_accessible_branches(current_user)]
    preview_rows = None

    if form.validate_on_submit():
        branch_id = form.branch_id.data
        period_year = form.period_year.data
        period_month = form.period_month.data

        units_used_by_asset = {}
        for key, value in request.form.items():
            if key.startswith('units_used_'):
                asset_id = int(key[len('units_used_'):])
                if value.strip():
                    try:
                        units_used_by_asset[asset_id] = Decimal(value)
                    except InvalidOperation:
                        pass

        if request.form.get('confirmed') == '1':
            try:
                post_depreciation_run(branch_id, period_year, period_month,
                                      units_used_by_asset, current_user.id)
                flash(f'Depreciation run posted for {period_year}-{period_month:02d}.', 'success')
                return redirect(url_for('fixed_asset_depreciation.list_runs'))
            except ValueError as e:
                flash(str(e), 'error')
                return redirect(url_for('fixed_asset_depreciation.new_run'))

        preview_rows = compute_depreciation_preview(branch_id, period_year, period_month,
                                                     units_used_by_asset)
        return render_template('fixed_asset_depreciation/new_run.html', form=form,
                               preview_rows=preview_rows, branch_id=branch_id,
                               period_year=period_year, period_month=period_month)

    return render_template('fixed_asset_depreciation/new_run.html', form=form,
                           preview_rows=None, branch_id=None, period_year=None,
                           period_month=None)


@fixed_asset_depreciation_bp.route('/fixed-asset-depreciation')
@login_required
def list_runs():
    accessible_ids = [b.id for b in get_accessible_branches(current_user)]
    runs = DepreciationRun.query.filter(DepreciationRun.branch_id.in_(accessible_ids)) \
        .order_by(DepreciationRun.period_year.desc(), DepreciationRun.period_month.desc()).all()
    return render_template('fixed_asset_depreciation/list.html', runs=runs,
                           reversal_form=ReversalForm())


@fixed_asset_depreciation_bp.route('/fixed-asset-depreciation/<int:id>/reverse',
                                   methods=['POST'])
@login_required
@_accountant_or_admin_required
def reverse_run(id):
    run = db.get_or_404(DepreciationRun, id)
    form = ReversalForm()
    if not form.validate_on_submit():
        flash('A valid reversal date is required.', 'error')
        return redirect(url_for('fixed_asset_depreciation.list_runs'))
    try:
        reverse_depreciation_run(run, form.reversal_date.data, current_user.id)
        flash(f'Depreciation run for {run.period_year}-{run.period_month:02d} reversed.',
             'success')
    except ValueError as e:
        flash(str(e), 'error')
    return redirect(url_for('fixed_asset_depreciation.list_runs'))


@fixed_asset_depreciation_bp.route('/fixed-asset-depreciation/schedule')
@login_required
def schedule_report():
    from app.reports.fixed_asset_schedule import generate_fixed_asset_schedule
    branch_id, as_of_date = _parse_report_params()
    accessible_ids = [b.id for b in get_accessible_branches(current_user)]
    branches = get_accessible_branches(current_user)
    report = None
    if branch_id and branch_id in accessible_ids:
        report = generate_fixed_asset_schedule(branch_id, as_of_date)
    return render_template('fixed_asset_depreciation/schedule_report.html', report=report,
                           branches=branches, branch_id=branch_id, as_of_date=as_of_date)


@fixed_asset_depreciation_bp.route('/fixed-asset-depreciation/schedule/export')
@login_required
def schedule_report_export_excel():
    from app.reports.fixed_asset_schedule import generate_fixed_asset_schedule
    from app.utils.export import export_to_excel
    branch_id, as_of_date = _parse_report_params()
    report = generate_fixed_asset_schedule(branch_id, as_of_date)
    rows = [
        {'category': cat['category_name'], 'code': a['code'], 'name': a['name'],
         'cost': float(a['cost']),
         'accumulated_depreciation': float(a['accumulated_depreciation']),
         'net_book_value': float(a['net_book_value'])}
        for cat in report['categories'] for a in cat['assets']
    ]
    return export_to_excel(
        rows, columns=['category', 'code', 'name', 'cost', 'accumulated_depreciation',
                       'net_book_value'],
        headers=['Category', 'Code', 'Name', 'Cost', 'Accumulated Depreciation',
                'Net Book Value'],
        filename=f'fixed_asset_schedule_{as_of_date.isoformat()}.xlsx',
        title=f'Fixed Asset Schedule — as of {as_of_date.isoformat()}',
    )
