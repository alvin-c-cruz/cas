"""Petty Cash Fund / Voucher / Replenishment CRUD + lifecycle (R-04 slice 4).

Role idiom mirrors app/bank_transfers/views.py: staff+ record vouchers (no JE,
no accountant gate); accountant+ establish/adjust/close funds and replenish
(they post journal entries). No RowVersioned concurrency guard is needed on
PettyCashFund/PettyCashVoucher edits (this app's usual claim_version pattern) --
the one genuinely concurrency-sensitive operation, replenishment, is guarded
inside app/petty_cash/replenishment.py itself (an atomic claim UPDATE, not a
view-layer row_version check -- see that module's docstring for why).
"""
from functools import wraps
from decimal import Decimal, InvalidOperation

from flask import Blueprint, render_template, redirect, url_for, flash, request, session
from flask_login import login_required, current_user

from app import db
from app.accounts.models import Account
from app.audit.utils import log_create, log_update, model_to_dict
from app.posting.control_accounts import ControlAccountError
from app.petty_cash.forms import (PettyCashFundForm, PettyCashFundAdjustForm,
                                  PettyCashVoucherForm, PettyCashReplenishForm)
from app.petty_cash.models import PettyCashFund, PettyCashVoucher, PettyCashReplenishment
from app.petty_cash.posting import post_establish, post_adjust_float, post_close, record_voucher
from app.petty_cash.replenishment import post_replenishment

petty_cash_bp = Blueprint('petty_cash', __name__, template_folder='templates')

_FUND_FIELDS = ['code', 'name', 'account_id', 'custodian', 'float_amount',
                'funding_bank_account_id', 'status']
_VOUCHER_FIELDS = ['payee', 'expense_account_id', 'amount', 'description', 'receipt_ref', 'status']


def staff_or_above_required(f):
    """Tier 1 ops (record/edit/delete a held voucher; read fund status) --
    staff, accountant, admin, chief accountant."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated:
            return redirect(url_for('users.login'))
        if current_user.role not in ['staff', 'accountant', 'admin', 'chief_accountant']:
            flash('You do not have permission to perform this action.', 'error')
            return redirect(url_for('dashboard.index'))
        return f(*args, **kwargs)
    return decorated_function


def accountant_or_above_required(f):
    """Tier 2 ops (establish/adjust/close a fund; replenish) -- these post JEs."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated:
            return redirect(url_for('users.login'))
        if not (current_user.role == 'accountant' or current_user.has_full_access):
            flash('You do not have permission to perform this action.', 'error')
            return redirect(url_for('dashboard.index'))
        return f(*args, **kwargs)
    return decorated_function


def _gl_account_choices(exclude_ids=None):
    """Active leaf accounts, minus any already claimed by another PettyCashFund
    (account_id is 1:1, same pattern as bank_accounts._available_account_choices)."""
    from app.posting.control_accounts import get_postable_accounts
    claimed = {f.account_id for f in PettyCashFund.query.all()}
    if exclude_ids:
        claimed -= set(exclude_ids)
    return [(a.id, f'{a.code} — {a.name}') for a in get_postable_accounts() if a.id not in claimed]


def _expense_account_choices():
    from app.posting.control_accounts import get_postable_accounts
    return [(a.id, f'{a.code} — {a.name}') for a in get_postable_accounts()]


def _bank_account_choices(branch_id):
    """Raw BankAccount.id choices for this branch -- funding_bank_account_id is a
    FK to bank_accounts.id, NOT accounts.id, so bank_accounts.service's
    cash_bank_account_choices (which returns GL account ids) doesn't fit here."""
    from app.bank_accounts.models import BankAccount
    rows = (BankAccount.query.filter_by(branch_id=branch_id, is_active=True)
            .order_by(BankAccount.code).all())
    return [(b.id, f'{b.code} — {b.name}') for b in rows]


def _account_label(account_id):
    account = db.session.get(Account, account_id)
    return f'{account.code} — {account.name}' if account else str(account_id)


@petty_cash_bp.route('/petty-cash/funds')
@login_required
def fund_list():
    branch_id = session.get('selected_branch_id')
    funds = (PettyCashFund.query.filter_by(branch_id=branch_id)
             .order_by(PettyCashFund.code).all())
    return render_template('petty_cash/fund_list.html', funds=funds)


@petty_cash_bp.route('/petty-cash/funds/new', methods=['GET', 'POST'])
@login_required
@accountant_or_above_required
def fund_new():
    form = PettyCashFundForm()
    branch_id = session.get('selected_branch_id')
    form.account_id.choices = _gl_account_choices()
    form.funding_bank_account_id.choices = _bank_account_choices(branch_id)

    if form.validate_on_submit():
        fund = PettyCashFund(
            branch_id=branch_id, code=form.code.data.strip(), name=form.name.data.strip(),
            account_id=form.account_id.data, custodian=(form.custodian.data or '').strip() or None,
            float_amount=form.float_amount.data, funding_bank_account_id=form.funding_bank_account_id.data,
        )
        db.session.add(fund)
        db.session.flush()
        try:
            post_establish(fund, actor=current_user)
        except (ValueError, ControlAccountError) as e:
            db.session.rollback()
            flash(str(e), 'error')
            return render_template('petty_cash/fund_form.html', form=form, fund=None)
        db.session.commit()
        log_create('petty_cash', fund.id, fund.code, model_to_dict(fund, _FUND_FIELDS))
        flash(f'Petty Cash Fund "{fund.code}" established.', 'success')
        return redirect(url_for('petty_cash.fund_status', id=fund.id))

    return render_template('petty_cash/fund_form.html', form=form, fund=None)


@petty_cash_bp.route('/petty-cash/funds/<int:id>/edit', methods=['GET', 'POST'])
@login_required
@accountant_or_above_required
def fund_edit(id):
    fund = db.get_or_404(PettyCashFund, id)
    form = PettyCashFundAdjustForm(obj=fund)

    if form.validate_on_submit():
        before = model_to_dict(fund, _FUND_FIELDS)
        fund.name = form.name.data.strip()
        fund.custodian = (form.custodian.data or '').strip() or None
        delta = form.float_delta.data
        if delta:
            try:
                post_adjust_float(fund, delta, actor=current_user)
            except (ValueError, ControlAccountError) as e:
                db.session.rollback()
                flash(str(e), 'error')
                return render_template('petty_cash/fund_form.html', form=form, fund=fund)
        db.session.commit()
        log_update('petty_cash', fund.id, fund.code, before, model_to_dict(fund, _FUND_FIELDS))
        flash(f'Petty Cash Fund "{fund.code}" updated.', 'success')
        return redirect(url_for('petty_cash.fund_status', id=fund.id))

    return render_template('petty_cash/fund_form.html', form=form, fund=fund)


@petty_cash_bp.route('/petty-cash/funds/<int:id>/close', methods=['POST'])
@login_required
@accountant_or_above_required
def fund_close(id):
    fund = db.get_or_404(PettyCashFund, id)
    before = model_to_dict(fund, _FUND_FIELDS)
    try:
        post_close(fund, actor=current_user)
    except (ValueError, ControlAccountError) as e:
        db.session.rollback()
        flash(str(e), 'error')
        return redirect(url_for('petty_cash.fund_status', id=id))
    db.session.commit()
    log_update('petty_cash', fund.id, fund.code, before, model_to_dict(fund, _FUND_FIELDS))
    flash(f'Petty Cash Fund "{fund.code}" closed.', 'success')
    return redirect(url_for('petty_cash.fund_status', id=id))


@petty_cash_bp.route('/petty-cash/funds/<int:id>')
@login_required
@staff_or_above_required
def fund_status(id):
    fund = db.get_or_404(PettyCashFund, id)
    held_vouchers = (PettyCashVoucher.query
                     .filter_by(fund_id=fund.id, status='held')
                     .order_by(PettyCashVoucher.voucher_date).all())
    held_total = sum((v.amount for v in held_vouchers), Decimal('0.00'))
    expected_cash = fund.float_amount - held_total
    return render_template('petty_cash/fund_status.html', fund=fund,
                           held_vouchers=held_vouchers, held_total=held_total,
                           expected_cash=expected_cash)


@petty_cash_bp.route('/petty-cash/funds/<int:fund_id>/vouchers/new', methods=['GET', 'POST'])
@login_required
@staff_or_above_required
def voucher_new(fund_id):
    fund = db.get_or_404(PettyCashFund, fund_id)
    form = PettyCashVoucherForm()
    form.expense_account_id.choices = _expense_account_choices()

    if form.validate_on_submit():
        v = record_voucher(fund, payee=form.payee.data.strip(),
                           expense_account_id=form.expense_account_id.data,
                           amount=form.amount.data, description=(form.description.data or '').strip(),
                           receipt_ref=(form.receipt_ref.data or '').strip(), created_by=current_user)
        db.session.commit()
        log_create('petty_cash', v.id, v.voucher_number, model_to_dict(v, _VOUCHER_FIELDS))
        flash(f'Voucher "{v.voucher_number}" recorded.', 'success')
        return redirect(url_for('petty_cash.fund_status', id=fund.id))

    return render_template('petty_cash/voucher_form.html', form=form, fund=fund, voucher=None)


@petty_cash_bp.route('/petty-cash/vouchers/<int:id>/edit', methods=['GET', 'POST'])
@login_required
@staff_or_above_required
def voucher_edit(id):
    v = db.get_or_404(PettyCashVoucher, id)
    if v.status != 'held':
        flash('Only held vouchers can be edited.', 'error')
        return redirect(url_for('petty_cash.fund_status', id=v.fund_id))
    form = PettyCashVoucherForm(obj=v)
    form.expense_account_id.choices = _expense_account_choices()

    if form.validate_on_submit():
        before = model_to_dict(v, _VOUCHER_FIELDS)
        v.payee = form.payee.data.strip()
        v.expense_account_id = form.expense_account_id.data
        v.amount = form.amount.data
        v.description = (form.description.data or '').strip()
        v.receipt_ref = (form.receipt_ref.data or '').strip()
        db.session.commit()
        log_update('petty_cash', v.id, v.voucher_number, before, model_to_dict(v, _VOUCHER_FIELDS))
        flash(f'Voucher "{v.voucher_number}" updated.', 'success')
        return redirect(url_for('petty_cash.fund_status', id=v.fund_id))

    return render_template('petty_cash/voucher_form.html', form=form, fund=v.fund, voucher=v)


@petty_cash_bp.route('/petty-cash/vouchers/<int:id>/delete', methods=['POST'])
@login_required
@staff_or_above_required
def voucher_delete(id):
    v = db.get_or_404(PettyCashVoucher, id)
    if v.status != 'held':
        flash('Only held vouchers can be deleted.', 'error')
        return redirect(url_for('petty_cash.fund_status', id=v.fund_id))
    fund_id = v.fund_id
    snapshot = model_to_dict(v, _VOUCHER_FIELDS)
    number = v.voucher_number
    db.session.delete(v)
    db.session.commit()
    log_update('petty_cash', id, number, snapshot, {'status': 'deleted'})
    flash(f'Voucher "{number}" deleted.', 'success')
    return redirect(url_for('petty_cash.fund_status', id=fund_id))


@petty_cash_bp.route('/petty-cash/funds/<int:id>/replenish', methods=['GET', 'POST'])
@login_required
@accountant_or_above_required
def replenish_new(id):
    fund = db.get_or_404(PettyCashFund, id)
    held_vouchers = (PettyCashVoucher.query
                     .filter_by(fund_id=fund.id, status='held')
                     .order_by(PettyCashVoucher.voucher_date).all())
    held_total = sum((v.amount for v in held_vouchers), Decimal('0.00'))
    expected_cash = fund.float_amount - held_total
    form = PettyCashReplenishForm()

    if form.validate_on_submit():
        raw_ids = (form.selected_voucher_ids.data or '').strip()
        try:
            selected_ids = [int(x) for x in raw_ids.split(',') if x.strip()]
        except ValueError:
            selected_ids = []
        if not selected_ids:
            flash('Select at least one held voucher to replenish.', 'error')
            return render_template('petty_cash/replenish_form.html', form=form, fund=fund,
                                   held_vouchers=held_vouchers, held_total=held_total,
                                   expected_cash=expected_cash)
        try:
            rep = post_replenishment(fund, selected_ids, physical_cash_counted=form.physical_cash_counted.data,
                                     actor=current_user)
        except ControlAccountError as e:
            db.session.rollback()
            flash(str(e), 'error')
            return render_template('petty_cash/replenish_form.html', form=form, fund=fund,
                                   held_vouchers=held_vouchers, held_total=held_total,
                                   expected_cash=expected_cash)
        if rep is None:
            db.session.rollback()
            flash('One or more selected vouchers were already replenished by another user. '
                 'Please refresh and try again.', 'error')
            return redirect(url_for('petty_cash.replenish_new', id=fund.id))
        db.session.commit()
        log_create('petty_cash', rep.id, rep.replenishment_number,
                  {'fund_id': fund.id, 'vouchers_total': str(rep.vouchers_total),
                   'short_over_amount': str(rep.short_over_amount),
                   'replenish_amount': str(rep.replenish_amount)})
        flash(f'Replenishment "{rep.replenishment_number}" posted.', 'success')
        return redirect(url_for('petty_cash.replenish_detail', id=rep.id))

    return render_template('petty_cash/replenish_form.html', form=form, fund=fund,
                           held_vouchers=held_vouchers, held_total=held_total,
                           expected_cash=expected_cash)


@petty_cash_bp.route('/petty-cash/replenishments/<int:id>')
@login_required
@staff_or_above_required
def replenish_detail(id):
    rep = db.get_or_404(PettyCashReplenishment, id)
    return render_template('petty_cash/replenish_detail.html', rep=rep)


@petty_cash_bp.route('/petty-cash/replenishments/<int:id>/print')
@login_required
@staff_or_above_required
def replenish_print(id):
    rep = db.get_or_404(PettyCashReplenishment, id)
    from app.settings import AppSettings
    from app.utils import ph_now
    company = {
        'name': AppSettings.get_setting('company_name', ''),
        'address': AppSettings.get_setting('company_address', ''),
        'tin': AppSettings.get_setting('company_tin', ''),
    }
    return render_template('petty_cash/replenish_print.html', rep=rep, company=company, printed_at=ph_now())
