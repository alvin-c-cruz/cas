import json
import pytest
from app.settings import AppSettings
from app.cash_disbursements.check_layout import (
    DEFAULT_CHECK_LAYOUT, LAYOUT_SETTING_KEY, FIELD_KEYS, SAFE_MARGIN, CANVAS_W,
    DATE_FORMATS, ALLOWED_FONTS, FONT_GROUPS, sanitize_layout, get_layout, save_layout,
    _layout_key,
)
from app.audit.models import AuditLog

pytestmark = [pytest.mark.unit, pytest.mark.cash_disbursements]


class TestSanitize:
    def test_empty_input_returns_full_default(self):
        out = sanitize_layout({})
        assert set(out['fields']) == set(FIELD_KEYS)
        assert out['page']['fontFamily'] == DEFAULT_CHECK_LAYOUT['page']['fontFamily']

    def test_check_field_keys(self):
        assert FIELD_KEYS == ['payee', 'check_date', 'amount_figures', 'amount_in_words', 'memo']
        # a check has NO line band and NO journal-entry face
        assert 'lineItems' not in sanitize_layout({})
        assert 'journalEntry' not in sanitize_layout({})

    def test_unknown_field_dropped(self):
        out = sanitize_layout({'fields': {'payee': {'x': 111, 'y': 222}, 'evil': {'x': 5, 'y': 5}}})
        assert 'evil' not in out['fields']
        assert out['fields']['payee']['x'] == 111

    def test_x_clamped_to_safe_margin(self):
        out = sanitize_layout({'fields': {'payee': {'x': 5, 'y': 200}}})
        assert out['fields']['payee']['x'] == SAFE_MARGIN
        assert sanitize_layout({'fields': {'payee': {'x': 9999}}})['fields']['payee']['x'] == CANVAS_W - SAFE_MARGIN

    def test_fields_have_width_and_it_clamps(self):
        # width is load-bearing: it lets the print route guard the amount/words line
        # against overflow (the legally-operative line can't be clipped).
        out = sanitize_layout({})
        assert all('width' in f for f in out['fields'].values())
        assert out['fields']['amount_in_words']['width'] >= 200   # a wide legal line by default
        narrowed = sanitize_layout({'fields': {'amount_in_words': {'width': 3}}})
        assert narrowed['fields']['amount_in_words']['width'] >= 10   # clamped up to WIDTH_MIN

    def test_no_default_field_inside_margin(self):
        assert all(f['x'] >= SAFE_MARGIN for f in DEFAULT_CHECK_LAYOUT['fields'].values())


class TestDateFormat:
    def test_mmddyyyy_available(self):
        # PCHC requires the check date as MM-DD-YYYY (dash) — the siblings lack a dash variant.
        from datetime import date
        assert any(v == '%m-%d-%Y' for v in DATE_FORMATS.values())
        key = next(k for k, v in DATE_FORMATS.items() if v == '%m-%d-%Y')
        assert date(2026, 7, 4).strftime(DATE_FORMATS[key]) == '07-04-2026'


class TestTexts:
    def test_texts_default_empty_but_supported(self):
        # A check's stock supplies its own labels; default = no layout texts, but the
        # arbitrary-text machinery still works (add one).
        assert sanitize_layout({})['texts'] == []
        out = sanitize_layout({'texts': [{'id': 'note1', 'text': 'VOID AFTER 90 DAYS', 'x': 80, 'y': 400}]})
        assert [t['id'] for t in out['texts']] == ['note1']


class TestFonts:
    def test_font_groups_and_default_monospace(self):
        assert 'monospace' in DEFAULT_CHECK_LAYOUT['page']['fontFamily']
        assert [f for _l, fonts in FONT_GROUPS for f in fonts] == ALLOWED_FONTS


class TestKeyingAndPersistence:
    def test_default_key_and_account_key(self):
        assert _layout_key(None) == LAYOUT_SETTING_KEY               # the Default
        assert _layout_key(7) == f'{LAYOUT_SETTING_KEY}:7'           # an account override

    def test_get_returns_default_when_unset(self, db_session):
        assert get_layout()['fields']['payee'] == DEFAULT_CHECK_LAYOUT['fields']['payee']

    def test_account_resolves_then_falls_back_to_default_then_hardcoded(self, db_session, admin_user):
        # Save an account-7 override + a Default; account-7 uses its own, account-99 falls to Default.
        save_layout({'fields': {'payee': {'x': 200, 'y': 200}}}, admin_user.username, account_id=7)
        save_layout({'fields': {'payee': {'x': 300, 'y': 200}}}, admin_user.username, account_id=None)
        assert get_layout(account_id=7)['fields']['payee']['x'] == 200     # account-specific
        assert get_layout(account_id=99)['fields']['payee']['x'] == 300    # -> Default
        # with neither stored, a fresh account -> hardcoded default
        assert get_layout(account_id=5)['fields']['payee']['x'] == 300     # Default still applies

    def test_save_persists_sanitized_and_audits(self, db_session, admin_user):
        result = save_layout({'fields': {'payee': {'x': 250, 'y': 90}}}, admin_user.username, account_id=7)
        assert result['fields']['payee']['x'] == 250
        stored = json.loads(AppSettings.get_setting(f'{LAYOUT_SETTING_KEY}:7'))
        assert stored['fields']['payee']['x'] == 250
        entry = AuditLog.query.filter_by(
            module='cash_disbursements', record_identifier='cd_check_layout'
        ).order_by(AuditLog.id.desc()).first()
        assert entry is not None and entry.action == 'update'

    def test_get_returns_default_on_corrupt_json(self, db_session):
        AppSettings.set_setting(LAYOUT_SETTING_KEY, 'not-json{', 'system')
        assert set(get_layout()['fields']) == set(FIELD_KEYS)
