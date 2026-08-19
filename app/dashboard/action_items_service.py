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
    from app.sales_invoices.models import SalesInvoice
    return [
        # Ordered along the Procure-to-Pay chain, as MODULE_REGISTRY is.
        ('Purchase Requisition', '📝', PurchaseRequest, 'pr_number', '/purchase-requests/{id}/edit', 'purchase_requests'),
        # purchase_orders is optional + per_user, like purchase_requests, so it
        # MUST name its module key -- otherwise Action Items would surface orders
        # from a module the instance never enabled, or that this user cannot
        # open, and link to an edit route the module guard then refuses.
        ('Purchase Order', '🛒', PurchaseOrder, 'po_number', '/purchase-orders/{id}/edit', 'purchase_orders'),
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
    q = Model.query.filter_by(status='draft', branch_id=branch_id)
    if user.role == 'staff':
        # Staff only see the drafts they created.
        q = q.filter_by(created_by_id=user.id)
    return q


def gather_draft_items(user, branch_id):
    """Draft documents the user should finish. Empty for viewers or when no
    branch is selected."""
    if not user or user.role == 'viewer' or not branch_id:
        return []
    items = []
    for label, icon, Model, num_attr, edit_tmpl, _key in _visible_draft_sources(user):
        for doc in _draft_query(Model, user, branch_id).order_by(Model.id.desc()).all():
            created = getattr(doc, 'created_at', None)
            items.append({
                'type': label,
                'icon': icon,
                'id': getattr(doc, num_attr, None) or '#{}'.format(doc.id),
                'desc': 'Unposted draft — continue editing to post it.',
                'by': _creator_name(doc),
                'when': created.strftime('%Y-%m-%d %H:%M') if created else '—',
                'state': 'Draft',
                'editUrl': edit_tmpl.format(id=doc.id),
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
    return [
        ('Purchase Requisition', '📝', PurchaseRequest, 'pr_number',
         '/purchase-requests/{id}', 'purchase_requests'),
        # A submitted PO is in exactly the state this list exists for: the staff
        # purchaser has handed it on and it is waiting on an approver. Same
        # approver audience -- _has_approve_level_role and _can_approve_documents
        # are the same rule (accountant or full access).
        ('Purchase Order', '🛒', PurchaseOrder, 'po_number',
         '/purchase-orders/{id}', 'purchase_orders'),
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
                .order_by(Model.id.desc()).all())
        for doc in docs:
            submitted_at = getattr(doc, 'submitted_at', None)
            items.append({
                'type': label,
                'icon': icon,
                'id': getattr(doc, num_attr, None) or '#{}'.format(doc.id),
                'desc': 'Submitted for approval.',
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


def count_action_items(user, branch_id):
    """Badge count = drafts the user can see + approvals they can review.
    Uses COUNT queries (no object hydration) for the per-request badge."""
    if not user or user.role == 'viewer':
        return 0
    n = 0
    if branch_id:
        # _visible_draft_sources, same as the list: gating one path and not the
        # other gives a badge that counts an item the page refuses to show.
        for _label, _icon, Model, _num, _edit, _key in _visible_draft_sources(user):
            n += _draft_query(Model, user, branch_id).count()
        n += len(gather_incoming_transfer_items(user, branch_id))
        # Documents awaiting approval. Counted here as well as listed, or the
        # badge says 1 while the page shows 2 -- the same list/badge divergence
        # the draft sources guard against.
        n += len(gather_document_approval_items(user, branch_id))
    if user.has_full_access or user.role == 'accountant':
        n += AccountChangeRequest.query.filter_by(status='pending').count()
        n += VATCategoryChangeRequest.query.filter_by(status='pending').count()
        n += SalesVATCategoryChangeRequest.query.filter_by(status='pending').count()
        n += WithholdingTaxChangeRequest.query.filter_by(status='pending').count()
        n += OpeningBalanceChangeRequest.query.filter_by(status='pending').count()
    if user.has_full_access:
        n += ApprovedEmail.query.filter_by(status='pending').count()
    if user.is_admin:
        # Admin-only by design: see gather_approval_items()'s Permission
        # Request block for the rationale.
        n += PermissionChangeRequest.query.filter_by(status='pending').count()
    return n
