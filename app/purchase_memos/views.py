"""Vendor Debit Memo views -- buy-side mirror of app/sales_memos/views.py's
credit-memo branch (a debit memo REDUCES AP, exactly like a credit memo REDUCES
AR -- see app/purchase_memos/je.py's module docstring for the full "name flip").

Only 'debit' is wired (a future Vendor Credit Memo would reuse memo_type='credit',
out of scope here) -- so, unlike sales_memos, this blueprint is NOT parameterized
by memo_type; every route is the debit-note-shaped one directly.

Adjudication 1 (Task 4, binding): sales_memos/views.py::_post_impl -- not
sales_memos/je.py::post_memo_je -- performs the AR-balance mutation
(_apply_memo_to_ar/_reverse_memo_from_ar). Task 3's post_purchase_memo_je
originally reduced the AP bill's balance itself; that has been MOVED here
(_apply_memo_to_ap/_reverse_memo_from_ap) to restore mirror parity. There is
now exactly ONE reduction site: debit_post -> _apply_memo_to_ap. je.py no
longer touches the bill at all (see its updated module docstring)."""
import json
from decimal import Decimal, InvalidOperation

from flask import (Blueprint, render_template, redirect, url_for, flash,
                   request, session, current_app, abort)
from flask_login import login_required, current_user

from app import db
from app.purchase_memos.models import PurchaseMemo, PurchaseMemoItem, generate_purchase_memo_number
from app.purchase_memos.forms import PurchaseMemoForm
from app.purchase_memos import service
from app.audit.utils import log_create, log_audit, model_to_dict
from app.errors.utils import log_exception
from app.utils import ph_now
from app.periods.utils import validate_transaction_date_with_flash
from app.purchase_memos.je import post_purchase_memo_je, reverse_purchase_memo_je

purchase_memos_bp = Blueprint('purchase_memos', __name__, template_folder='templates')

DEBITABLE_AP_STATUSES = ('posted', 'partially_paid', 'paid')


def _accountant_or_admin():
    return current_user.role == 'accountant' or current_user.has_full_access


def _memo_create_gate():
    if current_user.role not in ['staff', 'accountant', 'admin', 'chief_accountant']:
        flash('You do not have permission to enter memos.', 'error')
        return redirect(url_for('purchase_memos.debit_list'))
    return None


def _eligible_aps(branch_id):
    from app.accounts_payable.models import AccountsPayable
    return (AccountsPayable.query
            .filter(AccountsPayable.branch_id == branch_id,
                    AccountsPayable.payee_type == 'vendor',
                    AccountsPayable.status.in_(DEBITABLE_AP_STATUSES))
            .order_by(AccountsPayable.ap_date.desc(), AccountsPayable.id.desc()).all())


def _cash_account_choices():
    from app.accounts.models import Account
    accts = Account.query.filter_by(is_active=True).order_by(Account.code).all()
    return [(0, '- select cash account -')] + [(a.id, f'{a.code} - {a.name}') for a in accts]


def _parse_memo_lines(memo, ap, lines_json):
    """Attach memo lines from [{accounts_payable_item_id, amount}]. Each line snapshots
    the referenced AP line's VAT/WHT/account/product, but is AMOUNT-based: quantity/
    unit_price are left null so calculate_amounts uses the given amount directly. The
    per-line amount is guarded to the referenced AP line's amount (mirror
    sales_memos._parse_memo_lines)."""
    items = json.loads(lines_json) if lines_json else []
    ap_lines = {li.id: li for li in ap.line_items}
    kept = 0
    for d in items:
        api_id = d.get('accounts_payable_item_id')
        try:
            amt = Decimal(str(d.get('amount')))
        except (InvalidOperation, TypeError):
            amt = Decimal('0')
        if not api_id or amt <= 0:
            continue
        src = ap_lines.get(int(api_id))
        if src is None:
            raise ValueError('A memo line references a line not on the selected bill.')
        orig = Decimal(str(src.line_total if src.line_total is not None else (src.amount or 0)))
        if amt > orig:
            raise ValueError(f'Line amount {amt} exceeds the bill line amount {orig}.')
        kept += 1
        li = PurchaseMemoItem(
            line_number=kept,
            accounts_payable_item_id=src.id,
            product_id=src.product_id,
            uom_text=src.uom_text,
            unit_of_measure_id=src.unit_of_measure_id,
            amount=amt.quantize(Decimal('0.01')),
            vat_category=src.vat_category,
            vat_rate=src.vat_rate,
            wt_id=src.wt_id,
            wt_rate=src.wt_rate,
            account_id=src.account_id,
        )
        li.calculate_amounts()
        memo.line_items.append(li)
    if kept == 0:
        raise ValueError('Add at least one line.')


# -- routes ---------------------------------------------------------------------

@purchase_memos_bp.route('/vendor-debit-memos')
@login_required
def debit_list():
    branch_id = session.get('selected_branch_id')
    status_filter = request.args.get('status', 'all')
    query = PurchaseMemo.query.filter_by(branch_id=branch_id, memo_type='debit')
    if status_filter in ('draft', 'posted', 'voided'):
        query = query.filter_by(status=status_filter)
    memos = query.order_by(PurchaseMemo.memo_date.desc(), PurchaseMemo.id.desc()).all()
    return render_template('purchase_memos/list.html', memos=memos,
                           status_filter=status_filter, can_configure=_accountant_or_admin())


@purchase_memos_bp.route('/vendor-debit-memos/ap-lines/<int:ap_id>')
@login_required
def debit_ap_lines(ap_id):
    """JSON: the referenced AP bill's lines for the create grid."""
    from app.accounts_payable.models import AccountsPayable
    branch_id = session.get('selected_branch_id')
    ap = db.session.get(AccountsPayable, ap_id)
    if not ap or ap.branch_id != branch_id or ap.status not in DEBITABLE_AP_STATUSES:
        return {'error': 'Bill not found or not eligible.'}, 404
    if ap.payee_type != 'vendor':
        # _eligible_aps already filters these out of the picker; this guards a
        # tampered/crafted ap_id from reaching an employee-payee bill directly.
        return {'error': 'A Vendor Debit Memo can only reference a vendor bill, not an employee bill.'}, 404
    lines = []
    for li in ap.line_items:
        d = li.to_dict()
        # to_dict keys the line id as 'id'; the memo grid JS reads 'accounts_payable_item_id'.
        d['accounts_payable_item_id'] = li.id
        d['debitable'] = float(li.line_total if li.line_total is not None else (li.amount or 0))
        lines.append(d)
    return {'vendor_name': ap.vendor_name, 'lines': lines}


def _render_form(form):
    return render_template('purchase_memos/form.html', form=form, memo=None)


@purchase_memos_bp.route('/vendor-debit-memos/create', methods=['GET', 'POST'])
@login_required
def debit_create():
    gate = _memo_create_gate()
    if gate:
        return gate
    branch_id = session.get('selected_branch_id')
    form = PurchaseMemoForm()
    eligible = _eligible_aps(branch_id)
    form.accounts_payable_id.choices = [(ap.id, f'{ap.ap_number}: {ap.vendor_name}')
                                        for ap in eligible]
    form.cash_account_id.choices = _cash_account_choices()

    if form.validate_on_submit():
        from app.accounts_payable.models import AccountsPayable
        ap = db.session.get(AccountsPayable, form.accounts_payable_id.data)
        if not ap or ap.branch_id != branch_id or ap.status not in DEBITABLE_AP_STATUSES:
            flash('Select a valid posted Accounts Payable bill.', 'error')
            return _render_form(form)
        if ap.payee_type != 'vendor':
            # _eligible_aps already filters these out of the picker; this guards a
            # tampered accounts_payable_id from reaching an employee-payee bill directly.
            flash('A Vendor Debit Memo can only reference a vendor bill, not an employee bill.', 'error')
            return _render_form(form)
        if form.destination.data == 'cash_refund' and not form.cash_account_id.data:
            flash('Select a cash account.', 'error')
            return _render_form(form)
        try:
            memo = PurchaseMemo(
                memo_type='debit',
                memo_number=generate_purchase_memo_number('debit'),
                memo_date=form.memo_date.data,
                branch_id=branch_id,
                accounts_payable_id=ap.id,
                original_ap_number=ap.ap_number,
                vendor_id=ap.vendor_id, vendor_name=ap.vendor_name,
                vendor_tin=ap.vendor_tin, vendor_address=ap.vendor_address,
                reason=form.reason.data.strip(),
                reference=form.reference.data or None,
                destination=form.destination.data,
                cash_account_id=(form.cash_account_id.data or None
                                 if form.destination.data == 'cash_refund' else None),
                notes=form.notes.data or '',
                status='draft', created_by_id=current_user.id)
            _parse_memo_lines(memo, ap, request.form.get('lines', '[]'))
            memo.calculate_totals()
            db.session.add(memo)
            db.session.commit()
            log_create(module='purchase_memos', record_id=memo.id,
                       record_identifier=f'{memo.memo_number} - {memo.vendor_name}',
                       new_values=model_to_dict(memo, ['memo_number', 'memo_type',
                                                       'original_ap_number', 'total_amount',
                                                       'destination', 'status']))
            flash(f'Vendor Debit Memo "{memo.memo_number}" created.', 'success')
            return redirect(url_for('purchase_memos.debit_view', id=memo.id))
        except ValueError as e:
            db.session.rollback()
            flash(str(e), 'error')
            return _render_form(form)
        except Exception as e:
            db.session.rollback()
            current_app.logger.error('Error creating Vendor Debit Memo', exc_info=True)
            log_exception(e, severity='ERROR', module='purchase_memos.debit_create')
            flash('An error occurred while creating the Vendor Debit Memo.', 'error')
            return _render_form(form)

    if request.method == 'GET':
        form.memo_date.data = ph_now().date()
    return _render_form(form)


def _memo_or_404(id):
    memo = db.get_or_404(PurchaseMemo, id)
    if memo.memo_type != 'debit' or memo.branch_id != session.get('selected_branch_id'):
        abort(404)
    return memo


@purchase_memos_bp.route('/vendor-debit-memos/<int:id>')
@login_required
def debit_view(id):
    from app.users.models import User
    memo = _memo_or_404(id)
    created_by = db.session.get(User, memo.created_by_id) if memo.created_by_id else None
    return render_template('purchase_memos/detail.html', memo=memo,
                           can_manage=_accountant_or_admin(), created_by=created_by)


@purchase_memos_bp.route('/vendor-debit-memos/<int:id>/print')
@login_required
def debit_print(id):
    from app.settings import AppSettings
    memo = _memo_or_404(id)
    company = {'name': AppSettings.get_setting('company_name', ''),
               'address': AppSettings.get_setting('company_address', ''),
               'tin': AppSettings.get_setting('company_tin', '')}
    return render_template('purchase_memos/print.html', memo=memo, company=company,
                           printed_at=ph_now())


def _apply_memo_to_ap(memo):
    """AP-balance reduction: reduce the referenced bill's open balance (mirror
    sales_memos._apply_memo_to_ar). Only for a debit memo with destination='ap'.
    This is the ONE place the referenced bill's balance is mutated on post --
    post_purchase_memo_je (app/purchase_memos/je.py) builds the JE only."""
    ap = memo.accounts_payable
    amount = Decimal(str(memo.total_amount or 0))
    current = Decimal(str(ap.balance or 0))
    if amount > current:
        raise ValueError(
            f'The debit ({amount}) exceeds the bill open balance ({current}). '
            f'Use a cash refund or a vendor credit balance instead.')
    ap.amount_paid = Decimal(str(ap.amount_paid or 0)) + amount
    ap.balance = Decimal(str(ap.total_amount)) - ap.amount_paid
    if ap.balance <= 0:
        ap.status = 'paid'
    elif ap.amount_paid > 0:
        ap.status = 'partially_paid'


def _reverse_memo_from_ap(memo):
    ap = memo.accounts_payable
    amount = Decimal(str(memo.total_amount or 0))
    ap.amount_paid = Decimal(str(ap.amount_paid or 0)) - amount
    if ap.amount_paid < 0:
        ap.amount_paid = Decimal('0.00')
    ap.balance = Decimal(str(ap.total_amount)) - ap.amount_paid
    ap.status = 'posted' if ap.amount_paid <= 0 else 'partially_paid'


@purchase_memos_bp.route('/vendor-debit-memos/<int:id>/post', methods=['POST'])
@login_required
def debit_post(id):
    memo = _memo_or_404(id)
    view_url = url_for('purchase_memos.debit_view', id=id)
    if not _accountant_or_admin():
        flash('Only an accountant or administrator can post a Vendor Debit Memo.', 'error')
        return redirect(view_url)
    if memo.status != 'draft':
        flash('Only a draft Vendor Debit Memo can be posted.', 'error')
        return redirect(view_url)
    # Memos post real GL via post_purchase_memo_je, so -- like every other posting
    # document -- a memo dated in a closed period must not be posted.
    if not validate_transaction_date_with_flash(memo.memo_date, 'Vendor Debit Memo'):
        return redirect(view_url)
    try:
        memo.status = 'posted'
        memo.posted_by_id = current_user.id
        memo.posted_at = ph_now()
        je = post_purchase_memo_je(memo, current_user.id)   # status posted -> JE posted
        memo.journal_entry_id = je.id
        if memo.destination == 'ap':
            _apply_memo_to_ap(memo)
        db.session.commit()
        log_audit(module='purchase_memos', action='post', record_id=memo.id,
                  record_identifier=memo.memo_number, notes='Posted')
        flash(f'Vendor Debit Memo "{memo.memo_number}" posted.', 'success')
    except ValueError as e:
        db.session.rollback()
        flash(str(e), 'error')
    except Exception as e:
        db.session.rollback()
        current_app.logger.error('Error posting Vendor Debit Memo', exc_info=True)
        log_exception(e, severity='ERROR', module='purchase_memos.debit_post')
        flash('An error occurred posting the Vendor Debit Memo.', 'error')
    return redirect(view_url)


@purchase_memos_bp.route('/vendor-debit-memos/<int:id>/void', methods=['POST'])
@login_required
def debit_void(id):
    memo = _memo_or_404(id)
    view_url = url_for('purchase_memos.debit_view', id=id)
    if not _accountant_or_admin():
        flash('Only an accountant or administrator can void a Vendor Debit Memo.', 'error')
        return redirect(view_url)
    if memo.status == 'voided':
        flash('This Vendor Debit Memo is already voided.', 'error')
        return redirect(view_url)
    reason = (request.form.get('void_reason') or '').strip()
    if len(reason) < 10:
        flash('A void reason (min 10 characters) is required.', 'error')
        return redirect(view_url)
    # The void reverses via a JE dated TODAY (reverse_purchase_memo_je uses
    # ph_now().date()), so a closed current month must block it. Only matters
    # for a posted memo.
    if memo.status == 'posted' and not validate_transaction_date_with_flash(
            ph_now().date(), 'Reversal'):
        return redirect(view_url)
    try:
        if memo.status == 'posted':
            reverse_purchase_memo_je(memo, current_user.id)
            if memo.destination == 'ap':
                _reverse_memo_from_ap(memo)
        memo.status = 'voided'
        memo.voided_by_id = current_user.id
        memo.voided_at = ph_now()
        memo.void_reason = reason
        db.session.commit()
        log_audit(module='purchase_memos', action='void', record_id=memo.id,
                  record_identifier=memo.memo_number, notes=f'Voided: {reason}')
        flash(f'Vendor Debit Memo "{memo.memo_number}" voided.', 'warning')
    except Exception as e:
        db.session.rollback()
        current_app.logger.error('Error voiding Vendor Debit Memo', exc_info=True)
        log_exception(e, severity='ERROR', module='purchase_memos.debit_void')
        flash('An error occurred voiding the Vendor Debit Memo.', 'error')
    return redirect(view_url)


# -- Settings: accountant-assigned accounts (adjudication 2) --------------------

@purchase_memos_bp.route('/purchase-memos/settings')
@login_required
def settings():
    if not _accountant_or_admin():
        flash('Only Accountants and Administrators can access Purchase Memo settings.', 'error')
        return redirect(url_for('dashboard.index'))
    from app.accounts.models import Account
    returns_code = service.AppSettings.get_setting(service.PURCHASE_RETURNS_KEY)
    credits_code = service.AppSettings.get_setting(service.VENDOR_CREDITS_KEY)
    accounts = Account.query.filter_by(is_active=True).order_by(Account.code).all()
    return render_template('purchase_memos/settings.html', accounts=accounts,
                           returns_code=returns_code, credits_code=credits_code,
                           accounts_assigned=bool(returns_code) and bool(credits_code))


@purchase_memos_bp.route('/purchase-memos/settings/accounts', methods=['POST'])
@login_required
def save_accounts():
    """Accountant assigns the contra + vendor-credits accounts (stored as AppSettings codes)."""
    if not _accountant_or_admin():
        flash('Only Accountants and Administrators can perform this action.', 'error')
        return redirect(url_for('dashboard.index'))
    from app.accounts.models import Account
    returns = (request.form.get(service.PURCHASE_RETURNS_KEY) or '').strip()
    credits = (request.form.get(service.VENDOR_CREDITS_KEY) or '').strip()
    for code, label in ((returns, 'Purchase Returns & Allowances'),
                        (credits, 'Vendor Credits')):
        if code and Account.query.filter_by(code=code).first() is None:
            flash(f'Account {code} for {label} was not found.', 'error')
            return redirect(url_for('purchase_memos.settings'))
    service.AppSettings.set_setting(service.PURCHASE_RETURNS_KEY, returns,
                                    updated_by=current_user.username)
    service.AppSettings.set_setting(service.VENDOR_CREDITS_KEY, credits,
                                    updated_by=current_user.username)
    log_audit(module='purchase_memos', action='assign_accounts', record_id=None,
              record_identifier='purchase_memo_accounts',
              new_values={service.PURCHASE_RETURNS_KEY: returns,
                          service.VENDOR_CREDITS_KEY: credits},
              user_id=current_user.id)
    flash('Purchase Memo accounts saved.', 'success')
    return redirect(url_for('purchase_memos.settings'))
