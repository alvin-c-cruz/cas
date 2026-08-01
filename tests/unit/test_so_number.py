import pytest
from datetime import date
from app import db
from app.branches.models import Branch
from app.customers.models import Customer
from app.sales_orders.models import SalesOrder
from app.sales_orders.views import generate_so_number
pytestmark = [pytest.mark.usefixtures("app"), pytest.mark.sales_orders]


def _extra_branch(db_session):
    b = Branch(code='EXTRA', name='Extra Branch', is_active=True)
    db.session.add(b); db.session.commit()
    return b


def test_first_number_format_corp_no_suffix(db_session, main_branch):
    n = generate_so_number(main_branch, date(2025, 12, 18))
    assert n == '2025120001'


def test_first_number_format_extra_gets_e_suffix(db_session):
    extra = _extra_branch(db_session)
    n = generate_so_number(extra, date(2025, 12, 18))
    assert n == '2025120001E'


def test_increments_within_same_branch_and_month(db_session, main_branch):
    c = Customer(code='C001', name='C'); db.session.add(c); db.session.commit()
    n1 = generate_so_number(main_branch, date(2025, 12, 18))
    db.session.add(SalesOrder(so_number=n1, order_date=date(2025, 12, 18), customer_id=c.id,
                              customer_name='C', branch_id=main_branch.id))
    db.session.commit()
    assert generate_so_number(main_branch, date(2025, 12, 20)) == '2025120002'


def test_resets_the_following_month(db_session, main_branch):
    c = Customer(code='C001', name='C'); db.session.add(c); db.session.commit()
    db.session.add(SalesOrder(so_number='2025120001', order_date=date(2025, 12, 18),
                              customer_id=c.id, customer_name='C', branch_id=main_branch.id))
    db.session.commit()
    assert generate_so_number(main_branch, date(2026, 1, 5)) == '2026010001'


def test_corp_and_extra_sequences_are_independent(db_session, main_branch):
    extra = _extra_branch(db_session)
    c = Customer(code='C001', name='C'); db.session.add(c); db.session.commit()
    db.session.add(SalesOrder(so_number='2025120001', order_date=date(2025, 12, 18),
                              customer_id=c.id, customer_name='C', branch_id=main_branch.id))
    db.session.commit()
    # CORP already has one Dec-2025 SO; EXTRA has none -- EXTRA still starts at 0001.
    assert generate_so_number(main_branch, date(2025, 12, 20)) == '2025120002'
    assert generate_so_number(extra, date(2025, 12, 20)) == '2025120001E'


def test_ignores_legacy_prefixed_numbers(db_session, main_branch):
    c = Customer(code='C002', name='C'); db.session.add(c); db.session.commit()
    db.session.add(SalesOrder(so_number='SO-2026-07-0030', order_date=date(2026, 7, 1),
                              customer_id=c.id, customer_name='C', branch_id=main_branch.id))
    db.session.commit()
    assert generate_so_number(main_branch, date(2026, 7, 15)) == '2026070001'
