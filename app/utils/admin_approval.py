"""Shared admin-only access + sole-admin auto-approval for tax maintenance
(VAT Categories, Sales VAT Categories, Withholding Tax). Replaces the older
accountant-centric rule for these three modules only (owner decision 2026-06-20).
"""
from functools import wraps
from flask import flash, redirect, url_for
from flask_login import current_user
from app.users.models import User


def admin_required(list_endpoint, noun):
    """Decorator factory: block non-admins (view + write) on tax maintenance."""
    def decorator(f):
        @wraps(f)
        def wrapped(*args, **kwargs):
            if not current_user.is_authenticated:
                return redirect(url_for('users.login'))
            if current_user.role != 'admin':
                flash(f'Only Administrators can access {noun}.', 'error')
                return redirect(url_for('dashboard.home'))
            return f(*args, **kwargs)
        return wrapped
    return decorator


def sole_admin_can_auto_approve():
    """True iff the actor is an admin AND exactly one active admin exists.
    A lone admin self-applies immediately; with >= 2 admins a different admin
    must approve (self-approval blocked at review time)."""
    if current_user.role != 'admin':
        return False
    total_admins = User.query.filter(User.role == 'admin', User.is_active == True).count()
    return total_admins == 1


def another_active_admin_exists():
    """True if an active admin other than the current user exists. Used to
    block self-approval (four-eyes) while letting a sole admin self-resolve a
    stray pending request without deadlock."""
    return User.query.filter(
        User.role == 'admin', User.is_active == True,
        User.id != current_user.id).count() > 0
