from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_required, current_user

from app import db
from app.utils import ph_now
from app.year_end import service
from app.year_end.models import FiscalYearClose

year_end_bp = Blueprint('year_end', __name__,
                        template_folder='templates')


def _accountant_or_admin():
    return current_user.role == 'accountant' or current_user.has_full_access


@year_end_bp.route('/year-end')
@login_required
def index():
    if not _accountant_or_admin():
        flash('Only Accountants and Administrators can access Year-End Close.', 'error')
        return redirect(url_for('dashboard.index'))
    closes = FiscalYearClose.query.order_by(FiscalYearClose.fiscal_year.desc()).all()
    eligible = service.eligible_years(ph_now().date())
    return render_template('year_end/index.html', closes=closes, eligible_years=eligible)


@year_end_bp.route('/year-end/close', methods=['POST'])
@login_required
def close():
    if not _accountant_or_admin():
        flash('Only Accountants and Administrators can perform this action.', 'error')
        return redirect(url_for('dashboard.index'))
    try:
        year = int(request.form.get('year', ''))
    except ValueError:
        flash('Invalid year.', 'error')
        return redirect(url_for('year_end.index'))
    try:
        service.close_fiscal_year(year, current_user.id)
        db.session.commit()
        flash(f'Fiscal year {year} closed.', 'success')
    except ValueError as e:
        db.session.rollback()
        flash(str(e), 'error')
    except Exception:
        db.session.rollback()
        flash('An unexpected error occurred while closing the year.', 'error')
    return redirect(url_for('year_end.index'))


@year_end_bp.route('/year-end/reopen', methods=['POST'])
@login_required
def reopen():
    if not _accountant_or_admin():
        flash('Only Accountants and Administrators can perform this action.', 'error')
        return redirect(url_for('dashboard.index'))
    try:
        year = int(request.form.get('year', ''))
    except ValueError:
        flash('Invalid year.', 'error')
        return redirect(url_for('year_end.index'))
    try:
        service.reopen_fiscal_year(year, current_user.id)
        db.session.commit()
        flash(f'Fiscal year {year} reopened.', 'success')
    except ValueError as e:
        db.session.rollback()
        flash(str(e), 'error')
    except Exception:
        db.session.rollback()
        flash('An unexpected error occurred while reopening the year.', 'error')
    return redirect(url_for('year_end.index'))
