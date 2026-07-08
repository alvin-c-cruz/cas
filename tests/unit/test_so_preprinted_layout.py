import json
import pytest
from app.settings import AppSettings
from app.sales_orders.preprinted_layout import (
    DEFAULT_SO_PREPRINTED_LAYOUT, LAYOUT_SETTING_KEY, FIELD_KEYS, COLUMN_KEYS,
    ALLOWED_FONTS, FONT_GROUPS, sanitize_layout, get_layout, save_layout,
)
from app.audit.models import AuditLog

pytestmark = [pytest.mark.integration, pytest.mark.sales_orders]


class TestSanitize:
    def test_empty_input_returns_full_default(self):
        out = sanitize_layout({})
        assert set(out['fields']) == set(FIELD_KEYS)
        assert [c['key'] for c in out['lineItems']['columns']] == COLUMN_KEYS
        assert out['page']['fontFamily'] == DEFAULT_SO_PREPRINTED_LAYOUT['page']['fontFamily']

    def test_every_field_key_has_a_default_box(self):
        # A missing default would KeyError inside sanitize_layout; this guards it.
        out = sanitize_layout({})
        for k in FIELD_KEYS:
            box = out['fields'][k]
            assert {'x', 'y', 'fontSize', 'bold', 'hidden'} <= set(box)

    def test_unknown_field_dropped_known_field_kept(self):
        out = sanitize_layout({'fields': {'so_no': {'x': 111, 'y': 222},
                                          'evil_key': {'x': 5, 'y': 5}}})
        assert 'evil_key' not in out['fields']
        assert out['fields']['so_no']['x'] == 111
        assert out['fields']['so_no']['y'] == 222
        # missing field still present at its (sanitized) default
        assert out['fields']['terms'] == sanitize_layout({})['fields']['terms']

    def test_coords_and_sizes_clamped_and_coerced(self):
        out = sanitize_layout({'fields': {'so_no': {'x': -50, 'y': 99999,
                                                    'fontSize': 999, 'bold': 'yes'}}})
        f = out['fields']['so_no']
        assert f['x'] == 48           # clamped to >= SAFE_MARGIN (48)
        assert f['y'] == 1008         # clamped to canvas height (10.5in @96dpi)
        assert f['fontSize'] == 72    # clamped to <= 72
        assert f['bold'] is True      # truthy coerced to bool

    def test_disallowed_font_falls_back_to_default(self):
        out = sanitize_layout({'page': {'fontFamily': 'Comic Sans MS'}})
        assert out['page']['fontFamily'] == DEFAULT_SO_PREPRINTED_LAYOUT['page']['fontFamily']

    def test_columns_reorder_and_hide_preserved_unknown_dropped(self):
        out = sanitize_layout({'lineItems': {'columns': [
            {'key': 'amount', 'visible': True, 'width': 100},
            {'key': 'quantity', 'visible': False, 'width': 60},
            {'key': 'bogus', 'visible': True, 'width': 50},
        ]}})
        keys = [c['key'] for c in out['lineItems']['columns']]
        assert keys[0] == 'amount' and keys[1] == 'quantity'     # order preserved
        assert 'bogus' not in keys                                # unknown dropped
        assert set(keys) == set(COLUMN_KEYS)                      # missing ones appended
        assert out['lineItems']['columns'][1]['visible'] is False

    def test_columns_have_independent_x_and_band_has_rowheight(self):
        out = sanitize_layout({'lineItems': {'y': 250, 'rowHeight': 24,
                                             'columns': [{'key': 'amount', 'x': 777}]}})
        amount = next(c for c in out['lineItems']['columns'] if c['key'] == 'amount')
        assert amount['x'] == 777
        assert out['lineItems']['y'] == 250
        assert out['lineItems']['rowHeight'] == 24
        assert 'x' not in out['lineItems']
        assert 'width' not in out['lineItems']
        assert all('x' in c for c in out['lineItems']['columns'])


class TestPaper:
    def test_default_paper_is_continuous(self):
        assert DEFAULT_SO_PREPRINTED_LAYOUT['paper'] == 'continuous'
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
        assert {t['id'] for t in out['texts']} == {'preparer', 'checker', 'approver'}
        assert self._by_id(out)['preparer']['text'] == 'Prepared by:'


class TestExtras:
    def test_valid_extra_kept_unknown_dropped(self):
        out = sanitize_layout({'extras': [
            {'key': 'so_no', 'x': 100, 'y': 200, 'fontSize': 12, 'bold': True},
            {'key': 'bogus', 'x': 1, 'y': 1},
        ]})
        assert len(out['extras']) == 1
        assert out['extras'][0]['key'] == 'so_no'
        assert out['extras'][0]['x'] == 100 and out['extras'][0]['bold'] is True


class TestDateFormat:
    def test_default_is_long(self):
        assert DEFAULT_SO_PREPRINTED_LAYOUT['dateFormat'] == 'long'
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
        assert 'monospace' in DEFAULT_SO_PREPRINTED_LAYOUT['page']['fontFamily']


class TestGetSave:
    def test_get_returns_default_when_unset(self, db_session):
        out = get_layout()
        assert set(out['fields']) == set(FIELD_KEYS)
        assert out['fields']['so_no'] == DEFAULT_SO_PREPRINTED_LAYOUT['fields']['so_no']

    def test_get_returns_default_on_corrupt_json(self, db_session):
        AppSettings.set_setting(LAYOUT_SETTING_KEY, 'not-json{', 'system')
        assert set(get_layout()['fields']) == set(FIELD_KEYS)

    def test_save_persists_sanitized_and_round_trips_and_audits(self, db_session, admin_user):
        result = save_layout({'fields': {'so_no': {'x': 300, 'y': 90}}},
                             admin_user.username)
        assert result['fields']['so_no']['x'] == 300
        stored = json.loads(AppSettings.get_setting(LAYOUT_SETTING_KEY))
        assert stored['fields']['so_no']['x'] == 300
        # round-trip: reading it back yields the same value
        assert get_layout()['fields']['so_no']['x'] == 300
        entry = AuditLog.query.filter_by(
            module='sales_orders', record_identifier='so_preprinted_layout'
        ).order_by(AuditLog.id.desc()).first()
        assert entry is not None and entry.action == 'update'
