"""Aggregation of a user's Action Items.

Two kinds of items:
  * Drafts — unfinished transaction documents (Accounts Payable, Cash
    Disbursement, Cash Receipt, Sales Invoice) with status 'draft'. Staff see
    only their own drafts; admin/accountant see all drafts in the current
    branch.
  * For Approval — pending master-data change requests (Chart of Accounts, VAT
    Categories, Withholding Tax). Admin/accountant only.

Viewers get nothing (the route is blocked and the sidebar link is hidden).
"""
import json

from app.accounts.approval_models import AccountChangeRequest
from app.vat_categories.models import VATCategoryChangeRequest
from app.sales_vat_categories.models import SalesVATCategoryChangeRequest
from app.withholding_tax.models import WithholdingTaxChangeRequest
from app.users.approved_emails import ApprovedEmail
from app.opening_balances.approval_models import OpeningBalanceChangeRequest
from app.permission_requests.models import PermissionChangeRequest


def _draft_sources():
    """(label, icon, Model, document-number attr, edit-url template, module key).

    The module key is None for a CORE module -- one every instance has, which is
    why the original four needed no gate at all. An OPTIONAL module must name its
    key: `purchase_requests` ships default_enabled=False and per_user=True, so
    without a gate Action Items would report requisitions from a module the
    instance never enabled, or that this user cannot open, and link to an edit
    route the module guard then refuses. Action Items must never be a side
    channel around a gate the rest of the app enforces.
    """
    from app.accounts_payable.models import AccountsPayable
    from app.cash_disbursements.models import CashDisbursementVoucher
    from app.cash_receipts.models import CashReceiptVoucher
    from app.purchase_orders.models import PurchaseOrder
    from app.purchase_requests.models import PurchaseRequest
    from app.receiving_reports.models import ReceivingReport
    from app.sales_invoices.models import SalesInvoice
    return [
        # Ordered along the Procure-to-Pay chain, as MODULE_REGISTRY is.
        ('Purchase Requisition', '📝', PurchaseRequest, 'pr_number', '/purchase-requests/{id}/edit', 'purchase_requests'),
        # purchase_orders is optional + per_user, like purchase_requests, so it
        # MUST name its module key -- otherwise Action Items would surface orders
        # from a module the instance never enabled, or that this user cannot
        # open, and link to an edit route the module guard then refuses.
        ('Purchase Order', '🛒', PurchaseOrder, 'po_number', '/purchase-orders/{id}/edit', 'purchase_orders'),
        # receiving_reports is optional + per_user like the two above it, so it
        # names its key for the same reason.
        ('Receiving Report', '📦', ReceivingReport, 'rr_number', '/receiving-reports/{id}/edit', 'receiving_reports'),
        ('Accounts Payable', '🧾', AccountsPayable, 'ap_number', '/accounts-payable/{id}/edit', None),
        ('Cash Disbursement', '💸', CashDisbursementVoucher, 'cdv_number', '/cash-disbursements/{id}/edit', None),
        ('Cash Receipt', '💰', CashReceiptVoucher, 'crv_number', '/cash-receipts/{id}/edit', None),
        ('Sales Invoice', '📄', SalesInvoice, 'invoice_number', '/sales-invoices/{id}/edit', None),
    ]


def _visible_draft_sources(user):
    """Draft sources this user may actually see, optional modules gated.

    can_access_module(), NOT module_enabled(): the former checks the instance
    package gate AND the per-user book permission (admins bypass the latter),
    which is the same pair every guarded route applies.
    """
    from app.users.module_access import can_access_module
    return [src for src in _draft_sources()
            if src[5] is None or can_access_module(user, src[5])]


def _user_display(user_id):
    """Full name for a user id, or an em dash."""
    if not user_id:
        return '—'
    from app import db
    from app.users.models import User
    user = db.session.get(User, user_id)
    return user.full_name if user else '—'


def _creator_name(doc):
    """Who to chase about this draft.

    Four of the five source models declare a `created_by` relationship;
    PurchaseRequest declares only the `created_by_id` COLUMN, which is why its
    own detail view resolves the user by hand. Without this fallback a PR row
    renders 'by —' while every sibling row names someone, and the column stops
    meaning anything. Adding the missing relationship to the model is the
    tidier fix, but that is a models.py change and needs sign-off.
    """
    creator = getattr(doc, 'created_by', None)
    if creator is not None:
        return creator.full_name
    return _user_display(getattr(doc, 'created_by_id', None))


def _draft_query(Model, user, branch_id):
    """This user's OWN unfinished drafts, in this branch.

    Own-only for EVERY role since 2026-09-23, not just staff. Action Items is a
    worklist -- every row is something the reader can act on now (owner decision) --
    and somebody else's half-typed requisition is not the reader's next action, it
    is supervision. An accountant or admin previously saw the whole branch's drafts
    here, which is what made the page read as noise to them.

    Losing that overview is deliberate and was the owner's call. If it is wanted
    back it belongs in a list or report, not on a worklist.
    """
    return (Model.query
            .filter_by(status='draft', branch_id=branch_id)
            .filter_by(created_by_id=user.id))


# Model name -> attachments registry document_type, for draft-stage required-file
# annotation. Only the five documents with required slots appear here; other draft
# sources (CRV, SI) are absent and get the plain draft description.
_DRAFT_ATTACHMENT_DOCTYPE = {
    'PurchaseRequest': 'purchase_requests',
    'PurchaseOrder': 'purchase_orders',
    'ReceivingReport': 'receiving_reports',
    'AccountsPayable': 'accounts_payable',
    'CashDisbursementVoucher': 'cash_disbursements',
}


def gather_draft_items(user, branch_id):
    """Draft documents the user should finish. Empty for viewers or when no
    branch is selected. A draft that still lacks a required attachment names it
    in-line (one row, no duplicate with the submitted-only missing category)."""
    if not user or user.role == 'viewer' or not branch_id:
        return []
    from app.attachments.completeness import incomplete_map
    from app.attachments.registry import slots_for
    items = []
    for label, icon, Model, num_attr, edit_tmpl, _key in _visible_draft_sources(user):
        # OLDEST first. id.desc() buried the stalest draft at the bottom of the
        # page, which is exactly the one that has been forgotten.
        docs = _draft_query(Model, user, branch_id).order_by(Model.id.asc()).all()
        doctype = _DRAFT_ATTACHMENT_DOCTYPE.get(Model.__name__)
        missing = incomplete_map(doctype, docs) if doctype else {}
        slot_labels = {s.key: s.label for s in slots_for(doctype)} if doctype else {}
        for doc in docs:
            created = getattr(doc, 'created_at', None)
            miss = missing.get(doc.id)
            if miss:
                names = ', '.join(slot_labels.get(s.key, s.key) for s in miss)
                desc = f'Draft — attach {names} to complete it.'
            else:
                desc = 'Draft — continue editing to complete it.'
            items.append({
                'type': label,
                'icon': icon,
                'id': getattr(doc, num_attr, None) or '#{}'.format(doc.id),
                'desc': desc,
                'by': _creator_name(doc),
                'when': created.strftime('%Y-%m-%d %H:%M') if created else '—',
                'state': 'Draft',
                'editUrl': edit_tmpl.format(id=doc.id),
            })
    return items


def _missing_attachment_sources():
    """(label, icon, Model, num_attr, document_type, pre-approval statuses,
    detail-url template, module key) for the required-attachment worklist.

    SUBMITTED only, deliberately: a draft is already flagged in the Drafts
    category (with its own "continue editing" nudge), so also listing it here
    would double-count it in the sidebar badge and show it twice on the page.
    The distinct value of this category is the submitted document awaiting
    approval — past draft, files still missing, about to be approved.

    AP and CV have no 'submitted' step (draft -> posted), so they contribute
    nothing here; their missing files surface on the detail panel and at the
    posting soft gate instead. An item drops off the moment the document is
    approved/posted ("once approved it is considered complete").
    """
    from app.purchase_orders.models import PurchaseOrder
    from app.purchase_requests.models import PurchaseRequest
    from app.receiving_reports.models import ReceivingReport
    return [
        ('Purchase Requisition', '📝', PurchaseRequest, 'pr_number', 'purchase_requests',
         ('submitted',), '/purchase-requests/{id}', 'purchase_requests'),
        ('Purchase Order', '🛒', PurchaseOrder, 'po_number', 'purchase_orders',
         ('submitted',), '/purchase-orders/{id}', 'purchase_orders'),
        ('Receiving Report', '📦', ReceivingReport, 'rr_number', 'receiving_reports',
         ('submitted',), '/receiving-reports/{id}', 'receiving_reports'),
    ]


def _missing_attachment_docs(user, branch_id):
    """Yield (source, doc, missing_labels) for pre-approval documents that are
    missing a required attachment slot. Batched: one incomplete_map query per
    document type. Same gating as drafts (module access + staff-own + branch)."""
    from app.users.module_access import can_access_module
    from app.attachments.completeness import incomplete_map
    from app.attachments.registry import slots_for
    for src in _missing_attachment_sources():
        label, icon, Model, num_attr, doc_type, statuses, url_tmpl, key = src
        if key is not None and not can_access_module(user, key):
            continue
        q = Model.query.filter(Model.status.in_(statuses), Model.branch_id == branch_id)
        if user.role == 'staff':
            q = q.filter(Model.created_by_id == user.id)
        docs = q.order_by(Model.id.asc()).all()   # oldest first, as for drafts
        if not docs:
            continue
        miss = incomplete_map(doc_type, docs)
        if not miss:
            continue
        labels = {s.key: s.label for s in slots_for(doc_type)}
        for doc in docs:
            if doc.id in miss:
                names = [labels.get(s.key, s.key) for s in miss[doc.id]]
                yield src, doc, names


def gather_missing_attachment_items(user, branch_id):
    """Pre-approval documents missing a required attachment. Empty for viewers or
    with no branch selected. Drops off automatically once a document is
    approved/posted (those statuses are not in the pre-approval set)."""
    if not user or user.role == 'viewer' or not branch_id:
        return []
    items = []
    for src, doc, names in _missing_attachment_docs(user, branch_id):
        label, icon, Model, num_attr, doc_type, statuses, url_tmpl, key = src
        items.append({
            'type': label,
            'icon': '📎',
            'id': getattr(doc, num_attr, None) or '#{}'.format(doc.id),
            'desc': ('Attach required file%s: ' % ('s' if len(names) != 1 else '')) + ', '.join(names),
            'by': _creator_name(doc),
            'when': '—',
            'state': getattr(doc, 'status', '').replace('_', ' ').title() or '—',
            'editUrl': url_tmpl.format(id=doc.id),
        })
    return items


def _document_approval_sources():
    """(label, icon, Model, number attr, review-url template, module key).

    DOCUMENT approvals, as distinct from the master-data change requests below.
    Action Items had no notion of these at all: submitting a requisition removed
    it from Drafts (which filters status='draft') and nothing picked it up, so
    the one state that actually needs somebody's attention was the one state the
    page could not see.
    """
    from app.purchase_orders.models import PurchaseOrder
    from app.purchase_requests.models import PurchaseRequest
    from app.receiving_reports.models import ReceivingReport
    return [
        ('Purchase Requisition', '📝', PurchaseRequest, 'pr_number',
         '/purchase-requests/{id}', 'purchase_requests'),
        # A submitted PO is in exactly the state this list exists for: the staff
        # purchaser has handed it on and it is waiting on an approver. Same
        # approver audience -- _has_approve_level_role and _can_approve_documents
        # are the same rule (accountant or full access).
        ('Purchase Order', '🛒', PurchaseOrder, 'po_number',
         '/purchase-orders/{id}', 'purchase_orders'),
        ('Receiving Report', '📦', ReceivingReport, 'rr_number',
         '/receiving-reports/{id}', 'receiving_reports'),
    ]


def _can_approve_documents(user):
    """Mirrors purchase_requests.views._approve_gate.

    The audience is the APPROVER, not everyone with module access: submitting is
    open to staff, but approving is accountant/full-access only. An item the
    reader cannot action is noise on the page that exists to say "do this".
    """
    return bool(user) and (user.has_full_access or user.role == 'accountant')


def gather_document_approval_items(user, branch_id):
    """Submitted documents awaiting this user's approval, in the current branch."""
    if not user or not branch_id or not _can_approve_documents(user):
        return []
    from app.users.module_access import can_access_module

    items = []
    for label, icon, Model, num_attr, url_tmpl, key in _document_approval_sources():
        if key and not can_access_module(user, key):
            continue
        docs = (Model.query.filter_by(status='submitted', branch_id=branch_id)
                .order_by(Model.id.asc()).all())   # oldest first, as for drafts
        for doc in docs:
            submitted_at = getattr(doc, 'submitted_at', None)
            items.append({
                'type': label,
                'icon': icon,
                'id': getattr(doc, num_attr, None) or '#{}'.format(doc.id),
                'desc': 'Review and approve.',
                'by': _user_display(getattr(doc, 'submitted_by_id', None)),
                'when': submitted_at.strftime('%Y-%m-%d %H:%M') if submitted_at else '—',
                'state': 'Submitted',
                'reason': None,
                'reviewUrl': url_tmpl.format(id=doc.id),
            })
    return items


def gather_approval_items(user):
    """Pending master-data change requests. Full-access users (admin/chief accountant) + accountants."""
    if not user or not (user.has_full_access or user.role == 'accountant'):
        return []
    items = []

    # Purchase Requisition amendment requests. Unlike the master-data requests
    # below, this one is BRANCH-SCOPED and MODULE-GATED, for the reason
    # _draft_sources() already records: "Action Items must never be a side
    # channel around a gate the rest of the app enforces." purchase_requests is
    # optional + per_user, and the requests themselves carry a branch_id, so an
    # approver must see only requests in branches they can actually reach --
    # exactly the hole three fixes closed on 2026-08-20.
    from app.purchase_requests.amendment_service import (
        change_count, current_lines, diff_lines, pending_requests_for_branches)
    from app.users.module_access import can_access_module, module_enabled
    from app.users.utils import get_accessible_branches

    if module_enabled('purchase_requests') and can_access_module(user, 'purchase_requests'):
        branch_ids = {b.id for b in get_accessible_branches(user)}
        for req in pending_requests_for_branches(branch_ids):
            pr = req.purchase_request
            if pr is None:
                continue
            n = change_count(diff_lines(current_lines(pr), req.proposed_lines()))
            items.append({
                'type': 'PR Amendment', 'icon': '\U0001F4DD',
                'id': pr.pr_number, 'desc': 'Amendment requested — %d line%s changed'
                                            % (n, '' if n == 1 else 's'),
                'by': req.requested_by.username if req.requested_by else '—',
                'when': req.created_at.strftime('%Y-%m-%d %H:%M') if req.created_at else '—',
                'state': 'Pending', 'reason': req.request_reason,
                'reviewUrl': '/purchase-requests/amendment-requests/%d' % req.id,
            })

    # AP attachment amendment requests — branch-scoped, approve-level only
    # (the same audience as the PR block above; no module gate, since
    # accounts_payable is a CORE module every instance has).
    from flask import url_for
    from app.accounts_payable.amendment_service import pending_requests_for_branches as _ap_pending
    from app.attachments.registry import slots_for as _ap_slots_for
    _ap_slot_labels = {s.key: s.label for s in _ap_slots_for('accounts_payable')}
    for req in _ap_pending({b.id for b in get_accessible_branches(user)}):
        ap = req.ap
        label = _ap_slot_labels.get(req.kind, req.kind)
        items.append({
            'type': 'AP Amendment', 'icon': '📎',
            'id': ap.ap_number if ap else '#%s' % req.ap_id,
            'desc': 'AP amendment: attach %s (%s)' % (label, req.staged_original_filename),
            'by': req.requested_by.full_name if req.requested_by else '—',
            'when': req.created_at.strftime('%Y-%m-%d %H:%M') if req.created_at else '—',
            'state': 'Pending',
            'reviewUrl': url_for('accounts_payable.view', id=req.ap_id),
        })

    for req in AccountChangeRequest.query.filter_by(status='pending').all():
        cd = req.get_change_data()
        desc = cd.get('name', 'Account') if req.change_type == 'create' \
            else '{} — {}'.format(cd.get('name', 'Account'), req.change_type)
        items.append({
            'type': 'Chart of Accounts', 'icon': '📋',
            'id': cd.get('code', req.id), 'desc': desc,
            'by': req.requested_by or '—',
            'when': req.requested_at.strftime('%Y-%m-%d %H:%M') if req.requested_at else '—',
            'state': 'Pending', 'reason': req.request_reason,
            'reviewUrl': '/accounts/pending-approvals',
        })

    for req in VATCategoryChangeRequest.query.filter_by(status='pending').all():
        proposed = json.loads(req.proposed_data) if req.proposed_data else {}
        desc = proposed.get('name', 'VAT Category') if req.action == 'create' \
            else '{} — {}'.format(proposed.get('name', 'VAT Category'), req.action)
        items.append({
            'type': 'VAT Category', 'icon': '📊',
            'id': proposed.get('code', req.id), 'desc': desc,
            'by': req.requested_by.username if req.requested_by else '—',
            'when': req.requested_at.strftime('%Y-%m-%d %H:%M') if req.requested_at else '—',
            'state': 'Pending', 'reason': req.request_reason,
            'reviewUrl': '/vat-categories/change-requests/{}/review'.format(req.id),
        })

    for req in SalesVATCategoryChangeRequest.query.filter_by(status='pending').all():
        proposed = json.loads(req.proposed_data) if req.proposed_data else {}
        desc = proposed.get('name', 'Sales VAT Category') if req.action == 'create' \
            else '{} — {}'.format(proposed.get('name', 'Sales VAT Category'), req.action)
        items.append({
            'type': 'Sales VAT Category', 'icon': '📊',
            'id': proposed.get('code', req.id), 'desc': desc,
            'by': req.requested_by.username if req.requested_by else '—',
            'when': req.requested_at.strftime('%Y-%m-%d %H:%M') if req.requested_at else '—',
            'state': 'Pending', 'reason': req.request_reason,
            'reviewUrl': '/sales-vat-categories/change-requests/{}/review'.format(req.id),
        })

    for req in WithholdingTaxChangeRequest.query.filter_by(status='pending').all():
        proposed = json.loads(req.proposed_data) if req.proposed_data else {}
        desc = proposed.get('name', 'Withholding Tax') if req.action == 'create' \
            else '{} — {}'.format(proposed.get('name', 'Withholding Tax'), req.action)
        items.append({
            'type': 'Withholding Tax', 'icon': '💼',
            'id': proposed.get('code', req.id), 'desc': desc,
            'by': req.requested_by.username if req.requested_by else '—',
            'when': req.requested_at.strftime('%Y-%m-%d %H:%M') if req.requested_at else '—',
            'state': 'Pending', 'reason': req.request_reason,
            'reviewUrl': '/withholding-tax/change-requests/{}/review'.format(req.id),
        })

    for req in OpeningBalanceChangeRequest.query.filter_by(status='pending').all():
        cd = req.get_change_data()
        desc = 'Cutover {} — {} line(s)'.format(
            cd.get('cutover_date', '—'), len(cd.get('lines', [])))
        items.append({
            'type': 'Opening Balance', 'icon': '🏦',
            'id': req.id, 'desc': desc,
            'by': req.requested_by or '—',
            'when': req.requested_at.strftime('%Y-%m-%d %H:%M') if req.requested_at else '—',
            'state': 'Pending', 'reason': req.request_reason,
            'reviewUrl': '/opening-balances/pending-approvals',
        })

    if user.is_admin:
        # Permission Requests are admin-only by design (CA is the requester,
        # never the reviewer -- this closes a segregation-of-duties gap, so
        # a plain accountant or chief_accountant must not see these details).
        for req in PermissionChangeRequest.query.filter_by(status='pending').all():
            target_username = req.target_user.username if req.target_user else '(deleted user)'
            items.append({
                'type': 'Permission Request', 'icon': '🔑',
                'id': req.id,
                'desc': f'Grant {target_username}: {", ".join(req.get_requested_permissions().keys())}',
                'by': req.requested_by.username if req.requested_by else '—',
                'when': req.created_at.strftime('%Y-%m-%d %H:%M') if req.created_at else '—',
                'state': 'Pending', 'reason': req.request_reason,
                'reviewUrl': f'/permission-requests/{req.id}/review',
            })

    # Pending approved-email requests
    for ae in ApprovedEmail.query.filter_by(status='pending').all():
        items.append({
            'type': 'Approved Email Request', 'icon': '📧',
            'id': ae.email, 'desc': 'Registration email awaiting approval',
            'by': ae.requested_by.username if ae.requested_by else '—',
            'when': ae.approved_at.strftime('%Y-%m-%d %H:%M') if ae.approved_at else '—',
            'state': 'Pending', 'reason': None,
            'reviewUrl': '/approved-emails',
        })

    return items


def gather_incoming_transfer_items(user, branch_id):
    """Inter-branch transfers in_transit TO this branch, needing confirm/reject.
    Audience mirrors gather_approval_items: full-access + accountant."""
    if not user or not branch_id or not (user.has_full_access or user.role == 'accountant'):
        return []
    from app.bank_transfers.models import BankTransfer
    items = []
    transfers = (BankTransfer.query
                .filter_by(status='in_transit', to_branch_id=branch_id)
                .order_by(BankTransfer.id.desc()).all())
    for t in transfers:
        items.append({
            'type': 'Bank Transfer', 'icon': '🏦',
            'id': t.transfer_number,
            'desc': f'Incoming transfer of {t.amount} awaiting confirmation.',
            'by': t.from_bank_account.branch.name if t.from_bank_account and t.from_bank_account.branch else '—',
            'when': t.initiated_at.strftime('%Y-%m-%d %H:%M') if t.initiated_at else '—',
            'state': 'In Transit',
            'editUrl': f'/bank-transfers/{t.id}',
        })
    return items


#: The worklist, in the order a reader should work it. Each group carries its own
#: VERB -- the page used to render every row behind a single "Continue" button,
#: including rows whose actual need was "attach a file" or "receive goods".
#:
#: `url_key` names which key of the item dict holds the link, because the
#: gatherers predate this grouping and disagree (`editUrl` vs `reviewUrl`).
ACTION_GROUPS = (
    # FILES FIRST (owner, 2026-09-23). Attaching is the prerequisite: the same
    # document usually appears in both groups, and reading the page top-down should
    # put the file in place before the approve button is offered.
    #
    # This is a matter of ORDER ONLY. Approval is still permitted with files
    # missing -- that is a deliberate feature of this system, which records the
    # incomplete slots at approval time -- so nothing here blocks or hides an
    # incomplete document from the approver.
    ('attach', 'Missing a required file', 'Attach', 'editUrl'),
    # Then approvals: somebody else is blocked until these are done.
    ('approve', 'Waiting for your approval', 'Review', 'reviewUrl'),
    ('draft', 'Your unfinished drafts', 'Continue', 'editUrl'),
    ('receive', 'Goods arriving', 'Receive', 'editUrl'),
)


def gather_action_groups(user, branch_id):
    """``[{key, title, verb, url_key, items}, ...]`` -- the whole worklist.

    ONE source for both the page and the sidebar badge. They were computed
    separately before, with a comment on count_action_items apologising for the
    ways they could disagree; deriving both from this makes divergence
    impossible rather than merely tested for.

    A submitted document that is missing a required file appears in BOTH the
    'attach' and 'approve' groups, on purpose (owner decision, 2026-09-23). They
    are two genuinely different actions with two different verbs, and the reader
    needs to see both.

    An earlier version de-duplicated, keeping only the approval row -- which was a
    defect, because gather_document_approval_items describes every row as "Review
    and approve." and names no files, so the upload requirement vanished from the
    page entirely for anyone able to approve.

    Do NOT "fix" this back by excluding incomplete documents from the approval
    group either. This system deliberately permits approving with files missing
    and records which slots were incomplete at approval time (see
    attachments/service.py::record_approval_completeness); hiding the document
    would fight that.

    A consequence to keep in mind: the badge therefore counts ACTIONS, not
    documents, so one document can add two. That is the right reading for a
    worklist.

    Empty groups are dropped; the caller renders what it is given.
    """
    if not user or user.role == 'viewer':
        return []

    # NOT gated on branch_id. gather_approval_items is COMPANY-level -- account,
    # VAT, withholding-tax, opening-balance, permission and approved-email change
    # requests belong to no branch -- so returning early when no branch is selected
    # would hide them entirely. Every branch-scoped gatherer below already returns
    # [] for a missing branch_id, so they need no guard here.
    by_key = {
        'approve': (gather_document_approval_items(user, branch_id)
                    + gather_approval_items(user)),
        'attach': gather_missing_attachment_items(user, branch_id),
        'draft': gather_draft_items(user, branch_id),
        'receive': gather_incoming_transfer_items(user, branch_id),
    }
    return [{'key': key, 'title': title, 'verb': verb, 'url_key': url_key,
             'items': by_key[key]}
            for key, title, verb, url_key in ACTION_GROUPS if by_key[key]]


def count_action_items(user, branch_id):
    """Sidebar badge = exactly the number of rows the Action Items page shows.

    DERIVED from gather_action_groups rather than recomputed. The previous version
    summed its own COUNT queries and carried three separate comments apologising
    for the ways it could drift from the page -- one about draft-source gating,
    one about approval items, one about double-counting missing files. Deriving
    it makes that whole class of bug unrepresentable instead of merely commented.

    The cost is hydrating the rows on every request that renders the sidebar. That
    is a smaller job than it was: drafts are now the reader's OWN only, where they
    used to be the whole branch's for an accountant or admin, and the old version
    already hydrated approvals and transfers anyway.

    Counts ACTIONS, not documents. A submitted document missing a required file
    contributes two, because it needs two things doing -- see gather_action_groups.
    """
    if not user or user.role == 'viewer':
        return 0
    return sum(len(g['items']) for g in gather_action_groups(user, branch_id))
