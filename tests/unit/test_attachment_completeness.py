"""Required-slot resolution for the required/labeled attachments feature.

`required_slots` and `visible_slots` are pure over the code-seeded registry and a
duck-typed document (they read only `doc.payment_method` for the CV conditional),
so they need no app context. The DB-touching `missing_required` / `incomplete_map`
are covered by the integration suite.
"""
from types import SimpleNamespace

import pytest

from app.attachments.completeness import required_slots, visible_slots

pytestmark = [pytest.mark.unit, pytest.mark.attachments]


def _keys(slots):
    return [s.key for s in slots]


@pytest.mark.parametrize('doc_type,doc,expected', [
    ('purchase_requests', SimpleNamespace(), ['signed_pr']),
    ('purchase_orders', SimpleNamespace(), ['signed_po', 'vendor_quotation']),
    ('receiving_reports', SimpleNamespace(), ['signed_rr', 'vendor_dr_sr']),
    ('accounts_payable', SimpleNamespace(), ['signed_ap']),
    # CV: check copy required only when paid by check.
    ('cash_disbursements', SimpleNamespace(payment_method='check'),
     ['signed_cv', 'check_copy']),
    ('cash_disbursements', SimpleNamespace(payment_method='cash'), ['signed_cv']),
    ('cash_disbursements', SimpleNamespace(), ['signed_cv']),  # method unset → not check
])
def test_required_slots(doc_type, doc, expected):
    assert _keys(required_slots(doc_type, doc)) == expected


def test_check_copy_visible_only_when_paid_by_check():
    check = SimpleNamespace(payment_method='check')
    cash = SimpleNamespace(payment_method='cash')
    assert 'check_copy' in _keys(visible_slots('cash_disbursements', check))
    assert 'check_copy' not in _keys(visible_slots('cash_disbursements', cash))


def test_unknown_document_type_has_no_slots():
    assert required_slots('sales_invoices', SimpleNamespace()) == []
    assert visible_slots('sales_invoices', SimpleNamespace()) == []
