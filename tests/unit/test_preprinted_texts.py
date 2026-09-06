"""Unit tests for the shared pre-printed layout-text reader/migrator.

`clean_texts(raw, defaults)` is the ONE piece of the pre-printed layout with no
document-data binding, shared by SI/CRV/APV. It is a forward-compatible reader:
accept the legacy DICT shape OR the new LIST shape, always return a sanitized LIST.
A bug here silently destroys a saved layout (get_layout falls back to DEFAULT on a
raise), so these tests pin the migration hard.
"""
import pytest
from app.common.preprinted_texts import (clean_texts, MAX_TEXTS, TEXT_MAXLEN,
                                         WIDTH_MIN, WIDTH_MAX)

pytestmark = [pytest.mark.unit]

DEFAULTS = [
    {'id': 'prepared_by', 'text': 'Prepared by:', 'x': 60,  'y': 720, 'fontSize': 10, 'bold': False, 'hidden': False},
    {'id': 'checked_by',  'text': 'Checked by:',  'x': 340, 'y': 720, 'fontSize': 10, 'bold': False, 'hidden': False},
    {'id': 'approved_by', 'text': 'Approved by:', 'x': 620, 'y': 720, 'fontSize': 10, 'bold': False, 'hidden': False},
]


def ids(out):
    return [t['id'] for t in out]


class TestShape:
    def test_returns_a_list(self):
        assert isinstance(clean_texts(None, DEFAULTS), list)

    def test_none_returns_full_defaults_in_order(self):
        out = clean_texts(None, DEFAULTS)
        assert ids(out) == ['prepared_by', 'checked_by', 'approved_by']
        assert out[0]['text'] == 'Prepared by:' and out[0]['x'] == 60

    def test_garbage_returns_full_defaults(self):
        assert ids(clean_texts('not-a-container', DEFAULTS)) == ids(DEFAULTS)
        assert ids(clean_texts(12345, DEFAULTS)) == ids(DEFAULTS)


class TestLegacyDictMigration:
    def test_full_legacy_dict_migrates_to_list_by_id(self):
        raw = {
            'prepared_by': {'text': 'Prepared by:', 'x': 61, 'y': 700, 'fontSize': 10, 'bold': False, 'hidden': False},
            'checked_by':  {'text': 'Checked by:',  'x': 341, 'y': 700, 'fontSize': 10, 'bold': False, 'hidden': False},
            'approved_by': {'text': 'Approved by:', 'x': 621, 'y': 700, 'fontSize': 10, 'bold': False, 'hidden': False},
        }
        out = clean_texts(raw, DEFAULTS)
        assert ids(out) == ['prepared_by', 'checked_by', 'approved_by']   # default order
        by = {t['id']: t for t in out}
        assert by['prepared_by']['x'] == 61 and by['checked_by']['x'] == 341
        assert by['approved_by']['y'] == 700

    def test_partial_legacy_dict_override_lands_on_right_default(self):
        # Only one text overridden; the other two must survive at their DEFAULTS.
        out = clean_texts({'checked_by': {'x': 300}}, DEFAULTS)
        by = {t['id']: t for t in out}
        assert ids(out) == ['prepared_by', 'checked_by', 'approved_by']
        assert by['checked_by']['x'] == 300
        assert by['checked_by']['text'] == 'Checked by:'      # untouched text = default
        assert by['prepared_by']['x'] == 60                   # default
        assert by['approved_by']['text'] == 'Approved by:'    # default

    def test_real_stored_blob_round_trips_without_loss(self):
        # A realistic full layout blob as get_setting() returns it TODAY (dict texts).
        stored = {
            'preparer': {'text': 'Prepared by: Ana', 'x': 55, 'y': 690, 'fontSize': 11, 'bold': True, 'hidden': False},
            'checker':  {'text': 'Checked by:',      'x': 330, 'y': 690, 'fontSize': 10, 'bold': False, 'hidden': True},
            'approver': {'text': 'Approved by:',      'x': 610, 'y': 690, 'fontSize': 10, 'bold': False, 'hidden': False},
        }
        si_defaults = [
            {'id': 'preparer', 'text': 'Prepared by:', 'x': 60,  'y': 720, 'fontSize': 10, 'bold': False, 'hidden': False},
            {'id': 'checker',  'text': 'Checked by:',  'x': 340, 'y': 720, 'fontSize': 10, 'bold': False, 'hidden': False},
            {'id': 'approver', 'text': 'Approved by:', 'x': 620, 'y': 720, 'fontSize': 10, 'bold': False, 'hidden': False},
        ]
        out = clean_texts(stored, si_defaults)
        by = {t['id']: t for t in out}
        assert ids(out) == ['preparer', 'checker', 'approver']
        assert by['preparer']['text'] == 'Prepared by: Ana' and by['preparer']['bold'] is True
        assert by['preparer']['x'] == 55
        assert by['checker']['hidden'] is True


class TestListShape:
    def test_added_text_beyond_defaults_kept(self):
        raw = [
            {'id': 'prepared_by', 'text': 'Prepared by:', 'x': 60, 'y': 720},
            {'id': 'checked_by',  'text': 'Checked by:',  'x': 340, 'y': 720},
            {'id': 'approved_by', 'text': 'Approved by:', 'x': 620, 'y': 720},
            {'id': 'note1', 'text': 'Received the goods in good order.', 'x': 60, 'y': 800},
        ]
        out = clean_texts(raw, DEFAULTS)
        assert 'note1' in ids(out)
        assert next(t for t in out if t['id'] == 'note1')['text'] == 'Received the goods in good order.'

    def test_deleted_default_stays_deleted(self):
        # The user removed checked_by + approved_by and saved -> a one-entry list.
        out = clean_texts([{'id': 'prepared_by', 'text': 'Prepared by:', 'x': 60, 'y': 720}], DEFAULTS)
        assert ids(out) == ['prepared_by']          # deleted defaults NOT re-injected

    def test_empty_list_yields_no_texts(self):
        assert clean_texts([], DEFAULTS) == []

    def test_max_texts_cap(self):
        raw = [{'id': f'n{i}', 'text': 't', 'x': 0, 'y': 0} for i in range(200)]
        assert len(clean_texts(raw, DEFAULTS)) <= MAX_TEXTS

    def test_text_length_capped(self):
        out = clean_texts([{'id': 'n', 'text': 'x' * 500, 'x': 0, 'y': 0}], DEFAULTS)
        assert len(out[0]['text']) <= TEXT_MAXLEN

    def test_coords_clamped_and_coerced(self):
        out = clean_texts([{'id': 'n', 'text': 't', 'x': -5, 'y': 99999, 'fontSize': 999}], DEFAULTS)
        assert out[0]['x'] == 48 and out[0]['y'] == 1008 and out[0]['fontSize'] == 72   # x floors at SAFE_MARGIN

    def test_non_dict_entries_dropped(self):
        out = clean_texts(['junk', 42, {'id': 'ok', 'text': 't', 'x': 0, 'y': 0}], DEFAULTS)
        assert ids(out) == ['ok']

    def test_duplicate_ids_deduped(self):
        out = clean_texts([
            {'id': 'prepared_by', 'text': 'A', 'x': 10, 'y': 10},
            {'id': 'prepared_by', 'text': 'B', 'x': 20, 'y': 20},
        ], DEFAULTS)
        assert ids(out) == ['prepared_by']
        assert out[0]['text'] == 'A'          # first wins

    def test_known_default_id_anchors_on_its_default(self):
        # A list entry that reuses a default id but omits fields -> defaults fill in.
        out = clean_texts([{'id': 'checked_by', 'x': 500}], DEFAULTS)
        assert out[0]['id'] == 'checked_by'
        assert out[0]['text'] == 'Checked by:'    # default text
        assert out[0]['x'] == 500

    def test_junk_id_sanitized_or_replaced(self):
        out = clean_texts([{'id': 'a<b>c/d', 'text': 't', 'x': 0, 'y': 0}], DEFAULTS)
        assert len(out) == 1
        # id is a safe slug (no angle brackets / slashes)
        assert '<' not in out[0]['id'] and '/' not in out[0]['id'] and out[0]['id']


class TestLayoutTextWrapWidth:
    """Owner, 2026-09-06: "all elements should have resizable width."

    Layout texts (signatory lines and free text) had no width at all, so they were the
    one element on the page that could be moved but never sized. This module is shared by
    every pre-printed designer, so the key is added here rather than per document.

    Additive and optional: absent -> 0 -> content-sized and single-line, which is what
    every layout saved before today means. Nothing renders differently until a width is
    actually set.
    """

    def test_a_legacy_text_gets_width_zero(self):
        out = clean_texts([{'id': 'prepared_by', 'text': 'Prepared by:'}], DEFAULTS)
        assert out[0]['width'] == 0

    def test_a_default_carries_the_key_too(self):
        """The no-raw path returns the defaults; they must not be the one shape missing
        the key, or a template reading `t.width` would raise on a fresh layout."""
        for t in clean_texts(None, DEFAULTS):
            assert 'width' in t

    def test_a_set_width_survives(self):
        out = clean_texts([{'id': 'prepared_by', 'text': 'x', 'width': 240}], DEFAULTS)
        assert out[0]['width'] == 240

    def test_zero_stays_zero(self):
        """0 is a VALUE (unset), not a missing number -- clamping it into WIDTH_MIN..MAX
        would turn every un-sized text into a 10px sliver on its next read."""
        out = clean_texts([{'id': 'prepared_by', 'text': 'x', 'width': 0}], DEFAULTS)
        assert out[0]['width'] == 0

    def test_the_legacy_dict_shape_gets_it_as_well(self):
        """The dict shape is the forward-compat migration path; a layout coming through
        it must not be the one that silently loses the key."""
        out = clean_texts({'prepared_by': {'x': 100, 'y': 700, 'width': 180}}, DEFAULTS)
        assert [t for t in out if t['id'] == 'prepared_by'][0]['width'] == 180


class TestWrapWidthNeverThrows:
    """`clean_texts` must never raise on plausible stored JSON: get_layout() swallows the
    exception and falls back to defaults, so a raise here QUIETLY destroys a client's
    saved layout rather than erroring visibly.
    """

    @pytest.mark.parametrize('value', [
        None, '', 'wide', {}, [], True,
        1e999,          # json.loads("1e999") -> inf; int() refuses it (OverflowError)
        -1e999,
        float('nan'),
    ])
    def test_it_survives_junk(self, value):
        out = clean_texts([{'id': 'prepared_by', 'text': 'x', 'width': value}], DEFAULTS)
        assert isinstance(out[0]['width'], int)

    def test_a_negative_width_reads_as_unset(self):
        out = clean_texts([{'id': 'prepared_by', 'text': 'x', 'width': -40}], DEFAULTS)
        assert out[0]['width'] == 0

    def test_a_wild_width_is_clamped(self):
        out = clean_texts([{'id': 'prepared_by', 'text': 'x', 'width': 99999}], DEFAULTS)
        assert out[0]['width'] == WIDTH_MAX

    def test_a_sub_minimum_width_snaps_up_not_off(self):
        out = clean_texts([{'id': 'prepared_by', 'text': 'x', 'width': 2}], DEFAULTS)
        assert out[0]['width'] == WIDTH_MIN
