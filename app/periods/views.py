"""
Period management views for closing and reopening accounting periods.

Only administrators can close/reopen periods.
"""
from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_required, current_user
from functools import wraps
from datetime import date, datetime
from sqlalchemy import desc, asc

from app import db
from app.periods.models import AccountingPeriod
from app.journal_entries.models import JournalEntry
from app.reports.financial import generate_trial_balance
from app.audit.utils import log_create, log_update


periods_bp = Blueprint('periods', __name__, template_folder='templates')


def admin_required(f):
    """Decorator to require admin role for period management."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated:
            return redirect(url_for('users.login'))
        if current_user.role != 'admin':
            flash('Only Administrators can manage accounting periods.', 'error')
            return redirect(url_for('dashboard.index'))
        return f(*args, **kwargs)
    return decorated_function


@periods_bp.route('/periods')
@login_required
@admin_required
def list_periods():
    """List all accounting periods with their status"""
    # Get all periods ordered by year, month descending
    periods = AccountingPeriod.query.order_by(
        desc(AccountingPeriod.year),
        desc(AccountingPeriod.month)
    ).all()

    # Get current period (this month)
    today = date.today()
    current_period = AccountingPeriod.get_or_create_period(today.year, today.month)

    return render_template('periods/list.html',
                         periods=periods,
                         current_period=current_period,
                         today=today)


@periods_bp.route('/periods/<int:year>/<int:month>')
@login_required
@admin_required
def view_period(year, month):
    """View details of a specific accounting period"""
    period = AccountingPeriod.get_or_create_period(year, month)

    # Get statistics for this period
    period_start = date(year, month, 1)
    if month == 12:
        period_end = date(year + 1, 1, 1)
    else:
        period_end = date(year, month + 1, 1)

    # Count journal entries in this period
    entry_count = JournalEntry.query.filter(
        JournalEntry.entry_date >= period_start,
        JournalEntry.entry_date < period_end
    ).count()

    # Count posted entries
    posted_count = JournalEntry.query.filter(
        JournalEntry.entry_date >= period_start,
        JournalEntry.entry_date < period_end,
        JournalEntry.status == 'posted'
    ).count()

    # Count draft entries
    draft_count = JournalEntry.query.filter(
        JournalEntry.entry_date >= period_start,
        JournalEntry.entry_date < period_end,
        JournalEntry.status == 'draft'
    ).count()

    # Check if trial balance is balanced (for this period end)
    last_day_of_month = period_end - datetime.timedelta(days=1)
    trial_balance = generate_trial_balance(last_day_of_month.date() if hasattr(last_day_of_month, 'date') else last_day_of_month)
    is_balanced = trial_balance['is_balanced']

    return render_template('periods/view.html',
                         period=period,
                         entry_count=entry_count,
                         posted_count=posted_count,
                         draft_count=draft_count,
                         is_balanced=is_balanced,
                         can_close=(draft_count == 0 and is_balanced))


@periods_bp.route('/periods/<int:year>/<int:month>/close', methods=['GET', 'POST'])
@login_required
@admin_required
def close_period(year, month):
    """Close an accounting period after validation"""
    period = AccountingPeriod.get_or_create_period(year, month)

    if period.status == 'closed':
        flash(f'Period {period.get_period_name()} is already closed.', 'info')
        return redirect(url_for('periods.view_period', year=year, month=month))

    if request.method == 'POST':
        # Get notes from form
        notes = request.form.get('notes', '').strip()

        # Perform pre-close validation
        period_start = date(year, month, 1)
        if month == 12:
            period_end = date(year + 1, 1, 1)
        else:
            period_end = date(year, month + 1, 1)

        # Check for draft entries
        draft_count = JournalEntry.query.filter(
            JournalEntry.entry_date >= period_start,
            JournalEntry.entry_date < period_end,
            JournalEntry.status == 'draft'
        ).count()

        if draft_count > 0:
            flash(f'Cannot close period: {draft_count} draft journal entries must be posted or deleted first.', 'error')
            return redirect(url_for('periods.view_period', year=year, month=month))

        # Check trial balance
        from datetime import timedelta
        last_day_of_month = period_end - timedelta(days=1)
        trial_balance = generate_trial_balance(last_day_of_month)

        if not trial_balance['is_balanced']:
            flash(f'Cannot close period: Trial Balance is not balanced (difference: ₱{trial_balance["difference"]:,.2f}).', 'error')
            return redirect(url_for('periods.view_period', year=year, month=month))

        # Close the period
        success = period.close_period(current_user, notes)

        if success:
            # Log the closing
            log_create(
                module='accounting_period',
                record_id=period.id,
                record_identifier=f'{period.get_period_name()} - CLOSED',
                new_values={
                    'year': year,
                    'month': month,
                    'status': 'closed',
                    'closed_by': current_user.username,
                    'notes': notes
                }
            )

            flash(f'Period {period.get_period_name()} has been closed successfully.', 'success')
            return redirect(url_for('periods.list_periods'))
        else:
            flash('Error closing period.', 'error')

    # GET request - show confirmation page
    return render_template('periods/close.html', period=period)


@periods_bp.route('/periods/<int:year>/<int:month>/reopen', methods=['POST'])
@login_required
@admin_required
def reopen_period(year, month):
    """Reopen a closed accounting period"""
    period = AccountingPeriod.get_or_create_period(year, month)

    if period.status == 'open':
        flash(f'Period {period.get_period_name()} is already open.', 'info')
        return redirect(url_for('periods.view_period', year=year, month=month))

    # Reopen the period
    success = period.reopen_period()

    if success:
        # Log the reopening
        log_update(
            module='accounting_period',
            record_id=period.id,
            record_identifier=f'{period.get_period_name()} - REOPENED',
            old_values={'status': 'closed'},
            new_values={'status': 'open', 'reopened_by': current_user.username}
        )

        flash(f'Period {period.get_period_name()} has been reopened. Transactions can now be edited.', 'success')
    else:
        flash('Error reopening period.', 'error')

    return redirect(url_for('periods.list_periods'))
