"""One payee rule for the vouchers that can pay a vendor OR an employee.

The AP Voucher became polymorphic on 2026-07-08 (payee_type/payee_id, vendor_id
nullable). The Cash Disbursement Voucher followed on 2026-09-24. These helpers
were the APV's private ones and moved here unchanged so both documents apply
the SAME rule -- in particular the employee branch rule:

    an employee from any branch the user can REACH (set membership over
    get_accessible_branches), never equality with the selected branch. A user
    assigned two branches must still pay an employee in the one not selected.
    BUG-AP-EMPLOYEE-PAYEE-PICKER-NOT-BRANCH-FILTERED.

Two layers, both required: employee_payee_query() filters what the picker
OFFERS; resolve_payee() refuses a hand-posted id the picker never showed -- an
employee in an unreachable branch, or an INACTIVE vendor or employee -- by
returning None so the caller's existing "Selected payee not found." path runs
without confirming that the record exists in some other branch.

Vendors are deliberately NOT scoped: they carry no branch_id and are
company-wide, exactly like customers.
"""
from flask_login import current_user

from app import db


def parse_payee(raw):
    """'vendor:12' | 'employee:3' -> (payee_type, payee_id) or (None, None)."""
    try:
        kind, sid = (raw or '').split(':', 1)
        if kind in ('vendor', 'employee'):
            return kind, int(sid)
    except (ValueError, AttributeError):
        pass
    return None, None


def accessible_branch_ids():
    """Branches this user may act in. Full-access users get every active branch."""
    from app.users.utils import get_accessible_branches
    return {b.id for b in get_accessible_branches(current_user)}


def employee_payee_query():
    """Active employees this user may name as a payee, ordered by employee number."""
    from app.employees.models import Employee
    return (Employee.query
            .filter(Employee.is_active.is_(True),
                    Employee.branch_id.in_(accessible_branch_ids()))
            .order_by(Employee.employee_no))


def resolve_payee(payee_type, payee_id):
    """The Vendor/Employee row for the payee, or None (unknown, inactive, or an
    employee in an unreachable branch). The picker offers active payees only, so
    an inactive one can only arrive hand-posted -- refuse it the same way."""
    if not payee_id:
        return None
    row = None
    if payee_type == 'employee':
        from app.employees.models import Employee
        row = db.session.get(Employee, payee_id)
        if row is not None and row.branch_id not in accessible_branch_ids():
            return None
    elif payee_type == 'vendor':
        from app.vendors.models import Vendor
        row = db.session.get(Vendor, payee_id)
    if row is not None and not getattr(row, 'is_active', True):
        return None
    return row
