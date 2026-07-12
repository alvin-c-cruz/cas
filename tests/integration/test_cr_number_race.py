"""Regression test for BUG-DOCNUMBER-RACE-SILENT-DATA-LOSS (Cash Receipt).

Unlike JV (a pure system sequence, fixed with a silent auto-retry), crv_number is a
user-editable field meant to mirror a physical pre-printed receipt serial (see
test_crv_number_preprinted.py / memory project-preprinted-document-numbers). So the
fix here is SURFACED, not silent: on a collision, re-render the form with a freshly
suggested number and an explanatory flash -- never auto-commit under a different
number than what the user saw, since a collision might be a genuine duplicate-entry
mistake on a real physical serial, not just a race.

Deterministic repro: pre-commit a CashReceiptVoucher under the number a fresh
generate_crv_number() call would return (simulating "another user already won the
race"), then POST a create carrying that same stale number (simulating "the loser's
browser still shows the old suggestion"). The create must NOT silently fail with a
generic error and must NOT silently commit under a swapped number -- it must
re-render with a fresh suggestion, and a resubmission with that fresh number must
then succeed.

See docs/bug-reports/2026-07-12-jv-number-race-silent-data-loss.md and the
browser-level repro clients/cas/ui-tests/concurrency_cr_concurrent_create.py.
"""
import json
import re

import pytest
from decimal import Decimal

from app import db
from app.accounts.models import Account
from app.customers.models import Customer
from app.cash_receipts.models import CashReceiptVoucher
from app.cash_receipts.views import generate_crv_number
from app.utils import ph_now

pytestmark = [pytest.mark.integration, pytest.mark.cash_receipts]


def login(client):
    client.post('/login', data={'username': 'admin', 'password': 'admin123'},
                follow_redirects=True)


def setup_accounts(db_session):
    ar = Account(code='10201', name='AR Trade', account_type='Asset', normal_balance='debit', is_active=True)
    wt = Account(code='10212', name='WHT Receivable', account_type='Asset', normal_balance='debit', is_active=True)
    cash = Account(code='10101', name='Cash on Hand', account_type='Asset', normal_balance='debit', is_active=True)
    rev = Account(code='40101', name='Service Revenue', account_type='Income', normal_balance='credit', is_active=True)
    db_session.add_all([ar, wt, cash, rev])
    db_session.commit()
    from tests.conftest import assign_control_accounts
    assign_control_accounts(db_session)
    return ar, wt, cash, rev


def make_customer(db_session):
    c = Customer(code='CRRACE1', name='CR Race Customer', is_active=True)
    db_session.add(c)
    db_session.commit()
    return c


def post_create(client, customer, cash, rev, crv_number):
    revenue_lines = [{'description': 'Service fee', 'amount': 1000.0,
                      'vat_category': '', 'account_id': rev.id, 'wt_id': None}]
    return client.post('/cash-receipts/create', data={
        'crv_number': crv_number,
        'crv_date': ph_now().date().isoformat(),
        'customer_id': customer.id,
        'payment_method': 'cash',
        'cash_account_id': cash.id,
        'notes': 'race test particulars',
        'ar_lines': json.dumps([]),
        'revenue_lines': json.dumps(revenue_lines),
        'vat_override': '0', 'vat_override_value': '0',
        'wt_override': '0', 'wt_override_value': '0',
    }, follow_redirects=False)


def _extract_crv_number_value(html):
    m = re.search(r'name="crv_number"[^>]*value="([^"]*)"', html)
    if not m:
        m = re.search(r'value="([^"]*)"[^>]*name="crv_number"', html)
    return m.group(1) if m else None


class TestCrNumberRace:

    def test_create_surfaces_a_fresh_number_instead_of_failing_or_silently_swapping(
            self, client, db_session, admin_user, main_branch):
        login(client)
        ar, wt, cash, rev = setup_accounts(db_session)
        customer = make_customer(db_session)

        taken_number = generate_crv_number()
        winner = CashReceiptVoucher(
            branch_id=main_branch.id, crv_number=taken_number, crv_date=ph_now().date(),
            customer_id=customer.id, customer_name=customer.name, customer_tin=customer.tin,
            payment_method='cash', cash_account_id=cash.id, notes='concurrent winner',
            status='draft', created_by_id=admin_user.id,
        )
        db.session.add(winner)
        db.session.commit()

        resp = post_create(client, customer, cash, rev, crv_number=taken_number)

        assert resp.status_code == 200, (
            'a collision must re-render the form (200), not redirect as if it succeeded'
        )
        assert CashReceiptVoucher.query.filter_by(crv_number=taken_number).count() == 1, (
            'must not silently create a second row under the stale number'
        )
        body = resp.get_data(as_text=True)
        assert 'was just taken' in body or 'already exists' in body, (
            'the re-rendered form must explain the collision'
        )
        fresh_number = _extract_crv_number_value(body)
        assert fresh_number is not None, 'could not find the crv_number field in the response'
        assert fresh_number != taken_number, (
            'the re-rendered form must carry a FRESH suggested number, not the stale one'
        )

        # Resubmitting with the fresh number must succeed.
        resp2 = post_create(client, customer, cash, rev, crv_number=fresh_number)
        assert resp2.status_code == 302, 'resubmitting with the fresh number must succeed'
        assert CashReceiptVoucher.query.filter_by(crv_number=fresh_number).count() == 1
