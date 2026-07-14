"""Canonical authorization decorators for the two role boundaries (SI-P-72).

The Chief Accountant (CA) role is defined as "admin minus the Admin panel":

    admin_panel_required  -> is_admin only. The five system-administration areas
        the CA is excluded from: company settings, user CRUD, branches,
        backup/restore, error logs.

    full_access_required  -> has_full_access (admin OR chief_accountant). The
        accounting-oversight surfaces the CA shares with admin: periods,
        tax maintenance, audit-log view, approved-email management.

Both predicates live on the User model (``User.is_admin`` / ``User.has_full_access``);
these decorators are the single enforcement point so per-blueprint copies do not
drift. The role-level helpers back the approved-email escalation ceiling.
"""
from functools import wraps

from flask import flash, redirect, url_for
from flask_login import current_user


def admin_panel_required(f):
    """Restrict to the system administrator (``is_admin``).

    The Chief Accountant is intentionally excluded from these Admin-panel areas.
    """
    @wraps(f)
    def wrapped(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_admin:
            flash('Only administrators can access this area. You need administrator privileges.', 'error')
            return redirect(url_for('dashboard.index'))
        return f(*args, **kwargs)
    return wrapped


def full_access_required(f):
    """Restrict to full-access users (``has_full_access`` = admin OR Chief Accountant)."""
    @wraps(f)
    def wrapped(*args, **kwargs):
        if not current_user.is_authenticated:
            return redirect(url_for('users.login'))
        if not current_user.has_full_access:
            flash('Only administrators and Chief Accountants can access this area.', 'error')
            return redirect(url_for('dashboard.index'))
        return f(*args, **kwargs)
    return wrapped


# --- Role level ceiling (approved-email escalation guard) --------------------
# Ordered privilege ladder. 'admin' is the top rung but is NEVER an assignable
# self-registration position (see assignable_positions); it appears here only so
# the approve-time ceiling can compare against it defensively.
ROLE_LEVEL = {
    'viewer': 1,
    'staff': 2,
    'accountant': 3,
    'chief_accountant': 4,
    'admin': 5,
}


def role_level(role):
    """Numeric privilege level for a role name (unknown -> 0)."""
    return ROLE_LEVEL.get(role, 0)


def assignable_positions(approver):
    """Positions *approver* may grant on an approved-email row.

    A full-access approver (admin or CA) may grant up to chief_accountant; an
    accountant may grant up to accountant. 'admin' is never assignable to anyone
    (self-registration never mints an admin). This is the level ceiling: no one
    may grant a role above their own.
    """
    base = ['viewer', 'staff', 'accountant']
    if approver.has_full_access:
        base = base + ['chief_accountant']
    return base
