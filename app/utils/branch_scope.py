"""Branch scoping for document routes: say "wrong branch", don't just 404.

Every document route already refuses a record belonging to a branch other than the
one selected in the session. It did so with a bare `abort(404)`, which is correct
about ACCESS and useless about CAUSE: the document is right there, the user simply
has another branch selected, and the page says only "not found".

Owner report 2026-09-22. The path they hit is the ordinary one: the sidebar branch
switcher posts `request.full_path` as its return address (base.html), so switching
branch while viewing a document sends you straight back to that document -- which
now belongs to the other branch. Switch branch, get a 404, with nothing saying why.
This module fixes that case too, and deliberately WITHOUT a second mechanism in the
switcher: the switcher's redirect lands on the document route, and the guard below
is what that route runs.

THE RULE
--------
Wrong branch, and the user CAN reach that branch -> SWITCH the session to that
branch and let the page load. Wrong branch, and the user CANNOT reach that branch
-> the bare 404 stays.

The first cut (2026-09-22) named the branch and redirected to the module's list.
Owner, 2026-09-24, on meeting that notice: "remove this notification." They want
the record, not an instruction to go and get it, so the guard now does the switch
itself. It is a REAL switch -- the sidebar shows the new branch from then on and
it is audited exactly as the sidebar switcher's is -- not a one-page peek, so the
user is never silently reading one branch while the session says another.

The split is still the point. Switching into a branch confirms the record exists
there, so it happens only for users who can already reach that branch. Nobody
learns about a branch they have no access to. Do not "simplify" this by dropping
the accessibility test.

A JSON request keeps the 404 as well: an XHR is a background call from a page the
user is already on, and switching their whole session underneath that page would
be a surprise, not a convenience.
"""
from flask import abort, request, session
from flask_login import current_user

#: blueprint name -> the module's collection route. Kept from the redirect era:
#: `list_endpoint` is still accepted by require_same_branch for the two memo
#: blueprints, and `tests/unit/test_branch_scope_registry.py` still asserts every
#: guarded blueprint has an entry here or passes one, so nothing rots quietly if a
#: redirect is ever wanted again.
#:
#: Blueprints with more than ONE collection route are deliberately absent --
#: purchase_memos and sales_memos each serve a debit list and a credit list, and
#: only the caller knows which. They pass `list_endpoint` explicitly.
BRANCH_LIST_ENDPOINTS = {
    'accounts_payable': 'accounts_payable.list_ap',
    'cash_disbursements': 'cash_disbursements.list_cdvs',
    'cash_receipts': 'cash_receipts.list_crvs',
    'delivery_receipts': 'delivery_receipts.list',
    'journal_entries': 'journal_entries.list_entries',
    'payroll': 'payroll.register',
    'purchase_orders': 'purchase_orders.list_po',
    'purchase_requests': 'purchase_requests.list_pr',
    'quotations': 'quotations.list',
    'receiving_reports': 'receiving_reports.list_rr',
    'sales_invoices': 'sales_invoices.list_invoices',
    'sales_orders': 'sales_orders.list',
    'work_orders': 'work_orders.list',
}

#: Where to send someone whose blueprint has no entry and passed none. Never a
#: dead end, and never a leak -- the dashboard is branch-agnostic.
FALLBACK_ENDPOINT = 'dashboard.index'


def _wants_json():
    """True when the caller is an XHR/fetch expecting data rather than a page."""
    if request.is_json:
        return True
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return True
    accept = request.accept_mimetypes
    return accept['application/json'] > accept['text/html']


def _reachable_branch(branch_id):
    """The Branch object when the current user may select it, else None.

    Reuses get_accessible_branches -- the SAME list the branch switcher offers --
    so what the message admits to can never exceed what the switcher already shows.
    """
    if branch_id is None or not getattr(current_user, 'is_authenticated', False):
        return None
    from app.users.utils import get_accessible_branches
    for branch in get_accessible_branches(current_user):
        if branch.id == branch_id:
            return branch
    return None


def require_same_branch(obj, list_endpoint=None):
    """Guard a document route. Returns normally -- switching the session's branch
    to the record's when the user may reach it -- or raises a 404.

    Replaces the two-line `if obj.branch_id != session.get(...): abort(404)` that
    every document route carried. Call it straight after the record is loaded:

        so = db.get_or_404(SalesOrder, id)
        require_same_branch(so)

    `list_endpoint` is accepted for the two memo blueprints whose debit and credit
    lists share one blueprint; it is unused now that the guard switches instead of
    redirecting, and kept so the call sites and the registry test stay as they are.

    The switch is written to the session and audited as `branch_selected`, the
    same record the sidebar switcher writes, so the audit trail shows every branch
    change however it happened.
    """
    if obj is None:
        return
    target = getattr(obj, 'branch_id', None)
    if target == session.get('selected_branch_id'):
        return

    branch = _reachable_branch(target)
    if branch is None or _wants_json():
        abort(404)

    session['selected_branch_id'] = branch.id
    from app.audit.utils import log_audit
    log_audit(module='auth', action='branch_selected', record_id=current_user.id,
              record_identifier=current_user.username,
              notes=f'Selected branch: {branch.name} (ID: {branch.id}) -- switched '
                    f'by opening {request.path}')
