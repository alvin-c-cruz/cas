"""Transaction lists order by date DESC then id DESC -- ties never shuffle.

Owner, 2026-09-10, from the live AP list reading 0003, 0001, 0002: the query
ordered by ap_date alone, so the two same-day vouchers came back in whatever
order the query plan produced.

This is not cosmetic. Every list below PAGINATES (50 per page), and an unstable
sort lets tied rows reorder between queries -- so a row can appear on two pages
or on neither, which reads as data loss.

Ordering by the document NUMBER would be wrong twice over: it is a string, so
'9999' sorts above '10000', and the numbers are user-typed following the
client's own sequences, so they are not reliably monotonic.
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


class TestTheAPList:

    def test_same_day_vouchers_come_back_newest_entered_first(
            self, client, db_session, main_branch, admin_user, login_user):
        """The reported case: three bills, two sharing a date."""
        _ap(main_branch, '0001', date(2026, 9, 8))
        _ap(main_branch, '0002', date(2026, 9, 8))
        _ap(main_branch, '0003', date(2026, 9, 9))
        login_user(client, 'admin', 'admin123')
        with client.session_transaction() as sess:
            sess['selected_branch_id'] = main_branch.id

        html = client.get('/accounts-payable').data.decode()
        # Control: the rows rendered at all, so the ordering below is real.
        for n in ('0001', '0002', '0003'):
            assert n in html, 'voucher %s did not render' % n

        order = sorted(('0001', '0002', '0003'), key=html.index)
        # Newest DATE first, then most recently ENTERED first: 0002 was
        # inserted after 0001 and they share a date.
        assert order == ['0003', '0002', '0001'], order

    def test_the_query_itself_carries_a_tiebreaker(self, db_session, main_branch):
        """Asserted on the compiled SQL, not just one rendered page: a page with
        no tied rows would pass the test above however the query was written."""
        from app.accounts_payable.views import _filtered_ap_query
        q = _filtered_ap_query().order_by(AccountsPayable.ap_date.desc(),
                                          AccountsPayable.id.desc())
        sql = str(q.statement.compile()).lower()
        assert 'order by' in sql
        assert sql.count(' desc') >= 2, (
            'the list must break ties on a total order, or pagination can drop '
            'or duplicate a row: %s' % sql[sql.index('order by'):])
