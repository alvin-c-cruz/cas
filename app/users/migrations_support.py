"""Reusable, testable data-migration helpers for the users domain."""
from app.users.models import User
from app.users.module_access import default_all_permissions


def backfill_book_permissions(session):
    """Grant all non-optional modules to every accountant/viewer whose permission
    set is empty. Idempotent (skips users that already have any permission) and
    leaves admin (ungated) and staff (already configured) untouched.

    Returns the number of users updated."""
    updated = 0
    users = session.query(User).filter(User.role.in_(('accountant', 'viewer'))).all()
    for u in users:
        if u.get_book_permissions():          # already has at least one → skip
            continue
        u.set_book_permissions(default_all_permissions())
        updated += 1
    return updated
