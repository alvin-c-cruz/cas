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
Wrong branch, and the user CAN reach that branch -> name the branch and send them
to the module's own list, where the document they want is one branch-switch away.
Wrong branch, and the user CANNOT reach that branch -> the bare 404 stays.

That split is the point. A message naming the branch is friendlier but it confirms
the record exists, so it is shown only to users who can already see that branch
exists. Nobody learns about a branch they have no access to. Do not "simplify" this
by dropping the accessibility test.

A JSON request keeps the 404 as well: an XHR expecting data cannot do anything
sensible with a 302 to an HTML list, and would silently parse the redirect target.
"""
from flask import abort, flash, redirect, request, session, url_for
from flask_login import current_user

#: blueprint name -> the module's collection route. The destination for a
#: wrong-branch redirect, chosen over the dashboard because it keeps the user in
#: the module they were working in.
#:
#: Blueprints with more than ONE collection route are deliberately absent --
#: purchase_memos and sales_memos each serve a debit list and a credit list, and
#: only the caller knows which. They pass `list_endpoint` explicitly.
#:
#: `tests/unit/test_branch_scope_registry.py` asserts every blueprint that guards a
#: branch has a usable entry here or passes one, so this table cannot rot quietly.
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
    """Guard a document route. Returns normally, or raises the right refusal.

    Replaces the two-line `if obj.branch_id != session.get(...): abort(404)` that
    every document route carried. Call it straight after the record is loaded:

        so = db.get_or_404(SalesOrder, id)
        require_same_branch(so)

    `list_endpoint` overrides BRANCH_LIST_ENDPOINTS, for the two memo blueprints
    whose debit and credit lists share one blueprint.

    Raises rather than returning a response so the call site stays one line --
    `abort()` accepts a Response, and a 302 raised this way behaves exactly like
    the `abort(404)` it replaces.
    """
    if obj is None:
        return
    if getattr(obj, 'branch_id', None) == session.get('selected_branch_id'):
        return

    branch = _reachable_branch(getattr(obj, 'branch_id', None))
    if branch is None or _wants_json():
        abort(404)

    endpoint = (list_endpoint
                or BRANCH_LIST_ENDPOINTS.get(request.blueprint)
                or FALLBACK_ENDPOINT)
    flash('That record belongs to the %s branch, which is not the one you have '
          'selected. Switch to %s to open it.' % (branch.name, branch.name),
          'warning')
    abort(redirect(url_for(endpoint)))
