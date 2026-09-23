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


def _payee_text(body):
    """The text INSIDE the check's payee element. Scoped, because the vendor name can
    appear elsewhere on the page, so a bare `in body` could never fail."""
    import re
    m = re.search(r'data-el="payee"[^>]*>([^<]*)</div>', body)
    assert m, 'payee element not rendered'
    return m.group(1)


class TestPayeeName:
    """The vendor's Check Payee Name is who the cheque is made out to. It used to reach
    only the CDV voucher overlay; the check itself printed the vendor name."""

    def _print(self, client, db_session, main_branch, payee_name):
        cdv = _check_cdv(db_session, main_branch)
        cdv.vendor.check_payee_name = payee_name
        db_session.commit()
        _open(client, main_branch)
        return _payee_text(client.get(f'/cash-disbursements/{cdv.id}/print-check').data.decode())

    def test_check_payee_name_prints_instead_of_vendor_name(self, client, db_session, admin_user, main_branch):
        assert self._print(client, db_session, main_branch,
                           'Manila Electric Company') == 'Manila Electric Company'

    @pytest.mark.parametrize('blank', [None, '', '   '])
    def test_blank_payee_name_falls_back_to_vendor_name(self, client, db_session, admin_user, main_branch, blank):
        assert self._print(client, db_session, main_branch, blank) == 'Meralco'


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

    def test_option_data_attributes_are_real_attributes(self, client, db_session, admin_user, main_branch):
        """The designer reads stars/boxed/pitch back from data-* attributes. Found on
        production 2026-09-12: the template built the three attributes as ONE string and
        emitted it with `{{ opt }}`, so autoescape turned every quote into `&#34;` and the
        browser parsed `data-stars=&#34;both&#34;` as the unquoted value `"both"` -- quotes
        included. The strip then showed `* none` / boxed-unticked for a layout that had
        both set, and the next Save wrote what the strip showed: stars and boxed wiped."""
        from app.cash_disbursements.check_layout import save_layout
        cdv = _check_cdv(db_session, main_branch)
        save_layout({'fields': {'amount_figures': {'stars': 'both'},
                                'check_date': {'boxed': True, 'pitch': 26}}},
                    'admin', account_id=cdv._cash_acct_id)
        _open(client, main_branch)
        body = client.get(f'/cash-disbursements/{cdv.id}/print-check').data.decode()
        assert 'data-el="amount_figures"' in body
        figures = body[body.index('data-el="amount_figures"'):]
        figures = figures[:figures.index('>')]
        assert 'data-stars="both"' in figures
        date = body[body.index('data-el="check_date"'):]
        date = date[:date.index('>')]
        assert 'data-boxed="1"' in date and 'data-pitch="26"' in date

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


class TestDateDigitOffsets:
    """Per-digit horizontal placement for the boxed date.

    `pitch` spaces the digits evenly, which only fits stock whose date cells are
    themselves evenly spaced. Real PCHC stock groups them (MM DD YYYY) with wider gaps
    between the groups, so each digit carries its own x offset from the date field's
    origin. Offsets are horizontal ONLY -- every digit shares the field's y, so the run
    can never be knocked off its baseline. An empty list means "space evenly at pitch",
    which is the pre-existing behaviour, so no already-saved layout changes.
    """

    def test_default_is_empty_list(self):
        from app.cash_disbursements.check_layout import DEFAULT_CHECK_LAYOUT as D, sanitize_layout
        assert D['fields']['check_date'].get('digitOffsets', []) == []
        assert sanitize_layout({})['fields']['check_date']['digitOffsets'] == []

    def test_offsets_kept_and_clamped_into_the_canvas(self):
        from app.cash_disbursements.check_layout import sanitize_layout, CANVAS_W, SAFE_MARGIN
        out = sanitize_layout({'fields': {'check_date': {'digitOffsets': [0, 30, 9999, -50]}}})
        off = out['fields']['check_date']['digitOffsets']
        assert off[:2] == [0, 30]
        assert off[2] == CANVAS_W - SAFE_MARGIN     # clamped down
        assert off[3] == 0                          # clamped up; an offset is never negative

    def test_offsets_truncated_to_the_longest_possible_digit_run(self):
        from datetime import date
        from app.cash_disbursements.check_layout import (
            sanitize_layout, MAX_DATE_DIGITS, DATE_FORMATS)
        longest = max(sum(c.isdigit() for c in date(2026, 7, 8).strftime(f))
                      for f in DATE_FORMATS.values())
        assert MAX_DATE_DIGITS == longest == 8
        out = sanitize_layout({'fields': {'check_date': {'digitOffsets': list(range(0, 400, 20))}}})
        assert len(out['fields']['check_date']['digitOffsets']) == MAX_DATE_DIGITS

    def test_garbage_offsets_fall_back(self):
        from app.cash_disbursements.check_layout import sanitize_layout
        # Not a list at all -> no per-digit placement, back to even pitch.
        for junk in ('24,48', {'0': 24}, None, 7):
            out = sanitize_layout({'fields': {'check_date': {'digitOffsets': junk}}})
            assert out['fields']['check_date']['digitOffsets'] == []
        # A single unparseable entry falls back to that index's even-pitch position, so
        # one bad value can never stack two digits on top of each other.
        out = sanitize_layout({'fields': {'check_date': {'pitch': 30,
                                                         'digitOffsets': [0, 'x', 80]}}})
        assert out['fields']['check_date']['digitOffsets'] == [0, 30, 80]

    def test_offsets_survive_a_save_round_trip(self, db_session, admin_user):
        from app.cash_disbursements.check_layout import save_layout, get_layout
        save_layout({'fields': {'check_date': {'boxed': True, 'digitOffsets': [0, 26, 70, 96]}}},
                    admin_user.username, account_id=7)
        assert get_layout(account_id=7)['fields']['check_date']['digitOffsets'] == [0, 26, 70, 96]

    @staticmethod
    def _digit_spans(body):
        """[(style, digit), ...] for the boxed date's cells, in document order."""
        import re
        date_div = body[body.index('data-el="check_date"'):]
        date_div = date_div[:date_div.index('</div>')]
        return re.findall(r'<span class="pp-digit" style="([^"]*)">(\d)</span>', date_div)

    def test_digits_render_at_their_saved_offsets(self, client, db_session, admin_user, main_branch):
        from app.cash_disbursements.check_layout import save_layout
        cdv = _check_cdv(db_session, main_branch)
        # 07-08-2026 -> 8 digits, grouped MM  DD  YYYY with wider gaps between groups.
        save_layout({'fields': {'check_date': {'boxed': True, 'pitch': 24,
                                               'digitOffsets': [0, 24, 70, 94, 140, 164, 188, 212]}}},
                    'admin', account_id=cdv._cash_acct_id)
        _open(client, main_branch)
        body = client.get(f'/cash-disbursements/{cdv.id}/print-check').data.decode()
        spans = self._digit_spans(body)
        assert [d for _s, d in spans] == list('07082026')
        assert [s for s, _d in spans] == [
            f'position:absolute;left:{x}px;width:24px;text-align:center;'
            for x in (0, 24, 70, 94, 140, 164, 188, 212)]

    def test_digits_without_offsets_still_space_evenly_at_pitch(self, client, db_session, admin_user, main_branch):
        from app.cash_disbursements.check_layout import save_layout
        cdv = _check_cdv(db_session, main_branch)
        save_layout({'fields': {'check_date': {'boxed': True, 'pitch': 26}}},
                    'admin', account_id=cdv._cash_acct_id)
        _open(client, main_branch)
        body = client.get(f'/cash-disbursements/{cdv.id}/print-check').data.decode()
        lefts = [s for s, _d in self._digit_spans(body)]
        assert 'left:0px;' in lefts[0]
        assert 'left:26px;' in lefts[1] and 'left:52px;' in lefts[2]

    def test_digits_past_the_saved_offsets_fall_back_to_pitch(self, client, db_session, admin_user, main_branch):
        """A short offset list -- saved under a 6-digit format, then switched to an
        8-digit one -- must not drop the extra digits or stack them at 0."""
        from app.cash_disbursements.check_layout import save_layout
        cdv = _check_cdv(db_session, main_branch)
        save_layout({'fields': {'check_date': {'boxed': True, 'pitch': 20,
                                               'digitOffsets': [5, 35, 65]}}},
                    'admin', account_id=cdv._cash_acct_id)
        _open(client, main_branch)
        body = client.get(f'/cash-disbursements/{cdv.id}/print-check').data.decode()
        lefts = [s for s, _d in self._digit_spans(body)]
        assert len(lefts) == 8
        assert 'left:5px;' in lefts[0] and 'left:35px;' in lefts[1] and 'left:65px;' in lefts[2]
        assert 'left:60px;' in lefts[3] and 'left:140px;' in lefts[7]   # i * pitch

    def test_boxed_container_keeps_an_explicit_width(self, client, db_session, admin_user, main_branch):
        """The digits are absolutely positioned now, so they no longer size their parent.
        Without an explicit width the date div collapses to 0px wide and the designer
        loses the hit-box you grab to move the whole run."""
        from app.cash_disbursements.check_layout import save_layout
        cdv = _check_cdv(db_session, main_branch)
        save_layout({'fields': {'check_date': {'boxed': True, 'width': 180}}},
                    'admin', account_id=cdv._cash_acct_id)
        _open(client, main_branch)
        body = client.get(f'/cash-disbursements/{cdv.id}/print-check').data.decode()
        date_div = body[body.index('data-el="check_date"'):]
        date_div = date_div[:date_div.index('>')]
        assert 'width:180px' in date_div

    def test_the_run_grip_is_never_served_in_the_page(self, client, db_session, admin_user, main_branch):
        """The grip that moves the whole run is edit-mode chrome INJECTED BY THE DESIGNER,
        never rendered server-side. A grip in the markup would print onto the physical
        check -- and would print for staff, who never load the designer at all."""
        from app.cash_disbursements.check_layout import save_layout
        cdv = _check_cdv(db_session, main_branch)
        save_layout({'fields': {'check_date': {'boxed': True}}}, 'admin', account_id=cdv._cash_acct_id)
        _open(client, main_branch)
        body = client.get(f'/cash-disbursements/{cdv.id}/print-check').data.decode()
        assert 'class="pp-digit"' in body              # the run itself IS rendered
        # Scoped to the APPLIED attribute, never the bare class name: the page's inline
        # <style> block styles .pp-boxed-grip, so `'pp-boxed-grip' not in body` can never
        # fail and would be a test that only looks like one.
        assert 'class="pp-boxed-grip' not in body      # its grip is not
