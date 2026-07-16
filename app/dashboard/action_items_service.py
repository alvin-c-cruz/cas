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
    """(label, icon, Model, document-number attr, edit-url template)."""
    from app.accounts_payable.models import AccountsPayable
    from app.cash_disbursements.models import CashDisbursementVoucher
    from app.cash_receipts.models import CashReceiptVoucher
    from app.sales_invoices.models import SalesInvoice
    return [
        ('Accounts Payable', '🧾', AccountsPayable, 'ap_number', '/accounts-payable/{id}/edit'),
        ('Cash Disbursement', '💸', CashDisbursementVoucher, 'cdv_number', '/cash-disbursements/{id}/edit'),
        ('Cash Receipt', '💰', CashReceiptVoucher, 'crv_number', '/cash-receipts/{id}/edit'),
        ('Sales Invoice', '📄', SalesInvoice, 'invoice_number', '/sales-invoices/{id}/edit'),
    ]


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
    for label, icon, Model, num_attr, edit_tmpl in _draft_sources():
        for doc in _draft_query(Model, user, branch_id).order_by(Model.id.desc()).all():
            created = getattr(doc, 'created_at', None)
            items.append({
                'type': label,
                'icon': icon,
                'id': getattr(doc, num_attr, None) or '#{}'.format(doc.id),
                'desc': 'Unposted draft — continue editing to post it.',
                'by': doc.created_by.full_name if getattr(doc, 'created_by', None) else '—',
                'when': created.strftime('%Y-%m-%d %H:%M') if created else '—',
                'state': 'Draft',
                'editUrl': edit_tmpl.format(id=doc.id),
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


def count_action_items(user, branch_id):
    """Badge count = drafts the user can see + approvals they can review.
    Uses COUNT queries (no object hydration) for the per-request badge."""
    if not user or user.role == 'viewer':
        return 0
    n = 0
    if branch_id:
        for _label, _icon, Model, _num, _edit in _draft_sources():
            n += _draft_query(Model, user, branch_id).count()
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
