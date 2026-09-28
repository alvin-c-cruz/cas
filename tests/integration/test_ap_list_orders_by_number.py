"""The AP list is arranged by AP NUMBER, highest first -- numerically.

Owner, 2026-09-28, from the live EXTRA list reading 0012E above 0013E: the
list ordered by date, and 0012E carried the same date as 0013E but was
entered later. The owner reads the list as a numbered register and wants it
in AP# order.

Ordering by the raw string would be wrong: Philgen's own numbers change
width mid-series ('0009' then '00010'), and '0009' > '00010' as text. The
sort key is the NUMERIC value of the number; id DESC stays as the tiebreaker
so pagination keeps a total order (tests/integration/
test_list_ordering_is_stable.py).
"""
from datetime import date
from decimal import Decimal

import pytest

from app import db
from app.accounts_payable.models import AccountsPayable

pytestmark = [pytest.mark.integration, pytest.mark.accounts_payable]


def _ap(main_branch, number, when):
    ap = AccountsPayable(branch_id=main_branch.id, ap_number=number,
                         ap_date=when, due_date=date(2026, 10, 31),
                         payee_type='vendor', payee_id=1, vendor_id=1,
                         vendor_name='V', notes='', status='posted',
                         subtotal=Decimal('0'), total_amount=Decimal('0'),
                         amount_paid=Decimal('0'), balance=Decimal('0'))
    db.session.add(ap); db.session.commit()
    return ap


def _rendered_order(client, numbers):
    html = client.get('/accounts-payable').data.decode()
    for n in numbers:
        assert n in html, 'voucher %s did not render' % n
    return sorted(numbers, key=html.index)


class TestTheAPListIsInNumberOrder:

    def test_later_number_entered_earlier_still_lists_first(
            self, client, db_session, main_branch, admin_user, login_user):
        """The reported case: 0013E entered before 0012E, same date."""
        _ap(main_branch, '0013E', date(2026, 9, 23))
        _ap(main_branch, '0012E', date(2026, 9, 23))
        _ap(main_branch, '0011E', date(2026, 9, 23))
        login_user(client, 'admin', 'admin123')
        with client.session_transaction() as sess:
            sess['selected_branch_id'] = main_branch.id

        assert _rendered_order(client, ('0011E', '0012E', '0013E')) == \
            ['0013E', '0012E', '0011E']

    def test_number_order_beats_date_order(
            self, client, db_session, main_branch, admin_user, login_user):
        """A back-dated voucher with the higher number still lists first."""
        _ap(main_branch, '0005', date(2026, 9, 20))
        _ap(main_branch, '0006', date(2026, 9, 1))   # older date, higher number
        login_user(client, 'admin', 'admin123')
        with client.session_transaction() as sess:
            sess['selected_branch_id'] = main_branch.id

        assert _rendered_order(client, ('0005', '0006')) == ['0006', '0005']

    def test_width_change_in_the_series_sorts_numerically_not_as_text(
            self, client, db_session, main_branch, admin_user, login_user):
        """Philgen's CORP run goes 0009 -> 00010: as text '0009' > '00010'."""
        _ap(main_branch, '00010', date(2026, 9, 10))
        _ap(main_branch, '0009', date(2026, 9, 10))
        login_user(client, 'admin', 'admin123')
        with client.session_transaction() as sess:
            sess['selected_branch_id'] = main_branch.id

        assert _rendered_order(client, ('0009', '00010')) == ['00010', '0009']
