"""
Journal Entry views for manual GL adjustments.
"""
from flask import Blueprint, render_template, redirect, url_for, flash, request, session, abort, jsonify
from flask_login import login_required, current_user
from functools import wraps
from app import db
from app.journal_entries.models import JournalEntry, JournalEntryLine
from app.journal_entries.forms import JournalEntryForm
from app.accounts.models import Account
from app.audit.utils import log_create, log_update, log_delete, model_to_dict, log_audit
from app.utils import ph_now
from app.periods.utils import validate_transaction_date_with_flash
from app.journal_entries.utils import generate_entry_number, generate_jv_number
from app.settings import AppSettings
from app.journal_entries.preprinted_layout import get_layout, save_layout
from datetime import datetime, date
from decimal import Decimal
import json

journal_entries_bp = Blueprint('journal_entries', __name__, template_folder='templates')


def _accounts_for_select():
    """Active accounts for the JV line-item picker, each with a derived `is_group`
    flag (top-level or has children => non-postable group header, shown disabled).
    Mirrors the AP picker so the JV account select behaves like the other vouchers.
    """
    all_accts = Account.query.filter_by(is_active=True).order_by(Account.code).all()
    parent_ids = {a.parent_id for a in all_accts if a.parent_id is not None}
    return [{'id': a.id, 'code': a.code, 'name': a.name,
             'is_group': a.id in parent_ids} for a in all_accts]


def accountant_or_admin_required(f):
    """Decorator to require accountant or admin role."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated:
            return redirect(url_for('users.login'))
        if not (current_user.role == 'accountant' or current_user.has_full_access):
            flash('Only Accountants and Administrators can manage journal entries.', 'error')
            return redirect(url_for('dashboard.index'))
        return f(*args, **kwargs)
    return decorated_function


def _get_entry_or_404(id):
    """Fetch a journal entry scoped to the selected branch.

    Mirrors _get_invoice_or_404 / _get_ap_or_404: a voucher in another branch is a
    404, so ids cannot be walked across branches. No admin bypass -- a full-access
    user reaches another branch by switching the session branch.
    """
    entry = db.get_or_404(JournalEntry, id)
    if entry.branch_id != session.get('selected_branch_id'):
        abort(404)
    return entry


@journal_entries_bp.route('/journal-entries')
@login_required
def list_entries():
    """Redirect to the Journal Voucher view (journals redesign)."""
    return redirect(url_for('journals.voucher'))


@journal_entries_bp.route('/journal-entries/create', methods=['GET', 'POST'])
@login_required
@accountant_or_admin_required
def create():
    """Create new journal entry."""
    form = JournalEntryForm()

    if form.validate_on_submit():
        # Validate that the entry date is not in a closed period
        if not validate_transaction_date_with_flash(form.entry_date.data, 'journal entry'):
            return render_template('journal_entries/form.html', form=form, entry=None, accounts=_accounts_for_select())

        try:
            # Get lines from form
            lines_data = request.form.getlist('lines')
            if not lines_data or not lines_data[0]:
                flash('Please add at least two journal entry lines (debit and credit).', 'error')
                return render_template('journal_entries/form.html', form=form, entry=None, accounts=_accounts_for_select())

            lines = json.loads(lines_data[0])

            if len(lines) < 2:
                flash('Journal entry must have at least two lines.', 'error')
                return render_template('journal_entries/form.html', form=form, entry=None, accounts=_accounts_for_select())

            # Calculate totals
            total_debit = Decimal('0.00')
            total_credit = Decimal('0.00')

            for line in lines:
                total_debit += Decimal(str(line.get('debit', 0)))
                total_credit += Decimal(str(line.get('credit', 0)))

            # Validate balance
            if total_debit != total_credit:
                flash(f'Entry is not balanced! Debits: ₱{total_debit:,.2f}, Credits: ₱{total_credit:,.2f}. Difference: ₱{abs(total_debit - total_credit):,.2f}', 'error')
                return render_template('journal_entries/form.html', form=form, entry=None, accounts=_accounts_for_select())

            # Get current branch from session
            from flask import session
            current_branch_id = session.get('selected_branch_id')
            if not current_branch_id:
                flash('Please select a branch before creating journal entries.', 'error')
                return redirect(url_for('users.select_branch', next=request.url))

            # Create journal entry
            entry = JournalEntry(
                entry_number=form.entry_number.data,
                entry_date=form.entry_date.data,
                description=form.description.data,
                reference=form.reference.data,
                entry_type=form.entry_type.data,
                is_reversing=form.is_reversing.data,
                reversal_date=form.reversal_date.data if form.is_reversing.data else None,
                branch_id=current_branch_id,
                status='draft',
                created_by_id=current_user.id
            )

            # Add lines
            for idx, line_data in enumerate(lines, start=1):
                account_id = int(line_data.get('account_id'))
                debit = Decimal(str(line_data.get('debit', 0)))
                credit = Decimal(str(line_data.get('credit', 0)))

                # Validation: both debit and credit cannot be non-zero
                if debit > 0 and credit > 0:
                    flash(f'Line {idx}: Cannot have both debit and credit amounts.', 'error')
                    return render_template('journal_entries/form.html', form=form, entry=None, accounts=_accounts_for_select())

                # At least one must be non-zero
                if debit == 0 and credit == 0:
                    continue  # Skip empty lines

                line = JournalEntryLine(
                    line_number=idx,
                    account_id=account_id,
                    description=line_data.get('description', ''),
                    debit_amount=debit,
                    credit_amount=credit
                )
                entry.lines.append(line)

            # Calculate totals and check balance
            entry.calculate_totals()

            db.session.add(entry)
            db.session.commit()

            log_create(
                module='journal_entry',
                record_id=entry.id,
                record_identifier=f'{entry.entry_number} - {entry.description}',
                new_values=model_to_dict(entry, ['entry_number', 'entry_date', 'description', 'total_debit', 'total_credit', 'is_balanced', 'status'])
            )

            flash(f'Journal Entry "{entry.entry_number}" created successfully! {"✓ Balanced" if entry.is_balanced else "⚠ UNBALANCED"}', 'success' if entry.is_balanced else 'warning')
            return redirect(url_for('journal_entries.view', id=entry.id))

        except Exception as e:
            from flask import current_app
            from app.errors.utils import log_exception
            current_app.logger.error(f"Error creating journal entry", exc_info=True)
            log_exception(e, severity='ERROR', module='journal_entries.create')
            db.session.rollback()
            flash('An error occurred while creating the journal entry. Please try again.', 'error')

    if request.method == 'GET':
        # Get current branch from session for entry number generation
        from flask import session
        current_branch_id = session.get('selected_branch_id')

        # If no branch selected, try to get user's first assigned branch
        if not current_branch_id and current_user.branches.count() > 0:
            first_branch = current_user.branches.first()
            current_branch_id = first_branch.id
            session['selected_branch_id'] = current_branch_id

        if not current_branch_id:
            flash('Please select a branch before creating journal entries.', 'error')
            return redirect(url_for('users.select_branch', next=request.url))

        form.entry_number.data = generate_jv_number(current_branch_id)
        form.entry_date.data = date.today()

    return render_template('journal_entries/form.html', form=form, entry=None, accounts=_accounts_for_select())


@journal_entries_bp.route('/journal-entries/<int:id>')
@login_required
def view(id):
    """View journal entry details."""
    entry = _get_entry_or_404(id)
    return render_template('journal_entries/detail.html', entry=entry)


@journal_entries_bp.route('/journal-entries/<int:id>/print')
@login_required
def print_entry(id):
    """Print preview for a journal entry; layout chosen by the jv_print_form setting."""
    entry = _get_entry_or_404(id)
    form_mode = AppSettings.get_setting('jv_print_form', 'current')

    if form_mode == 'hidden':
        flash('Printing is disabled for Journal Vouchers.', 'error')
        return redirect(url_for('journal_entries.view', id=entry.id))

    if form_mode == 'preprinted':
        from app.journal_entries.preprinted_layout import (
            FIELD_LABELS, COLUMN_LABELS, PAPER_SIZES, PAPER_LABELS,
            DATE_FORMATS, FONT_GROUPS, TEXT_KEYS)
        date_labels = {'long': 'Long (25 December 2026)', 'medium': 'Medium (Dec 25, 2026)',
                       'us': 'US (12/25/2026)', 'eu': 'EU (25/12/2026)', 'iso': 'ISO (2026-12-25)'}
        return render_template(
            'journal_entries/print_preprinted.html',
            entry=entry,
            lines=entry.lines.order_by(JournalEntryLine.line_number).all(),
            layout=get_layout(entry.branch_id),
            can_edit_layout=current_user.has_full_access,
            field_labels=FIELD_LABELS, column_labels=COLUMN_LABELS,
            paper_sizes=PAPER_SIZES, paper_labels=PAPER_LABELS,
            date_formats=DATE_FORMATS, date_labels=date_labels,
            font_groups=FONT_GROUPS, signatory_ids=set(TEXT_KEYS),
        )

    company = {
        'name': AppSettings.get_setting('company_name', ''),
        'address': AppSettings.get_setting('company_address', ''),
        'tin': AppSettings.get_setting('company_tin', ''),
    }
    return render_template('journal_entries/print.html', entry=entry,
                           company=company, printed_at=ph_now())


@journal_entries_bp.route('/journal-entries/print-layout', methods=['POST'])
@login_required
def save_jv_print_layout():
    """Persist the JV pre-printed layout JSON (full-access only)."""
    if not current_user.has_full_access:
        abort(403)
    data = request.get_json(silent=True) or {}
    clean = save_layout(data, current_user.username, session.get('selected_branch_id'))
    return jsonify(ok=True, layout=clean)


@journal_entries_bp.route('/journal-entries/<int:id>/post', methods=['POST'])
@login_required
@accountant_or_admin_required
def post(id):
    """Post journal entry (makes it final)."""
    entry = _get_entry_or_404(id)

    if entry.status != 'draft':
        flash('Only draft journal entries can be posted.', 'error')
        return redirect(url_for('journal_entries.view', id=id))

    if not entry.is_balanced:
        flash('Cannot post unbalanced journal entry!', 'error')
        return redirect(url_for('journal_entries.view', id=id))

    # Re-validate the period at post, like create does -- a draft dated before a close
    # must not be posted into the closed period after the fact.
    if not validate_transaction_date_with_flash(entry.entry_date, 'journal entry'):
        return redirect(url_for('journal_entries.view', id=id))

    try:
        entry.status = 'posted'
        entry.posted_by_id = current_user.id
        entry.posted_at = ph_now()
        db.session.commit()

        log_audit(
            module='journal_entry',
            action='post',
            record_id=entry.id,
            record_identifier=f'{entry.entry_number} - {entry.description}',
            notes=f'Journal entry posted by {current_user.username}'
        )

        flash(f'Journal Entry "{entry.entry_number}" posted successfully!', 'success')
    except Exception as e:
        from flask import current_app
        from app.errors.utils import log_exception
        current_app.logger.error(f"Error posting journal entry", exc_info=True)
        log_exception(e, severity='ERROR', module='journal_entries.post')
        db.session.rollback()
        flash('An error occurred while posting the journal entry. Please try again.', 'error')

    return redirect(url_for('journal_entries.view', id=id))


@journal_entries_bp.route('/journal-entries/<int:id>/cancel', methods=['POST'])
@login_required
@accountant_or_admin_required
def cancel(id):
    """Cancel journal entry."""
    entry = _get_entry_or_404(id)

    if entry.status == 'cancelled':
        flash('Journal entry is already cancelled.', 'error')
        return redirect(url_for('journal_entries.view', id=id))

    # `create` guards its date; `cancel` never did. Cancelling is the ONLY in-app
    # mutation a posted voucher has -- there is no journal-entry edit route -- so
    # without this an accountant could soft-void a historical entry in a period the
    # books were already closed on. Matters most for replayed legacy books.
    if not validate_transaction_date_with_flash(entry.entry_date, 'journal entry'):
        return redirect(url_for('journal_entries.view', id=id))

    try:
        entry.status = 'cancelled'
        entry.cancelled_at = ph_now()
        db.session.commit()

        log_audit(
            module='journal_entry',
            action='cancel',
            record_id=entry.id,
            record_identifier=f'{entry.entry_number} - {entry.description}',
            notes=f'Journal entry cancelled by {current_user.username}'
        )

        flash(f'Journal Entry "{entry.entry_number}" cancelled.', 'warning')
    except Exception as e:
        from flask import current_app
        from app.errors.utils import log_exception
        current_app.logger.error(f"Error cancelling journal entry", exc_info=True)
        log_exception(e, severity='ERROR', module='journal_entries.cancel')
        db.session.rollback()
        flash('An error occurred while cancelling the journal entry. Please try again.', 'error')

    return redirect(url_for('journal_entries.view', id=id))


@journal_entries_bp.route('/journal-entries/<int:id>/delete', methods=['POST'])
@login_required
@accountant_or_admin_required
def delete(id):
    """Delete journal entry (only drafts can be deleted)."""
    entry = _get_entry_or_404(id)

    if entry.status != 'draft':
        flash('Only draft journal entries can be deleted.', 'error')
        return redirect(url_for('journal_entries.view', id=id))

    try:
        old_values = model_to_dict(entry, ['entry_number', 'entry_date', 'description', 'total_debit', 'total_credit', 'status'])
        entry_number = entry.entry_number

        db.session.delete(entry)
        db.session.commit()

        log_delete(
            module='journal_entry',
            record_id=id,
            record_identifier=f'{entry_number}',
            old_values=old_values
        )

        flash(f'Journal Entry "{entry_number}" deleted successfully!', 'success')
    except Exception as e:
        from flask import current_app
        from app.errors.utils import log_exception
        current_app.logger.error(f"Error deleting journal entry", exc_info=True)
        log_exception(e, severity='ERROR', module='journal_entries.delete')
        db.session.rollback()
        flash('An error occurred while deleting the journal entry. Please try again.', 'error')

    return redirect(url_for('journal_entries.list_entries'))
