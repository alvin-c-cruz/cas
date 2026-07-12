"""Regression test for BUG-DOCNUMBER-RACE-SILENT-DATA-LOSS (Cash Disbursement).

Two users' browsers can both fetch the SAME suggested cdv_number (neither has
committed yet). Deterministic repro: pre-commit a CashDisbursementVoucher under the
number a fresh `generate_cdv_number()` call would return (simulating "the other user
already won the race"), then POST a create carrying that same stale number
(simulating "the loser's browser still shows the old suggestion").

Unlike JV (a pure system sequence, fixed via silent auto-retry), cdv_number is a
user-editable field meant to mirror a physical pre-printed serial -- so the fix here
does NOT silently commit under a different number. It re-renders the form with a
freshly suggested number pre-filled and an explanatory flash, requiring the user to
review and resubmit. This also preserves the existing duplicate-number UX
(test_cdv_number_editable.py) for a genuinely user-typed duplicate.

See docs/bug-reports/2026-07-12-jv-number-race-silent-data-loss.md and the browser-level
repro clients/cas/ui-tests/concurrency_cd_concurrent_create.py.
"""
import json

import pytest

from app import db
from app.accounts.models import Account
from app.vendors.models import Vendor
from app.cash_disbursements.models import CashDisbursementVoucher
from app.cash_disbursements.views import generate_cdv_number
from app.utils import ph_now

pytestmark = [pytest.mark.integration, pytest.mark.cash_disbursements]


def login(client):
    client.post('/login', data={'username': 'admin', 'password': 'admin123'},
                follow_redirects=True)


def setup_accounts(db_session):
    ap = Account(code='20101', name='AP Trade', account_type='Liability',
                 normal_balance='credit', is_active=True)
    wt = Account(code='20301', name='WHT Payable', account_type='Liability',
                 normal_balance='credit', is_active=True)
    cash = Account(code='10101', name='Cash on Hand', account_type='Asset',
                   normal_balance='debit', is_active=True)
    exp = Account(code='60101', name='Office Supplies', account_type='Expense',
                  normal_balance='debit', is_active=True)
    db_session.add_all([ap, wt, cash, exp])
    db_session.commit()
    from tests.conftest import assign_control_accounts
    assign_control_accounts(db_session)
    return ap, wt, cash, exp


def make_vendor(db_session):
    v = Vendor(code='CDR01', name='Race Vendor', check_payee_name='Race Vendor', is_active=True)
    db_session.add(v)
    db_session.commit()
    return v


def post_create(client, vendor, cash, exp, cdv_number, notes='race test'):
    expense_lines = [{'description': 'Supplies', 'amount': 500.0,
                      'vat_category': '', 'account_id': exp.id, 'wt_id': None}]
    return client.post('/cash-disbursements/create', data={
        'cdv_number': cdv_number,
        'cdv_date': ph_now().date().isoformat(),
        'vendor_id': vendor.id,
        'payment_method': 'cash',
        'cash_account_id': cash.id,
        'notes': notes,
        'ap_lines': json.dumps([]),
        'expense_lines': json.dumps(expense_lines),
        'vat_override': '0', 'vat_override_value': '0',
        'wt_override': '0', 'wt_override_value': '0',
    }, follow_redirects=False)


class TestCdvNumberRace:
    def test_create_does_not_silently_lose_work_on_a_number_taken_by_a_concurrent_commit(
            self, client, db_session, admin_user, main_branch):
        login(client)
        ap, wt, cash, exp = setup_accounts(db_session)
        vendor = make_vendor(db_session)

        taken_number = generate_cdv_number()
        winner = CashDisbursementVoucher(
            branch_id=main_branch.id, cdv_number=taken_number, cdv_date=ph_now().date(),
            vendor_id=vendor.id, vendor_name=vendor.name, vendor_tin=vendor.tin,
            payment_method='cash', cash_account_id=cash.id, notes='concurrent winner',
            status='draft', created_by_id=admin_user.id,
        )
        db.session.add(winner)
        db.session.commit()

        resp = post_create(client, vendor, cash, exp, taken_number, notes='concurrency test loser')

        assert resp.status_code == 200, 'must re-render the form, not redirect as if it succeeded'
        loser = CashDisbursementVoucher.query.filter_by(notes='concurrency test loser').first()
        assert loser is None, 'must NOT silently create a second CDV under the stale number'

        body = resp.get_data(as_text=True)
        assert taken_number not in _cdv_number_field_value(body), (
            'the re-rendered form must show a FRESH suggested number, not the stale one'
        )
        fresh = _cdv_number_field_value(body)
        assert fresh and fresh != taken_number

        # Resubmitting with the fresh number must succeed.
        resp2 = post_create(client, vendor, cash, exp, fresh, notes='concurrency test loser retry')
        assert resp2.status_code == 302
        retried = CashDisbursementVoucher.query.filter_by(notes='concurrency test loser retry').first()
        assert retried is not None
        assert retried.cdv_number == fresh


def _cdv_number_field_value(html):
    import re
    m = re.search(r'id="cdv_number"[^>]*value="([^"]*)"', html)
    if not m:
        m = re.search(r'value="([^"]*)"[^>]*id="cdv_number"', html)
    return m.group(1) if m else ''
