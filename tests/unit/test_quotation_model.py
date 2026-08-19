import pytest
from datetime import date, timedelta
from decimal import Decimal
from app.quotations.models import Quotation, QuotationItem

pytestmark = [pytest.mark.usefixtures("app"), pytest.mark.integration, pytest.mark.quotations]


def _quote(treatment, amounts):
    q = Quotation(quotation_number='QTN-T', quotation_date=date(2026, 7, 9),
                  valid_until=date(2026, 8, 9), customer_id=1, customer_name='Acme',
                  vat_treatment=treatment, status='draft')
    for i, a in enumerate(amounts, start=1):
        li = QuotationItem(line_number=i, amount=Decimal(str(a)), vat_rate=Decimal('12'))
        li.calculate_amounts()
        q.line_items.append(li)
    q.calculate_totals()
    return q


def test_generate_quotation_number_starts_at_00001(db_session, main_branch):
    from app.quotations.models import generate_quotation_number
    assert generate_quotation_number(main_branch.id) == '00001'


def test_generate_quotation_number_is_per_branch_under_branch_scope(db_session, main_branch,
                                                                    branch_manila):
    from app.settings import AppSettings
    from app.quotations.models import generate_quotation_number
    AppSettings.set_setting('document_number_scope', 'branch')
    db_session.add(Quotation(quotation_number='00007', quotation_date=date(2026, 8, 19),
                             customer_id=1, customer_name='Acme',
                             branch_id=main_branch.id, status='draft'))
    db_session.add(Quotation(quotation_number='90000', quotation_date=date(2026, 8, 19),
                             customer_id=1, customer_name='Acme',
                             branch_id=branch_manila.id, status='draft'))
    db_session.commit()
    assert generate_quotation_number(main_branch.id) == '00008'


def test_generate_quotation_number_is_company_wide_by_default(db_session, main_branch,
                                                              branch_manila):
    """CONTROL -- no setting row."""
    from app.quotations.models import generate_quotation_number
    db_session.add(Quotation(quotation_number='00007', quotation_date=date(2026, 8, 19),
                             customer_id=1, customer_name='Acme',
                             branch_id=main_branch.id, status='draft'))
    db_session.add(Quotation(quotation_number='90000', quotation_date=date(2026, 8, 19),
                             customer_id=1, customer_name='Acme',
                             branch_id=branch_manila.id, status='draft'))
    db_session.commit()
    assert generate_quotation_number(main_branch.id) == '90001'


def test_generate_quotation_number_continues_from_legacy_literal_number(db_session, main_branch):
    from app.quotations.models import generate_quotation_number
    q = Quotation(quotation_number='4200', quotation_date=date(2026, 7, 9),
                  customer_id=1, customer_name='Legacy Co', branch_id=main_branch.id,
                  status='draft')
    db_session.add(q); db_session.commit()
    assert generate_quotation_number(main_branch.id) == '04201'


def test_generate_quotation_number_ignores_legacy_prefixed_numbers(db_session, main_branch):
    from app.quotations.models import generate_quotation_number
    q = Quotation(quotation_number='QTN-2026-07-0030', quotation_date=date(2026, 7, 9),
                  customer_id=1, customer_name='Legacy Co', branch_id=main_branch.id,
                  status='draft')
    db_session.add(q); db_session.commit()
    assert generate_quotation_number(main_branch.id) == '00001'


def test_calculate_totals_three_treatments():
    # inclusive: 1120 gross -> net 1000, vat 120, total 1120
    inc = _quote('inclusive', ['1120.00'])
    assert inc.subtotal == Decimal('1120.00') and inc.vat_amount == Decimal('120.00')
    assert inc.total_amount == Decimal('1120.00')
    # exclusive: 1000 net -> vat 120, total 1120
    exc = _quote('exclusive', ['1000.00'])
    assert exc.subtotal == Decimal('1000.00') and exc.vat_amount == Decimal('120.00')
    assert exc.total_amount == Decimal('1120.00')
    # zero_rated: 1000 -> vat 0, total 1000
    zr = _quote('zero_rated', ['1000.00'])
    assert zr.vat_amount == Decimal('0.00') and zr.total_amount == Decimal('1000.00')


def test_is_expired_only_when_sent_and_past():
    q = _quote('inclusive', ['100.00'])
    q.status = 'sent'; q.valid_until = date.today() - timedelta(days=1)
    assert q.is_expired is True
    q.status = 'draft'
    assert q.is_expired is False           # draft is never "expired"
    q.status = 'sent'; q.valid_until = date.today() + timedelta(days=5)
    assert q.is_expired is False
