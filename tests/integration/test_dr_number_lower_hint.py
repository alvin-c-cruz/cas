"""B5-W A: a DR number typed lower than the last one gets a hint beside DR #; saving still goes through.

Owner, typed in the root 23 Nov 2026 13:4x: "B5-W A". As put to him: "A hint beside DR # as soon as a lower number is
typed: 'Lower than the last DR number, 0275 -- fine if it is the paper's number'. Saving still goes through." Philgen
SO-DR trial, 22 Nov 2026: DR 0264 was typed after 0275 and accepted silently (a number equal to an existing DR is
already refused). Work order: 2026-11-22-so-dr-form-minor-polish.md (item 2).

"The last DR number" is the highest plain-digit DR number in the series a new DR continues: the same numbers the
automatic numbering counts (app/utils/doc_numbering.py), company-wide unless the series is per branch. The browser part
(the hint appearing while typing) is tests/e2e/test_dr_number_hint_smoke.py.
"""
import re
from datetime import date

import pytest

from app import db
from app.branches.models import Branch
from app.customers.models import Customer
from app.delivery_receipts.models import DeliveryReceipt, last_dr_number
from app.settings import AppSettings
from tests.integration.test_delivery_receipts_lifecycle import _branch, _login, dr_enabled  # noqa: F401
from tests.integration.test_dr_without_sales_order import _create, _last, stuff  # noqa: F401

pytestmark = [pytest.mark.integration, pytest.mark.delivery_receipts]


def _dr(number, branch_id, customer_id):
    db.session.add(DeliveryReceipt(dr_number=number, branch_id=branch_id, delivery_date=date(2026, 11, 22),
                                   customer_id=customer_id, customer_name='Hi-Las', status='draft'))
    db.session.commit()


@pytest.fixture
def hilas(db_session):
    c = Customer(code='C-HL', name='Hi-Las', is_active=True)
    db.session.add(c); db.session.commit()
    return c


@pytest.fixture
def other_branch(db_session):
    b = Branch(code='GS', name='GenSan', is_active=True)
    db.session.add(b); db.session.commit()
    return b


def _hint(html):
    return re.search(r'<div[^>]*id="dr-number-hint"[^>]*>', html)


class TestTheLastNumber:

    def test_none_without_a_numbered_dr(self, db_session, main_branch, hilas):
        assert last_dr_number(main_branch.id) is None
        _dr('DR-2026-07-0030', main_branch.id, hilas.id)        # an old prefixed number is not in the series
        assert last_dr_number(main_branch.id) is None

    def test_the_highest_plain_number_as_written(self, db_session, main_branch, hilas):
        for number in ('0264', '0275', '0270', 'DR-2026-07-0030'):
            _dr(number, main_branch.id, hilas.id)
        assert last_dr_number(main_branch.id) == '0275'

    def test_by_value_not_by_text(self, db_session, main_branch, hilas):
        for number in ('999', '01000'):
            _dr(number, main_branch.id, hilas.id)
        assert last_dr_number(main_branch.id) == '01000'

    def test_company_wide_by_default(self, db_session, main_branch, other_branch, hilas):
        _dr('0275', main_branch.id, hilas.id)
        _dr('50010', other_branch.id, hilas.id)
        assert last_dr_number(main_branch.id) == '50010'

    def test_per_branch_when_the_series_is(self, db_session, main_branch, other_branch, hilas):
        AppSettings.set_setting('document_number_scope', 'branch', 'admin')
        db_session.commit()
        _dr('0275', main_branch.id, hilas.id)
        _dr('50010', other_branch.id, hilas.id)
        assert last_dr_number(main_branch.id) == '0275'
        assert last_dr_number(other_branch.id) == '50010'


class TestThePage:

    def test_a_new_dr_carries_the_last_number_for_the_hint(self, client, db_session, admin_user, main_branch, hilas):
        for number in ('0264', '0275'):
            _dr(number, main_branch.id, hilas.id)
        _login(client, admin_user); _branch(client, main_branch.id)
        html = client.get('/delivery-receipts/create').get_data(as_text=True)
        tag = _hint(html)
        assert tag and 'data-last="0275"' in tag.group(0) and 'display:none' in tag.group(0), tag
        assert 'js/dr_number_hint.js' in html

    def test_no_hint_without_a_last_number(self, client, db_session, admin_user, main_branch):
        _login(client, admin_user); _branch(client, main_branch.id)
        assert _hint(client.get('/delivery-receipts/create').get_data(as_text=True)) is None

    def test_no_hint_when_editing(self, client, db_session, admin_user, main_branch, stuff):
        """A saved DR's own number is older than the last one; that is no news."""
        cust, prod, _ = stuff
        _login(client, admin_user); _branch(client, main_branch.id)
        _create(client, cust.id, [{'product_id': prod.id, 'delivered_quantity': '1'}], dr_source='none',
                dr_number='0264')
        _dr('0275', main_branch.id, cust.id)
        own = DeliveryReceipt.query.filter_by(dr_number='0264').one()
        assert _hint(client.get(f'/delivery-receipts/{own.id}/edit').get_data(as_text=True)) is None


class TestSavingStillGoesThrough:

    def test_a_lower_number_is_saved(self, client, db_session, admin_user, main_branch, stuff):
        cust, prod, _ = stuff
        _dr('0275', main_branch.id, cust.id)
        _login(client, admin_user); _branch(client, main_branch.id)
        _create(client, cust.id, [{'product_id': prod.id, 'delivered_quantity': '1'}], dr_source='none',
                dr_number='0264')
        assert _last().dr_number == '0264'
