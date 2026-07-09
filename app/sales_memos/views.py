"""Sales Memo views -- Credit Memo (Sales Returns) register + shared settings.

Phase 1 builds the Credit Memo (memo_type='credit'); Debit Note (memo_type='debit')
routes arrive in Phase 2. View functions are prefixed `credit_*` / `debit_*` so the two
MODULE_REGISTRY keys can gate one blueprint by endpoint prefix. The account-assignment
settings routes are intentionally NOT prefixed (shared config, inline accountant/admin gated).
"""
import json
from decimal import Decimal, InvalidOperation

from flask import (Blueprint, render_template, redirect, url_for, flash,
                   request, session, current_app, abort)
from flask_login import login_required, current_user

from app import db
from app.sales_memos.models import SalesMemo, SalesMemoItem, generate_memo_number
from app.sales_memos.forms import SalesMemoForm
from app.sales_memos import service
from app.sales_orders.models import copy_salesperson
from app.audit.utils import log_create, log_audit, model_to_dict
from app.errors.utils import log_exception
from app.utils import ph_now
from app.sales_memos.je import post_memo_je, reverse_memo_je

sales_memos_bp = Blueprint('sales_memos', __name__, template_folder='templates')

VALID_STATUSES = ('draft', 'posted', 'voided')
CREDITABLE_SI_STATUSES = ('posted', 'partially_paid', 'paid')


def _accountant_or_admin():
    return current_user.role == 'accountant' or current_user.has_full_access


def _memo_create_gate():
    if current_user.role not in ['staff', 'accountant', 'admin', 'chief_accountant']:
        flash('You do not have permission to enter memos.', 'error')
        return redirect(url_for('sales_memos.credit_list'))
    return None


def _eligible_invoices(branch_id):
    from app.sales_invoices.models import SalesInvoice
    return (SalesInvoice.query
            .filter(SalesInvoice.branch_id == branch_id,
                    SalesInvoice.status.in_(CREDITABLE_SI_STATUSES))
            .order_by(SalesInvoice.invoice_date.desc(), SalesInvoice.id.desc()).all())


def _salesperson_choices(branch_id):
    from app.sales_orders.views import _salesperson_choices as so_choices
    return so_choices(branch_id)


def _cash_account_choices():
    from app.accounts.models import Account
    accts = Account.query.filter_by(is_active=True).order_by(Account.code).all()
    return [(0, '- select cash account -')] + [(a.id, f'{a.code} - {a.name}') for a in accts]


def _parse_memo_lines(memo, si, lines_json):
    """Attach memo lines from [{sales_invoice_item_id, amount}]. Each line snapshots the
    referenced SI line's VAT/WHT/account/product, but is AMOUNT-based: quantity/unit_price
    are deliberately left null so calculate_amounts uses the credited amount directly (a
    partial credit is a monetary amount, not qty x unit_price). Credited amount is guarded
    to the referenced SI line's amount."""
    items = json.loads(lines_json) if lines_json else []
    si_lines = {li.id: li for li in si.line_items}
    kept = 0
    for d in items:
        soi_id = d.get('sales_invoice_item_id')
        try:
            amt = Decimal(str(d.get('amount')))
        except (InvalidOperation, TypeError):
            amt = Decimal('0')
        if not soi_id or amt <= 0:
            continue
        src = si_lines.get(int(soi_id))
        if src is None:
            raise ValueError('A memo line references a line not on the selected invoice.')
        orig = Decimal(str(src.line_total if src.line_total is not None else (src.amount or 0)))
        if amt > orig:
            raise ValueError(
                f'Line credit {amt} exceeds the invoice line amount {orig}.')
        kept += 1
        li = SalesMemoItem(
            line_number=kept,
            sales_invoice_item_id=src.id,
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
        raise ValueError('Add at least one line to credit.')


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


@sales_memos_bp.route('/credit-memos/si-lines/<int:si_id>')
@login_required
def credit_si_lines(si_id):
    """JSON: the referenced SI's lines for the create grid (reuses SalesInvoiceItem.to_dict)."""
    from app.sales_invoices.models import SalesInvoice
    branch_id = session.get('selected_branch_id')
    si = db.session.get(SalesInvoice, si_id)
    if not si or si.branch_id != branch_id or si.status not in CREDITABLE_SI_STATUSES:
        return {'error': 'Invoice not found or not creditable.'}, 404
    lines = []
    for li in si.line_items:
        d = li.to_dict()
        # to_dict keys the line id as 'id'; the memo grid JS reads 'sales_invoice_item_id'.
        d['sales_invoice_item_id'] = li.id
        d['creditable'] = float(li.line_total if li.line_total is not None else (li.amount or 0))
        lines.append(d)
    return {'customer_name': si.customer_name, 'salesperson_id': si.salesperson_id, 'lines': lines}


@sales_memos_bp.route('/credit-memos/create', methods=['GET', 'POST'])
@login_required
def credit_create():
    gate = _memo_create_gate()
    if gate:
        return gate
    branch_id = session.get('selected_branch_id')
    form = SalesMemoForm()
    eligible = _eligible_invoices(branch_id)
    form.sales_invoice_id.choices = [(si.id, f'{si.invoice_number}: {si.customer_name}')
                                     for si in eligible]
    form.salesperson_id.choices = _salesperson_choices(branch_id)
    form.cash_account_id.choices = _cash_account_choices()

    if form.validate_on_submit():
        from app.sales_invoices.models import SalesInvoice
        si = db.session.get(SalesInvoice, form.sales_invoice_id.data)
        if not si or si.branch_id != branch_id or si.status not in CREDITABLE_SI_STATUSES:
            flash('Select a valid posted Sales Invoice.', 'error')
            return _render_credit_form(form, eligible)
        if form.destination.data == 'cash_refund' and not form.cash_account_id.data:
            flash('Select a cash account for the refund.', 'error')
            return _render_credit_form(form, eligible)
        try:
            memo = SalesMemo(
                memo_type='credit',
                memo_number=generate_memo_number('credit'),
                memo_date=form.memo_date.data,
                branch_id=branch_id,
                sales_invoice_id=si.id,
                original_invoice_number=si.invoice_number,
                customer_id=si.customer_id, customer_name=si.customer_name,
                customer_tin=si.customer_tin, customer_address=si.customer_address,
                reason=form.reason.data.strip(),
                reference=form.reference.data or None,
                destination=form.destination.data,
                cash_account_id=(form.cash_account_id.data or None
                                 if form.destination.data == 'cash_refund' else None),
                notes=form.notes.data or '',
                status='draft', created_by_id=current_user.id)
            copy_salesperson(si, memo)
            if form.salesperson_id.data:
                memo.salesperson_id = form.salesperson_id.data
            _parse_memo_lines(memo, si, request.form.get('lines', '[]'))
            memo.calculate_totals()
            db.session.add(memo)
            db.session.commit()
            log_create(module='sales_memos', record_id=memo.id,
                       record_identifier=f'{memo.memo_number} - {memo.customer_name}',
                       new_values=model_to_dict(memo, ['memo_number', 'memo_type',
                                                       'original_invoice_number', 'total_amount',
                                                       'destination', 'status']))
            flash(f'Credit Memo "{memo.memo_number}" created.', 'success')
            return redirect(url_for('sales_memos.credit_view', id=memo.id))
        except ValueError as e:
            db.session.rollback()
            flash(str(e), 'error')
            return _render_credit_form(form, eligible)
        except Exception as e:
            db.session.rollback()
            current_app.logger.error('Error creating credit memo', exc_info=True)
            log_exception(e, severity='ERROR', module='sales_memos.credit_create')
            flash('An error occurred while creating the Credit Memo.', 'error')
            return _render_credit_form(form, eligible)

    if request.method == 'GET':
        form.memo_date.data = ph_now().date()
    return _render_credit_form(form, eligible)


def _render_credit_form(form, eligible):
    return render_template('sales_memos/form.html', form=form, memo=None,
                           memo_type='credit', doc_title='Credit Memo')


@sales_memos_bp.route('/credit-memos/<int:id>')
@login_required
def credit_view(id):
    from app.users.models import User
    memo = _memo_or_404(id, 'credit')
    created_by = db.session.get(User, memo.created_by_id) if memo.created_by_id else None
    return render_template('sales_memos/detail.html', memo=memo, doc_title='Credit Memo',
                           can_manage=_accountant_or_admin(), created_by=created_by)


@sales_memos_bp.route('/credit-memos/<int:id>/print')
@login_required
def credit_print(id):
    from app.settings import AppSettings
    memo = _memo_or_404(id, 'credit')
    company = {'name': AppSettings.get_setting('company_name', ''),
               'address': AppSettings.get_setting('company_address', ''),
               'tin': AppSettings.get_setting('company_tin', '')}
    return render_template('sales_memos/print.html', memo=memo, company=company,
                           printed_at=ph_now(), doc_title='Credit Memo')


# -- lifecycle: post / void ----------------------------------------------------

def _memo_or_404(id, memo_type):
    memo = db.get_or_404(SalesMemo, id)
    if memo.memo_type != memo_type or memo.branch_id != session.get('selected_branch_id'):
        abort(404)
    return memo


def _apply_memo_to_ar(memo):
    """Credit-memo AR settlement: reduce the referenced SI's open balance (mirror
    _apply_ar_collections). Only for destination='ar'."""
    inv = memo.sales_invoice
    amount = Decimal(str(memo.total_amount or 0))
    current = Decimal(str(inv.balance or 0))
    if amount > current:
        raise ValueError(
            f'The credit ({amount}) exceeds the invoice open balance ({current}). '
            f'Use a cash refund or a customer credit balance instead.')
    inv.amount_paid = Decimal(str(inv.amount_paid or 0)) + amount
    inv.balance = Decimal(str(inv.total_amount)) - inv.amount_paid
    if inv.balance <= 0:
        inv.status = 'paid'
    elif inv.amount_paid > 0:
        inv.status = 'partially_paid'


def _reverse_memo_from_ar(memo):
    inv = memo.sales_invoice
    amount = Decimal(str(memo.total_amount or 0))
    inv.amount_paid = Decimal(str(inv.amount_paid or 0)) - amount
    if inv.amount_paid < 0:
        inv.amount_paid = Decimal('0.00')
    inv.balance = Decimal(str(inv.total_amount)) - inv.amount_paid
    inv.status = 'posted' if inv.amount_paid <= 0 else 'partially_paid'


@sales_memos_bp.route('/credit-memos/<int:id>/post', methods=['POST'])
@login_required
def credit_post(id):
    memo = _memo_or_404(id, 'credit')
    if not _accountant_or_admin():
        flash('Only an accountant or administrator can post a Credit Memo.', 'error')
        return redirect(url_for('sales_memos.credit_view', id=id))
    if memo.status != 'draft':
        flash('Only a draft Credit Memo can be posted.', 'error')
        return redirect(url_for('sales_memos.credit_view', id=id))
    try:
        memo.status = 'posted'
        memo.posted_by_id = current_user.id
        memo.posted_at = ph_now()
        je = post_memo_je(memo, current_user.id)   # status posted -> JE posted
        memo.journal_entry_id = je.id
        if memo.destination == 'ar':
            _apply_memo_to_ar(memo)
        db.session.commit()
        log_audit(module='sales_memos', action='post', record_id=memo.id,
                  record_identifier=memo.memo_number, notes='Posted')
        flash(f'Credit Memo "{memo.memo_number}" posted.', 'success')
    except ValueError as e:
        db.session.rollback()
        flash(str(e), 'error')
    except Exception as e:
        db.session.rollback()
        current_app.logger.error('Error posting credit memo', exc_info=True)
        log_exception(e, severity='ERROR', module='sales_memos.credit_post')
        flash('An error occurred posting the Credit Memo.', 'error')
    return redirect(url_for('sales_memos.credit_view', id=id))


@sales_memos_bp.route('/credit-memos/<int:id>/void', methods=['POST'])
@login_required
def credit_void(id):
    memo = _memo_or_404(id, 'credit')
    if not _accountant_or_admin():
        flash('Only an accountant or administrator can void a Credit Memo.', 'error')
        return redirect(url_for('sales_memos.credit_view', id=id))
    if memo.status == 'voided':
        flash('This Credit Memo is already voided.', 'error')
        return redirect(url_for('sales_memos.credit_view', id=id))
    reason = (request.form.get('void_reason') or '').strip()
    if len(reason) < 10:
        flash('A void reason (min 10 characters) is required.', 'error')
        return redirect(url_for('sales_memos.credit_view', id=id))
    try:
        if memo.status == 'posted':
            reverse_memo_je(memo, current_user.id)
            if memo.destination == 'ar':
                _reverse_memo_from_ar(memo)
        memo.status = 'voided'
        memo.voided_by_id = current_user.id
        memo.voided_at = ph_now()
        memo.void_reason = reason
        db.session.commit()
        log_audit(module='sales_memos', action='void', record_id=memo.id,
                  record_identifier=memo.memo_number, notes=f'Voided: {reason}')
        flash(f'Credit Memo "{memo.memo_number}" voided.', 'warning')
    except Exception as e:
        db.session.rollback()
        current_app.logger.error('Error voiding credit memo', exc_info=True)
        log_exception(e, severity='ERROR', module='sales_memos.credit_void')
        flash('An error occurred voiding the Credit Memo.', 'error')
    return redirect(url_for('sales_memos.credit_view', id=id))


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
