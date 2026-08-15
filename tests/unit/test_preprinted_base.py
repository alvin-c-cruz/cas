"""The shared pre-printed layout core.

This carries the highest test weight in the arc: a defect here breaks all three
consuming modules at once, and it is the code that decides what a client's
saved stationery alignment looks like after an upgrade.
"""
import json

import pytest

from app.common import preprinted_base as base

pytestmark = [pytest.mark.unit]

FIELD_KEYS = ['doc_no', 'doc_date']

DEFAULT = {
    'paper': 'continuous',
    'dateFormat': 'ymd',
    'page': {'fontFamily': base.ALLOWED_FONTS[0]},
    'fields': {
        'doc_no': {'x': 100, 'y': 100, 'w': 200, 'fontSize': 10, 'bold': False, 'hidden': False},
        'doc_date': {'x': 300, 'y': 100, 'w': 120, 'fontSize': 10, 'bold': False, 'hidden': False},
    },
    'lineItems': {'y': 300, 'rowHeight': 20, 'fontSize': 9, 'bold': False, 'columns': {}},
    'extras': [],
    'texts': {k: '' for k in base.TEXT_KEYS},
}


@pytest.fixture
def api():
    return base.build_layout_api('test_preprinted_layout', FIELD_KEYS, DEFAULT,
                                 'test_module', 'test_preprinted_layout')


class TestTheSanitiserRejectsJunk:

    def test_an_unknown_top_level_key_is_dropped(self, api):
        sanitize, _, _ = api
        out = sanitize({'paper': 'letter', 'evil': 'payload'})
        assert 'evil' not in out

    def test_an_unknown_field_key_is_dropped(self, api):
        """A stored layout naming a field this document does not have must not
        survive -- that is how one document's layout leaks into another's."""
        sanitize, _, _ = api
        out = sanitize({'fields': {'doc_no': {'x': 10}, 'not_a_field': {'x': 10}}})
        assert set(out['fields']) == set(FIELD_KEYS)

    def test_an_unlisted_font_falls_back_to_the_default(self, api):
        sanitize, _, _ = api
        out = sanitize({'page': {'fontFamily': 'Comic Sans MS; DROP TABLE'}})
        assert out['page']['fontFamily'] in base.ALLOWED_FONTS

    def test_an_unlisted_paper_falls_back(self, api):
        sanitize, _, _ = api
        assert sanitize({'paper': 'A0'})['paper'] in base.ALLOWED_PAPERS

    @pytest.mark.parametrize('bad', [-5000, 99999, 'x', None])
    def test_an_out_of_range_coordinate_is_clamped_or_defaulted(self, api, bad):
        sanitize, _, _ = api
        x = sanitize({'fields': {'doc_no': {'x': bad}}})['fields']['doc_no']['x']
        assert 0 <= x <= base.CANVAS_W

    def test_font_size_is_clamped_to_the_allowed_band(self, api):
        sanitize, _, _ = api
        big = sanitize({'fields': {'doc_no': {'fontSize': 999}}})['fields']['doc_no']['fontSize']
        assert base.FONT_MIN <= big <= base.FONT_MAX

    def test_extras_are_capped(self, api):
        sanitize, _, _ = api
        out = sanitize({'extras': [{'key': 'doc_no', 'x': 1, 'y': 1}] * (base.MAX_EXTRAS + 25)})
        assert len(out['extras']) <= base.MAX_EXTRAS


class TestForwardCompatibility:
    """The upgrade case: a layout saved before a field existed must still render
    that field at its default rather than vanishing or raising."""

    def test_a_layout_missing_a_field_gets_it_at_default(self, api):
        sanitize, _, _ = api
        out = sanitize({'fields': {'doc_no': {'x': 50, 'y': 60}}})
        assert out['fields']['doc_date'] == DEFAULT['fields']['doc_date']

    def test_an_empty_layout_returns_the_full_default(self, api):
        sanitize, _, _ = api
        assert sanitize({}) == sanitize(DEFAULT)

    def test_a_non_dict_input_does_not_raise(self, api):
        sanitize, _, _ = api
        assert sanitize(None)['paper'] in base.ALLOWED_PAPERS


class TestPersistence:

    def test_get_returns_defaults_when_unset(self, db_session, api):
        _, get_layout, _ = api
        assert get_layout(branch_id=1)['paper'] == DEFAULT['paper']

    def test_save_then_get_round_trips_per_branch(self, db_session, admin_user, api):
        """Layouts are PER BRANCH -- branch 2 must not see branch 1's layout."""
        _, get_layout, save_layout = api
        save_layout({'fields': {'doc_no': {'x': 222}}}, admin_user.username, branch_id=1)
        assert get_layout(branch_id=1)['fields']['doc_no']['x'] == 222
        assert get_layout(branch_id=2)['fields']['doc_no']['x'] == DEFAULT['fields']['doc_no']['x']

    def test_corrupt_stored_json_falls_back_to_defaults(self, db_session, api):
        """A hand-edited or truncated settings row must not 500 the print page."""
        from app.settings import AppSettings
        _, get_layout, _ = api
        AppSettings.set_setting('test_preprinted_layout:1', '{not json')
        assert get_layout(branch_id=1)['paper'] == DEFAULT['paper']

    def test_save_writes_an_audit_row(self, db_session, admin_user, api):
        from app.audit.models import AuditLog
        _, _, save_layout = api
        save_layout({'paper': 'letter'}, admin_user.username, branch_id=1)
        assert AuditLog.query.filter_by(record_identifier='test_preprinted_layout').count() == 1
