"""Which documents accept shared attachments, and who may add or remove one.

Owner's rule (2026-09-15): "Staff can upload as long as the document has not
been Approved. Any additional upload can be handled in the amendment."

"Approved" is a per-document notion, so each target spells out the statuses in
which an EDIT-level user may still attach (`open_statuses`) and, where the module
has an amendment path, the statuses and role in which an APPROVE-level user may
attach through it (`amend_statuses` + `amend_level`). RR, AP and CDV have no
amendment path, so their attachments freeze on approval/posting.

The predicates here are pure: they read `user.role`, `user.has_full_access`,
`user.id`, `doc.status` and `attachment.uploaded_by_id` and nothing else, so the
unit test can drive them with plain namespaces and no app context.

Targets load their model lazily so this package never imports a views module
(the views modules import THIS package for the create-form hook).
"""
from dataclasses import dataclass
from importlib import import_module

from app import db

#: Roles that may create/edit a draft of every target below. Mirrors the
#: `_role_gate` / `_pr_role_gate` / `RR_EDIT_ROLES` / `staff_or_above_required`
#: lists in the four modules, which are identical today.
EDIT_ROLES = ('staff', 'accountant', 'admin', 'chief_accountant')


def _approve_level(user):
    """The approve-level predicate shared by PR (`_approve_gate`) and PO
    (`_has_approve_level_role`): accountant, or anyone with full access."""
    return bool(user.has_full_access or user.role == 'accountant')


@dataclass(frozen=True)
class AttachmentTarget:
    #: Matches the module's audit `module` name and the upload folder name.
    document_type: str
    #: 'package.module:ClassName' of the document model, imported on first use.
    model_path: str
    #: Attribute holding the human document number (pr_number, po_number, ...).
    number_attr: str
    #: Endpoint of the document's detail page, for redirects after an action.
    view_endpoint: str
    #: Statuses in which an edit-level user may upload / delete.
    open_statuses: tuple
    edit_roles: tuple = EDIT_ROLES
    #: Statuses reachable only through the module's amend path. Empty when the
    #: module has no amendment.
    amend_statuses: tuple = ()
    #: (user) -> bool. Who may attach through the amend path.
    amend_level: object = None

    def model(self):
        module_name, _, class_name = self.model_path.partition(':')
        return getattr(import_module(module_name), class_name)

    def load(self, document_id):
        """The document row, or None. Plain get: branch scoping is applied by
        the caller through the module's own view on redirect, and every route
        here re-checks the status gate before doing anything."""
        return db.session.get(self.model(), document_id)

    def number(self, doc):
        return getattr(doc, self.number_attr, None) or f'#{doc.id}'


TARGETS = {
    'purchase_requests': AttachmentTarget(
        document_type='purchase_requests',
        model_path='app.purchase_requests.models:PurchaseRequest',
        number_attr='pr_number',
        view_endpoint='purchase_requests.view',
        open_statuses=('draft', 'submitted', 'rejected'),
        amend_statuses=('approved', 'partially_converted', 'partially_received',
                        'converted'),
        amend_level=_approve_level,
    ),
    'purchase_orders': AttachmentTarget(
        document_type='purchase_orders',
        model_path='app.purchase_orders.models:PurchaseOrder',
        number_attr='po_number',
        view_endpoint='purchase_orders.view',
        open_statuses=('draft', 'submitted'),
        amend_statuses=('approved', 'partially_received'),
        amend_level=_approve_level,
    ),
    'receiving_reports': AttachmentTarget(
        document_type='receiving_reports',
        model_path='app.receiving_reports.models:ReceivingReport',
        number_attr='rr_number',
        view_endpoint='receiving_reports.view',
        open_statuses=('draft', 'submitted'),
    ),
    'cash_disbursements': AttachmentTarget(
        document_type='cash_disbursements',
        model_path='app.cash_disbursements.models:CashDisbursementVoucher',
        number_attr='cdv_number',
        view_endpoint='cash_disbursements.view',
        open_statuses=('draft',),
    ),
}


def get_target(document_type):
    return TARGETS.get(document_type)


def can_upload(target, doc, user):
    """May *user* attach a file to *doc* right now?"""
    if user.role in target.edit_roles and doc.status in target.open_statuses:
        return True
    if target.amend_statuses and doc.status in target.amend_statuses:
        return bool(target.amend_level and target.amend_level(user))
    return False


def can_delete(target, doc, user, attachment):
    """Same status gate as upload, plus ownership: staff may undo their own
    mistaken upload but not remove a colleague's evidence; accountants and
    full-access users may remove any."""
    if not can_upload(target, doc, user):
        return False
    return (attachment.uploaded_by_id == user.id
            or user.has_full_access
            or user.role == 'accountant')
