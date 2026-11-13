"""Reusable, testable data-migration helpers for the users domain."""
from app.users.models import User
from app.users.module_access import default_all_permissions


def backfill_book_permissions(session):
    """Grant all non-optional modules to every accountant/viewer whose permission
    set is empty. Idempotent (skips users that already have any permission) and
    leaves admin (ungated) and staff (already configured) untouched.

    Both accountants and viewers get every non-optional key via
    default_all_permissions().

    Returns the number of users updated."""
    from sqlalchemy.orm import load_only
    updated = 0
    # load_only: this runs inside migration 36517765f386, against the schema of ITS revision.
    # Selecting the whole model would ask for every column added to `users` since (e.g.
    # must_change_password, pwforce_0001) and fail on a database upgraded from empty.
    users = (session.query(User)
             .options(load_only(User.id, User.role, User.book_permissions))
             .filter(User.role.in_(('accountant', 'viewer'))).all())
    for u in users:
        if u.get_book_permissions():          # already has at least one → skip
            continue
        grant = default_all_permissions()
        u.set_book_permissions(grant)
        updated += 1
    return updated
