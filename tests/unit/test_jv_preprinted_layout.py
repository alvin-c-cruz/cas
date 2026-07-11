import json
import pytest
from app.settings import AppSettings
from app.journal_entries.preprinted_layout import (
    DEFAULT_JV_PREPRINTED_LAYOUT, LAYOUT_SETTING_KEY, FIELD_KEYS, COLUMN_KEYS,
    TEXT_KEYS, ALLOWED_FONTS, FONT_GROUPS, sanitize_layout, get_layout, save_layout,
    _layout_key, SAFE_MARGIN,
)
from app.audit.models import AuditLog

pytestmark = [pytest.mark.unit]


class TestSanitize:
    def test_empty_input_returns_full_default(self):
        out = sanitize_layout({})
        assert set(out['fields']) == set(FIELD_KEYS)
        assert [c['key'] for c in out['lineItems']['columns']] == COLUMN_KEYS
        assert out['page']['fontFamily'] == DEFAULT_JV_PREPRINTED_LAYOUT['page']['fontFamily']
        assert 'journalEntry' not in out          # JV drops the APV JE block

    def test_jv_field_keys(self):
        assert FIELD_KEYS == ['jv_no', 'jv_date', 'entry_type', 'particulars',
                              'total_debit', 'total_credit']
        assert 'apv_no' not in FIELD_KEYS and 'vendor_name' not in FIELD_KEYS

    def test_jv_columns(self):
        assert COLUMN_KEYS == ['line_number', 'account_code', 'account_title', 'debit', 'credit']

    def test_unknown_field_dropped_known_kept(self):
        out = sanitize_layout({'fields': {'jv_no': {'x': 111, 'y': 222},
                                          'evil_key': {'x': 5, 'y': 5}}})
        assert 'evil_key' not in out['fields']
        assert out['fields']['jv_no']['x'] == 111 and out['fields']['jv_no']['y'] == 222
        assert out['fields']['particulars'] == sanitize_layout({})['fields']['particulars']

    def test_coords_clamped_and_coerced(self):
        f = sanitize_layout({'fields': {'jv_no': {'x': -50, 'y': 99999,
                                                  'fontSize': 999, 'bold': 'yes'}}})['fields']['jv_no']
        assert f['x'] == SAFE_MARGIN and f['y'] == 1008 and f['fontSize'] == 72 and f['bold'] is True

    def test_left_margin_rule(self):
        assert sanitize_layout({'fields': {'jv_no': {'x': 5}}})['fields']['jv_no']['x'] == SAFE_MARGIN
        assert all(f['x'] >= SAFE_MARGIN for f in DEFAULT_JV_PREPRINTED_LAYOUT['fields'].values())

    def test_disallowed_font_falls_back(self):
        assert sanitize_layout({'page': {'fontFamily': 'Comic Sans MS'}})['page']['fontFamily'] \
            == DEFAULT_JV_PREPRINTED_LAYOUT['page']['fontFamily']

    def test_columns_reorder_hide_unknown_dropped(self):
        out = sanitize_layout({'lineItems': {'columns': [
            {'key': 'credit', 'visible': True, 'width': 100},
            {'key': 'account_title', 'visible': False, 'width': 80},
            {'key': 'bogus', 'visible': True, 'width': 50},
        ]}})
        keys = [c['key'] for c in out['lineItems']['columns']]
        assert keys[0] == 'credit' and keys[1] == 'account_title'
        assert 'bogus' not in keys and set(keys) == set(COLUMN_KEYS)
        assert out['lineItems']['columns'][1]['visible'] is False

    def test_columns_independent_x(self):
        out = sanitize_layout({'lineItems': {'y': 250, 'rowHeight': 24,
                                             'columns': [{'key': 'credit', 'x': 777}]}})
        col = next(c for c in out['lineItems']['columns'] if c['key'] == 'credit')
        assert col['x'] == 777 and out['lineItems']['y'] == 250 and out['lineItems']['rowHeight'] == 24


class TestTexts:
    def test_default_signature_texts(self):
        out = sanitize_layout({})
        assert {t['id'] for t in out['texts']} == set(TEXT_KEYS) == {'prepared_by', 'checked_by', 'approved_by'}

    def test_text_edited_and_capped(self):
        by = {t['id']: t for t in sanitize_layout({'texts': {'checked_by': {'text': 'x' * 500, 'x': 200}}})['texts']}
        assert len(by['checked_by']['text']) <= 200 and by['checked_by']['x'] == 200


class TestPaperFontDate:
    def test_defaults(self):
        assert DEFAULT_JV_PREPRINTED_LAYOUT['paper'] == 'continuous'
        assert sanitize_layout({})['dateFormat'] == 'long'
        assert 'monospace' in DEFAULT_JV_PREPRINTED_LAYOUT['page']['fontFamily']
        assert [f for _l, fonts in FONT_GROUPS for f in fonts] == ALLOWED_FONTS

    def test_letter_and_unknown_fallback(self):
        assert sanitize_layout({'paper': 'letter'})['paper'] == 'letter'
        assert sanitize_layout({'paper': 'a4'})['paper'] == 'continuous'


class TestGetSave:
    def test_get_default_when_unset(self, db_session):
        assert get_layout()['fields']['jv_no'] == DEFAULT_JV_PREPRINTED_LAYOUT['fields']['jv_no']

    def test_get_default_on_corrupt_json(self, db_session):
        AppSettings.set_setting(LAYOUT_SETTING_KEY, 'not-json{', 'system')
        assert set(get_layout()['fields']) == set(FIELD_KEYS)

    def test_save_persists_sanitized_and_audits(self, db_session, admin_user):
        result = save_layout({'fields': {'jv_no': {'x': 300, 'y': 90}}}, admin_user.username)
        assert result['fields']['jv_no']['x'] == 300
        assert json.loads(AppSettings.get_setting(LAYOUT_SETTING_KEY))['fields']['jv_no']['x'] == 300
        entry = AuditLog.query.filter_by(module='journal_entries',
                                         record_identifier='jv_preprinted_layout').order_by(AuditLog.id.desc()).first()
        assert entry is not None and entry.action == 'update'


class TestBranchScope:
    def test_branch_key_namespacing(self):
        assert _layout_key(None) == LAYOUT_SETTING_KEY
        assert _layout_key(7) == f'{LAYOUT_SETTING_KEY}:7'

    def test_two_branches_independent(self, db_session, admin_user):
        save_layout({'fields': {'jv_no': {'x': 100, 'y': 10}}}, admin_user.username, branch_id=1)
        save_layout({'fields': {'jv_no': {'x': 800, 'y': 10}}}, admin_user.username, branch_id=2)
        assert get_layout(branch_id=1)['fields']['jv_no']['x'] == 100
        assert get_layout(branch_id=2)['fields']['jv_no']['x'] == 800
