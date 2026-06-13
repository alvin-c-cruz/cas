from app.branches.models import Branch


def get_accessible_branches(user):
    """Return active branches accessible to the given user.

    Admins and accountants access all active branches.
    Staff and viewers access only their assigned branches.
    """
    active = Branch.query.filter_by(is_active=True).order_by(Branch.name).all()
    if user.role in ('admin', 'accountant'):
        return active
    assigned_ids = {b.id for b in user.branches.all()}
    return [b for b in active if b.id in assigned_ids]
