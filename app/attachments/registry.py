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


def _paid_by_check(doc):
    """CV 'Check copy' slot applies only when the voucher is paid by check."""
    return getattr(doc, 'payment_method', None) == 'check'


@dataclass(frozen=True)
class Slot:
    """A named attachment slot on a document type.

    `required` is the CODE-SEEDED default; Company Settings may override it per
    company (task 4). `applies_when`, when set, is a predicate `(doc) -> bool`:
    the slot is only shown and only considered required for documents it applies
    to (e.g. a CV 'Check copy' only when paid by check). A slot with
    `applies_when=None` always applies.
    """
    key: str
    label: str
    required: bool = False
    applies_when: object = None

    def applies_to(self, doc):
        return self.applies_when is None or bool(self.applies_when(doc))


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
    #: Named slots (Slot objects) this document type defines, in display order.
    #: A file with kind=NULL is an unlabeled "Other" and belongs to no slot.
    slots: tuple = ()
    #: Post-approval statuses in which an APPROVE-level user may fill a STILL-EMPTY
    #: required slot (attachments-only late completion; no replace, no Other).
    #: PR/PO leave this empty -- their amend path already allows post-approval
    #: uploads. RR and CV use it because they have no amendment path.
    late_complete_statuses: tuple = ()

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
        slots=(
            Slot('signed_pr', 'Signed PR', required=True),
        ),
    ),
    'purchase_orders': AttachmentTarget(
        document_type='purchase_orders',
        model_path='app.purchase_orders.models:PurchaseOrder',
        number_attr='po_number',
        view_endpoint='purchase_orders.view',
        open_statuses=('draft', 'submitted'),
        amend_statuses=('approved', 'partially_received'),
        amend_level=_approve_level,
        slots=(
            Slot('signed_po', 'Signed PO', required=True),
            Slot('vendor_quotation', 'Vendor Quotation', required=True),
        ),
    ),
    'receiving_reports': AttachmentTarget(
        document_type='receiving_reports',
        model_path='app.receiving_reports.models:ReceivingReport',
        number_attr='rr_number',
        view_endpoint='receiving_reports.view',
        open_statuses=('draft', 'submitted'),
        slots=(
            Slot('signed_rr', 'Signed RR', required=True),
            Slot('vendor_dr_sr', 'Vendor DR/SR', required=True),
        ),
        late_complete_statuses=('approved', 'billed'),
    ),
    'cash_disbursements': AttachmentTarget(
        document_type='cash_disbursements',
        model_path='app.cash_disbursements.models:CashDisbursementVoucher',
        number_attr='cdv_number',
        view_endpoint='cash_disbursements.view',
        open_statuses=('draft',),
        slots=(
            Slot('signed_cv', 'Signed CV', required=True),
            Slot('check_copy', 'Check copy', required=True, applies_when=_paid_by_check),
        ),
        late_complete_statuses=('posted',),
    ),
}


def get_target(document_type):
    return TARGETS.get(document_type)


# Accounts Payable keeps its own attachment table and its own upload routes, so
# it is deliberately NOT a shared-attachment TARGET above. Required/labeled
# completeness spans it too (spec D4), so its slots live here, and slots_for()
# unifies the lookup across all five document types.
_AP_SLOTS = (
    Slot('signed_ap', 'Signed AP', required=True),
)


def slots_for(document_type):
    """Named slots for any of the five document types (AP included), in display
    order. Empty tuple for an unknown type."""
    if document_type == 'accounts_payable':
        return _AP_SLOTS
    target = TARGETS.get(document_type)
    return target.slots if target else ()


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


def can_late_complete(target, doc, user, kind):
    """May *user* fill the *kind* required slot on an already-approved *doc*?

    Attachments-only late completion (spec task 10/D10): an APPROVE-level user may
    add a file to a STILL-EMPTY REQUIRED slot on a document in a
    late_complete_status. It never permits replacing an existing file, filling a
    non-required/Other slot, or any financial change. Emptiness is checked by the
    caller (the route), which knows what is already present.
    """
    if not target.late_complete_statuses or doc.status not in target.late_complete_statuses:
        return False
    if not (user.has_full_access or user.role == 'accountant'):
        return False
    from app.attachments.completeness import required_slots
    return kind in {s.key for s in required_slots(target.document_type, doc)}
