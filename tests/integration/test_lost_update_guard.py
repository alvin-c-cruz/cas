"""Integration tests for the lost-update guard on transaction document edits.

Two encoders open the same draft.  The second save must be refused, and the
refusal must not damage the winner's data: every edit route is a replace-all
that discards the stored lines and (for APV/CDV/CRV) deletes and recreates the
linked journal entry, so a losing request that gets as far as the teardown has
already destroyed the winner's rows.

The guard therefore has to be the FIRST write of the request, not a check
performed somewhere before the commit.
"""
import json
import pytest
from datetime import date
from decimal import Decimal

from app.accounts.models import Account
from app.accounts_payable.models import AccountsPayable, AccountsPayableItem
from app.journal_entries.models import JournalEntry
from app.vendors.models import Vendor

pytestmark = [pytest.mark.integration, pytest.mark.accounts_payable]


def login(client, username='accountant', password='accountant123'):
    client.post('/login', data={'username': username, 'password': password},
                follow_redirects=True)


def make_vendor(db_session, code='LUG001'):
    v = Vendor(code=code, name='Guard Vendor', check_payee_name='Guard Vendor',
               is_active=True, payment_terms='Net 30')
    db_session.add(v)
    db_session.commit()
    return v


def get_or_create_account(db_session, code, name, acct_type):
    a = Account.query.filter_by(code=code).first()
    if not a:
        a = Account(code=code, name=name, account_type=acct_type,
                    normal_balance='debit' if acct_type == 'Expense' else 'credit',
                    is_active=True)
        db_session.add(a)
        db_session.commit()
    return a


def line_items(amount, account_id):
    return json.dumps([{
        'description': 'Guard Line', 'amount': amount, 'vat_category': '',
        'account_id': account_id, 'wt_id': None, 'wt_rate': None,
    }])


def ap_payload(vendor, exp, amount, row_version, ap_number='AP-GUARD-0001'):
    data = {
        'ap_number': ap_number,
        'ap_date': date.today().isoformat(),
        'due_date': date.today().isoformat(),
        'vendor_id': vendor.id,
        'payment_terms': 'Net 30',
        'notes': 'guard test',
        'line_items': line_items(amount, exp.id),
        'vat_override': '0', 'vat_override_value': '0',
        'wt_override': '0', 'wt_override_value': '0',
    }
    if row_version is not None:
        data['row_version'] = row_version
    return data


@pytest.fixture
def bill(client, db_session, accountant_user, main_branch):
    """A freshly created draft APV at row_version 1."""
    login(client)
    vendor = make_vendor(db_session)
    get_or_create_account(db_session, '20101', 'Accounts Payable - Trade', 'Liability')
    exp = get_or_create_account(db_session, '61001', 'Rent Expense', 'Expense')

    client.post('/accounts-payable/create',
                data=ap_payload(vendor, exp, 5000.00, row_version=None),
                follow_redirects=True)

    ap = AccountsPayable.query.order_by(AccountsPayable.id.desc()).first()
    assert ap is not None, 'setup: bill was not created'
    assert ap.status == 'draft'
    return ap, vendor, exp


class TestAPVLostUpdateGuard:

    def test_fresh_document_starts_at_version_one(self, bill, db_session):
        ap, _, _ = bill
        assert ap.row_version == 1

    def test_a_normal_edit_succeeds_and_bumps_the_version(self, client, db_session, bill):
        ap, vendor, exp = bill

        client.post(f'/accounts-payable/{ap.id}/edit',
                    data=ap_payload(vendor, exp, 6000.00, row_version=1),
                    follow_redirects=True)

        db_session.expire_all()
        ap = db_session.get(AccountsPayable, ap.id)
        assert ap.row_version == 2
        assert ap.subtotal == Decimal('6000.00')

    def test_second_encoder_with_a_stale_token_is_refused(self, client, db_session, bill):
        """The whole point: B saves, then A saves with A's original token."""
        ap, vendor, exp = bill
        ap_id = ap.id

        # Encoder B wins the race.
        client.post(f'/accounts-payable/{ap_id}/edit',
                    data=ap_payload(vendor, exp, 6000.00, row_version=1),
                    follow_redirects=True)

        # Encoder A submits the form they loaded before B saved.
        resp = client.post(f'/accounts-payable/{ap_id}/edit',
                           data=ap_payload(vendor, exp, 9999.00, row_version=1),
                           follow_redirects=True)

        assert b'NOT saved' in resp.data
        assert b'reload' in resp.data.lower()

        db_session.expire_all()
        ap = db_session.get(AccountsPayable, ap_id)
        assert ap.row_version == 2, 'a losing save must not bump the version'
        assert ap.subtotal == Decimal('6000.00'), "encoder B's amount must survive"

    def test_losing_save_does_not_destroy_the_winners_lines(self, client, db_session, bill):
        ap, vendor, exp = bill
        ap_id = ap.id

        client.post(f'/accounts-payable/{ap_id}/edit',
                    data=ap_payload(vendor, exp, 6000.00, row_version=1),
                    follow_redirects=True)

        client.post(f'/accounts-payable/{ap_id}/edit',
                    data=ap_payload(vendor, exp, 9999.00, row_version=1),
                    follow_redirects=True)

        db_session.expire_all()
        lines = AccountsPayableItem.query.filter_by(ap_id=ap_id).all()
        assert len(lines) == 1, 'the winner lines must not be deleted by the loser'
        assert lines[0].amount == Decimal('6000.00')

    def test_losing_save_does_not_destroy_the_winners_journal_entry(
            self, client, db_session, bill):
        """edit() deletes and recreates the JE -- the loser must never get there.

        Assert on the JE's AMOUNT, not its id: edit() deletes the old JE row and
        SQLite happily reuses the freed integer, so an id comparison passes even
        when the JE was in fact destroyed and rebuilt from the loser's payload.
        """
        ap, vendor, exp = bill
        ap_id = ap.id

        client.post(f'/accounts-payable/{ap_id}/edit',
                    data=ap_payload(vendor, exp, 6000.00, row_version=1),
                    follow_redirects=True)
        db_session.expire_all()
        winner_je_id = db_session.get(AccountsPayable, ap_id).journal_entry_id
        assert winner_je_id is not None

        client.post(f'/accounts-payable/{ap_id}/edit',
                    data=ap_payload(vendor, exp, 9999.00, row_version=1),
                    follow_redirects=True)

        db_session.expire_all()
        ap = db_session.get(AccountsPayable, ap_id)
        assert JournalEntry.query.count() == 1

        je = db_session.get(JournalEntry, ap.journal_entry_id)
        assert je is not None
        debits = sorted(l.debit_amount for l in je.lines if l.debit_amount)
        assert debits == [Decimal('6000.00')], \
            "the JE must still carry the winner's amount, not the loser's"

    def test_missing_token_fails_closed(self, client, db_session, bill):
        """An edit POST with no token at all must be refused, not waved through."""
        ap, vendor, exp = bill
        ap_id = ap.id

        resp = client.post(f'/accounts-payable/{ap_id}/edit',
                           data=ap_payload(vendor, exp, 9999.00, row_version=None),
                           follow_redirects=True)

        assert b'NOT saved' in resp.data
        db_session.expire_all()
        ap = db_session.get(AccountsPayable, ap_id)
        assert ap.row_version == 1
        assert ap.subtotal == Decimal('5000.00')

    def test_conflict_page_redisplays_the_losers_typed_lines(self, client, db_session, bill):
        """The loser's work stays on screen; only reload replaces it."""
        ap, vendor, exp = bill
        ap_id = ap.id

        client.post(f'/accounts-payable/{ap_id}/edit',
                    data=ap_payload(vendor, exp, 6000.00, row_version=1),
                    follow_redirects=True)

        resp = client.post(f'/accounts-payable/{ap_id}/edit',
                           data=ap_payload(vendor, exp, 9999.00, row_version=1),
                           follow_redirects=True)

        assert b'9999' in resp.data, "the loser's typed amount must be restored"

    def test_conflict_rerender_carries_the_stale_token_so_resave_fails_again(
            self, client, db_session, bill):
        """No 'Save Anyway': re-submitting the conflicted form must fail identically."""
        ap, vendor, exp = bill
        ap_id = ap.id

        client.post(f'/accounts-payable/{ap_id}/edit',
                    data=ap_payload(vendor, exp, 6000.00, row_version=1),
                    follow_redirects=True)
        client.post(f'/accounts-payable/{ap_id}/edit',
                    data=ap_payload(vendor, exp, 9999.00, row_version=1),
                    follow_redirects=True)

        # The re-rendered form still holds token 1, so pressing Save again re-conflicts.
        resp = client.post(f'/accounts-payable/{ap_id}/edit',
                           data=ap_payload(vendor, exp, 9999.00, row_version=1),
                           follow_redirects=True)
        assert b'NOT saved' in resp.data

        db_session.expire_all()
        assert db_session.get(AccountsPayable, ap_id).subtotal == Decimal('6000.00')
