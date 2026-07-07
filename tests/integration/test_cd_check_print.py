"""Integration tests for the CDV check-writer print/design page (`print_check`).

Same mechanics as the pre-printed forms: ONE HTML page that renders the real check
values at the layout positions, prints via the browser (@page margin:0), and doubles as
the layout designer for full-access users. The layout is resolved by -- and Edit-Layout
saves to -- the voucher's cash/bank account. Placeholder geometry (default layout); exact
registration is a Phase-0 physical step. Covers the gate truth-table, the rendered page,
the three-way money tie-out, per-account keying, edit-chrome gating, and the amount/words
presence guard. No facsimile signature is ever drawn.
"""
from decimal import Decimal
from datetime import date

import pytest

from app.settings import AppSettings
pytestmark = [pytest.mark.cash_disbursements, pytest.mark.integration]


def login(client, u='admin', p='admin123'):
    client.post('/login', data={'username': u, 'password': p}, follow_redirects=True)


def _check_cdv(db_session, main_branch, status='posted', method='check',
               check_number='CHK-5000', total='5550.00'):
    """A check-payment CDV whose JE cash-credit leg == total_amount (net cash disbursed)."""
    from app.vendors.models import Vendor
    from app.accounts.models import Account
    from app.cash_disbursements.models import CashDisbursementVoucher
    from app.journal_entries.models import JournalEntry, JournalEntryLine

    vendor = Vendor(code='CKV1', name='Meralco', tin='111-222-333-000', is_active=True)
    db_session.add(vendor); db_session.commit()

    def acct(code, name, atype, nb):
        a = Account(code=code, name=name, account_type=atype, normal_balance=nb, is_active=True)
        db_session.add(a); db_session.commit(); return a
    util = acct('5030', 'Utilities', 'Expense', 'debit')
    ivat = acct('1160', 'Input VAT', 'Asset', 'debit')
    wht = acct('2040', 'WHT Payable', 'Liability', 'credit')
    cash = acct('1011', 'Cash in Bank', 'Asset', 'debit')

    je = JournalEntry(entry_number='JE-CK-1', entry_date=date(2026, 7, 7), description='chk',
                      entry_type='disbursement', branch_id=main_branch.id, status='posted',
                      total_debit=Decimal('5600'), total_credit=Decimal('5600'), is_balanced=True)
    db_session.add(je); db_session.commit()
    for ln in (
        JournalEntryLine(entry_id=je.id, line_number=1, account_id=util.id, debit_amount=Decimal('5000'), credit_amount=Decimal('0')),
        JournalEntryLine(entry_id=je.id, line_number=2, account_id=ivat.id, debit_amount=Decimal('600'), credit_amount=Decimal('0')),
        JournalEntryLine(entry_id=je.id, line_number=3, account_id=wht.id, debit_amount=Decimal('0'), credit_amount=Decimal('50')),
        JournalEntryLine(entry_id=je.id, line_number=4, account_id=cash.id, debit_amount=Decimal('0'), credit_amount=Decimal('5550')),
    ):
        db_session.add(ln)
    db_session.commit()

    cdv = CashDisbursementVoucher(
        branch_id=main_branch.id, cdv_number='CD-CK-1', cdv_date=date(2026, 7, 7),
        vendor_id=vendor.id, vendor_name=vendor.name, payment_method=method,
        check_number=check_number, check_date=date(2026, 7, 8), check_bank='Chinabank',
        cash_account_id=cash.id, status=status, total_amount=Decimal(total),
        journal_entry_id=je.id, notes='July electricity')
    db_session.add(cdv); db_session.commit()
    cdv._cash_leg = Decimal('5550'); cdv._cash_acct_id = cash.id
    return cdv


def _open(client, main_branch, u='admin', p='admin123'):
    login(client, u, p)
    with client.session_transaction() as s:
        s['selected_branch_id'] = main_branch.id


class TestGate:
    def test_posted_check_returns_html_page(self, client, db_session, admin_user, main_branch):
        cdv = _check_cdv(db_session, main_branch)
        _open(client, main_branch)
        resp = client.get(f'/cash-disbursements/{cdv.id}/print-check')
        assert resp.status_code == 200
        assert resp.mimetype == 'text/html'
        body = resp.data.decode()
        # It is the check overlay page, not a fall-through to another document.
        assert 'ppCanvas' in body
        assert 'window.print()' in body

    def test_cash_cdv_blocked(self, client, db_session, admin_user, main_branch):
        cdv = _check_cdv(db_session, main_branch, method='cash', check_number=None)
        _open(client, main_branch)
        assert client.get(f'/cash-disbursements/{cdv.id}/print-check').status_code == 302

    def test_draft_blocked_when_posted_only(self, client, db_session, admin_user, main_branch):
        AppSettings.set_setting('cd_check_print_access', 'posted_only', 'admin')
        cdv = _check_cdv(db_session, main_branch, status='draft')
        _open(client, main_branch)
        assert client.get(f'/cash-disbursements/{cdv.id}/print-check').status_code == 302

    def test_draft_allowed_when_draft_and_posted(self, client, db_session, admin_user, main_branch):
        AppSettings.set_setting('cd_check_print_access', 'draft_and_posted', 'admin')
        cdv = _check_cdv(db_session, main_branch, status='draft')
        _open(client, main_branch)
        assert client.get(f'/cash-disbursements/{cdv.id}/print-check').status_code == 200

    def test_voided_blocked(self, client, db_session, admin_user, main_branch):
        AppSettings.set_setting('cd_check_print_access', 'draft_and_posted', 'admin')
        cdv = _check_cdv(db_session, main_branch, status='voided')
        _open(client, main_branch)
        assert client.get(f'/cash-disbursements/{cdv.id}/print-check').status_code == 302

    def test_blank_serial_blocked(self, client, db_session, admin_user, main_branch):
        cdv = _check_cdv(db_session, main_branch, check_number='   ')
        _open(client, main_branch)
        assert client.get(f'/cash-disbursements/{cdv.id}/print-check').status_code == 302

    def test_zero_amount_blocked(self, client, db_session, admin_user, main_branch):
        cdv = _check_cdv(db_session, main_branch, total='0.00')
        _open(client, main_branch)
        assert client.get(f'/cash-disbursements/{cdv.id}/print-check').status_code == 302

    def test_print_hidden_blocked(self, client, db_session, admin_user, main_branch):
        AppSettings.set_setting('cd_check_print_access', 'hidden', 'admin')
        cdv = _check_cdv(db_session, main_branch)
        _open(client, main_branch)
        assert client.get(f'/cash-disbursements/{cdv.id}/print-check').status_code == 302


class TestRenderedValues:
    def test_real_values_rendered_on_page(self, client, db_session, admin_user, main_branch):
        from app.common.amount_to_words import amount_to_words
        cdv = _check_cdv(db_session, main_branch)
        _open(client, main_branch)
        body = client.get(f'/cash-disbursements/{cdv.id}/print-check').data.decode()
        assert 'Meralco' in body                                # payee
        assert '5,550.00' in body                               # figures (bare, no symbol)
        assert amount_to_words(Decimal('5550.00')) in body      # legally-operative words
        assert '07-08-2026' in body                             # check date MM-DD-YYYY

    def test_layout_keyed_to_cash_account(self, client, db_session, admin_user, main_branch):
        """The overlay layout is resolved by -- and Edit-Layout saves to -- the voucher's
        cash/bank account (the user's rule)."""
        cdv = _check_cdv(db_session, main_branch)
        _open(client, main_branch)
        body = client.get(f'/cash-disbursements/{cdv.id}/print-check').data.decode()
        assert f'account_id={cdv._cash_acct_id}' in body        # save-url is account-scoped


class TestEditChrome:
    def test_edit_chrome_for_full_access(self, client, db_session, admin_user, main_branch):
        cdv = _check_cdv(db_session, main_branch)
        _open(client, main_branch)
        body = client.get(f'/cash-disbursements/{cdv.id}/print-check').data.decode()
        assert 'editLayoutBtn' in body                          # designer available in-page

    def test_no_edit_chrome_for_non_full_access(self, client, db_session, staff_user, main_branch):
        staff_user.set_branches([main_branch]); db_session.commit()
        cdv = _check_cdv(db_session, main_branch)
        _open(client, main_branch, 'staff', 'staff123')
        resp = client.get(f'/cash-disbursements/{cdv.id}/print-check')
        assert resp.status_code == 200                          # can still print
        assert 'editLayoutBtn' not in resp.data.decode()        # but cannot redesign


class TestAmountGuards:
    def test_hidden_words_field_refused(self, client, db_session, admin_user, main_branch):
        cdv = _check_cdv(db_session, main_branch)
        from app.cash_disbursements.check_layout import save_layout
        save_layout({'fields': {'amount_in_words': {'hidden': True}}}, 'admin', account_id=cdv._cash_acct_id)
        _open(client, main_branch)
        assert client.get(f'/cash-disbursements/{cdv.id}/print-check').status_code == 302


class TestCheckOptions:
    """Two per-field layout options (both default OFF): protective asterisks on the
    amounts (none/left/right/both) and boxed/spaced date digits."""

    def test_stars_sanitize(self):
        from app.cash_disbursements.check_layout import sanitize_layout, STARS_MODES, PITCH_MIN, PITCH_MAX
        lay = sanitize_layout({'fields': {'amount_figures': {'stars': 'both'},
                                          'amount_in_words': {'stars': 'nope'}}})
        assert lay['fields']['amount_figures']['stars'] == 'both'
        assert lay['fields']['amount_in_words']['stars'] == 'none'   # invalid -> off
        assert 'none' in STARS_MODES and PITCH_MIN < PITCH_MAX

    def test_boxed_pitch_sanitize_and_clamp(self):
        from app.cash_disbursements.check_layout import sanitize_layout, PITCH_MIN, PITCH_MAX
        lay = sanitize_layout({'fields': {'check_date': {'boxed': True, 'pitch': 28}}})
        assert lay['fields']['check_date']['boxed'] is True
        assert lay['fields']['check_date']['pitch'] == 28
        lo = sanitize_layout({'fields': {'check_date': {'pitch': 1}}})['fields']['check_date']['pitch']
        hi = sanitize_layout({'fields': {'check_date': {'pitch': 9999}}})['fields']['check_date']['pitch']
        assert lo == PITCH_MIN and hi == PITCH_MAX

    def test_defaults_off(self):
        from app.cash_disbursements.check_layout import DEFAULT_CHECK_LAYOUT as D
        assert D['fields']['amount_figures'].get('stars', 'none') == 'none'
        assert D['fields']['check_date'].get('boxed', False) is False

    def test_stars_rendered_around_amounts(self, client, db_session, admin_user, main_branch):
        from app.cash_disbursements.check_layout import save_layout
        cdv = _check_cdv(db_session, main_branch)
        save_layout({'fields': {'amount_figures': {'stars': 'both'},
                                'amount_in_words': {'stars': 'left'}}},
                    'admin', account_id=cdv._cash_acct_id)
        _open(client, main_branch)
        body = client.get(f'/cash-disbursements/{cdv.id}/print-check').data.decode()
        assert '***5,550.00***' in body                              # both sides
        assert '***FIVE THOUSAND' in body                            # left only

    def test_boxed_date_renders_digit_cells(self, client, db_session, admin_user, main_branch):
        from app.cash_disbursements.check_layout import save_layout
        cdv = _check_cdv(db_session, main_branch)
        save_layout({'fields': {'check_date': {'boxed': True, 'pitch': 26}}},
                    'admin', account_id=cdv._cash_acct_id)
        _open(client, main_branch)
        body = client.get(f'/cash-disbursements/{cdv.id}/print-check').data.decode()
        # 07-08-2026 -> 8 digit cells, separators dropped
        assert body.count('pp-digit') >= 8


class TestTieOutAndSignature:
    def test_three_way_tie_out(self, db_session, main_branch, app):
        from app.cash_disbursements.views import _build_check_values
        from app.cash_disbursements.check_layout import get_layout
        from app.common.amount_to_words import amount_to_words
        cdv = _check_cdv(db_session, main_branch)
        values, err = _build_check_values(cdv, get_layout(cdv._cash_acct_id))
        assert err is None
        # figures == words(total) == JE cash-credit leg == total_amount
        assert values['amount_figures'] == '5,550.00'
        assert values['amount_in_words'] == amount_to_words(Decimal('5550.00'))
        assert cdv._cash_leg == cdv.total_amount == Decimal('5550.00')

    def test_no_facsimile_signature_field(self):
        from app.cash_disbursements.check_layout import FIELD_KEYS
        assert not any('sign' in k for k in FIELD_KEYS)   # the overlay never draws a signature


class TestButton:
    def test_button_shown_for_printable_check_cdv(self, client, db_session, admin_user, main_branch):
        cdv = _check_cdv(db_session, main_branch)
        _open(client, main_branch)
        body = client.get(f'/cash-disbursements/{cdv.id}').data.decode()
        assert f'/cash-disbursements/{cdv.id}/print-check' in body

    def test_button_hidden_for_cash_cdv(self, client, db_session, admin_user, main_branch):
        cdv = _check_cdv(db_session, main_branch, method='cash', check_number=None)
        _open(client, main_branch)
        body = client.get(f'/cash-disbursements/{cdv.id}').data.decode()
        assert '/print-check' not in body
