"""Regression test for BUG-DOCNUMBER-RACE-SILENT-DATA-LOSS (Accounts Payable).

ap_number is user-editable (mirrors a physical pre-printed serial) -- unlike JV's
silent auto-retry, a collision here must be SURFACED: the create form re-renders
with a freshly suggested number and an explanatory flash, never silently
substituting the user's value or discarding the submission with a bare error.

See docs/bug-reports/2026-07-12-jv-number-race-silent-data-loss.md and the
browser-level repro clients/cas/ui-tests/concurrency_ap_concurrent_create.py.
"""
import json
import re
from datetime import date, timedelta
from decimal import Decimal

import pytest

from app import db
from app.accounts.models import Account
from app.accounts_payable.models import AccountsPayable
from app.accounts_payable.views import generate_ap_number
from app.vendors.models import Vendor
from tests.conftest import assign_control_accounts

pytestmark = [pytest.mark.integration, pytest.mark.accounts_payable]


def login(client, username='admin', password='admin123'):
    client.post('/login', data={'username': username, 'password': password},
                follow_redirects=True)


def _seed():
    vendor = Vendor(code='RACEV01', name='Race Test Vendor',
                     check_payee_name='Race Test Vendor', is_active=True,
                     payment_terms='Net 30')
    expense = Account(code='69900', name='Race Test Expense', account_type='Expense',
                       normal_balance='debit', is_active=True)
    ap_trade = Account(code='20101', name='Accounts Payable - Trade', account_type='Liability',
                        normal_balance='credit', is_active=True)
    db.session.add_all([vendor, expense, ap_trade])
    db.session.commit()
    return vendor, expense


def _lines_payload(account_id, amount='100.00'):
    return json.dumps([{'description': 'race line', 'amount': amount,
                         'vat_category': '', 'account_id': account_id, 'wt_id': None}])


def _post(client, ap_number, vendor_id, account_id, notes='race test'):
    return client.post('/accounts-payable/create', data={
        'ap_number': ap_number,
        'ap_date': date.today().isoformat(),
        'due_date': (date.today() + timedelta(days=30)).isoformat(),
        'vendor_id': vendor_id,
        'payment_terms': 'Net 30',
        'notes': notes,
        'line_items': _lines_payload(account_id),
        'vat_override': '0', 'vat_override_value': '0',
        'wt_override': '0', 'wt_override_value': '0',
    }, follow_redirects=False)


def _extract_value(body, field_name):
    tag = re.search(r'<input[^>]*\bname="%s"[^>]*>' % field_name, body)
    assert tag, 'no <input name="%s"> found in the response' % field_name
    val = re.search(r'value="([^"]*)"', tag.group(0))
    return val.group(1) if val else ''


def test_collision_is_surfaced_not_silently_lost_or_substituted(
        client, admin_user, main_branch, db_session):
    login(client)
    assign_control_accounts(db_session)
    vendor, expense = _seed()

    taken_number = generate_ap_number()
    winner = AccountsPayable(
        ap_number=taken_number, vendor_id=vendor.id, vendor_name=vendor.name,
        vendor_tin='', vendor_address='', branch_id=main_branch.id,
        ap_date=date.today(), due_date=date.today(), status='draft',
        subtotal=Decimal('1.00'), vat_amount=Decimal('0.00'),
        total_before_wt=Decimal('1.00'), withholding_tax_rate=Decimal('0.00'),
        withholding_tax_amount=Decimal('0.00'), total_amount=Decimal('1.00'),
        amount_paid=Decimal('0.00'), balance=Decimal('1.00'), payment_terms='Net 30',
    )
    db.session.add(winner)
    db.session.commit()

    resp = _post(client, taken_number, vendor.id, expense.id,
                 notes='concurrency test loser')

    assert resp.status_code == 200, 'must re-render the form, not redirect as if it succeeded'
    loser = AccountsPayable.query.filter_by(notes='concurrency test loser').first()
    assert loser is None, 'must NOT silently create a bill under the stale colliding number'

    body = resp.get_data(as_text=True)
    assert 'already in use' in body.lower()
    fresh_number = _extract_value(body, 'ap_number')
    assert fresh_number and fresh_number != taken_number

    # Resubmitting with the fresh, suggested number must succeed.
    resp2 = _post(client, fresh_number, vendor.id, expense.id,
                  notes='concurrency test loser retry')
    assert resp2.status_code == 302
    retried = AccountsPayable.query.filter_by(notes='concurrency test loser retry').first()
    assert retried is not None
    assert retried.ap_number == fresh_number
