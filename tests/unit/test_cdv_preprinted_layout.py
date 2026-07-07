import json
import pytest
from app.settings import AppSettings
from app.cash_disbursements.preprinted_layout import (
    DEFAULT_CDV_PREPRINTED_LAYOUT, LAYOUT_SETTING_KEY, FIELD_KEYS, COLUMN_KEYS,
    TEXT_KEYS, ALLOWED_FONTS, FONT_GROUPS, sanitize_layout, get_layout, save_layout,
    _layout_key,
)
from app.audit.models import AuditLog

pytestmark = [pytest.mark.unit, pytest.mark.cash_disbursements]


class TestSanitize:
    def test_empty_input_returns_full_default(self):
        out = sanitize_layout({})
        assert set(out['fields']) == set(FIELD_KEYS)
        assert [c['key'] for c in out['lineItems']['columns']] == COLUMN_KEYS
        assert out['page']['fontFamily'] == DEFAULT_CDV_PREPRINTED_LAYOUT['page']['fontFamily']

    def test_cdv_specific_field_keys(self):
        # CDV header + payment fields (NOT the APV / SI / CRV header fields)
        for k in ('cdv_no', 'cdv_date', 'payment_method', 'check_no', 'cash_account',
                  'vendor_name'):
            assert k in FIELD_KEYS
        assert 'apv_no' not in FIELD_KEYS       # that's the APV form's field
        assert 'invoice_no' not in FIELD_KEYS   # that's the SI form's field

    def test_summary_fields_absent(self):
        # No SUMMARY block on the CDV pre-printed voucher (user 2026-07-07).
        for k in ('gross', 'net_payable', 'net_cash_disbursed', 'total_wt', 'input_vat'):
            assert k not in FIELD_KEYS

    def test_unknown_field_dropped_known_field_kept(self):
        out = sanitize_layout({'fields': {'cdv_no': {'x': 111, 'y': 222},
                                          'evil_key': {'x': 5, 'y': 5}}})
        assert 'evil_key' not in out['fields']
        assert out['fields']['cdv_no']['x'] == 111
        assert out['fields']['cdv_no']['y'] == 222
        assert out['fields']['payment_method'] == \
            sanitize_layout({})['fields']['payment_method']

    def test_coords_and_sizes_clamped_and_coerced(self):
        out = sanitize_layout({'fields': {'cdv_no': {'x': -50, 'y': 99999,
                                                     'fontSize': 999, 'bold': 'yes'}}})
        f = out['fields']['cdv_no']
        assert f['x'] == 0 and f['y'] == 1008 and f['fontSize'] == 72 and f['bold'] is True

    def test_disallowed_font_falls_back_to_default(self):
        out = sanitize_layout({'page': {'fontFamily': 'Comic Sans MS'}})
        assert out['page']['fontFamily'] == DEFAULT_CDV_PREPRINTED_LAYOUT['page']['fontFamily']

    def test_section_b_expense_columns(self):
        # The line band = Section B (Direct Expenses); Section A (AP bills) is NOT a band.
        assert COLUMN_KEYS == ['line_number', 'product', 'description', 'qty',
                               'uom', 'unit_price', 'account_title', 'amount']

    def test_columns_reorder_and_hide_preserved_unknown_dropped(self):
        out = sanitize_layout({'lineItems': {'columns': [
            {'key': 'amount', 'visible': True, 'width': 100},
            {'key': 'description', 'visible': False, 'width': 80},
            {'key': 'bogus', 'visible': True, 'width': 50},
        ]}})
        keys = [c['key'] for c in out['lineItems']['columns']]
        assert keys[0] == 'amount' and keys[1] == 'description'
        assert 'bogus' not in keys and set(keys) == set(COLUMN_KEYS)
        assert out['lineItems']['columns'][1]['visible'] is False


class TestJournalEntryBlock:
    def test_default_mode_is_combined(self):
        assert DEFAULT_CDV_PREPRINTED_LAYOUT['journalEntry']['mode'] == 'combined'
        assert sanitize_layout({})['journalEntry']['mode'] == 'combined'

    def test_mode_whitelisted(self):
        assert sanitize_layout({'journalEntry': {'mode': 'separated'}})['journalEntry']['mode'] == 'separated'
        assert sanitize_layout({'journalEntry': {'mode': 'bogus'}})['journalEntry']['mode'] == 'combined'

    def test_band_positions_clamped(self):
        je = sanitize_layout({'journalEntry': {'combined': {'x': -5, 'y': 99999, 'width': 5}}})['journalEntry']
        assert je['combined']['x'] == 0 and je['combined']['y'] == 1008 and je['combined']['width'] >= 10

    def test_debit_and_credit_bands_independent(self):
        je = sanitize_layout({'journalEntry': {'debit': {'x': 111}, 'credit': {'x': 777}}})['journalEntry']
        assert je['debit']['x'] == 111 and je['credit']['x'] == 777


class TestTexts:
    def _by_id(self, out):
        return {t['id']: t for t in out['texts']}

    def test_default_signature_texts(self):
        out = sanitize_layout({})
        assert isinstance(out['texts'], list)
        assert {t['id'] for t in out['texts']} == set(TEXT_KEYS) == {'prepared_by', 'checked_by', 'approved_by'}
        assert self._by_id(out)['checked_by']['text'] == 'Checked by:'

    def test_added_text_kept_and_deleted_default_stays_gone(self):
        out = sanitize_layout({'texts': [
            {'id': 'prepared_by', 'text': 'Prepared by:', 'x': 60, 'y': 720},
            {'id': 'note1', 'text': 'Received the cash/check', 'x': 60, 'y': 800},
        ]})
        assert [t['id'] for t in out['texts']] == ['prepared_by', 'note1']


class TestPaperAndDate:
    def test_default_paper_continuous_date_long(self):
        assert DEFAULT_CDV_PREPRINTED_LAYOUT['paper'] == 'continuous'
        assert sanitize_layout({})['dateFormat'] == 'long'

    def test_letter_and_iso_accepted_unknown_falls_back(self):
        assert sanitize_layout({'paper': 'letter'})['paper'] == 'letter'
        assert sanitize_layout({'paper': 'a4'})['paper'] == 'continuous'
        assert sanitize_layout({'dateFormat': 'iso'})['dateFormat'] == 'iso'


class TestFonts:
    def test_dot_matrix_group_and_default_monospace(self):
        assert 'Dot-matrix friendly' in [label for label, _ in FONT_GROUPS]
        assert 'monospace' in DEFAULT_CDV_PREPRINTED_LAYOUT['page']['fontFamily']
        assert [f for _l, fonts in FONT_GROUPS for f in fonts] == ALLOWED_FONTS


class TestGetSave:
    def test_get_returns_default_when_unset(self, db_session):
        assert get_layout()['fields']['cdv_no'] == DEFAULT_CDV_PREPRINTED_LAYOUT['fields']['cdv_no']

    def test_get_returns_default_on_corrupt_json(self, db_session):
        AppSettings.set_setting(LAYOUT_SETTING_KEY, 'not-json{', 'system')
        assert set(get_layout()['fields']) == set(FIELD_KEYS)

    def test_save_persists_sanitized_and_audits(self, db_session, admin_user):
        result = save_layout({'fields': {'cdv_no': {'x': 300, 'y': 90}}}, admin_user.username)
        assert result['fields']['cdv_no']['x'] == 300
        stored = json.loads(AppSettings.get_setting(LAYOUT_SETTING_KEY))
        assert stored['fields']['cdv_no']['x'] == 300
        entry = AuditLog.query.filter_by(
            module='cash_disbursements', record_identifier='cdv_preprinted_layout'
        ).order_by(AuditLog.id.desc()).first()
        assert entry is not None and entry.action == 'update'


class TestBranchScope:
    def test_branch_key_namespacing(self):
        assert _layout_key(None) == LAYOUT_SETTING_KEY
        assert _layout_key(7) == f'{LAYOUT_SETTING_KEY}:7'

    def test_two_branches_keep_independent_layouts(self, db_session, admin_user):
        save_layout({'fields': {'cdv_no': {'x': 100, 'y': 10}}}, admin_user.username, branch_id=1)
        save_layout({'fields': {'cdv_no': {'x': 800, 'y': 10}}}, admin_user.username, branch_id=2)
        assert get_layout(branch_id=1)['fields']['cdv_no']['x'] == 100
        assert get_layout(branch_id=2)['fields']['cdv_no']['x'] == 800
