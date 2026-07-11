"""Branch + permission-subset boundaries for accountant Staff Management.

Every boundary is a pure-ish function over the accountant and the target user so
it can be unit-tested in isolation. Server-side intersection is the real
enforcement — the posted form is never trusted."""
from flask import abort
from app.users.models import User
from app.branches.models import Branch
from app.users.utils import get_accessible_branches
from app.users.module_access import all_permission_keys


def accountant_permission_keys(accountant):
    """Module keys the approver may grant (their ceiling).

    A full-access approver (admin or chief_accountant) has the entire grid as
    their ceiling regardless of stored keys -- they typically store none, relying
    on the has_full_access short-circuit, so reading raw stored keys would give
    an empty ceiling and let them grant nothing. A plain accountant's ceiling is
    exactly the keys they hold."""
    if accountant.has_full_access:
        return set(all_permission_keys())
    perms = accountant.get_book_permissions()
    return {k for k in all_permission_keys() if perms.get(k)}


def _accountant_branch_ids(accountant):
    return {b.id for b in get_accessible_branches(accountant)}


def manageable_users(accountant):
    """Staff/viewers sharing >=1 branch with the accountant (never accountants/admins)."""
    own = _accountant_branch_ids(accountant)
    if not own:
        return []
    candidates = User.query.filter(User.role.in_(('staff', 'viewer'))).all()
    return [u for u in candidates if own.intersection(u.get_branch_ids())]


def is_in_scope(accountant, target):
    if target.role not in ('staff', 'viewer'):
        return False
    return bool(_accountant_branch_ids(accountant).intersection(target.get_branch_ids()))


def assert_in_scope(accountant, target):
    if not is_in_scope(accountant, target):
        abort(403)


def merge_branches(accountant, target, submitted_ids):
    """(submitted ∩ own) ∪ (target_existing − own). Returns Branch objects."""
    own = _accountant_branch_ids(accountant)
    submitted = {int(i) for i in submitted_ids} if submitted_ids else set()
    existing = set(target.get_branch_ids())
    final_ids = (submitted & own) | (existing - own)
    if not final_ids:
        return []
    return Branch.query.filter(Branch.id.in_(final_ids)).all()


def merge_permissions(accountant, target, submitted_keys):
    """(submitted ∩ own) ∪ (target_existing − own). Returns a full bool dict of
    every granted key."""
    own = accountant_permission_keys(accountant)
    submitted = set(submitted_keys or [])
    existing = {k for k in all_permission_keys() if target.get_book_permissions().get(k)}
    granted = (submitted & own) | (existing - own)
    return {k: (k in granted) for k in all_permission_keys()}
