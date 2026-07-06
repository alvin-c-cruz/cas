from decimal import Decimal, InvalidOperation
from functools import wraps

from flask import (Blueprint, render_template, redirect, url_for, request,
                   flash, session)
from flask_login import login_required, current_user

from app import db
from app.journal_entries.models import JournalEntry, JournalEntryLine
from app.journal_entries.utils import generate_jv_number
from app.audit.utils import log_create, log_update, log_audit, model_to_dict
from app.periods.utils import validate_transaction_date_with_flash
from app.settings import AppSettings
from app.utils import ph_now
from app.opening_balances.forms import OpeningBalanceForm
from app.opening_balances.utils import (
    get_opening_entry, is_opening_locked, opening_account_choices,
    opening_leaf_account_ids, LOCK_KEY,
)
from app.utils.authz import full_access_required

opening_balances_bp = Blueprint('opening_balances', __name__, template_folder='templates')

AUDIT_FIELDS = ['entry_number', 'entry_date', 'reference', 'entry_type',
                'total_debit', 'total_credit', 'status', 'branch_id']


def accountant_or_admin_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not (current_user.role == 'accountant' or current_user.has_full_access):
            flash('You do not have permission to manage opening balances.', 'error')
            return redirect(url_for('opening_balances.index'))
        return f(*args, **kwargs)
    return wrapper


def _branch_id():
    return session.get('selected_branch_id')


def _to_decimal(raw):
    try:
        return Decimal(str(raw or '0').replace(',', '').strip() or '0')
    except (InvalidOperation, ValueError):
        return Decimal('0')


class OpeningLineError(Exception):
    pass


def _parse_lines(form):
    """Parse parallel account_id[]/debit[]/credit[] arrays into validated rows.

    Returns list of dicts {account_id, debit, credit}. Skips all-zero rows.
    Raises OpeningLineError on a non-leaf account or a row with both debit+credit.
    """
    account_ids = form.getlist('account_id')
    debits = form.getlist('debit')
    credits = form.getlist('credit')
    leaf_ids = opening_leaf_account_ids()

    rows = []
    for i, acc_raw in enumerate(account_ids):
        try:
            account_id = int(acc_raw)
        except (TypeError, ValueError):
            continue
        debit = _to_decimal(debits[i] if i < len(debits) else 0)
        credit = _to_decimal(credits[i] if i < len(credits) else 0)
        if debit == 0 and credit == 0:
            continue
        if debit != 0 and credit != 0:
            raise OpeningLineError('Each line must have a debit OR a credit, not both.')
        if account_id not in leaf_ids:
            raise OpeningLineError('Each line must use a valid, postable account.')
        rows.append({'account_id': account_id, 'debit': debit, 'credit': credit})
    return rows


def _build_lines(entry, rows):
    """Replace entry's lines with rows (delete + re-add), then recompute totals."""
    for line in entry.lines.all():
        db.session.delete(line)
    db.session.flush()
    for n, row in enumerate(rows, start=1):
        db.session.add(JournalEntryLine(
            entry_id=entry.id, line_number=n, account_id=row['account_id'],
            debit_amount=row['debit'], credit_amount=row['credit'],
        ))
    db.session.flush()
    entry.calculate_totals()


@opening_balances_bp.route('/opening-balances')
@login_required
def index():
    branch_id = _branch_id()
    entry = get_opening_entry(branch_id) if branch_id else None
    return render_template(
        'opening_balances/form.html',
        form=OpeningBalanceForm(),
        entry=entry,
        accounts=opening_account_choices(),
        locked=is_opening_locked(branch_id) if branch_id else False,
        can_edit=(current_user.role == 'accountant' or current_user.has_full_access),
        can_finalize=current_user.has_full_access,
    )


@opening_balances_bp.route('/opening-balances/save', methods=['POST'])
@login_required
@accountant_or_admin_required
def save_draft():
    branch_id = _branch_id()
    if is_opening_locked(branch_id):
        flash('Opening balances are locked and can no longer be edited.', 'error')
        return redirect(url_for('opening_balances.index'))

    form = OpeningBalanceForm()
    if not form.validate_on_submit():
        flash('A valid cutover date is required.', 'error')
        return redirect(url_for('opening_balances.index'))

    try:
        rows = _parse_lines(request.form)
    except OpeningLineError as exc:
        flash(str(exc), 'error')
        return redirect(url_for('opening_balances.index'))

    entry = get_opening_entry(branch_id)
    if entry is not None and entry.status != 'draft':
        # Save only edits drafts. A posted opening must be re-opened first, so we
        # never rebuild a 'posted' entry in place (which could push an unbalanced
        # entry into the trial balance). Mirrors the lifecycle: post -> reopen -> edit.
        flash('Re-open the posted opening balances before editing.', 'error')
        return redirect(url_for('opening_balances.index'))
    is_new = entry is None
    if is_new:
        entry = JournalEntry(
            entry_number=generate_jv_number(branch_id),
            entry_date=form.cutover_date.data,
            description='Opening Balances', reference='OPENING BALANCES',
            entry_type='opening_balance', status='draft', branch_id=branch_id,
            created_by_id=current_user.id,
        )
        db.session.add(entry)
        db.session.flush()
    else:
        old_values = model_to_dict(entry, AUDIT_FIELDS)
        entry.entry_date = form.cutover_date.data

    _build_lines(entry, rows)
    db.session.commit()

    identifier = f'{entry.entry_number} - Opening Balances'
    if is_new:
        log_create(module='opening_balances', record_id=entry.id,
                   record_identifier=identifier,
                   new_values=model_to_dict(entry, AUDIT_FIELDS))
    else:
        log_update(module='opening_balances', record_id=entry.id,
                   record_identifier=identifier, old_values=old_values,
                   new_values=model_to_dict(entry, AUDIT_FIELDS))
    flash('Opening balances draft saved.', 'success')
    return redirect(url_for('opening_balances.index'))


@opening_balances_bp.route('/opening-balances/post', methods=['POST'])
@login_required
@accountant_or_admin_required
def post_entry():
    branch_id = _branch_id()
    entry = get_opening_entry(branch_id)
    if entry is None or entry.status != 'draft':
        flash('No draft opening balances to post.', 'error')
        return redirect(url_for('opening_balances.index'))
    if is_opening_locked(branch_id):
        flash('Opening balances are locked and can no longer be edited.', 'error')
        return redirect(url_for('opening_balances.index'))
    if not validate_transaction_date_with_flash(entry.entry_date, 'opening balances'):
        return redirect(url_for('opening_balances.index'))

    entry.calculate_totals()
    if not entry.is_balanced or entry.total_debit <= 0:
        flash('Opening balances must be balanced (total debits = total credits) before posting.', 'error')
        return redirect(url_for('opening_balances.index'))

    entry.status = 'posted'
    entry.posted_by_id = current_user.id
    entry.posted_at = ph_now()
    db.session.commit()

    log_audit(module='opening_balances', action='post', record_id=entry.id,
              record_identifier=f'{entry.entry_number} - Opening Balances',
              notes=f'Posted opening balances ({entry.total_debit}).')
    flash('Opening balances posted.', 'success')
    return redirect(url_for('opening_balances.index'))


@opening_balances_bp.route('/opening-balances/reopen', methods=['POST'])
@login_required
@accountant_or_admin_required
def reopen():
    branch_id = _branch_id()
    if is_opening_locked(branch_id):
        flash('Opening balances are locked and can no longer be edited.', 'error')
        return redirect(url_for('opening_balances.index'))
    entry = get_opening_entry(branch_id)
    if entry is None or entry.status != 'posted':
        flash('No posted opening balances to re-open.', 'error')
        return redirect(url_for('opening_balances.index'))

    entry.status = 'draft'
    entry.posted_at = None
    entry.posted_by_id = None
    db.session.commit()
    log_audit(module='opening_balances', action='reopen', record_id=entry.id,
              record_identifier=f'{entry.entry_number} - Opening Balances',
              notes='Re-opened posted opening balances for editing.')
    flash('Opening balances re-opened for editing.', 'success')
    return redirect(url_for('opening_balances.index'))


@opening_balances_bp.route('/opening-balances/finalize', methods=['POST'])
@login_required
@full_access_required
def finalize():
    branch_id = _branch_id()
    entry = get_opening_entry(branch_id)
    if entry is None or entry.status != 'posted':
        flash('Post the opening balances before finalizing.', 'error')
        return redirect(url_for('opening_balances.index'))

    AppSettings.set_setting(LOCK_KEY(branch_id), '1', updated_by=current_user.username)
    log_audit(module='opening_balances', action='finalize', record_id=entry.id,
              record_identifier=f'{entry.entry_number} - Opening Balances',
              notes='Finalized opening balances (locked).')
    flash('Opening balances finalized and locked.', 'success')
    return redirect(url_for('opening_balances.index'))
