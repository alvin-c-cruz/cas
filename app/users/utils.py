from app.branches.models import Branch


# Display labels for the five user roles. Single source of truth for the role
# pill/label, replacing the if/elif blocks that were copy-pasted across the
# user/branch/staff templates (BUG-USERLIST-CA-ROLE-BADGE).
ROLE_LABELS = {
    'admin': 'Administrator',
    'chief_accountant': 'Chief Accountant',
    'accountant': 'Accountant',
    'staff': 'Staff',
    'viewer': 'Viewer',
}


def role_label(role):
    """Humanized display label for a user role. Unknown roles fall back to a
    title-cased version of the raw key; empty/None -> ''."""
    return ROLE_LABELS.get(role) or (role or '').replace('_', ' ').title()


def get_accessible_branches(user):
    """Return active branches accessible to the given user.

    Admins and Chief Accountants access all active branches.
    Accountants, staff, and viewers access only their assigned branches.
    """
    active = Branch.query.filter_by(is_active=True).order_by(Branch.name).all()
    if user.has_full_access:
        return active
    assigned_ids = {b.id for b in user.branches.all()}
    return [b for b in active if b.id in assigned_ids]


def backfill_accountant_branches():
    """Backfill accountants who have zero branch assignments with all active branches.

    Idempotent: skips accountants who already have at least one assignment.
    Returns the number of rows inserted.
    """
    from sqlalchemy import text
    from app import db
    sql = text("""
        INSERT INTO user_branches (user_id, branch_id)
        SELECT u.id, b.id FROM users u CROSS JOIN branches b
        WHERE u.role = 'accountant' AND b.is_active = 1
          AND NOT EXISTS (
              SELECT 1 FROM user_branches ub
              WHERE ub.user_id = u.id
          )
    """)
    result = db.session.execute(sql)
    db.session.commit()
    return result.rowcount


def accountant_self_approval_enabled():
    """True when the company allows accountants to self-approve registration emails
    (staff/viewer only). Reads the AppSettings policy flag; default off."""
    from app.settings import AppSettings
    return AppSettings.get_setting('accountant_email_self_approval', '0') == '1'


# ── First-run admin bootstrap ────────────────────────────────────────────────
# The reserved username whose first registration on an admin-less DB becomes the
# system administrator. Exact, case-sensitive match (no normalization).
FIRST_RUN_ADMIN_USERNAME = 'admin'


def system_has_admin():
    """True once at least one ACTIVE admin account exists.

    Single source of truth for the one-time first-run admin bootstrap: the
    whitelist bypass and the admin grant both gate on ``not system_has_admin()``,
    so the bypass closes the instant this becomes True.
    """
    from app import db
    from app.users.models import User
    return db.session.query(User.id).filter_by(role='admin', is_active=True).first() is not None
