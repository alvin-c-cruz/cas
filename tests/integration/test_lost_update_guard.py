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
from app.cash_disbursements.models import CashDisbursementVoucher
from app.journal_entries.models import JournalEntry
from app.utils import ph_now
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
                    normal_balance='debit' if acct_type in ('Expense', 'Asset') else 'credit',
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
    from tests.conftest import assign_control_accounts
    assign_control_accounts(db_session)

    client.post('/accounts-payable/create',
                data=ap_payload(vendor, exp, 5000.00, row_version=None),
                follow_redirects=True)

    ap = AccountsPayable.query.order_by(AccountsPayable.id.desc()).first()
    assert ap is not None, 'setup: bill was not created'
    assert ap.status == 'draft'
    return ap, vendor, exp


def admin_login(client):
    client.post('/login', data={'username': 'admin', 'password': 'admin123'},
                follow_redirects=True)


def cdv_payload(vendor, cash, exp, amount, row_version, cdv_number='CD-GUARD-0001',
                check_number=None):
    data = {
        'cdv_number': cdv_number,
        'cdv_date': ph_now().date().isoformat(),
        'vendor_id': vendor.id,
        'payment_method': 'check' if check_number else 'cash',
        'cash_account_id': cash.id,
        'notes': 'guard test',
        'ap_lines': json.dumps([]),
        'expense_lines': json.dumps([{
            'description': 'Guard Expense', 'amount': amount,
            'vat_category': '', 'account_id': exp.id, 'wt_id': None,
        }]),
        'vat_override': '0', 'vat_override_value': '0',
        'wt_override': '0', 'wt_override_value': '0',
    }
    if check_number:
        data['check_number'] = check_number
        data['check_date'] = ph_now().date().isoformat()
    if row_version is not None:
        data['row_version'] = row_version
    return data


@pytest.fixture
def voucher(client, db_session, admin_user, main_branch):
    """A freshly created draft CDV at row_version 1."""
    admin_login(client)
    # CDV's JE assembly resolves AP Trade and WHT Payable via the accountant-
    # assigned control-account settings, so both the accounts AND the settings
    # must exist or create() raises and the fixture silently yields nothing.
    get_or_create_account(db_session, '20101', 'AP Trade', 'Liability')
    get_or_create_account(db_session, '20301', 'WHT Payable', 'Liability')
    cash = get_or_create_account(db_session, '10101', 'Cash on Hand', 'Asset')
    exp = get_or_create_account(db_session, '60101', 'Office Supplies', 'Expense')
    from tests.conftest import assign_control_accounts
    assign_control_accounts(db_session)
    vendor = make_vendor(db_session, code='CDVG1')

    client.post('/cash-disbursements/create',
                data=cdv_payload(vendor, cash, exp, 500.00, row_version=None),
                follow_redirects=True)
    cdv = CashDisbursementVoucher.query.order_by(CashDisbursementVoucher.id.desc()).first()
    assert cdv is not None, 'setup: CDV was not created'
    return cdv, vendor, cash, exp


class TestCDVLostUpdateGuard:

    def test_second_encoder_with_a_stale_token_is_refused(self, client, db_session, voucher):
        cdv, vendor, cash, exp = voucher
        cdv_id, num = cdv.id, cdv.cdv_number

        client.post(f'/cash-disbursements/{cdv_id}/edit',
                    data=cdv_payload(vendor, cash, exp, 700.00, 1, cdv_number=num),
                    follow_redirects=True)

        resp = client.post(f'/cash-disbursements/{cdv_id}/edit',
                           data=cdv_payload(vendor, cash, exp, 9999.00, 1, cdv_number=num),
                           follow_redirects=True)

        assert b'NOT saved' in resp.data
        db_session.expire_all()
        cdv = db_session.get(CashDisbursementVoucher, cdv_id)
        assert cdv.row_version == 2
        assert len(cdv.expense_lines) == 1
        assert cdv.expense_lines[0].amount == Decimal('700.00'), \
            "encoder B's line must survive the loser's replace-all"

    def test_missing_token_fails_closed(self, client, db_session, voucher):
        cdv, vendor, cash, exp = voucher
        cdv_id, num = cdv.id, cdv.cdv_number

        resp = client.post(f'/cash-disbursements/{cdv_id}/edit',
                           data=cdv_payload(vendor, cash, exp, 9999.00, None, cdv_number=num),
                           follow_redirects=True)

        assert b'NOT saved' in resp.data
        db_session.expire_all()
        assert db_session.get(CashDisbursementVoucher, cdv_id).row_version == 1


class TestCDVEditRestoresSubmittedLines:
    """CDV edit re-rendered from the DB, silently discarding the encoder's lines."""

    def test_conflict_rerender_shows_the_losers_typed_amount(self, client, db_session, voucher):
        cdv, vendor, cash, exp = voucher
        cdv_id, num = cdv.id, cdv.cdv_number

        client.post(f'/cash-disbursements/{cdv_id}/edit',
                    data=cdv_payload(vendor, cash, exp, 700.00, 1, cdv_number=num),
                    follow_redirects=True)

        resp = client.post(f'/cash-disbursements/{cdv_id}/edit',
                           data=cdv_payload(vendor, cash, exp, 9999.00, 1, cdv_number=num),
                           follow_redirects=True)

        body = resp.data.decode()
        assert '9999' in body, "the loser's typed line must be carried back"
        assert 'restore_expense_lines' not in body  # sanity: template consumed it

    def test_duplicate_cdv_number_rerenders_the_submitted_lines(
            self, client, db_session, voucher):
        cdv, vendor, cash, exp = voucher

        # A second CDV whose number we will collide with.
        client.post('/cash-disbursements/create',
                    data=cdv_payload(vendor, cash, exp, 100.00, None,
                                     cdv_number='CD-GUARD-0002'),
                    follow_redirects=True)

        resp = client.post(f'/cash-disbursements/{cdv.id}/edit',
                           data=cdv_payload(vendor, cash, exp, 4242.00, cdv.row_version,
                                            cdv_number='CD-GUARD-0002'),
                           follow_redirects=True)

        assert resp.status_code == 200
        assert b'already in use' in resp.data
        assert b'4242' in resp.data, 'submitted lines must survive a bounced edit'


class TestCDVEditSerialErrorDoesNotCrash:
    """edit() called _render_form(), which is nested in create() -- a NameError.

    That call was dead code: `_check_serial_error(cdv)` runs a Query while `cdv`
    is already dirty with the new check_number, so autoflush trips the partial
    unique index and raises IntegrityError before the friendly message is ever
    returned.  The request then lands in `except Exception`.

    So this test pins only what the fix guarantees: the edit route does not blow
    up on this path.  That the user sees the GENERIC error instead of the curated
    "Check number ... is already used" flash is a separate, pre-existing defect
    (the query needs db.session.no_autoflush) and is NOT fixed here.
    """

    def test_duplicate_check_serial_on_edit_does_not_raise_nameerror(
            self, client, db_session, voucher):
        cdv, vendor, cash, exp = voucher

        # Another CDV already holds check serial 1001 on the same cash account.
        client.post('/cash-disbursements/create',
                    data=cdv_payload(vendor, cash, exp, 100.00, None,
                                     cdv_number='CD-GUARD-0003', check_number='1001'),
                    follow_redirects=True)

        resp = client.post(f'/cash-disbursements/{cdv.id}/edit',
                           data=cdv_payload(vendor, cash, exp, 300.00, cdv.row_version,
                                            cdv_number=cdv.cdv_number, check_number='1001'),
                           follow_redirects=True)

        assert resp.status_code == 200, 'must re-render, not raise NameError'
        # The bad serial is not persisted, whichever error path ran.
        db_session.expire_all()
        assert db_session.get(CashDisbursementVoucher, cdv.id).check_number != '1001'


class TestDRLineOnlyEditBumpsVersion:
    """DR is why row_version is an explicit column rather than reused `updated_at`.

    Its header carries no totals and its edit is line-only (`dr.line_items.clear()`),
    so the header row is never dirtied by an ORM mutation and SQLAlchemy's
    `onupdate=ph_now` would never fire.  A guard built on `updated_at` would fail
    OPEN on exactly this module.  claim_version's UPDATE always advances the row.
    """

    @pytest.fixture
    def dr_setup(self, client, db_session, admin_user, main_branch):
        from tests.integration.test_delivery_receipts_crud import _confirmed_so, _login
        from app.delivery_receipts.models import DeliveryReceipt
        from app.settings import AppSettings
        from app.utils.cache_helpers import clear_module_config_cache

        # Delivery Receipts is an opt-in module; without this the route 404s and
        # the fixture yields no DR at all.
        AppSettings.set_setting('module_enabled:delivery_receipts', '1')
        db_session.commit()
        clear_module_config_cache()

        so = _confirmed_so(db_session, main_branch.id)
        _login(client, admin_user)
        with client.session_transaction() as s:
            s['selected_branch_id'] = main_branch.id
        soi_id = so.line_items[0].id
        client.post('/delivery-receipts/create', data={
            'sales_order_id': so.id, 'delivery_date': '2026-07-09',
            'lines': json.dumps([{'sales_order_item_id': soi_id, 'delivered_quantity': '4'}]),
        }, follow_redirects=True)
        dr = DeliveryReceipt.query.first()
        assert dr is not None, 'setup: DR was not created'
        return dr, so, soi_id, DeliveryReceipt

    def test_line_only_edit_advances_the_version(self, client, db_session, dr_setup):
        dr, so, soi_id, DeliveryReceipt = dr_setup
        assert dr.row_version == 1

        client.post(f'/delivery-receipts/{dr.id}/edit', data={
            'sales_order_id': so.id, 'delivery_date': '2026-07-09',  # header unchanged
            'row_version': 1,
            'lines': json.dumps([{'sales_order_item_id': soi_id, 'delivered_quantity': '6'}]),
        }, follow_redirects=True)

        db_session.expire_all()
        dr = db_session.get(DeliveryReceipt, dr.id)
        assert dr.row_version == 2, 'a line-only edit must still advance the version'
        assert dr.line_items[0].delivered_quantity == Decimal('6')

    def test_stale_token_refused_after_a_line_only_edit(self, client, db_session, dr_setup):
        dr, so, soi_id, DeliveryReceipt = dr_setup
        dr_id = dr.id

        client.post(f'/delivery-receipts/{dr_id}/edit', data={
            'sales_order_id': so.id, 'delivery_date': '2026-07-09', 'row_version': 1,
            'lines': json.dumps([{'sales_order_item_id': soi_id, 'delivered_quantity': '6'}]),
        }, follow_redirects=True)

        resp = client.post(f'/delivery-receipts/{dr_id}/edit', data={
            'sales_order_id': so.id, 'delivery_date': '2026-07-09', 'row_version': 1,
            'lines': json.dumps([{'sales_order_item_id': soi_id, 'delivered_quantity': '2'}]),
        }, follow_redirects=True)

        assert b'NOT saved' in resp.data
        db_session.expire_all()
        dr = db_session.get(DeliveryReceipt, dr_id)
        assert dr.row_version == 2
        assert dr.line_items[0].delivered_quantity == Decimal('6'), \
            "the winner's quantity must survive"


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
