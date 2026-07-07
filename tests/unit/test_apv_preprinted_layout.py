import json
import pytest
from app.settings import AppSettings
from app.accounts_payable.preprinted_layout import (
    DEFAULT_APV_PREPRINTED_LAYOUT, LAYOUT_SETTING_KEY, FIELD_KEYS, COLUMN_KEYS,
    TEXT_KEYS, ALLOWED_FONTS, FONT_GROUPS, sanitize_layout, get_layout, save_layout,
    _layout_key,
)
from app.audit.models import AuditLog

pytestmark = [pytest.mark.unit, pytest.mark.accounts_payable]


class TestSanitize:
    def test_empty_input_returns_full_default(self):
        out = sanitize_layout({})
        assert set(out['fields']) == set(FIELD_KEYS)
        assert [c['key'] for c in out['lineItems']['columns']] == COLUMN_KEYS
        assert out['page']['fontFamily'] == DEFAULT_APV_PREPRINTED_LAYOUT['page']['fontFamily']

    def test_apv_specific_field_keys(self):
        # APV header + vendor + BIR payable summary fields (NOT the SI/CRV fields)
        for k in ('apv_no', 'apv_date', 'due_date', 'terms',
                  'vendor_name', 'vendor_invoice_no', 'net_payable'):
            assert k in FIELD_KEYS
        assert 'crv_no' not in FIELD_KEYS       # that's the CRV form's field
        assert 'invoice_no' not in FIELD_KEYS   # that's the SI form's field

    def test_unknown_field_dropped_known_field_kept(self):
        out = sanitize_layout({'fields': {'apv_no': {'x': 111, 'y': 222},
                                          'evil_key': {'x': 5, 'y': 5}}})
        assert 'evil_key' not in out['fields']
        assert out['fields']['apv_no']['x'] == 111
        assert out['fields']['apv_no']['y'] == 222
        # a field the input omitted still renders at its default
        assert out['fields']['net_payable'] == \
            sanitize_layout({})['fields']['net_payable']

    def test_coords_and_sizes_clamped_and_coerced(self):
        out = sanitize_layout({'fields': {'apv_no': {'x': -50, 'y': 99999,
                                                     'fontSize': 999, 'bold': 'yes'}}})
        f = out['fields']['apv_no']
        assert f['x'] == 0
        assert f['y'] == 1008
        assert f['fontSize'] == 72
        assert f['bold'] is True

    def test_disallowed_font_falls_back_to_default(self):
        out = sanitize_layout({'page': {'fontFamily': 'Comic Sans MS'}})
        assert out['page']['fontFamily'] == DEFAULT_APV_PREPRINTED_LAYOUT['page']['fontFamily']

    def test_particulars_columns(self):
        assert COLUMN_KEYS == ['line_number', 'product', 'description', 'qty',
                               'uom', 'unit_price', 'amount', 'account_title']

    def test_columns_reorder_and_hide_preserved_unknown_dropped(self):
        out = sanitize_layout({'lineItems': {'columns': [
            {'key': 'amount', 'visible': True, 'width': 100},
            {'key': 'description', 'visible': False, 'width': 80},
            {'key': 'bogus', 'visible': True, 'width': 50},
        ]}})
        keys = [c['key'] for c in out['lineItems']['columns']]
        assert keys[0] == 'amount' and keys[1] == 'description'
        assert 'bogus' not in keys
        assert set(keys) == set(COLUMN_KEYS)
        assert out['lineItems']['columns'][1]['visible'] is False

    def test_columns_have_independent_x(self):
        out = sanitize_layout({'lineItems': {'y': 250, 'rowHeight': 24,
                                             'columns': [{'key': 'amount', 'x': 777}]}})
        col = next(c for c in out['lineItems']['columns'] if c['key'] == 'amount')
        assert col['x'] == 777
        assert out['lineItems']['y'] == 250 and out['lineItems']['rowHeight'] == 24
        assert all('x' in c for c in out['lineItems']['columns'])


class TestTexts:
    def _by_id(self, out):
        return {t['id']: t for t in out['texts']}

    def test_default_signature_texts(self):
        out = sanitize_layout({})
        assert isinstance(out['texts'], list)
        assert {t['id'] for t in out['texts']} == set(TEXT_KEYS) == {'prepared_by', 'checked_by', 'approved_by'}
        assert self._by_id(out)['checked_by']['text'] == 'Checked by:'

    def test_text_edited_and_capped(self):
        # Legacy dict input still migrates; a stored override lands on the right id.
        out = sanitize_layout({'texts': {'checked_by': {'text': 'x' * 500, 'x': 200}}})
        by = self._by_id(out)
        assert len(by['checked_by']['text']) <= 200
        assert by['checked_by']['x'] == 200
        assert by['approved_by']['text'] == 'Approved by:'

    def test_added_text_kept_and_deleted_default_stays_gone(self):
        out = sanitize_layout({'texts': [
            {'id': 'prepared_by', 'text': 'Prepared by:', 'x': 60, 'y': 720},
            {'id': 'note1', 'text': 'Subject to 2% EWT', 'x': 60, 'y': 800},
        ]})
        ids = [t['id'] for t in out['texts']]
        assert ids == ['prepared_by', 'note1']   # checked_by/approved_by NOT re-injected


class TestPaperAndDate:
    def test_default_paper_continuous_date_long(self):
        assert DEFAULT_APV_PREPRINTED_LAYOUT['paper'] == 'continuous'
        assert sanitize_layout({})['dateFormat'] == 'long'

    def test_letter_and_iso_accepted_unknown_falls_back(self):
        assert sanitize_layout({'paper': 'letter'})['paper'] == 'letter'
        assert sanitize_layout({'paper': 'a4'})['paper'] == 'continuous'
        assert sanitize_layout({'dateFormat': 'iso'})['dateFormat'] == 'iso'
        assert sanitize_layout({'dateFormat': 'bogus'})['dateFormat'] == 'long'


class TestFonts:
    def test_dot_matrix_group_and_default_monospace(self):
        assert 'Dot-matrix friendly' in [label for label, _ in FONT_GROUPS]
        assert 'monospace' in DEFAULT_APV_PREPRINTED_LAYOUT['page']['fontFamily']
        flat = [f for _l, fonts in FONT_GROUPS for f in fonts]
        assert flat == ALLOWED_FONTS


class TestExtras:
    def test_valid_extra_kept_unknown_dropped_capped(self):
        out = sanitize_layout({'extras': [
            {'key': 'apv_no', 'x': 100, 'y': 200, 'fontSize': 12, 'bold': True},
            {'key': 'bogus', 'x': 1, 'y': 1},
        ]})
        assert len(out['extras']) == 1 and out['extras'][0]['key'] == 'apv_no'
        many = [{'key': 'notes', 'x': 0, 'y': 0} for _ in range(200)]
        assert len(sanitize_layout({'extras': many})['extras']) <= 50


class TestGetSave:
    def test_get_returns_default_when_unset(self, db_session):
        assert get_layout()['fields']['apv_no'] == \
            DEFAULT_APV_PREPRINTED_LAYOUT['fields']['apv_no']

    def test_get_returns_default_on_corrupt_json(self, db_session):
        AppSettings.set_setting(LAYOUT_SETTING_KEY, 'not-json{', 'system')
        assert set(get_layout()['fields']) == set(FIELD_KEYS)

    def test_save_persists_sanitized_and_audits(self, db_session, admin_user):
        result = save_layout({'fields': {'apv_no': {'x': 300, 'y': 90}}}, admin_user.username)
        assert result['fields']['apv_no']['x'] == 300
        stored = json.loads(AppSettings.get_setting(LAYOUT_SETTING_KEY))
        assert stored['fields']['apv_no']['x'] == 300
        entry = AuditLog.query.filter_by(
            module='accounts_payable', record_identifier='apv_preprinted_layout'
        ).order_by(AuditLog.id.desc()).first()
        assert entry is not None and entry.action == 'update'


class TestBranchScope:
    def test_branch_key_namespacing(self):
        assert _layout_key(None) == LAYOUT_SETTING_KEY
        assert _layout_key(7) == f'{LAYOUT_SETTING_KEY}:7'

    def test_two_branches_keep_independent_layouts(self, db_session, admin_user):
        save_layout({'fields': {'apv_no': {'x': 100, 'y': 10}}}, admin_user.username, branch_id=1)
        save_layout({'fields': {'apv_no': {'x': 800, 'y': 10}}}, admin_user.username, branch_id=2)
        assert get_layout(branch_id=1)['fields']['apv_no']['x'] == 100
        assert get_layout(branch_id=2)['fields']['apv_no']['x'] == 800

    def test_unset_branch_falls_back_to_default(self, db_session, admin_user):
        save_layout({'fields': {'apv_no': {'x': 100, 'y': 10}}}, admin_user.username, branch_id=1)
        # branch 99 never saved -> default, not branch 1's layout
        assert get_layout(branch_id=99)['fields']['apv_no'] == \
            DEFAULT_APV_PREPRINTED_LAYOUT['fields']['apv_no']
