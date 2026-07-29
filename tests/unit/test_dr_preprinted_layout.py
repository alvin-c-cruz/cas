import json
import pytest
from app.settings import AppSettings
from app.delivery_receipts.preprinted_layout import (
    DEFAULT_DR_PREPRINTED_LAYOUT, LAYOUT_SETTING_KEY, FIELD_KEYS, COLUMN_KEYS,
    MULTILINE_FIELD_KEYS, MAX_NOTE_LINES, ALLOWED_FONTS, FONT_GROUPS,
    sanitize_layout, get_layout, save_layout, cap_note_lines,
)
from app.audit.models import AuditLog

pytestmark = [pytest.mark.integration, pytest.mark.delivery_receipts]


class TestSanitize:
    def test_empty_input_returns_full_default(self):
        out = sanitize_layout({})
        assert set(out['fields']) == set(FIELD_KEYS)
        assert [c['key'] for c in out['lineItems']['columns']] == COLUMN_KEYS
        assert out['page']['fontFamily'] == DEFAULT_DR_PREPRINTED_LAYOUT['page']['fontFamily']

    def test_every_field_key_has_a_default_box(self):
        # A missing default would KeyError inside sanitize_layout; this guards it.
        out = sanitize_layout({})
        for k in FIELD_KEYS:
            box = out['fields'][k]
            assert {'x', 'y', 'fontSize', 'bold', 'hidden'} <= set(box)

    def test_multiline_fields_use_identical_box_shape_no_extra_keys(self):
        # packing_notes/schedule_notes must sanitize to EXACTLY the same box shape
        # as any other field -- no unclamped attribute leaks in for them.
        out = sanitize_layout({})
        for k in MULTILINE_FIELD_KEYS:
            assert k in FIELD_KEYS
            assert set(out['fields'][k]) == {'x', 'y', 'fontSize', 'bold', 'hidden'}

    def test_unknown_field_dropped_known_field_kept(self):
        out = sanitize_layout({'fields': {'dr_no': {'x': 111, 'y': 222},
                                          'evil_key': {'x': 5, 'y': 5}}})
        assert 'evil_key' not in out['fields']
        assert out['fields']['dr_no']['x'] == 111
        assert out['fields']['dr_no']['y'] == 222
        # missing field still present at its (sanitized) default
        assert out['fields']['salesperson'] == sanitize_layout({})['fields']['salesperson']

    def test_coords_and_sizes_clamped_and_coerced(self):
        out = sanitize_layout({'fields': {'dr_no': {'x': -50, 'y': 99999,
                                                    'fontSize': 999, 'bold': 'yes'}}})
        f = out['fields']['dr_no']
        assert f['x'] == 48           # clamped to >= SAFE_MARGIN (48)
        assert f['y'] == 1008         # clamped to canvas height (10.5in @96dpi)
        assert f['fontSize'] == 72    # clamped to <= 72
        assert f['bold'] is True      # truthy coerced to bool

    def test_disallowed_font_falls_back_to_default(self):
        out = sanitize_layout({'page': {'fontFamily': 'Comic Sans MS'}})
        assert out['page']['fontFamily'] == DEFAULT_DR_PREPRINTED_LAYOUT['page']['fontFamily']

    def test_columns_reorder_and_hide_preserved_unknown_dropped(self):
        out = sanitize_layout({'lineItems': {'columns': [
            {'key': 'uom', 'visible': True, 'width': 60},
            {'key': 'quantity', 'visible': False, 'width': 80},
            {'key': 'bogus', 'visible': True, 'width': 50},
        ]}})
        keys = [c['key'] for c in out['lineItems']['columns']]
        assert keys[0] == 'uom' and keys[1] == 'quantity'          # order preserved
        assert 'bogus' not in keys                                  # unknown dropped
        assert set(keys) == set(COLUMN_KEYS)                        # missing ones appended
        assert out['lineItems']['columns'][1]['visible'] is False

    def test_columns_have_independent_x_and_band_has_rowheight(self):
        out = sanitize_layout({'lineItems': {'y': 250, 'rowHeight': 24,
                                             'columns': [{'key': 'quantity', 'x': 777}]}})
        qty = next(c for c in out['lineItems']['columns'] if c['key'] == 'quantity')
        assert qty['x'] == 777
        assert out['lineItems']['y'] == 250
        assert out['lineItems']['rowHeight'] == 24
        assert 'x' not in out['lineItems']
        assert 'width' not in out['lineItems']
        assert all('x' in c for c in out['lineItems']['columns'])


class TestPaper:
    def test_default_paper_is_continuous(self):
        assert DEFAULT_DR_PREPRINTED_LAYOUT['paper'] == 'continuous'
        assert sanitize_layout({})['paper'] == 'continuous'

    def test_letter_paper_accepted(self):
        assert sanitize_layout({'paper': 'letter'})['paper'] == 'letter'

    def test_unknown_paper_falls_back_to_continuous(self):
        assert sanitize_layout({'paper': 'a4-ish'})['paper'] == 'continuous'


class TestTexts:
    def _by_id(self, out):
        return {t['id']: t for t in out['texts']}

    def test_default_signature_texts(self):
        out = sanitize_layout({})
        assert isinstance(out['texts'], list)
        assert {t['id'] for t in out['texts']} == {'prepared_by', 'released_by', 'received_by'}
        assert self._by_id(out)['prepared_by']['text'] == 'Prepared by:'


class TestExtras:
    def test_valid_extra_kept_unknown_dropped(self):
        out = sanitize_layout({'extras': [
            {'key': 'dr_no', 'x': 100, 'y': 200, 'fontSize': 12, 'bold': True},
            {'key': 'bogus', 'x': 1, 'y': 1},
        ]})
        assert len(out['extras']) == 1
        assert out['extras'][0]['key'] == 'dr_no'
        assert out['extras'][0]['x'] == 100 and out['extras'][0]['bold'] is True

    def test_multiline_field_key_valid_as_extra(self):
        out = sanitize_layout({'extras': [
            {'key': 'packing_notes', 'x': 100, 'y': 200, 'fontSize': 10, 'bold': False},
        ]})
        assert out['extras'][0]['key'] == 'packing_notes'


class TestDateFormat:
    def test_default_is_long(self):
        assert DEFAULT_DR_PREPRINTED_LAYOUT['dateFormat'] == 'long'
        assert sanitize_layout({})['dateFormat'] == 'long'

    def test_iso_accepted(self):
        assert sanitize_layout({'dateFormat': 'iso'})['dateFormat'] == 'iso'

    def test_unknown_falls_back_to_long(self):
        assert sanitize_layout({'dateFormat': 'bogus'})['dateFormat'] == 'long'


class TestFonts:
    def test_groups_flatten_to_allowed_no_dupes(self):
        flat = [f for _label, fonts in FONT_GROUPS for f in fonts]
        assert flat == ALLOWED_FONTS
        assert len(ALLOWED_FONTS) == len(set(ALLOWED_FONTS))

    def test_default_font_is_monospace(self):
        assert 'monospace' in DEFAULT_DR_PREPRINTED_LAYOUT['page']['fontFamily']


class TestGetSave:
    def test_get_returns_default_when_unset(self, db_session):
        out = get_layout()
        assert set(out['fields']) == set(FIELD_KEYS)
        assert out['fields']['dr_no'] == DEFAULT_DR_PREPRINTED_LAYOUT['fields']['dr_no']

    def test_get_returns_default_on_corrupt_json(self, db_session):
        AppSettings.set_setting(LAYOUT_SETTING_KEY, 'not-json{', 'system')
        assert set(get_layout()['fields']) == set(FIELD_KEYS)

    def test_save_persists_sanitized_and_round_trips_and_audits(self, db_session, admin_user):
        result = save_layout({'fields': {'dr_no': {'x': 300, 'y': 90}}},
                             admin_user.username)
        assert result['fields']['dr_no']['x'] == 300
        stored = json.loads(AppSettings.get_setting(LAYOUT_SETTING_KEY))
        assert stored['fields']['dr_no']['x'] == 300
        # round-trip: reading it back yields the same value
        assert get_layout()['fields']['dr_no']['x'] == 300
        entry = AuditLog.query.filter_by(
            module='delivery_receipts', record_identifier='dr_preprinted_layout'
        ).order_by(AuditLog.id.desc()).first()
        assert entry is not None and entry.action == 'update'

    def test_get_save_are_branch_scoped(self, db_session, admin_user, main_branch, branch_manila):
        save_layout({'fields': {'dr_no': {'x': 111}}}, admin_user.username, main_branch.id)
        save_layout({'fields': {'dr_no': {'x': 222}}}, admin_user.username, branch_manila.id)
        assert get_layout(main_branch.id)['fields']['dr_no']['x'] == 111
        assert get_layout(branch_manila.id)['fields']['dr_no']['x'] == 222
        # un-scoped (legacy) key is untouched by either branch save
        assert get_layout()['fields']['dr_no']['x'] == DEFAULT_DR_PREPRINTED_LAYOUT['fields']['dr_no']['x']


class TestCapNoteLines:
    def test_blank_or_none_returns_empty_string(self):
        assert cap_note_lines(None) == ''
        assert cap_note_lines('') == ''

    def test_short_text_unchanged(self):
        text = 'line1\nline2'
        assert cap_note_lines(text) == text

    def test_truncates_to_max_note_lines(self):
        lines = [f'line{i}' for i in range(MAX_NOTE_LINES + 5)]
        out = cap_note_lines('\n'.join(lines))
        out_lines = out.split('\n')
        assert len(out_lines) == MAX_NOTE_LINES
        assert out_lines[-1] == f'line{MAX_NOTE_LINES - 1}'
        assert f'line{MAX_NOTE_LINES}' not in out

    def test_crlf_normalized(self):
        assert cap_note_lines('a\r\nb\r\nc') == 'a\nb\nc'
