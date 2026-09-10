"""The suggested AP number continues the numbering the client actually uses.

Owner, 2026-09-10. PhilGen's books run plain sequential numbers -- AP 0001,
0002; PO 00984; RR 00634 -- but the generator imposed AP-YYYY-MM-NNNN, so
every bill entered through the app broke out of the client's own sequence.

The rule: read the most recent bill by INSERTION ORDER and increment it in its
own shape, preserving the digit width. Fall back to the built-in format only
when there is nothing to follow.

Insertion order, not a lexicographic sort on the number: this codebase has a
recorded bug report about exactly that (docs/bug-reports/2026-07-12-jv-number-
race-silent-data-loss.md), and a string sort puts '9999' after '10000'.
"""
from datetime import date
from decimal import Decimal

import pytest

from app import db
from app.accounts_payable.models import AccountsPayable

pytestmark = [pytest.mark.integration, pytest.mark.accounts_payable]


def _ap(db_session, main_branch, number, vendor=None):
    ap = AccountsPayable(branch_id=main_branch.id, ap_number=number,
                         ap_date=date(2026, 9, 10), due_date=date(2026, 10, 10),
                         payee_type='vendor', payee_id=(vendor.id if vendor else 1),
                         vendor_id=(vendor.id if vendor else 1),
                         vendor_name='V', notes='', status='draft',
                         subtotal=Decimal('0'), total_amount=Decimal('0'),
                         amount_paid=Decimal('0'), balance=Decimal('0'))
    db.session.add(ap); db.session.commit()
    return ap


class TestItFollowsTheLastEntry:

    def test_a_plain_sequence_continues(self, db_session, main_branch):
        """The case the owner reported: 0002 -> 0003, NOT AP-2026-09-0001."""
        from app.accounts_payable.views import next_ap_number
        _ap(db_session, main_branch, '0001')
        _ap(db_session, main_branch, '0002')
        assert next_ap_number() == '0003'

    def test_the_digit_width_is_preserved(self, db_session, main_branch):
        """0003, not 3. The width IS the format to a bookkeeper."""
        from app.accounts_payable.views import next_ap_number
        _ap(db_session, main_branch, '00984')
        assert next_ap_number() == '00985'

    def test_a_prefixed_sequence_keeps_its_prefix(self, db_session, main_branch):
        from app.accounts_payable.views import next_ap_number
        _ap(db_session, main_branch, '25-0914')
        assert next_ap_number() == '25-0915'

    def test_the_built_in_format_still_increments(self, db_session, main_branch):
        """An install already using AP-YYYY-MM-NNNN must keep doing so."""
        from app.accounts_payable.views import next_ap_number
        _ap(db_session, main_branch, 'AP-2026-09-0002')
        assert next_ap_number() == 'AP-2026-09-0003'

    def test_with_no_bills_at_all_it_falls_back_to_the_built_in_format(
            self, db_session, main_branch):
        from app.accounts_payable.views import next_ap_number
        assert next_ap_number().startswith('AP-')

    def test_a_number_with_no_digits_falls_back(self, db_session, main_branch):
        """Nothing to increment, so invent nothing -- use the built-in format."""
        from app.accounts_payable.views import next_ap_number
        _ap(db_session, main_branch, 'OPENING')
        assert next_ap_number().startswith('AP-')

    def test_it_widens_rather_than_wrapping(self, db_session, main_branch):
        from app.accounts_payable.views import next_ap_number
        _ap(db_session, main_branch, '9999')
        assert next_ap_number() == '10000'

    def test_it_reads_the_LAST_INSERTED_not_the_lexicographically_largest(
            self, db_session, main_branch):
        """THE bug this repo has a report about. Inserted 9999 then 10000: a
        string sort calls '9999' the greatest and would suggest 10000 a second
        time, colliding with a row that already exists."""
        from app.accounts_payable.views import next_ap_number
        _ap(db_session, main_branch, '9999')
        _ap(db_session, main_branch, '10000')
        assert next_ap_number() == '10001'

    def test_a_taken_number_is_skipped(self, db_session, main_branch):
        """Numbers can be typed by hand, so the next one up may already exist.
        Suggesting it would hand the user a value that cannot be saved."""
        from app.accounts_payable.views import next_ap_number
        _ap(db_session, main_branch, '0007')
        _ap(db_session, main_branch, '0005')      # newest by insertion order
        _ap(db_session, main_branch, '0006')      # newest; 0007 is taken
        assert next_ap_number() == '0008'


class TestTheFormOffersIt:

    def test_the_create_form_is_prefilled_with_it(self, client, db_session,
                                                  main_branch, admin_user,
                                                  login_user):
        from app.accounts_payable.views import next_ap_number
        _ap(db_session, main_branch, '0042')
        login_user(client, 'admin', 'admin123')
        with client.session_transaction() as sess:
            sess['selected_branch_id'] = main_branch.id
        html = client.get('/accounts-payable/create').data.decode()
        # Scoped to the rendered input, not a bare substring: '0043' could
        # appear in an amount or an id elsewhere on the page.
        assert 'value="0043"' in html
