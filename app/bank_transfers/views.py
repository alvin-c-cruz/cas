"""Lifecycle routes for Bank Transfers (R-04 slice 2).

Role/branch idiom mirrors app/cash_disbursements/views.py's post()/cancel(): staff+ may
create/edit a draft, accountant+ (role=='accountant' or has_full_access) may run the
money-moving transitions -- but each transition ALSO requires the actor to be at the
specific branch the transition belongs to (from_branch_id for post/initiate/cancel,
to_branch_id for confirm/reject), checked via get_accessible_branches(). Every
transition claims the RowVersioned lock (claim_version) as its FIRST write, per
app/utils/concurrency.py's documented contract.
"""
from functools import wraps

from flask import Blueprint, render_template, redirect, url_for, flash, request, session, abort, current_app
from flask_login import login_required, current_user

from app import db
from app.audit.utils import log_create, log_update, model_to_dict
from app.errors.utils import log_exception
from app.bank_accounts.models import BankAccount
from app.bank_transfers.forms import BankTransferForm
from app.bank_transfers.models import BankTransfer
from app.bank_transfers.numbering import generate_bank_transfer_number
from app.bank_transfers.posting import (post_intra_branch_transfer, post_transfer_initiate,
                                        post_transfer_confirm, post_transfer_reversal)
from app.users.utils import get_accessible_branches
from app.utils.concurrency import claim_version, conflict_message, submitted_version

bank_transfers_bp = Blueprint('bank_transfers', __name__, template_folder='templates')

# Fields tracked in the audit log across every transition.
_FIELDS = ['transfer_number', 'from_bank_account_id', 'to_bank_account_id',
          'from_branch_id', 'to_branch_id', 'is_inter_branch', 'amount',
          'transfer_date', 'memo', 'status']


def staff_or_above_required(f):
    """Tier 1 ops (create/edit a draft) -- staff, accountant, admin, chief accountant."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated:
            return redirect(url_for('users.login'))
        if current_user.role not in ['staff', 'accountant', 'admin', 'chief_accountant']:
            flash('You do not have permission to perform this action.', 'error')
            return redirect(url_for('dashboard.index'))
        return f(*args, **kwargs)
    return decorated_function


def _is_accountant_or_above():
    return current_user.role == 'accountant' or current_user.has_full_access


def _branch_accessible(branch_id):
    if current_user.has_full_access:
        return True
    return any(b.id == branch_id for b in get_accessible_branches(current_user))


def _require_accountant_at(branch_id):
    """accountant+ role AND that user must be able to access the given branch."""
    return _is_accountant_or_above() and _branch_accessible(branch_id)


def _bank_account_choices():
    accounts = (BankAccount.query.filter_by(is_active=True)
                .order_by(BankAccount.code).all())
    return [(a.id, f'{a.code} — {a.name} ({a.branch.name})') for a in accounts]


def _bank_account_branch_meta():
    """{account_id: {branch_id, branch_name}} for the create/edit form's inline
    JS -- drives the live "this is an inter-branch transfer" note without a
    page reload (the two accounts' branches are compared client-side)."""
    accounts = BankAccount.query.filter_by(is_active=True).all()
    return {a.id: {'branch_id': a.branch_id, 'branch_name': a.branch.name} for a in accounts}


def _render_form(form, transfer):
    return render_template('bank_transfers/form.html', form=form, transfer=transfer,
                           bank_accounts_meta=_bank_account_branch_meta())


def _validate_transfer_inputs(form):
    """Shared create/edit validation. Returns an error message, or None if OK.
    On success, also returns the resolved (from_ba, to_ba) BankAccount pair."""
    from_ba = db.session.get(BankAccount, form.from_bank_account_id.data)
    to_ba = db.session.get(BankAccount, form.to_bank_account_id.data)
    if not from_ba or not to_ba:
        return 'Selected bank account not found.', None, None
    if from_ba.id == to_ba.id:
        return 'From and To accounts must be different.', None, None
    if not from_ba.is_active or not to_ba.is_active:
        return 'Both accounts must be Active.', None, None
    if form.amount.data is None or form.amount.data <= 0:
        return 'Amount must be greater than zero.', None, None
    return None, from_ba, to_ba


def _transfer_visible(bt):
    """Branch-scoped both ways -- the selected branch may be either leg."""
    if current_user.has_full_access:
        return True
    branch_id = session.get('selected_branch_id')
    return branch_id in (bt.from_branch_id, bt.to_branch_id)


@bank_transfers_bp.route('/bank-transfers/')
@login_required
def list_transfers():
    branch_id = session.get('selected_branch_id')
    transfers = (BankTransfer.query
                .filter(db.or_(BankTransfer.from_branch_id == branch_id,
                               BankTransfer.to_branch_id == branch_id))
                .order_by(BankTransfer.transfer_date.desc(), BankTransfer.id.desc())
                .all())
    return render_template('bank_transfers/list.html', transfers=transfers)


@bank_transfers_bp.route('/bank-transfers/new', methods=['GET', 'POST'])
@login_required
@staff_or_above_required
def new_transfer():
    form = BankTransferForm()
    choices = _bank_account_choices()
    form.from_bank_account_id.choices = choices
    form.to_bank_account_id.choices = choices

    if form.validate_on_submit():
        error, from_ba, to_ba = _validate_transfer_inputs(form)
        if error:
            flash(error, 'error')
            return _render_form(form, None)

        bt = BankTransfer(
            transfer_number=generate_bank_transfer_number(),
            from_bank_account_id=from_ba.id,
            to_bank_account_id=to_ba.id,
            from_branch_id=from_ba.branch_id,
            to_branch_id=to_ba.branch_id,
            is_inter_branch=(from_ba.branch_id != to_ba.branch_id),
            amount=form.amount.data,
            transfer_date=form.transfer_date.data,
            memo=(form.memo.data or None),
            status='draft',
            created_by_id=current_user.id,
        )
        db.session.add(bt)
        db.session.commit()
        log_create('bank_transfers', bt.id, bt.transfer_number, model_to_dict(bt, _FIELDS))
        flash(f'Bank Transfer "{bt.transfer_number}" saved as draft.', 'success')
        return redirect(url_for('bank_transfers.view_transfer', id=bt.id))

    return _render_form(form, None)


@bank_transfers_bp.route('/bank-transfers/<int:id>/edit', methods=['GET', 'POST'])
@login_required
@staff_or_above_required
def edit_transfer(id):
    bt = db.get_or_404(BankTransfer, id)
    if bt.status != 'draft':
        flash('Only draft transfers can be edited.', 'error')
        return redirect(url_for('bank_transfers.view_transfer', id=id))

    form = BankTransferForm(obj=bt)
    choices = _bank_account_choices()
    form.from_bank_account_id.choices = choices
    form.to_bank_account_id.choices = choices

    if request.method == 'GET':
        form.from_bank_account_id.data = bt.from_bank_account_id
        form.to_bank_account_id.data = bt.to_bank_account_id

    if form.validate_on_submit():
        error, from_ba, to_ba = _validate_transfer_inputs(form)
        if error:
            flash(error, 'error')
            return _render_form(form, bt)

        # Lost-update guard -- first write of the request.
        if not claim_version(BankTransfer, bt.id, submitted_version()):
            db.session.rollback()
            flash(conflict_message('bank_transfers', bt.id), 'error')
            return _render_form(form, bt)

        old_values = model_to_dict(bt, _FIELDS)
        bt.from_bank_account_id = from_ba.id
        bt.to_bank_account_id = to_ba.id
        bt.from_branch_id = from_ba.branch_id
        bt.to_branch_id = to_ba.branch_id
        bt.is_inter_branch = (from_ba.branch_id != to_ba.branch_id)
        bt.amount = form.amount.data
        bt.transfer_date = form.transfer_date.data
        bt.memo = (form.memo.data or None)
        db.session.commit()
        log_update('bank_transfers', bt.id, bt.transfer_number, old_values, model_to_dict(bt, _FIELDS))
        flash(f'Bank Transfer "{bt.transfer_number}" updated.', 'success')
        return redirect(url_for('bank_transfers.view_transfer', id=bt.id))

    return _render_form(form, bt)


def _je_section(title, je_id):
    """No `sender_je`/`receiver_je`/`reversal_je` relationship exists on BankTransfer
    (Task 1's model only carries the plain *_je_id FK columns) -- fetched directly
    here rather than adding one, since a models.py change is out of this task's
    scope and needs its own sign-off."""
    if je_id is None:
        return None
    from app.journal_entries.models import JournalEntry
    je = db.session.get(JournalEntry, je_id)
    if je is None:
        return None
    return {
        'title': title,
        'entries': [{'code': line.account.code if line.account else '—',
                    'name': line.account.name if line.account else '—',
                    'debit': line.debit_amount, 'credit': line.credit_amount}
                   for line in je.lines.all()],
    }


def _actor_name(user_id):
    if user_id is None:
        return None
    from app.users.models import User
    u = db.session.get(User, user_id)
    return u.full_name if u else None


@bank_transfers_bp.route('/bank-transfers/<int:id>')
@login_required
def view_transfer(id):
    bt = db.get_or_404(BankTransfer, id)
    if not _transfer_visible(bt):
        abort(404)

    je_sections = [s for s in (
        _je_section('Sender Leg', bt.sender_je_id),
        _je_section('Receiver Leg', bt.receiver_je_id),
        _je_section('Reversal', bt.reversal_je_id),
    ) if s]

    actions = dict(
        can_edit=(bt.status == 'draft'
                 and current_user.role in ['staff', 'accountant', 'admin', 'chief_accountant']),
        can_post=(bt.status == 'draft' and not bt.is_inter_branch
                 and _require_accountant_at(bt.from_branch_id)),
        can_initiate=(bt.status == 'draft' and bt.is_inter_branch
                     and _require_accountant_at(bt.from_branch_id)),
        can_confirm=(bt.status == 'in_transit' and _require_accountant_at(bt.to_branch_id)),
        can_reject=(bt.status == 'in_transit' and _require_accountant_at(bt.to_branch_id)),
        can_cancel=(bt.status == 'in_transit' and _require_accountant_at(bt.from_branch_id)),
    )

    return render_template('bank_transfers/detail.html', transfer=bt,
                           je_sections=je_sections,
                           initiated_by_name=_actor_name(bt.initiated_by_id),
                           confirmed_by_name=_actor_name(bt.confirmed_by_id),
                           rejected_by_name=_actor_name(bt.rejected_by_id),
                           cancelled_by_name=_actor_name(bt.cancelled_by_id),
                           **actions)


@bank_transfers_bp.route('/bank-transfers/<int:id>/post', methods=['POST'])
@login_required
def post_transfer(id):
    """Intra-branch only -- an inter-branch draft must use Initiate instead."""
    bt = db.get_or_404(BankTransfer, id)
    if not _require_accountant_at(bt.from_branch_id):
        flash('Only Accountants and Administrators at the sending branch can post this transfer.', 'error')
        return redirect(url_for('bank_transfers.view_transfer', id=id))
    if bt.status != 'draft':
        flash('Only draft transfers can be posted.', 'error')
        return redirect(url_for('bank_transfers.view_transfer', id=id))
    if bt.is_inter_branch:
        flash('This is an inter-branch transfer — use Initiate instead of Post.', 'error')
        return redirect(url_for('bank_transfers.view_transfer', id=id))

    if not claim_version(BankTransfer, bt.id, submitted_version()):
        db.session.rollback()
        flash(conflict_message('bank_transfers', bt.id), 'error')
        return redirect(url_for('bank_transfers.view_transfer', id=id))

    try:
        old_values = model_to_dict(bt, _FIELDS)
        post_intra_branch_transfer(bt, current_user)
        db.session.commit()
        log_update('bank_transfers', bt.id, bt.transfer_number, old_values, model_to_dict(bt, _FIELDS))
        flash(f'Bank Transfer "{bt.transfer_number}" posted.', 'success')
    except ValueError as e:
        db.session.rollback()
        flash(str(e), 'error')
    except Exception as e:
        db.session.rollback()
        current_app.logger.error('Error posting bank transfer', exc_info=True)
        log_exception(e, severity='ERROR', module='bank_transfers.post_transfer')
        flash('An unexpected error occurred while posting the transfer. Please try '
              'again; if it persists, contact your administrator.', 'error')
    return redirect(url_for('bank_transfers.view_transfer', id=id))


@bank_transfers_bp.route('/bank-transfers/<int:id>/initiate', methods=['POST'])
@login_required
def initiate_transfer(id):
    bt = db.get_or_404(BankTransfer, id)
    if not _require_accountant_at(bt.from_branch_id):
        flash('Only Accountants and Administrators at the sending branch can initiate this transfer.', 'error')
        return redirect(url_for('bank_transfers.view_transfer', id=id))
    if bt.status != 'draft':
        flash('Only draft transfers can be initiated.', 'error')
        return redirect(url_for('bank_transfers.view_transfer', id=id))
    if not bt.is_inter_branch:
        flash('This is an intra-branch transfer — use Post instead of Initiate.', 'error')
        return redirect(url_for('bank_transfers.view_transfer', id=id))

    if not claim_version(BankTransfer, bt.id, submitted_version()):
        db.session.rollback()
        flash(conflict_message('bank_transfers', bt.id), 'error')
        return redirect(url_for('bank_transfers.view_transfer', id=id))

    try:
        old_values = model_to_dict(bt, _FIELDS)
        post_transfer_initiate(bt, current_user)
        db.session.commit()
        log_update('bank_transfers', bt.id, bt.transfer_number, old_values, model_to_dict(bt, _FIELDS))
        flash(f'Bank Transfer "{bt.transfer_number}" initiated — awaiting confirmation at '
              f'{bt.to_bank_account.branch.name}.', 'success')
    except ValueError as e:
        db.session.rollback()
        flash(str(e), 'error')
    except Exception as e:
        db.session.rollback()
        current_app.logger.error('Error initiating bank transfer', exc_info=True)
        log_exception(e, severity='ERROR', module='bank_transfers.initiate_transfer')
        flash('An unexpected error occurred while initiating the transfer. Please try '
              'again; if it persists, contact your administrator.', 'error')
    return redirect(url_for('bank_transfers.view_transfer', id=id))


@bank_transfers_bp.route('/bank-transfers/<int:id>/confirm', methods=['POST'])
@login_required
def confirm_transfer(id):
    bt = db.get_or_404(BankTransfer, id)
    if not _require_accountant_at(bt.to_branch_id):
        flash('Only Accountants and Administrators at the receiving branch can confirm this transfer.', 'error')
        return redirect(url_for('bank_transfers.view_transfer', id=id))
    if bt.status != 'in_transit':
        flash('Only in-transit transfers can be confirmed.', 'error')
        return redirect(url_for('bank_transfers.view_transfer', id=id))

    if not claim_version(BankTransfer, bt.id, submitted_version()):
        db.session.rollback()
        flash(conflict_message('bank_transfers', bt.id), 'error')
        return redirect(url_for('bank_transfers.view_transfer', id=id))

    try:
        old_values = model_to_dict(bt, _FIELDS)
        post_transfer_confirm(bt, current_user)
        db.session.commit()
        # Clears itself: Task 5's action-item source query excludes non-in_transit
        # transfers, so no extra call is needed here.
        log_update('bank_transfers', bt.id, bt.transfer_number, old_values, model_to_dict(bt, _FIELDS))
        flash(f'Bank Transfer "{bt.transfer_number}" confirmed and completed.', 'success')
    except ValueError as e:
        db.session.rollback()
        flash(str(e), 'error')
    except Exception as e:
        db.session.rollback()
        current_app.logger.error('Error confirming bank transfer', exc_info=True)
        log_exception(e, severity='ERROR', module='bank_transfers.confirm_transfer')
        flash('An unexpected error occurred while confirming the transfer. Please try '
              'again; if it persists, contact your administrator.', 'error')
    return redirect(url_for('bank_transfers.view_transfer', id=id))


@bank_transfers_bp.route('/bank-transfers/<int:id>/reject', methods=['POST'])
@login_required
def reject_transfer(id):
    bt = db.get_or_404(BankTransfer, id)
    if not _require_accountant_at(bt.to_branch_id):
        flash('Only Accountants and Administrators at the receiving branch can reject this transfer.', 'error')
        return redirect(url_for('bank_transfers.view_transfer', id=id))
    if bt.status != 'in_transit':
        flash('Only in-transit transfers can be rejected.', 'error')
        return redirect(url_for('bank_transfers.view_transfer', id=id))

    if not claim_version(BankTransfer, bt.id, submitted_version()):
        db.session.rollback()
        flash(conflict_message('bank_transfers', bt.id), 'error')
        return redirect(url_for('bank_transfers.view_transfer', id=id))

    try:
        old_values = model_to_dict(bt, _FIELDS)
        post_transfer_reversal(bt, current_user, 'rejected')
        db.session.commit()
        log_update('bank_transfers', bt.id, bt.transfer_number, old_values, model_to_dict(bt, _FIELDS))
        flash(f'Bank Transfer "{bt.transfer_number}" rejected. Reversal JE created.', 'success')
    except ValueError as e:
        db.session.rollback()
        flash(str(e), 'error')
    except Exception as e:
        db.session.rollback()
        current_app.logger.error('Error rejecting bank transfer', exc_info=True)
        log_exception(e, severity='ERROR', module='bank_transfers.reject_transfer')
        flash('An unexpected error occurred while rejecting the transfer. Please try '
              'again; if it persists, contact your administrator.', 'error')
    return redirect(url_for('bank_transfers.view_transfer', id=id))


@bank_transfers_bp.route('/bank-transfers/<int:id>/cancel', methods=['POST'])
@login_required
def cancel_transfer(id):
    bt = db.get_or_404(BankTransfer, id)
    if not _require_accountant_at(bt.from_branch_id):
        flash('Only Accountants and Administrators at the sending branch can cancel this transfer.', 'error')
        return redirect(url_for('bank_transfers.view_transfer', id=id))
    if bt.status != 'in_transit':
        flash('Only in-transit transfers can be cancelled.', 'error')
        return redirect(url_for('bank_transfers.view_transfer', id=id))

    if not claim_version(BankTransfer, bt.id, submitted_version()):
        db.session.rollback()
        flash(conflict_message('bank_transfers', bt.id), 'error')
        return redirect(url_for('bank_transfers.view_transfer', id=id))

    try:
        old_values = model_to_dict(bt, _FIELDS)
        post_transfer_reversal(bt, current_user, 'cancelled')
        db.session.commit()
        log_update('bank_transfers', bt.id, bt.transfer_number, old_values, model_to_dict(bt, _FIELDS))
        flash(f'Bank Transfer "{bt.transfer_number}" cancelled. Reversal JE created.', 'success')
    except ValueError as e:
        db.session.rollback()
        flash(str(e), 'error')
    except Exception as e:
        db.session.rollback()
        current_app.logger.error('Error cancelling bank transfer', exc_info=True)
        log_exception(e, severity='ERROR', module='bank_transfers.cancel_transfer')
        flash('An unexpected error occurred while cancelling the transfer. Please try '
              'again; if it persists, contact your administrator.', 'error')
    return redirect(url_for('bank_transfers.view_transfer', id=id))
