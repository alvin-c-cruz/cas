"""
Journal Entry views for manual GL adjustments.
"""
from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_required, current_user
from functools import wraps
from app import db
from app.journal_entries.models import JournalEntry, JournalEntryLine
from app.journal_entries.forms import JournalEntryForm
from app.accounts.models import Account
from app.audit.utils import log_create, log_update, log_delete, model_to_dict, log_audit
from app.utils import ph_now
from datetime import datetime, date
from decimal import Decimal
import json

journal_entries_bp = Blueprint('journal_entries', __name__, template_folder='templates')


def accountant_or_admin_required(f):
    """Decorator to require accountant or admin role."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated:
            return redirect(url_for('users.login'))
        if current_user.role not in ['accountant', 'admin']:
            flash('Only Accountants and Administrators can manage journal entries.', 'error')
            return redirect(url_for('dashboard.index'))
        return f(*args, **kwargs)
    return decorated_function


def generate_entry_number():
    """Generate next journal entry number: JE-YYYY-####"""
    current_year = datetime.now().year
    prefix = f'JE-{current_year}-'

    latest_entry = JournalEntry.query.filter(
        JournalEntry.entry_number.like(f'{prefix}%')
    ).order_by(JournalEntry.entry_number.desc()).first()

    if latest_entry:
        try:
            last_num = int(latest_entry.entry_number.split('-')[-1])
            next_num = last_num + 1
        except (ValueError, IndexError):
            next_num = 1
    else:
        next_num = 1

    return f'{prefix}{next_num:04d}'


@journal_entries_bp.route('/journal-entries')
@login_required
def list_entries():
    """List all journal entries."""
    status_filter = request.args.get('status', 'all')
    type_filter = request.args.get('type', 'all')

    # Default to current year (January 1 to December 31)
    current_year = datetime.now().year
    default_date_from = f'{current_year}-01-01'
    default_date_to = f'{current_year}-12-31'

    date_from = request.args.get('date_from', default_date_from)
    date_to = request.args.get('date_to', default_date_to)

    query = JournalEntry.query

    if status_filter != 'all':
        query = query.filter_by(status=status_filter)

    if type_filter != 'all':
        query = query.filter_by(entry_type=type_filter)

    # Date filtering
    if date_from:
        try:
            from_date = datetime.strptime(date_from, '%Y-%m-%d').date()
            query = query.filter(JournalEntry.entry_date >= from_date)
        except ValueError:
            flash('Invalid date format for "From" date.', 'error')

    if date_to:
        try:
            to_date = datetime.strptime(date_to, '%Y-%m-%d').date()
            query = query.filter(JournalEntry.entry_date <= to_date)
        except ValueError:
            flash('Invalid date format for "To" date.', 'error')

    entries = query.order_by(JournalEntry.entry_date.desc()).all()

    return render_template('journal_entries/list.html',
                         entries=entries,
                         status_filter=status_filter,
                         type_filter=type_filter,
                         date_from=date_from,
                         date_to=date_to)


@journal_entries_bp.route('/journal-entries/create', methods=['GET', 'POST'])
@login_required
@accountant_or_admin_required
def create():
    """Create new journal entry."""
    form = JournalEntryForm()

    if form.validate_on_submit():
        try:
            # Get lines from form
            lines_data = request.form.getlist('lines')
            if not lines_data or not lines_data[0]:
                flash('Please add at least two journal entry lines (debit and credit).', 'error')
                return render_template('journal_entries/form.html', form=form, entry=None, accounts=Account.query.order_by(Account.code).all())

            lines = json.loads(lines_data[0])

            if len(lines) < 2:
                flash('Journal entry must have at least two lines.', 'error')
                return render_template('journal_entries/form.html', form=form, entry=None, accounts=Account.query.order_by(Account.code).all())

            # Calculate totals
            total_debit = Decimal('0.00')
            total_credit = Decimal('0.00')

            for line in lines:
                total_debit += Decimal(str(line.get('debit', 0)))
                total_credit += Decimal(str(line.get('credit', 0)))

            # Validate balance
            if total_debit != total_credit:
                flash(f'Entry is not balanced! Debits: ₱{total_debit:,.2f}, Credits: ₱{total_credit:,.2f}. Difference: ₱{abs(total_debit - total_credit):,.2f}', 'error')
                return render_template('journal_entries/form.html', form=form, entry=None, accounts=Account.query.order_by(Account.code).all())

            # Create journal entry
            entry = JournalEntry(
                entry_number=form.entry_number.data,
                entry_date=form.entry_date.data,
                description=form.description.data,
                reference=form.reference.data,
                entry_type=form.entry_type.data,
                is_reversing=form.is_reversing.data,
                reversal_date=form.reversal_date.data if form.is_reversing.data else None,
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
                    return render_template('journal_entries/form.html', form=form, entry=None, accounts=Account.query.order_by(Account.code).all())

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
            flash(f'Error creating journal entry: {str(e)}', 'error')

    if request.method == 'GET':
        form.entry_number.data = generate_entry_number()
        form.entry_date.data = date.today()

    accounts = Account.query.order_by(Account.code).all()
    # Convert accounts to dictionaries for JSON serialization
    accounts_data = [{'id': acc.id, 'code': acc.code, 'name': acc.name} for acc in accounts]
    return render_template('journal_entries/form.html', form=form, entry=None, accounts=accounts_data)


@journal_entries_bp.route('/journal-entries/<int:id>')
@login_required
def view(id):
    """View journal entry details."""
    entry = JournalEntry.query.get_or_404(id)
    return render_template('journal_entries/detail.html', entry=entry)


@journal_entries_bp.route('/journal-entries/<int:id>/post', methods=['POST'])
@login_required
@accountant_or_admin_required
def post(id):
    """Post journal entry (makes it final)."""
    entry = JournalEntry.query.get_or_404(id)

    if entry.status != 'draft':
        flash('Only draft journal entries can be posted.', 'error')
        return redirect(url_for('journal_entries.view', id=id))

    if not entry.is_balanced:
        flash('Cannot post unbalanced journal entry!', 'error')
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
        db.session.rollback()
        flash(f'Error posting journal entry: {str(e)}', 'error')

    return redirect(url_for('journal_entries.view', id=id))


@journal_entries_bp.route('/journal-entries/<int:id>/cancel', methods=['POST'])
@login_required
@accountant_or_admin_required
def cancel(id):
    """Cancel journal entry."""
    entry = JournalEntry.query.get_or_404(id)

    if entry.status == 'cancelled':
        flash('Journal entry is already cancelled.', 'error')
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
        db.session.rollback()
        flash(f'Error cancelling journal entry: {str(e)}', 'error')

    return redirect(url_for('journal_entries.view', id=id))


@journal_entries_bp.route('/journal-entries/<int:id>/delete', methods=['POST'])
@login_required
@accountant_or_admin_required
def delete(id):
    """Delete journal entry (only drafts can be deleted)."""
    entry = JournalEntry.query.get_or_404(id)

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
        db.session.rollback()
        flash(f'Error deleting journal entry: {str(e)}', 'error')

    return redirect(url_for('journal_entries.list_entries'))
