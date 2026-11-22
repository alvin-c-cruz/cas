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

THE SWITCHER, 22 Nov 2026 (BRANCH-SWITCH B)
-------------------------------------------
Relying on the guard alone had one bad case: switching branch FROM a document page.
The switcher redirected back to the document, the guard switched the session back
to the document's branch, and the user read "You are now working in: EXTRA" while
the sidebar and the session said CORP. Owner, 22 Nov 2026: "What I want to happen
here is that the user will be redirected to the other Branch's Disbursement page",
then "all 15 modules". So the switcher now has its own rule after all:
list_url_for_document_page() sends a switch made from a document page to that
module's list in the new branch. Following a link to another branch's document is
unchanged -- the guard still switches to the document's branch.

The rule applies whenever a branch was already selected, not only when the new one
differs: a page left open while the branch was switched in another tab still shows
the old branch's document. The sign-in branch picker is not the switcher (no branch
is selected yet) and still takes the user to the page they asked for.

BRANCH-SWITCH-2 (owner, 22 Nov 2026: "A") puts five more modules under the same
rule: petty cash, production runs, bank accounts, manufacturing departments and
work centers (SESSION_SCOPED_LIST_ENDPOINTS). They never used the guard; their
record pages are "not found" in any other branch, which is where the switcher used
to send the user back to.
"""
from urllib.parse import urlsplit

from flask import abort, current_app, request, session, url_for
from flask_login import current_user
from werkzeug.exceptions import HTTPException
from werkzeug.routing import BuildError

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

#: The two guarded blueprints with a debit and a credit list. Their endpoints are
#: named '<kind>_<action>' (credit_view, debit_print ...), so a page's own endpoint
#: names its list: '<kind>_list'.
MEMO_BLUEPRINTS = ('purchase_memos', 'sales_memos')

#: blueprint name -> list route, for the modules that do NOT call require_same_branch.
#: Each loads its record as "this id in the session's branch, else 404"
#: (`.filter_by(id=id, branch_id=session.get('selected_branch_id')).first_or_404()`),
#: so a branch switch that returned to one of their record pages met "not found" --
#: the owner's 22 Sep complaint, never fixed for these five. BRANCH-SWITCH-2 (owner,
#: 22 Nov 2026: "A") gives them the switcher's rule too. Kept apart from
#: BRANCH_LIST_ENDPOINTS because tests/unit/test_branch_scope_registry.py ties that
#: table to the callers of require_same_branch; this one is tied to the lookup above
#: by tests/integration/test_branch_switch_from_document.py. Petty cash has one list,
#: its funds; vouchers and replenishments land there.
SESSION_SCOPED_LIST_ENDPOINTS = {
    'bank_accounts': 'bank_accounts.list_accounts',
    'manufacturing_departments': 'manufacturing_departments.list',
    'petty_cash': 'petty_cash.fund_list',
    'production_runs': 'production_runs.list',
    'work_centers': 'work_centers.list',
}


def list_url_for_document_page(next_url):
    """The list a branch switch should land on when it was made from a document page
    of a branch-bound module, or None when `next_url` is any other page
    (BRANCH-SWITCH B, and BRANCH-SWITCH-2 for the five session-scoped modules).

    A document page is a GET route of such a blueprint that takes URL arguments: it
    is about ONE record, whatever the argument is called -- view, edit, print, a
    payslip of a run, an SO revision, a requisition's amendment request (`req_id`),
    a new voucher under one petty cash fund (`fund_id`). Lists, create pages and the
    dashboard take none. The list endpoint comes from BRANCH_LIST_ENDPOINTS or
    SESSION_SCOPED_LIST_ENDPOINTS, or for the memo blueprints from the page's own
    endpoint name."""
    try:
        endpoint, args = current_app.url_map.bind('').match(urlsplit(next_url).path, method='GET')
    except HTTPException:          # no such page, wrong method, or a routing redirect
        return None
    if not args:
        return None
    blueprint, _, name = endpoint.partition('.')
    list_endpoint = BRANCH_LIST_ENDPOINTS.get(blueprint) or SESSION_SCOPED_LIST_ENDPOINTS.get(blueprint)
    if list_endpoint:
        return url_for(list_endpoint)
    if blueprint in MEMO_BLUEPRINTS:
        try:
            return url_for(f'{blueprint}.{name.split("_")[0]}_list')
        except BuildError:
            return None
    return None


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
