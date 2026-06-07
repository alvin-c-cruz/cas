"""
Period validation utilities for transaction date checking.

Prevents creating/editing transactions in closed periods.
"""
from datetime import date
from flask import flash
from app.periods.models import AccountingPeriod


def is_period_closed(transaction_date):
    """
    Check if the period for a given date is closed.

    Args:
        transaction_date: date - Transaction date to check

    Returns:
        bool - True if period is closed, False otherwise
    """
    if not transaction_date:
        return False

    year = transaction_date.year
    month = transaction_date.month

    return AccountingPeriod.is_period_closed(year, month)


def validate_transaction_date(transaction_date, transaction_type='transaction'):
    """
    Validate that a transaction date is not in a closed period.

    Args:
        transaction_date: date - Transaction date to validate
        transaction_type: str - Type of transaction (for error message)

    Returns:
        tuple - (is_valid: bool, error_message: str or None)
    """
    if not transaction_date:
        return False, "Transaction date is required."

    if is_period_closed(transaction_date):
        period_name = transaction_date.strftime('%B %Y')
        error_message = (
            f"Cannot create or edit {transaction_type} in {period_name}. "
            f"This accounting period has been closed."
        )
        return False, error_message

    return True, None


def validate_transaction_date_with_flash(transaction_date, transaction_type='transaction'):
    """
    Validate transaction date and show flash message if invalid.

    Args:
        transaction_date: date - Transaction date to validate
        transaction_type: str - Type of transaction (for error message)

    Returns:
        bool - True if valid, False if invalid (and flash message shown)
    """
    is_valid, error_message = validate_transaction_date(transaction_date, transaction_type)

    if not is_valid:
        flash(error_message, 'error')
        return False

    return True


def get_latest_open_period():
    """
    Get the most recent period that is still open.

    Returns:
        AccountingPeriod or None - Latest open period
    """
    from sqlalchemy import desc

    return AccountingPeriod.query.filter_by(
        status='open'
    ).order_by(
        desc(AccountingPeriod.year),
        desc(AccountingPeriod.month)
    ).first()


def get_earliest_closed_period():
    """
    Get the earliest period that has been closed.

    Returns:
        AccountingPeriod or None - Earliest closed period
    """
    from sqlalchemy import asc

    return AccountingPeriod.query.filter_by(
        status='closed'
    ).order_by(
        asc(AccountingPeriod.year),
        asc(AccountingPeriod.month)
    ).first()


def can_edit_transaction(transaction_date):
    """
    Check if a transaction with the given date can be edited.

    Args:
        transaction_date: date - Transaction date

    Returns:
        bool - True if can edit, False otherwise
    """
    return not is_period_closed(transaction_date)


def get_period_status_message(transaction_date):
    """
    Get a user-friendly message about the period status.

    Args:
        transaction_date: date - Transaction date

    Returns:
        str - Status message
    """
    if is_period_closed(transaction_date):
        period_name = transaction_date.strftime('%B %Y')
        return f"Period {period_name} is CLOSED. Editing is not allowed."
    else:
        period_name = transaction_date.strftime('%B %Y')
        return f"Period {period_name} is OPEN. Editing is allowed."
