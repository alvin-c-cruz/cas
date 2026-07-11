"""Unit tests for PurchaseRequest -- a thin internal requisition (mirror of Quotation).
Operational: posts no JE. No vendor, no price; converts to a draft PO on approval."""
from decimal import Decimal
from datetime import date

# Module-level import so the model is registered before any db_session create_all().
from app.purchase_requests.models import PurchaseRequest, PurchaseRequestItem  # noqa: F401


def test_generate_pr_number_increments(db_session):
    from app.purchase_requests.models import generate_pr_number
    n1 = generate_pr_number()
    assert n1.startswith('PR-') and n1.endswith('-0001')
    pr = PurchaseRequest(pr_number=n1, request_date=date(2026, 7, 11), status='draft')
    db_session.add(pr); db_session.commit()
    assert generate_pr_number().endswith('-0002')


def test_pr_has_no_price_columns(db_session):
    """A requisition line carries product/uom/qty/description only -- no price/amount/vat."""
    li = PurchaseRequestItem(line_number=1, description='Cement', quantity=Decimal('10'))
    for absent in ('unit_price', 'amount', 'vat_rate', 'vat_amount'):
        assert not hasattr(li, absent)


def test_forward_link_to_po_defaults_none(db_session):
    pr = PurchaseRequest(pr_number='PR-2026-07-0001', request_date=date(2026, 7, 11),
                         status='draft')
    assert pr.purchase_order_id is None


def test_lines_persist(db_session):
    pr = PurchaseRequest(pr_number='PR-2026-07-0002', request_date=date(2026, 7, 11),
                         status='draft', reason='Site needs cement')
    pr.line_items.append(PurchaseRequestItem(line_number=1, description='Cement',
                                             quantity=Decimal('10'), uom_text='bag'))
    db_session.add(pr); db_session.commit()
    assert len(pr.line_items) == 1
    assert pr.line_items[0].description == 'Cement'
    assert pr.line_items[0].quantity == Decimal('10')
    d = pr.to_dict()
    assert d['pr_number'] == 'PR-2026-07-0002' and d['status'] == 'draft'
