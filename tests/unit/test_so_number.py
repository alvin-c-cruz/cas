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


# -- the branch's own series (owner, 2026-09-25) ------------------------------
#
# "Check the SO# for Corp and Extra, they should increment based of the last number
# on record." Philgen's SOs are 00001E, 00002E -- five digits plus the branch marker,
# typed off the pad -- which generate_so_number's YYYYMMnnnn shape never recognised,
# so it suggested a number from a different series. next_so_number_for continues the
# branch's own series (the CV pad rule, 2026-09-24): numeric max + 1, width and marker
# kept, generated-shape numbers ignored, a taken number skipped, and the generator as
# the fallback for a branch with nothing on record.

from app.sales_orders.views import next_so_number_for


def _so(number, branch, c):
    db.session.add(SalesOrder(so_number=number, order_date=date(2026, 9, 22), customer_id=c.id,
                              customer_name='C', branch_id=branch.id))
    db.session.commit()


@pytest.fixture
def cust(db_session):
    c = Customer(code='CPAD', name='C'); db.session.add(c); db.session.commit()
    return c


def test_extra_continues_its_own_series(db_session, cust):
    extra = _extra_branch(db_session)
    _so('00001E', extra, cust); _so('00002E', extra, cust)
    assert next_so_number_for(extra, date(2026, 9, 25)) == '00003E'


def test_corp_continues_its_own_series(db_session, main_branch, cust):
    _so('00041', main_branch, cust); _so('00040', main_branch, cust)
    assert next_so_number_for(main_branch, date(2026, 9, 25)) == '00042'


def test_the_branches_do_not_mix(db_session, main_branch, cust):
    extra = _extra_branch(db_session)
    _so('00100', main_branch, cust); _so('00002E', extra, cust)
    assert next_so_number_for(extra, date(2026, 9, 25)) == '00003E'
    assert next_so_number_for(main_branch, date(2026, 9, 25)) == '00101'


def test_generated_shape_numbers_do_not_hijack_the_series(db_session, cust):
    """'2026090001E' is all digits too; read as a pad number it would win every max."""
    extra = _extra_branch(db_session)
    _so('2026090001E', extra, cust); _so('00002E', extra, cust)
    assert next_so_number_for(extra, date(2026, 9, 25)) == '00003E'


def test_width_grows_on_overflow(db_session, main_branch, cust):
    _so('99999', main_branch, cust)
    assert next_so_number_for(main_branch, date(2026, 9, 25)) == '100000'


def test_a_taken_number_is_skipped(db_session, main_branch, cust):
    extra = _extra_branch(db_session)
    _so('00002E', extra, cust)
    _so('00003E', main_branch, cust)     # so_number is unique company-wide
    assert next_so_number_for(extra, date(2026, 9, 25)) == '00004E'


def test_nothing_on_record_falls_back_to_the_generator(db_session, main_branch):
    assert next_so_number_for(main_branch, date(2026, 9, 25)) == '2026090001'
