"""Sales Memo views -- Credit Memo (Sales Returns) register + shared settings.

Phase 1 builds the Credit Memo (memo_type='credit'); Debit Note (memo_type='debit')
routes arrive in Phase 2. View functions are prefixed `credit_*` / `debit_*` so the two
MODULE_REGISTRY keys can gate one blueprint by endpoint prefix. The account-assignment
settings routes are intentionally NOT prefixed (shared config, inline accountant/admin gated).
"""
from flask import (Blueprint, render_template, redirect, url_for, flash,
                   request, session)
from flask_login import login_required, current_user

from app import db
from app.sales_memos.models import SalesMemo
from app.sales_memos import service

sales_memos_bp = Blueprint('sales_memos', __name__, template_folder='templates')

VALID_STATUSES = ('draft', 'posted', 'voided')


def _accountant_or_admin():
    return current_user.role == 'accountant' or current_user.has_full_access


# -- Credit Memo register ------------------------------------------------------

@sales_memos_bp.route('/credit-memos')
@login_required
def credit_list():
    branch_id = session.get('selected_branch_id')
    status_filter = request.args.get('status', 'all')
    query = SalesMemo.query.filter_by(branch_id=branch_id, memo_type='credit')
    if status_filter in VALID_STATUSES:
        query = query.filter_by(status=status_filter)
    memos = query.order_by(SalesMemo.memo_date.desc(), SalesMemo.id.desc()).all()
    return render_template('sales_memos/list.html', memos=memos, memo_type='credit',
                           doc_title='Credit Memos', status_filter=status_filter,
                           can_configure=_accountant_or_admin())


# -- Shared settings: accountant-assigned accounts -----------------------------

@sales_memos_bp.route('/sales-memos/settings')
@login_required
def settings():
    if not _accountant_or_admin():
        flash('Only Accountants and Administrators can access Sales Memo settings.', 'error')
        return redirect(url_for('dashboard.index'))
    from app.accounts.models import Account
    returns_code = service.AppSettings.get_setting(service.SALES_RETURNS_KEY)
    credits_code = service.AppSettings.get_setting(service.CUSTOMER_CREDITS_KEY)
    accounts = Account.query.filter_by(is_active=True).order_by(Account.code).all()
    return render_template('sales_memos/settings.html', accounts=accounts,
                           returns_code=returns_code, credits_code=credits_code,
                           accounts_assigned=bool(returns_code) and bool(credits_code))


@sales_memos_bp.route('/sales-memos/settings/accounts', methods=['POST'])
@login_required
def save_accounts():
    """Accountant assigns the contra + customer-credits accounts (stored as AppSettings codes)."""
    if not _accountant_or_admin():
        flash('Only Accountants and Administrators can perform this action.', 'error')
        return redirect(url_for('dashboard.index'))
    from app.accounts.models import Account
    from app.audit.utils import log_audit
    returns = (request.form.get(service.SALES_RETURNS_KEY) or '').strip()
    credits = (request.form.get(service.CUSTOMER_CREDITS_KEY) or '').strip()
    for code, label in ((returns, 'Sales Returns & Allowances'),
                        (credits, 'Customer Credits/Advances')):
        if code and Account.query.filter_by(code=code).first() is None:
            flash(f'Account {code} for {label} was not found.', 'error')
            return redirect(url_for('sales_memos.settings'))
    service.AppSettings.set_setting(service.SALES_RETURNS_KEY, returns,
                                    updated_by=current_user.username)
    service.AppSettings.set_setting(service.CUSTOMER_CREDITS_KEY, credits,
                                    updated_by=current_user.username)
    log_audit(module='sales_memos', action='assign_accounts', record_id=None,
              record_identifier='sales_memo_accounts',
              new_values={service.SALES_RETURNS_KEY: returns,
                          service.CUSTOMER_CREDITS_KEY: credits},
              user_id=current_user.id)
    flash('Sales Memo accounts saved.', 'success')
    return redirect(url_for('sales_memos.settings'))
