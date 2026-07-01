"""Reusable, testable data-migration helpers for the users domain."""
from app.users.models import User
from app.users.module_access import default_all_permissions, all_permission_keys


def backfill_book_permissions(session):
    """Grant all non-optional modules to every accountant/viewer whose permission
    set is empty. Idempotent (skips users that already have any permission) and
    leaves admin (ungated) and staff (already configured) untouched.

    Accountants get every non-optional key via default_all_permissions().
    Viewers get every key EXCEPT print_layouts: print_layouts is an
    EDIT-capability key (P-69 spec grants it only as a staff-delegation
    permission), and viewers are read-only and denied at the
    preprinted_forms._edit_required gate regardless of any grant — so
    including it in the viewer backfill would be inert and misleading.
    Viewers keep every other (module-visibility) key so fresh-run viewers
    don't lose page access.

    Returns the number of users updated."""
    updated = 0
    users = session.query(User).filter(User.role.in_(('accountant', 'viewer'))).all()
    for u in users:
        if u.get_book_permissions():          # already has at least one → skip
            continue
        if u.role == 'viewer':
            grant = {k: True for k in all_permission_keys() if k != 'print_layouts'}
        else:
            grant = default_all_permissions()
        u.set_book_permissions(grant)
        updated += 1
    return updated
