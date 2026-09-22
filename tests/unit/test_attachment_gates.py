"""Gate table for shared document attachments (app/attachments/registry.py).

"Approved" per document type, from the owner's rule "staff can upload as long as
the document has not been Approved; any additional upload is handled in the
amendment":

  PR  -> approved and everything after it; amend path for approve-level users
  PO  -> approved and everything after it; amend path for approve-level users
  RR  -> approved / billed; no amendment path exists
  CDV -> posted; no amendment path exists

Pure predicates over duck-typed user/document objects, so no app context.
"""
from types import SimpleNamespace

import pytest

from app.attachments.registry import (TARGETS, can_delete, can_upload,
                                      get_target)

pytestmark = [pytest.mark.unit, pytest.mark.attachments]


def _user(role, uid=1):
    return SimpleNamespace(id=uid, role=role,
                           has_full_access=(role in ('admin', 'chief_accountant')))


def _doc(status):
    return SimpleNamespace(status=status)


STAFF = _user('staff', 1)
OTHER_STAFF = _user('staff', 2)
ACCOUNTANT = _user('accountant', 3)
ADMIN = _user('admin', 4)
VIEWER = _user('viewer', 5)


def test_amend_statuses_track_the_models():
    """The registry spells the tuples out literally (so the gate stays pure);
    this pins them to the models so a change there cannot drift silently."""
    from app.purchase_requests.models import PurchaseRequest
    from app.purchase_orders.models import PurchaseOrder
    assert get_target('purchase_requests').amend_statuses == PurchaseRequest.AMEND_STATUSES
    assert get_target('purchase_orders').amend_statuses == PurchaseOrder.AMEND_STATUSES


def test_every_target_is_registered():
    """The four buy-side documents, plus vendors (master data, added
    2026-09-22 so a supplier's BIR 2303, SEC registration and Business Permit
    have somewhere to live).

    accounts_payable stays absent on purpose: it predates this module and keeps
    its own table and routes, which is why slots_for special-cases it."""
    assert set(TARGETS) == {'purchase_requests', 'purchase_orders',
                            'receiving_reports', 'cash_disbursements',
                            'vendors'}
    assert get_target('accounts_payable') is None


def test_the_vendor_target_declares_no_required_slot():
    """A required slot drives a warning badge and an approval soft gate, both
    built for approvable documents. A vendor has no approval step, so a
    required slot there could never be cleared by its own workflow."""
    target = get_target('vendors')
    assert [s.key for s in target.slots] == ['bir_2303', 'sec_registration',
                                             'business_permit']
    assert not any(s.required for s in target.slots)


def test_a_vendor_is_uploadable_whether_active_or_inactive():
    """Going inactive is not an approval and freezes nothing, so the
    certificates must stay manageable either way."""
    from types import SimpleNamespace
    target = get_target('vendors')
    staff = SimpleNamespace(role='staff', has_full_access=False, id=1)
    for status in ('active', 'inactive'):
        assert can_upload(target, SimpleNamespace(status=status), staff) is True


@pytest.mark.parametrize('doc_type,status,user,expected', [
    # Purchase Requisition
    ('purchase_requests', 'draft', STAFF, True),
    ('purchase_requests', 'submitted', STAFF, True),
    ('purchase_requests', 'rejected', STAFF, True),
    ('purchase_requests', 'approved', STAFF, False),
    ('purchase_requests', 'converted', STAFF, False),
    ('purchase_requests', 'cancelled', STAFF, False),
    ('purchase_requests', 'approved', ACCOUNTANT, True),      # amend path
    ('purchase_requests', 'partially_converted', ADMIN, True),  # amend path
    ('purchase_requests', 'cancelled', ADMIN, False),          # not amendable
    ('purchase_requests', 'draft', VIEWER, False),
    # Purchase Order
    ('purchase_orders', 'draft', STAFF, True),
    ('purchase_orders', 'submitted', STAFF, True),
    ('purchase_orders', 'approved', STAFF, False),
    ('purchase_orders', 'approved', ACCOUNTANT, True),         # amend path
    ('purchase_orders', 'partially_received', ADMIN, True),    # amend path
    ('purchase_orders', 'closed', ADMIN, False),
    ('purchase_orders', 'cancelled', ACCOUNTANT, False),
    # Receiving Report
    ('receiving_reports', 'draft', STAFF, True),
    ('receiving_reports', 'submitted', STAFF, True),
    ('receiving_reports', 'approved', STAFF, False),
    ('receiving_reports', 'approved', ADMIN, False),           # no amend path
    ('receiving_reports', 'billed', ACCOUNTANT, False),
    # Cash Disbursement Voucher
    ('cash_disbursements', 'draft', STAFF, True),
    ('cash_disbursements', 'draft', ACCOUNTANT, True),
    ('cash_disbursements', 'posted', STAFF, False),
    ('cash_disbursements', 'posted', ADMIN, False),            # no amend path
    ('cash_disbursements', 'voided', ADMIN, False),
])
def test_can_upload(doc_type, status, user, expected):
    assert can_upload(get_target(doc_type), _doc(status), user) is expected


def test_can_delete_requires_upload_gate_and_ownership():
    target = get_target('purchase_orders')
    mine = SimpleNamespace(uploaded_by_id=STAFF.id)
    # Draft: uploader yes, another staff no, accountant/admin yes.
    assert can_delete(target, _doc('draft'), STAFF, mine) is True
    assert can_delete(target, _doc('draft'), OTHER_STAFF, mine) is False
    assert can_delete(target, _doc('draft'), ACCOUNTANT, mine) is True
    assert can_delete(target, _doc('draft'), ADMIN, mine) is True
    # Approved: the upload gate closes for staff even on their own file.
    assert can_delete(target, _doc('approved'), STAFF, mine) is False
    # Approved: accountant is amend-level, so may still delete.
    assert can_delete(target, _doc('approved'), ACCOUNTANT, mine) is True
