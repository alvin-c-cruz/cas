"""Unit tests for PurchaseRequest -- a thin internal requisition (mirror of Quotation).
Operational: posts no JE. No vendor, no price; converts to a draft PO on approval."""
from decimal import Decimal
from datetime import date

# Module-level import so the model is registered before any db_session create_all().
from app.purchase_requests.models import PurchaseRequest, PurchaseRequestItem  # noqa: F401
import pytest

pytestmark = [pytest.mark.purchase_requests]


def test_generate_pr_number_increments(db_session):
    from app.purchase_requests.models import generate_pr_number
    n1 = generate_pr_number()
    assert n1 == '00001'
    pr = PurchaseRequest(pr_number=n1, request_date=date(2026, 7, 11), status='draft')
    db_session.add(pr); db_session.commit()
    assert generate_pr_number() == '00002'


def test_generate_pr_number_continues_from_legacy_literal_number(db_session):
    from app.purchase_requests.models import generate_pr_number
    pr = PurchaseRequest(pr_number='50000', request_date=date(2026, 7, 11), status='draft')
    db_session.add(pr); db_session.commit()
    assert generate_pr_number() == '50001'


def test_generate_pr_number_ignores_legacy_prefixed_numbers(db_session):
    from app.purchase_requests.models import generate_pr_number
    pr = PurchaseRequest(pr_number='PR-2026-07-0030', request_date=date(2026, 7, 11),
                         status='draft')
    db_session.add(pr); db_session.commit()
    assert generate_pr_number() == '00001'


def test_generate_pr_number_is_per_branch_under_branch_scope(db_session, main_branch,
                                                             branch_manila):
    """The delegate must actually PASS branch_id through, not just accept it."""
    from app.settings import AppSettings
    from app.purchase_requests.models import generate_pr_number
    AppSettings.set_setting('document_number_scope', 'branch')
    db_session.add(PurchaseRequest(pr_number='00007', request_date=date(2026, 8, 19),
                                   status='draft', branch_id=main_branch.id))
    db_session.add(PurchaseRequest(pr_number='90000', request_date=date(2026, 8, 19),
                                   status='draft', branch_id=branch_manila.id))
    db_session.commit()
    assert generate_pr_number(main_branch.id) == '00008'


def test_generate_pr_number_is_company_wide_by_default(db_session, main_branch,
                                                       branch_manila):
    """CONTROL -- no setting row, so the other branch's higher number DOES lead."""
    from app.purchase_requests.models import generate_pr_number
    db_session.add(PurchaseRequest(pr_number='00007', request_date=date(2026, 8, 19),
                                   status='draft', branch_id=main_branch.id))
    db_session.add(PurchaseRequest(pr_number='90000', request_date=date(2026, 8, 19),
                                   status='draft', branch_id=branch_manila.id))
    db_session.commit()
    assert generate_pr_number(main_branch.id) == '90001'


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


# ---------------------------------------------------------------------------
# User-defined number prefix (e.g. '25-0914'). The prefix is chosen by the
# client and CHANGES over time -- they may move to '26-' next year -- so the
# generator carries forward whatever prefix the PREVIOUS record used rather
# than knowing any prefix itself.
# ---------------------------------------------------------------------------

def test_generate_pr_number_continues_a_user_defined_prefix(db_session):
    """'25-0972' -> '25-0973': prefix preserved, numeric tail incremented."""
    from app.purchase_requests.models import generate_pr_number
    for n in ('25-0914', '25-0915', '25-0916', '25-0972'):
        db_session.add(PurchaseRequest(pr_number=n, request_date=date(2026, 8, 24),
                                       status='draft'))
    db_session.commit()
    assert generate_pr_number() == '25-0973'


def test_generate_pr_number_preserves_the_tail_width(db_session):
    """A 4-digit tail stays 4 digits; it is not re-padded to the 5-digit default."""
    from app.purchase_requests.models import generate_pr_number
    db_session.add(PurchaseRequest(pr_number='25-0009', request_date=date(2026, 8, 24),
                                   status='draft'))
    db_session.commit()
    assert generate_pr_number() == '25-0010'


def test_generate_pr_number_follows_the_newest_prefix_when_it_changes(db_session):
    """After the client switches to '26-', the series continues under the NEW
    prefix -- the older '25-' rows must not drag it back."""
    from app.purchase_requests.models import generate_pr_number
    db_session.add(PurchaseRequest(pr_number='25-0972', request_date=date(2026, 8, 24),
                                   status='draft'))
    db_session.commit()
    db_session.add(PurchaseRequest(pr_number='26-0001', request_date=date(2027, 1, 4),
                                   status='draft'))
    db_session.commit()
    assert generate_pr_number() == '26-0002'


def test_generate_pr_number_skips_a_taken_number_within_the_prefix(db_session):
    """Uniqueness is global, so a gap-filling candidate already in use is skipped."""
    from app.purchase_requests.models import generate_pr_number
    for n in ('25-0009', '25-0010'):
        db_session.add(PurchaseRequest(pr_number=n, request_date=date(2026, 8, 24),
                                       status='draft'))
    db_session.commit()
    assert generate_pr_number() == '25-0011'
