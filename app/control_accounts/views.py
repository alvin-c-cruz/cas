from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_required, current_user

from app.settings import AppSettings
from app.accounts.models import Account
from app.audit.utils import log_audit
from app.posting.control_accounts import CONTROL_ACCOUNTS

control_accounts_bp = Blueprint('control_accounts', __name__,
                                template_folder='templates')


def _accountant_or_admin():
    return current_user.role == 'accountant' or current_user.has_full_access


def _postable_accounts():
    from app.posting.control_accounts import get_postable_accounts
    return get_postable_accounts()


def _postable_codes():
    return {a.code for a in _postable_accounts()}


@control_accounts_bp.route('/settings/control-accounts')
@login_required
def index():
    if not _accountant_or_admin():
        flash('Only Accountants and Administrators can assign control accounts.', 'error')
        return redirect(url_for('dashboard.index'))
    accounts = _postable_accounts()
    current = {key: AppSettings.get_setting(setting_key)
               for key, (setting_key, _) in CONTROL_ACCOUNTS.items()}
    return render_template('control_accounts/index.html',
                           accounts=accounts, control=CONTROL_ACCOUNTS, current=current)


@control_accounts_bp.route('/settings/control-accounts', methods=['POST'])
@login_required
def save():
    if not _accountant_or_admin():
        flash('Only Accountants and Administrators can perform this action.', 'error')
        return redirect(url_for('dashboard.index'))
    postable = _postable_codes()
    submitted = {}
    for key, (setting_key, label) in CONTROL_ACCOUNTS.items():
        code = (request.form.get(setting_key) or '').strip()
        if code and code not in postable:
            flash(f'Account {code} for {label} was not found or is not postable.', 'error')
            return redirect(url_for('control_accounts.index'))
        submitted[setting_key] = code
    for setting_key, code in submitted.items():
        AppSettings.set_setting(setting_key, code, updated_by=current_user.username)
    log_audit(module='control_accounts', action='assign_accounts',
              record_id=None, record_identifier='control_accounts',
              new_values=submitted, user_id=current_user.id)
    flash('Control accounts saved.', 'success')
    return redirect(url_for('control_accounts.index'))
