from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_required, current_user

from app import db
from app.utils import ph_now
from app.vat_settlement import service
from app.vat_settlement.models import VatSettlement

vat_settlement_bp = Blueprint('vat_settlement', __name__,
                              template_folder='templates')


def _accountant_or_admin():
    return current_user.role == 'accountant' or current_user.has_full_access


@vat_settlement_bp.route('/vat-settlement')
@login_required
def index():
    if not _accountant_or_admin():
        flash('Only Accountants and Administrators can access VAT Settlement.', 'error')
        return redirect(url_for('dashboard.index'))
    from app.settings import AppSettings
    from app.accounts.models import Account
    settlements = VatSettlement.query.order_by(
        VatSettlement.fiscal_year.desc(), VatSettlement.quarter.desc()).all()
    eligible = service.eligible_quarters(ph_now().date())
    latest = service._latest_settled()
    latest_key = (latest.fiscal_year, latest.quarter) if latest else None
    pay_code = AppSettings.get_setting('vat_payable_account_code')
    carry_code = AppSettings.get_setting('input_vat_carryover_account_code')
    accounts_assigned = bool(pay_code) and bool(carry_code)
    accounts = Account.query.filter_by(is_active=True).order_by(Account.code).all()
    return render_template('vat_settlement/index.html', settlements=settlements,
                           eligible=eligible, latest_key=latest_key, accounts=accounts,
                           pay_code=pay_code, carry_code=carry_code,
                           accounts_assigned=accounts_assigned)


@vat_settlement_bp.route('/vat-settlement/accounts', methods=['POST'])
@login_required
def save_accounts():
    """Accountant assigns the two settlement target accounts (stored as AppSettings codes)."""
    if not _accountant_or_admin():
        flash('Only Accountants and Administrators can perform this action.', 'error')
        return redirect(url_for('dashboard.index'))
    from app.settings import AppSettings
    from app.accounts.models import Account
    from app.audit.utils import log_audit
    pay = (request.form.get('vat_payable_account_code') or '').strip()
    carry = (request.form.get('input_vat_carryover_account_code') or '').strip()
    for code, label in ((pay, 'VAT Payable'), (carry, 'Excess Input Tax Carry-Over')):
        if code and Account.query.filter_by(code=code).first() is None:
            flash(f'Account {code} for {label} was not found.', 'error')
            return redirect(url_for('vat_settlement.index'))
    AppSettings.set_setting('vat_payable_account_code', pay, updated_by=current_user.username)
    AppSettings.set_setting('input_vat_carryover_account_code', carry, updated_by=current_user.username)
    log_audit(module='vat_settlement', action='assign_accounts',
              record_id=None, record_identifier='vat_settlement_accounts',
              new_values={'vat_payable_account_code': pay,
                          'input_vat_carryover_account_code': carry},
              user_id=current_user.id)
    flash('VAT accounts saved.', 'success')
    return redirect(url_for('vat_settlement.index'))


def _parse_yq():
    return int(request.form.get('year', '')), int(request.form.get('quarter', ''))


@vat_settlement_bp.route('/vat-settlement/settle', methods=['POST'])
@login_required
def settle():
    if not _accountant_or_admin():
        flash('Only Accountants and Administrators can perform this action.', 'error')
        return redirect(url_for('dashboard.index'))
    try:
        year, quarter = _parse_yq()
    except ValueError:
        flash('Invalid year/quarter.', 'error')
        return redirect(url_for('vat_settlement.index'))
    try:
        service.settle_quarter(year, quarter, current_user.id)
        db.session.commit()
        flash(f'{year} Q{quarter} VAT settled.', 'success')
    except ValueError as e:
        db.session.rollback(); flash(str(e), 'error')
    except Exception:
        db.session.rollback()
        flash('An unexpected error occurred while settling VAT.', 'error')
    return redirect(url_for('vat_settlement.index'))


@vat_settlement_bp.route('/vat-settlement/reverse', methods=['POST'])
@login_required
def reverse():
    if not _accountant_or_admin():
        flash('Only Accountants and Administrators can perform this action.', 'error')
        return redirect(url_for('dashboard.index'))
    try:
        year, quarter = _parse_yq()
    except ValueError:
        flash('Invalid year/quarter.', 'error')
        return redirect(url_for('vat_settlement.index'))
    try:
        service.reverse_settlement(year, quarter, current_user.id)
        db.session.commit()
        flash(f'{year} Q{quarter} VAT settlement reversed.', 'success')
    except ValueError as e:
        db.session.rollback(); flash(str(e), 'error')
    except Exception:
        db.session.rollback()
        flash('An unexpected error occurred while reversing.', 'error')
    return redirect(url_for('vat_settlement.index'))
