from app.branches.models import Branch


def get_accessible_branches(user):
    """Return active branches accessible to the given user.

    Only admins access all active branches.
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
