import json
import pytest
from app.settings import AppSettings
from app.cash_receipts.preprinted_layout import (
    DEFAULT_CRV_PREPRINTED_LAYOUT, LAYOUT_SETTING_KEY, FIELD_KEYS, COLUMN_KEYS,
    TEXT_KEYS, ALLOWED_FONTS, FONT_GROUPS, sanitize_layout, get_layout, save_layout,
)
from app.audit.models import AuditLog

pytestmark = [pytest.mark.unit, pytest.mark.cash_receipts]


class TestSanitize:
    def test_empty_input_returns_full_default(self):
        out = sanitize_layout({})
        assert set(out['fields']) == set(FIELD_KEYS)
        assert [c['key'] for c in out['lineItems']['columns']] == COLUMN_KEYS
        assert out['page']['fontFamily'] == DEFAULT_CRV_PREPRINTED_LAYOUT['page']['fontFamily']

    def test_crv_specific_field_keys(self):
        # CRV header + BIR CRV summary fields (NOT the SI invoice fields)
        for k in ('crv_no', 'crv_date', 'payment_method', 'check_no',
                  'ar_applied', 'net_cash_received'):
            assert k in FIELD_KEYS
        assert 'invoice_no' not in FIELD_KEYS   # that's the SI form's field

    def test_unknown_field_dropped_known_field_kept(self):
        out = sanitize_layout({'fields': {'crv_no': {'x': 111, 'y': 222},
                                          'evil_key': {'x': 5, 'y': 5}}})
        assert 'evil_key' not in out['fields']
        assert out['fields']['crv_no']['x'] == 111
        assert out['fields']['crv_no']['y'] == 222
        # a field the input omitted still renders at its default
        assert out['fields']['net_cash_received'] == \
            sanitize_layout({})['fields']['net_cash_received']

    def test_coords_and_sizes_clamped_and_coerced(self):
        out = sanitize_layout({'fields': {'crv_no': {'x': -50, 'y': 99999,
                                                     'fontSize': 999, 'bold': 'yes'}}})
        f = out['fields']['crv_no']
        assert f['x'] == 0
        assert f['y'] == 1008
        assert f['fontSize'] == 72
        assert f['bold'] is True

    def test_disallowed_font_falls_back_to_default(self):
        out = sanitize_layout({'page': {'fontFamily': 'Comic Sans MS'}})
        assert out['page']['fontFamily'] == DEFAULT_CRV_PREPRINTED_LAYOUT['page']['fontFamily']

    def test_ar_collection_columns(self):
        assert COLUMN_KEYS == ['line_number', 'invoice_no', 'invoice_date',
                               'original_balance', 'amount_applied']

    def test_columns_reorder_and_hide_preserved_unknown_dropped(self):
        out = sanitize_layout({'lineItems': {'columns': [
            {'key': 'amount_applied', 'visible': True, 'width': 100},
            {'key': 'invoice_no', 'visible': False, 'width': 80},
            {'key': 'bogus', 'visible': True, 'width': 50},
        ]}})
        keys = [c['key'] for c in out['lineItems']['columns']]
        assert keys[0] == 'amount_applied' and keys[1] == 'invoice_no'
        assert 'bogus' not in keys
        assert set(keys) == set(COLUMN_KEYS)
        assert out['lineItems']['columns'][1]['visible'] is False

    def test_columns_have_independent_x(self):
        out = sanitize_layout({'lineItems': {'y': 250, 'rowHeight': 24,
                                             'columns': [{'key': 'amount_applied', 'x': 777}]}})
        col = next(c for c in out['lineItems']['columns'] if c['key'] == 'amount_applied')
        assert col['x'] == 777
        assert out['lineItems']['y'] == 250 and out['lineItems']['rowHeight'] == 24
        assert all('x' in c for c in out['lineItems']['columns'])


class TestTexts:
    def test_default_signature_texts(self):
        out = sanitize_layout({})
        assert set(out['texts']) == set(TEXT_KEYS) == {'prepared_by', 'received_by', 'approved_by'}
        assert out['texts']['received_by']['text'] == 'Received by:'

    def test_text_edited_and_capped(self):
        out = sanitize_layout({'texts': {'received_by': {'text': 'x' * 500, 'x': 200}}})
        assert len(out['texts']['received_by']['text']) <= 200
        assert out['texts']['received_by']['x'] == 200
        assert out['texts']['approved_by']['text'] == 'Approved by:'


class TestPaperAndDate:
    def test_default_paper_continuous_date_long(self):
        assert DEFAULT_CRV_PREPRINTED_LAYOUT['paper'] == 'continuous'
        assert sanitize_layout({})['dateFormat'] == 'long'

    def test_letter_and_iso_accepted_unknown_falls_back(self):
        assert sanitize_layout({'paper': 'letter'})['paper'] == 'letter'
        assert sanitize_layout({'paper': 'a4'})['paper'] == 'continuous'
        assert sanitize_layout({'dateFormat': 'iso'})['dateFormat'] == 'iso'
        assert sanitize_layout({'dateFormat': 'bogus'})['dateFormat'] == 'long'


class TestFonts:
    def test_dot_matrix_group_and_default_monospace(self):
        assert 'Dot-matrix friendly' in [label for label, _ in FONT_GROUPS]
        assert 'monospace' in DEFAULT_CRV_PREPRINTED_LAYOUT['page']['fontFamily']
        flat = [f for _l, fonts in FONT_GROUPS for f in fonts]
        assert flat == ALLOWED_FONTS


class TestExtras:
    def test_valid_extra_kept_unknown_dropped_capped(self):
        out = sanitize_layout({'extras': [
            {'key': 'crv_no', 'x': 100, 'y': 200, 'fontSize': 12, 'bold': True},
            {'key': 'bogus', 'x': 1, 'y': 1},
        ]})
        assert len(out['extras']) == 1 and out['extras'][0]['key'] == 'crv_no'
        many = [{'key': 'notes', 'x': 0, 'y': 0} for _ in range(200)]
        assert len(sanitize_layout({'extras': many})['extras']) <= 50


class TestGetSave:
    def test_get_returns_default_when_unset(self, db_session):
        assert get_layout()['fields']['crv_no'] == \
            DEFAULT_CRV_PREPRINTED_LAYOUT['fields']['crv_no']

    def test_get_returns_default_on_corrupt_json(self, db_session):
        AppSettings.set_setting(LAYOUT_SETTING_KEY, 'not-json{', 'system')
        assert set(get_layout()['fields']) == set(FIELD_KEYS)

    def test_save_persists_sanitized_and_audits(self, db_session, admin_user):
        result = save_layout({'fields': {'crv_no': {'x': 300, 'y': 90}}}, admin_user.username)
        assert result['fields']['crv_no']['x'] == 300
        stored = json.loads(AppSettings.get_setting(LAYOUT_SETTING_KEY))
        assert stored['fields']['crv_no']['x'] == 300
        entry = AuditLog.query.filter_by(
            module='cash_receipts', record_identifier='crv_preprinted_layout'
        ).order_by(AuditLog.id.desc()).first()
        assert entry is not None and entry.action == 'update'
