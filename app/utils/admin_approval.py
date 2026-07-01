"""Shared full-access-only gate + sole-reviewer auto-approval for tax maintenance
(VAT Categories, Sales VAT Categories, Withholding Tax). Replaces the older
accountant-centric rule for these three modules only (owner decision 2026-06-20).
Expanded to cover Chief Accountant (P-68, 2026-07-01).
"""
from functools import wraps
from flask import flash, redirect, url_for
from flask_login import current_user
from app.users.models import User


def admin_required(list_endpoint, noun):
    """Decorator factory: block non-full-access users (view + write) on tax maintenance."""
    def decorator(f):
        @wraps(f)
        def wrapped(*args, **kwargs):
            if not current_user.is_authenticated:
                return redirect(url_for('users.login'))
            if not current_user.has_full_access:
                flash(f'Only Administrators and Chief Accountants can access {noun}.', 'error')
                return redirect(url_for('dashboard.home'))
            return f(*args, **kwargs)
        return wrapped
    return decorator


def sole_full_access_user_can_auto_approve():
    """True iff the actor has full access AND exactly one active full-access user
    (admin or chief accountant) exists. A lone reviewer self-applies immediately;
    with >= 2 reviewers a different one must approve."""
    if not current_user.has_full_access:
        return False
    total = User.query.filter(
        User.role.in_(['admin', 'chief_accountant']), User.is_active == True).count()
    return total == 1


def another_active_reviewer_exists():
    """True if an active full-access reviewer (admin or CA) other than the current
    user exists. Blocks four-eyes self-approval while a lone reviewer can self-resolve."""
    return User.query.filter(
        User.role.in_(['admin', 'chief_accountant']), User.is_active == True,
        User.id != current_user.id).count() > 0
