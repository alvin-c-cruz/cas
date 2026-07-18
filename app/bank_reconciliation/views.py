"""Bank Reconciliation register/work/detail/print views (R-04 slice 3).

Accountant/admin/chief-accountant only, mirroring the exact inline role-check
idiom used for CDV posting -- every route in this module, no staff tier (unlike
petty_cash's two-tier staff/accountant split): reconciling is a control activity,
not a data-entry one.
"""
from functools import wraps
from decimal import Decimal, InvalidOperation

from flask import Blueprint, render_template, redirect, url_for, flash, request, session
from flask_login import login_required, current_user

from app import db
from app.accounts.models import Account
from app.audit.utils import log_create, log_update, model_to_dict
from app.utils.concurrency import submitted_version
from app.bank_reconciliation.forms import NewReconciliationForm, AdjustmentForm
from app.bank_reconciliation.models import BankReconciliation
from app.bank_reconciliation import service

bank_reconciliation_bp = Blueprint('bank_reconciliation', __name__, template_folder='templates')

_REC_FIELDS = ['bank_account_id', 'statement_date', 'statement_ending_balance', 'beginning_balance', 'status']


def accountant_or_above_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated:
            return redirect(url_for('users.login'))
        if not (current_user.role == 'accountant' or current_user.has_full_access):
            flash('You do not have permission to perform this action.', 'error')
            return redirect(url_for('dashboard.index'))
        return f(*args, **kwargs)
    return decorated_function


def _expense_account_choices():
    from app.posting.control_accounts import get_postable_accounts
    return [(a.id, f'{a.code} — {a.name}') for a in get_postable_accounts()]


@bank_reconciliation_bp.route('/bank-reconciliation/')
@login_required
@accountant_or_above_required
def pick_account():
    """Landing page for the sidebar link -- lists this branch's active bank
    accounts so the user can pick which one to reconcile."""
    from app.bank_accounts.models import BankAccount
    branch_id = session.get('selected_branch_id')
    accounts = (BankAccount.query.filter_by(branch_id=branch_id, is_active=True)
                .order_by(BankAccount.code).all())
    return render_template('bank_reconciliation/pick_account.html', accounts=accounts)


@bank_reconciliation_bp.route('/bank-reconciliation/<int:bank_account_id>/register')
@login_required
@accountant_or_above_required
def register(bank_account_id):
    from app.bank_accounts.models import BankAccount
    bank_account = db.get_or_404(BankAccount, bank_account_id)
    recs = (BankReconciliation.query.filter_by(bank_account_id=bank_account_id)
            .order_by(BankReconciliation.statement_date.desc()).all())
    return render_template('bank_reconciliation/register.html', bank_account=bank_account, recs=recs)


@bank_reconciliation_bp.route('/bank-reconciliation/<int:bank_account_id>/new', methods=['GET', 'POST'])
@login_required
@accountant_or_above_required
def new(bank_account_id):
    from app.bank_accounts.models import BankAccount
    bank_account = db.get_or_404(BankAccount, bank_account_id)
    form = NewReconciliationForm()

    prior = (BankReconciliation.query
             .filter_by(bank_account_id=bank_account_id, status='completed')
             .order_by(BankReconciliation.statement_date.desc()).first())
    beginning_balance = prior.adjusted_balance if prior else bank_account.opening_balance

    if form.validate_on_submit():
        rec = BankReconciliation(
            bank_account_id=bank_account.id, statement_date=form.statement_date.data,
            statement_ending_balance=form.statement_ending_balance.data,
            beginning_balance=beginning_balance,
        )
        db.session.add(rec)
        db.session.commit()
        log_create('bank_reconciliation', rec.id, f'{bank_account.code} {rec.statement_date}',
                  model_to_dict(rec, _REC_FIELDS))
        flash(f'Reconciliation for {bank_account.code} ({rec.statement_date}) started.', 'success')
        return redirect(url_for('bank_reconciliation.work', id=rec.id))

    return render_template('bank_reconciliation/new.html', form=form, bank_account=bank_account,
                           beginning_balance=beginning_balance)


@bank_reconciliation_bp.route('/bank-reconciliation/<int:id>/work')
@login_required
@accountant_or_above_required
def work(id):
    rec = db.get_or_404(BankReconciliation, id)
    if rec.status != 'draft':
        return redirect(url_for('bank_reconciliation.detail', id=id))
    items = service.uncleared_book_items(rec.bank_account, exclude_reconciliation_id=rec.id)
    already_ticked = {i.je_line_id for i in rec.items}
    adj_form = AdjustmentForm()
    adj_form.account_id.choices = _expense_account_choices()
    return render_template('bank_reconciliation/work.html', rec=rec, items=items,
                           already_ticked=already_ticked, adj_form=adj_form)


@bank_reconciliation_bp.route('/bank-reconciliation/<int:id>/add-adjustment', methods=['POST'])
@login_required
@accountant_or_above_required
def add_adjustment(id):
    rec = db.get_or_404(BankReconciliation, id)
    if rec.status != 'draft':
        flash('Only a draft reconciliation can take an adjustment.', 'error')
        return redirect(url_for('bank_reconciliation.detail', id=id))
    form = AdjustmentForm()
    form.account_id.choices = _expense_account_choices()
    if form.validate_on_submit():
        service.post_adjustment(rec, account_id=form.account_id.data, amount=form.amount.data,
                                direction=form.direction.data, description=form.description.data,
                                actor=current_user)
        db.session.commit()
        flash('Adjustment posted and cleared.', 'success')
    else:
        flash('Could not post the adjustment -- check the amount and account.', 'error')
    return redirect(url_for('bank_reconciliation.work', id=id))


@bank_reconciliation_bp.route('/bank-reconciliation/<int:id>/complete', methods=['POST'])
@login_required
@accountant_or_above_required
def complete(id):
    rec = db.get_or_404(BankReconciliation, id)
    if rec.status != 'draft':
        return redirect(url_for('bank_reconciliation.detail', id=id))

    raw_ids = (request.form.get('ticked_line_ids') or '').strip()
    try:
        ticked_ids = {int(x) for x in raw_ids.split(',') if x.strip()}
    except ValueError:
        ticked_ids = set()

    before = model_to_dict(rec, _REC_FIELDS)
    ok = service.complete_reconciliation(rec, ticked_ids, submitted_version(), current_user)
    if not ok:
        db.session.rollback()
        if rec.status == 'draft':
            flash('Reconciliation does not balance yet -- tick items or post an adjustment until '
                 'the difference is zero.', 'error')
        else:
            flash('This reconciliation was changed by another user. Please refresh and try again.', 'error')
        return redirect(url_for('bank_reconciliation.work', id=id))

    db.session.commit()
    log_update('bank_reconciliation', rec.id, f'{rec.bank_account.code} {rec.statement_date}',
              before, model_to_dict(rec, _REC_FIELDS))
    flash('Reconciliation completed.', 'success')
    return redirect(url_for('bank_reconciliation.detail', id=id))


@bank_reconciliation_bp.route('/bank-reconciliation/<int:id>')
@login_required
@accountant_or_above_required
def detail(id):
    rec = db.get_or_404(BankReconciliation, id)
    if rec.status != 'completed':
        return redirect(url_for('bank_reconciliation.work', id=id))
    return render_template('bank_reconciliation/detail.html', rec=rec)


@bank_reconciliation_bp.route('/bank-reconciliation/<int:id>/print')
@login_required
@accountant_or_above_required
def print_rec(id):
    rec = db.get_or_404(BankReconciliation, id)
    if rec.status != 'completed':
        flash('Only a completed reconciliation can be printed.', 'error')
        return redirect(url_for('bank_reconciliation.work', id=id))
    from app.settings import AppSettings
    from app.utils import ph_now
    company = {
        'name': AppSettings.get_setting('company_name', ''),
        'address': AppSettings.get_setting('company_address', ''),
        'tin': AppSettings.get_setting('company_tin', ''),
    }
    return render_template('bank_reconciliation/print.html', rec=rec, company=company, printed_at=ph_now())
