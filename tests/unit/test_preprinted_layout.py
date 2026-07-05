import json
import pytest
from app.settings import AppSettings
from app.sales_invoices.preprinted_layout import (
    DEFAULT_SV_PREPRINTED_LAYOUT, LAYOUT_SETTING_KEY, FIELD_KEYS, COLUMN_KEYS,
    ALLOWED_FONTS, FONT_GROUPS, sanitize_layout, get_layout, save_layout,
)
from app.audit.models import AuditLog

pytestmark = [pytest.mark.unit, pytest.mark.sales_invoices]


class TestSanitize:
    def test_empty_input_returns_full_default(self):
        out = sanitize_layout({})
        assert set(out['fields']) == set(FIELD_KEYS)
        assert [c['key'] for c in out['lineItems']['columns']] == COLUMN_KEYS
        assert out['page']['fontFamily'] == DEFAULT_SV_PREPRINTED_LAYOUT['page']['fontFamily']

    def test_unknown_field_dropped_known_field_kept(self):
        out = sanitize_layout({'fields': {'invoice_no': {'x': 111, 'y': 222},
                                          'evil_key': {'x': 5, 'y': 5}}})
        assert 'evil_key' not in out['fields']
        assert out['fields']['invoice_no']['x'] == 111
        assert out['fields']['invoice_no']['y'] == 222
        # missing field still present at its default
        assert out['fields']['terms'] == DEFAULT_SV_PREPRINTED_LAYOUT['fields']['terms']

    def test_coords_and_sizes_clamped_and_coerced(self):
        out = sanitize_layout({'fields': {'invoice_no': {'x': -50, 'y': 99999,
                                                         'fontSize': 999, 'bold': 'yes'}}})
        f = out['fields']['invoice_no']
        assert f['x'] == 0            # clamped to >= 0
        assert f['y'] == 1008         # clamped to canvas height (10.5in @96dpi)
        assert f['fontSize'] == 72    # clamped to <= 72
        assert f['bold'] is True      # truthy coerced to bool

    def test_disallowed_font_falls_back_to_default(self):
        out = sanitize_layout({'page': {'fontFamily': 'Comic Sans MS'}})
        assert out['page']['fontFamily'] == DEFAULT_SV_PREPRINTED_LAYOUT['page']['fontFamily']

    def test_columns_reorder_and_hide_preserved_unknown_dropped(self):
        out = sanitize_layout({'lineItems': {'columns': [
            {'key': 'amount', 'visible': True, 'width': 100},
            {'key': 'description', 'visible': False, 'width': 300},
            {'key': 'bogus', 'visible': True, 'width': 50},
        ]}})
        keys = [c['key'] for c in out['lineItems']['columns']]
        assert keys[0] == 'amount' and keys[1] == 'description'   # order preserved
        assert 'bogus' not in keys                                # unknown dropped
        assert set(keys) == set(COLUMN_KEYS)                      # missing ones appended
        assert out['lineItems']['columns'][1]['visible'] is False

    def test_columns_have_independent_x_and_band_has_rowheight(self):
        out = sanitize_layout({'lineItems': {'y': 250, 'rowHeight': 24,
                                             'columns': [{'key': 'amount', 'x': 777}]}})
        amount = next(c for c in out['lineItems']['columns'] if c['key'] == 'amount')
        assert amount['x'] == 777                 # per-column x preserved
        assert out['lineItems']['y'] == 250
        assert out['lineItems']['rowHeight'] == 24
        assert 'x' not in out['lineItems']         # no block-level x/width anymore
        assert 'width' not in out['lineItems']
        # every column carries its own x
        assert all('x' in c for c in out['lineItems']['columns'])


class TestFonts:
    def test_new_monospace_fonts_allowed_and_round_trip(self):
        for f in ['Consolas, "Courier New", monospace', '"Lucida Console", Monaco, monospace']:
            assert f in ALLOWED_FONTS
            assert sanitize_layout({'page': {'fontFamily': f}})['page']['fontFamily'] == f

    def test_groups_flatten_to_allowed_no_dupes(self):
        flat = [f for _label, fonts in FONT_GROUPS for f in fonts]
        assert flat == ALLOWED_FONTS
        assert len(ALLOWED_FONTS) == len(set(ALLOWED_FONTS))

    def test_dot_matrix_group_exists(self):
        labels = [label for label, _fonts in FONT_GROUPS]
        assert 'Dot-matrix friendly' in labels

    def test_default_font_is_monospace(self):
        assert 'monospace' in DEFAULT_SV_PREPRINTED_LAYOUT['page']['fontFamily']


class TestGetSave:
    def test_get_returns_default_when_unset(self, db_session):
        assert get_layout()['fields']['invoice_no'] == \
            DEFAULT_SV_PREPRINTED_LAYOUT['fields']['invoice_no']

    def test_get_returns_default_on_corrupt_json(self, db_session):
        AppSettings.set_setting(LAYOUT_SETTING_KEY, 'not-json{', 'system')
        assert set(get_layout()['fields']) == set(FIELD_KEYS)

    def test_save_persists_sanitized_and_audits(self, db_session, admin_user):
        result = save_layout({'fields': {'invoice_no': {'x': 300, 'y': 90}}},
                             admin_user.username)
        assert result['fields']['invoice_no']['x'] == 300
        stored = json.loads(AppSettings.get_setting(LAYOUT_SETTING_KEY))
        assert stored['fields']['invoice_no']['x'] == 300
        entry = AuditLog.query.filter_by(
            module='sales_invoices', record_identifier='sv_preprinted_layout'
        ).order_by(AuditLog.id.desc()).first()
        assert entry is not None and entry.action == 'update'
