"""The shared pre-printed layout core.

This carries the highest test weight in the arc: a defect here breaks all three
consuming modules at once, and it is the code that decides what a client's
saved stationery alignment looks like after an upgrade.

Two rules these tests hold themselves to, learned from the first review of this
file:

1. **Never assert one sanitiser call against another** (`sanitize({}) ==
   sanitize(DEFAULT)`). Both sides run the code under test, so anything the
   sanitiser drops from BOTH sides is invisible -- that assertion still passed
   with `texts` deleted from the output entirely. Expected values are written
   out as literals here.
2. **Pin the exact value, not a range.** `0 <= x <= CANVAS_W` passes with the
   bounds swapped, with SAFE_MARGIN ignored, and with the default returned
   instead of a clamp -- i.e. it pins nothing that matters.
"""
import json

import pytest

from app.common import preprinted_base as base
from app.common import preprinted_texts

pytestmark = [pytest.mark.unit]

FIELD_KEYS = ['doc_no', 'doc_date']

FONT = base.ALLOWED_FONTS[0]
OTHER_FONT = base.ALLOWED_FONTS[3]

DEFAULT = {
    'paper': 'continuous',
    'dateFormat': 'iso',
    'page': {'fontFamily': FONT},
    'fields': {
        'doc_no': {'x': 100, 'y': 100, 'w': 200, 'fontSize': 10, 'bold': False, 'hidden': False},
        'doc_date': {'x': 300, 'y': 100, 'w': 120, 'fontSize': 10, 'bold': False, 'hidden': False},
    },
    'lineItems': {'y': 300, 'rowHeight': 20, 'fontSize': 9, 'bold': False, 'columns': {}},
    'extras': [],
    'texts': {k: '' for k in base.TEXT_KEYS},
}

# What `sanitize` must return for an empty / absent / junk input. Written out in
# full, as a literal -- NOT derived by calling the sanitiser on DEFAULT.
EXPECTED_DEFAULT = {
    'paper': 'continuous',
    'dateFormat': 'iso',
    'page': {'fontFamily': FONT},
    'fields': {
        'doc_no': {'x': 100, 'y': 100, 'w': 200, 'fontSize': 10, 'bold': False, 'hidden': False},
        'doc_date': {'x': 300, 'y': 100, 'w': 120, 'fontSize': 10, 'bold': False, 'hidden': False},
    },
    'lineItems': {'y': 300, 'rowHeight': 20, 'fontSize': 9, 'bold': False, 'columns': []},
    'extras': [],
    'texts': [
        {'id': 'preparer', 'text': '', 'x': 60, 'y': 720,
         'fontSize': 10, 'bold': False, 'hidden': False},
        {'id': 'checker', 'text': '', 'x': 340, 'y': 720,
         'fontSize': 10, 'bold': False, 'hidden': False},
        {'id': 'approver', 'text': '', 'x': 620, 'y': 720,
         'fontSize': 10, 'bold': False, 'hidden': False},
    ],
}

# A second document declaration, this one WITH line-item columns -- the `{}`
# columns of DEFAULT exercise the no-columns document, this one exercises
# _clean_columns proper.
COLUMNS = [
    {'key': 'line_number', 'x': 56, 'visible': True, 'width': 30},
    {'key': 'product', 'x': 92, 'visible': True, 'width': 300},
    {'key': 'amount', 'x': 690, 'visible': False, 'width': 100},
]
COLUMN_KEYS = [c['key'] for c in COLUMNS]

DEFAULT_WITH_COLUMNS = dict(
    DEFAULT,
    lineItems={'y': 300, 'rowHeight': 20, 'fontSize': 9, 'bold': False,
               'columns': [dict(c) for c in COLUMNS]},
)


@pytest.fixture
def api():
    return base.build_layout_api('test_preprinted_layout', FIELD_KEYS, DEFAULT,
                                 'test_module', 'test_preprinted_layout')


@pytest.fixture
def api_cols():
    return base.build_layout_api('test_cols_layout', FIELD_KEYS, DEFAULT_WITH_COLUMNS,
                                 'test_module', 'test_cols_layout')


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
        assert out['page']['fontFamily'] == FONT

    def test_a_listed_font_survives(self, api):
        """CONTROL: rejecting every user choice must not pass the test above."""
        sanitize, _, _ = api
        assert sanitize({'page': {'fontFamily': OTHER_FONT}})['page']['fontFamily'] == OTHER_FONT

    def test_an_unlisted_paper_falls_back(self, api):
        sanitize, _, _ = api
        assert sanitize({'paper': 'A0'})['paper'] == 'continuous'

    def test_a_listed_paper_survives(self, api):
        """CONTROL for the paper allow-list."""
        sanitize, _, _ = api
        assert sanitize({'paper': 'letter'})['paper'] == 'letter'

    def test_an_unlisted_date_format_falls_back(self, api):
        """An unknown key reaches the print template as
        `date_formats[layout.dateFormat]` -> Undefined -> strftime raises -> 500."""
        sanitize, _, _ = api
        assert sanitize({'dateFormat': 'ymd'})['dateFormat'] == 'iso'

    def test_a_listed_date_format_survives(self, api):
        """CONTROL for the date-format allow-list."""
        sanitize, _, _ = api
        assert sanitize({'dateFormat': 'us'})['dateFormat'] == 'us'

    @pytest.mark.parametrize('bad, expected', [
        (-5000, base.SAFE_MARGIN),                    # clamped UP to the safe margin
        (99999, base.CANVAS_W - base.SAFE_MARGIN),    # clamped DOWN inside it
        ('x', 100),                                   # unparseable -> the declared default
        (None, 100),
    ])
    def test_an_out_of_range_coordinate_lands_on_an_exact_value(self, api, bad, expected):
        sanitize, _, _ = api
        x = sanitize({'fields': {'doc_no': {'x': bad}}})['fields']['doc_no']['x']
        assert x == expected

    def test_an_in_range_coordinate_survives(self, api):
        """CONTROL: clamping must not swallow a legitimate drag."""
        sanitize, _, _ = api
        assert sanitize({'fields': {'doc_no': {'x': 512}}})['fields']['doc_no']['x'] == 512

    @pytest.mark.parametrize('bad, expected', [
        (999, base.FONT_MAX),
        (1, base.FONT_MIN),
        ('big', 10),      # unparseable -> the declared default
    ])
    def test_font_size_lands_on_an_exact_value(self, api, bad, expected):
        sanitize, _, _ = api
        out = sanitize({'fields': {'doc_no': {'fontSize': bad}}})
        assert out['fields']['doc_no']['fontSize'] == expected

    def test_an_in_range_font_size_survives(self, api):
        """CONTROL for the font-size clamp."""
        sanitize, _, _ = api
        assert sanitize({'fields': {'doc_no': {'fontSize': 14}}})['fields']['doc_no']['fontSize'] == 14

    @pytest.mark.parametrize('bad, expected', [
        (99999, base.WIDTH_MAX),
        (0, base.WIDTH_MIN),
        ('wide', 200),    # unparseable -> the declared default, NOT WIDTH_MIN
    ])
    def test_field_width_lands_on_an_exact_value(self, api, bad, expected):
        sanitize, _, _ = api
        assert sanitize({'fields': {'doc_no': {'w': bad}}})['fields']['doc_no']['w'] == expected

    def test_an_in_range_width_survives(self, api):
        """CONTROL for the width clamp."""
        sanitize, _, _ = api
        assert sanitize({'fields': {'doc_no': {'w': 150}}})['fields']['doc_no']['w'] == 150

    def test_extras_are_capped_and_keep_the_first_ones(self, api):
        sanitize, _, _ = api
        out = sanitize({'extras': [{'key': 'doc_no', 'x': 100 + i, 'y': 1}
                                   for i in range(base.MAX_EXTRAS + 25)]})
        assert len(out['extras']) == base.MAX_EXTRAS
        assert [e['x'] for e in out['extras']] == list(range(100, 100 + base.MAX_EXTRAS))

    def test_an_extra_naming_an_unknown_field_is_dropped(self, api):
        sanitize, _, _ = api
        out = sanitize({'extras': [
            {'key': 'not_a_field', 'x': 100, 'y': 1},
            {'key': 'doc_no', 'x': 200, 'y': 1},
        ]})
        assert [e['key'] for e in out['extras']] == ['doc_no']
        assert out['extras'][0]['x'] == 200

    @pytest.mark.parametrize('bad_key', [['doc_no'], {'k': 'doc_no'}, 42, None, True])
    def test_an_extra_with_a_non_string_key_is_dropped(self, api, bad_key):
        """The `_clean_columns` sibling. `_clean_extras` tests membership against
        a LIST, so an unhashable key compares by `==` and never hashes -- this
        pins that immunity rather than leaving it incidental, and pins that the
        two siblings accept the SAME payloads."""
        sanitize, _, _ = api
        out = sanitize({'extras': [
            {'key': bad_key, 'x': 100, 'y': 1},
            {'key': 'doc_no', 'x': 200, 'y': 1},
        ]})
        assert [e['key'] for e in out['extras']] == ['doc_no']
        assert out['extras'][0]['x'] == 200

    def test_field_hidden_is_coerced_to_a_real_bool(self, api):
        """A raw `"false"` reaching `{% if f.hidden %}` is TRUTHY, so the field
        vanishes from the print. The value below must come back as the bool
        `True`, not the string -- `== True` would pass on neither, `is True`
        pins the coercion itself."""
        sanitize, _, _ = api
        assert sanitize({'fields': {'doc_no': {'hidden': 'false'}}})['fields']['doc_no']['hidden'] is True

    def test_a_falsy_non_bool_hidden_is_coerced_too(self, api):
        """CONTROL for the same coercion from the other side."""
        sanitize, _, _ = api
        assert sanitize({'fields': {'doc_no': {'hidden': 0}}})['fields']['doc_no']['hidden'] is False

    def test_field_bold_is_coerced_to_a_real_bool(self, api):
        sanitize, _, _ = api
        out = sanitize({'fields': {'doc_no': {'bold': 'false'}, 'doc_date': {'bold': 0}}})
        assert out['fields']['doc_no']['bold'] is True
        assert out['fields']['doc_date']['bold'] is False

    def test_an_infinite_coordinate_falls_back_instead_of_raising(self, api):
        """`json.loads('1e999')` is `inf`, and `round(inf)` raises OverflowError
        -- NOT one of the two exception types `_clamp` used to catch. `save_layout`
        has no try/except, so that was a 500 on an authenticated POST."""
        sanitize, _, _ = api
        raw = json.loads('{"fields": {"doc_no": {"x": 1e999, "y": -1e999, "w": 1e999}}}')
        box = sanitize(raw)['fields']['doc_no']
        assert (box['x'], box['y'], box['w']) == (100, 100, 200)   # the declared defaults

    def test_a_nan_coordinate_falls_back(self, api):
        sanitize, _, _ = api
        raw = json.loads('{"fields": {"doc_no": {"x": NaN}}}')
        assert sanitize(raw)['fields']['doc_no']['x'] == 100


class TestTheColumnsSanitiser:
    """`columns` is written on save AND re-read on load, so a bad payload is
    sticky: it breaks that branch's print page until someone re-saves."""

    def test_an_unknown_column_key_is_dropped(self, api_cols):
        sanitize, _, _ = api_cols
        out = sanitize({'lineItems': {'columns': [
            {'key': '../../etc/passwd', 'x': 1, 'width': 1},
            {'key': 'product', 'x': 200, 'width': 50},
        ]}})
        assert [c['key'] for c in out['lineItems']['columns']] == \
            ['product', 'line_number', 'amount']

    @pytest.mark.parametrize('bad_key', [['product'], {'k': 'product'}, 42, None, True])
    def test_a_non_string_column_key_is_dropped_and_never_raises(self, api_cols, bad_key):
        """`{"lineItems": {"columns": [{"key": [1]}]}}` is valid JSON. The
        allow-list is a DICT, so `key in defaults` HASHES the key -- an
        unhashable one raised `TypeError: unhashable type: 'list'` out of the
        sanitiser. `get_layout` swallows that, but the established save route is
        `save_layout(request.get_json(silent=True) or {}, ...)` with NO guard, so
        it was a 500 on an authenticated POST."""
        sanitize, _, _ = api_cols
        out = sanitize({'lineItems': {'columns': [
            {'key': bad_key, 'x': 1, 'width': 1},
            {'key': 'product', 'x': 200, 'width': 50},
        ]}})
        assert [c['key'] for c in out['lineItems']['columns']] == \
            ['product', 'line_number', 'amount']
        assert out['lineItems']['columns'][0]['x'] == 200

    def test_a_duplicated_column_key_resolves_to_its_first_occurrence(self, api_cols):
        """Values and position must come from the SAME occurrence. They used to
        disagree: `by_key` kept the LAST duplicate's values while the ordering
        pass kept the FIRST one's position."""
        sanitize, _, _ = api_cols
        cols = sanitize({'lineItems': {'columns': [
            {'key': 'product', 'x': 100, 'width': 50, 'visible': True},
            {'key': 'product', 'x': 200, 'width': 60, 'visible': False},
        ]}})['lineItems']['columns']
        assert len(cols) == len(COLUMNS)
        assert cols[0] == {'key': 'product', 'x': 100, 'visible': True, 'width': 50}

    def test_column_visible_is_coerced_to_a_real_bool(self, api_cols):
        sanitize, _, _ = api_cols
        cols = sanitize({'lineItems': {'columns': [
            {'key': 'product', 'visible': 'false'},
            {'key': 'amount', 'visible': 0},
        ]}})['lineItems']['columns']
        by_key = {c['key']: c for c in cols}
        assert by_key['product']['visible'] is True
        assert by_key['amount']['visible'] is False

    def test_unknown_column_properties_are_dropped(self, api_cols):
        sanitize, _, _ = api_cols
        out = sanitize({'lineItems': {'columns': [
            {'key': 'product', 'x': 200, 'width': 50, 'evil': 'payload',
             'nested': {'deep': [1, 2, 3]}},
        ]}})
        product = out['lineItems']['columns'][0]
        assert set(product) == {'key', 'x', 'visible', 'width'}

    def test_out_of_range_column_numbers_are_clamped(self, api_cols):
        sanitize, _, _ = api_cols
        out = sanitize({'lineItems': {'columns': [
            {'key': 'product', 'x': -99999, 'width': 1000000000},
        ]}})
        product = out['lineItems']['columns'][0]
        assert product['x'] == base.SAFE_MARGIN
        assert product['width'] == base.WIDTH_MAX

    @pytest.mark.parametrize('sent, stored', [
        (-99999, base.SAFE_MARGIN),                   # clamped UP to the safe margin
        (0, base.SAFE_MARGIN),                        # the canvas edge is NOT reachable
        (10, base.SAFE_MARGIN),                       # inside the tractor-feed margin
        (47, base.SAFE_MARGIN),                       # one px outside the bound
        (900, base.CANVAS_W - base.SAFE_MARGIN),      # clamped DOWN inside the right inset
        (base.CANVAS_W, base.CANVAS_W - base.SAFE_MARGIN),
        (99999, base.CANVAS_W - base.SAFE_MARGIN),
    ])
    def test_a_column_x_clamps_to_the_safe_margin_exactly_like_a_field(
            self, api_cols, sent, stored):
        """A COLUMN's x is clamped to SAFE_MARGIN..CANVAS_W - SAFE_MARGIN -- the SAME
        bound as a field's (`_clean_box`), pinned value-by-value.

        It used to clamp to the bare canvas (0..CANVAS_W), so a user could drag a
        column onto the tractor-feed perforations and the server would PERSIST it
        there, while a field dragged to the same point was pulled back to the margin.
        That asymmetry was removed deliberately on 2026-08-15 (owner decision:
        tighten the server, not loosen the client). The sibling test below drives the
        SAME values through a field and asserts an identical result, so neither clamp
        can be loosened on its own without one of the two going red.
        """
        sanitize, _, _ = api_cols
        cols = sanitize({'lineItems': {'columns': [
            {'key': 'product', 'x': sent, 'width': 50},
        ]}})['lineItems']['columns']
        assert cols[0]['x'] == stored

    @pytest.mark.parametrize('sent, stored', [
        (-99999, base.SAFE_MARGIN),
        (0, base.SAFE_MARGIN),
        (10, base.SAFE_MARGIN),
        (47, base.SAFE_MARGIN),
        (900, base.CANVAS_W - base.SAFE_MARGIN),
        (base.CANVAS_W, base.CANVAS_W - base.SAFE_MARGIN),
        (99999, base.CANVAS_W - base.SAFE_MARGIN),
    ])
    def test_a_field_x_clamps_to_the_same_values_as_a_column(
            self, api_cols, sent, stored):
        """The other half of the pairing above: the SAME inputs through `_clean_box`
        must produce the SAME stored x. Fields and columns behave IDENTICALLY now."""
        sanitize, _, _ = api_cols
        out = sanitize({'fields': {'doc_no': {'x': sent}}})
        assert out['fields']['doc_no']['x'] == stored

    def test_a_column_and_a_field_sent_the_same_x_are_stored_at_the_same_x(self, api_cols):
        """The pairing stated as one assertion, so the symmetry itself is the subject.

        Written as the direct inversion of the old
        `test_column_clamps_to_the_canvas_where_a_field_clamps_to_the_safe_margin`
        e2e/unit pair, which asserted these two values must DIFFER.
        """
        sanitize, _, _ = api_cols
        for sent in (-1, 0, 10, 47, 48, 500, 864, 865, 912, 99999):
            out = sanitize({
                'fields': {'doc_no': {'x': sent}},
                'lineItems': {'columns': [{'key': 'product', 'x': sent, 'width': 50}]},
            })
            col_x = out['lineItems']['columns'][0]['x']
            field_x = out['fields']['doc_no']['x']
            assert col_x == field_x, f'x={sent} stored as column {col_x} but field {field_x}'
            assert base.SAFE_MARGIN <= col_x <= base.CANVAS_W - base.SAFE_MARGIN

    def test_in_range_column_numbers_survive(self, api_cols):
        """CONTROL: a legitimate column drag must round-trip."""
        sanitize, _, _ = api_cols
        out = sanitize({'lineItems': {'columns': [
            {'key': 'product', 'x': 150, 'width': 240, 'visible': False},
        ]}})
        assert out['lineItems']['columns'][0] == \
            {'key': 'product', 'x': 150, 'visible': False, 'width': 240}

    def test_a_column_missing_from_stored_json_reappears_at_its_default(self, api_cols):
        """Column-level forward compatibility: a release adds a column, the
        client's stored JSON predates it -- it must still print and be
        draggable, not silently vanish."""
        sanitize, _, _ = api_cols
        out = sanitize({'lineItems': {'columns': [{'key': 'amount', 'x': 700, 'width': 110}]}})
        cols = out['lineItems']['columns']
        assert [c['key'] for c in cols] == ['amount', 'line_number', 'product']
        assert cols[1] == {'key': 'line_number', 'x': 56, 'visible': True, 'width': 30}
        assert cols[2] == {'key': 'product', 'x': 92, 'visible': True, 'width': 300}

    def test_a_dict_of_columns_yields_a_list(self, api_cols):
        """Jinja's `{% for col in li.columns %}` over a dict iterates bare string
        keys, so `col.x` renders `left:px` -- silently broken, no error."""
        sanitize, _, _ = api_cols
        cols = sanitize({'lineItems': {'columns': {'product': {'x': 5}}}})['lineItems']['columns']
        assert isinstance(cols, list)
        assert [c['key'] for c in cols] == COLUMN_KEYS

    def test_a_document_with_no_columns_yields_a_list(self, api):
        sanitize, _, _ = api
        out = sanitize({'lineItems': {'columns': [{'key': 'x', 'x': 1, 'width': 1}]}})
        assert out['lineItems']['columns'] == []

    def test_a_huge_column_payload_is_capped(self, api_cols):
        """5000 entries persisted 555 KB into a settings row before this cap."""
        sanitize, _, _ = api_cols
        payload = {'lineItems': {'columns': [
            {'key': 'product', 'x': 1, 'width': 1, 'junk': 'z' * 100} for _ in range(5000)]}}
        out = sanitize(payload)
        assert len(out['lineItems']['columns']) == len(COLUMNS)
        assert len(json.dumps(out)) < 5000

    def test_a_document_declaring_too_many_columns_is_capped(self):
        wide = dict(DEFAULT, lineItems={
            'y': 300, 'rowHeight': 20, 'fontSize': 9, 'bold': False,
            # x starts AT the safe margin: a declared column may no longer sit
            # inside the tractor-feed inset, so `x: i` (0, 1, 2, ...) would now be
            # rejected by the declaration validator before the cap is ever reached.
            'columns': [{'key': f'c{i}', 'x': base.SAFE_MARGIN + i, 'width': 20}
                        for i in range(base.MAX_COLUMNS + 10)],
        })
        sanitize, _, _ = base.build_layout_api('test_wide_layout', FIELD_KEYS, wide,
                                               'test_module', 'test_wide_layout')
        assert len(sanitize({})['lineItems']['columns']) == base.MAX_COLUMNS

    def test_the_returned_columns_do_not_alias_the_module_default(self, api_cols):
        """A returned default object held BY REFERENCE would let one caller's
        edit corrupt the process-wide default for every branch and every later
        request until the worker restarts."""
        sanitize, _, _ = api_cols
        out = sanitize({})
        out['lineItems']['columns'][0]['x'] = 999
        out['lineItems']['columns'].append({'key': 'injected'})
        assert DEFAULT_WITH_COLUMNS['lineItems']['columns'][0]['x'] == 56
        assert sanitize({})['lineItems']['columns'][0]['x'] == 56
        assert len(sanitize({})['lineItems']['columns']) == len(COLUMNS)

    def test_the_returned_layout_does_not_alias_the_module_default_anywhere(self, api):
        """Same check, whole-layout: mutate every branch of the result, then
        prove a fresh sanitize is untouched."""
        sanitize, _, _ = api
        out = sanitize({})
        out['fields']['doc_no']['x'] = 999
        out['page']['fontFamily'] = 'mutated'
        out['lineItems']['y'] = 999
        out['texts'][0]['x'] = 999
        out['extras'].append({'key': 'doc_no'})
        assert sanitize({}) == EXPECTED_DEFAULT
        assert DEFAULT['fields']['doc_no']['x'] == 100


class TestTheLineItemBand:
    """The band's OWN position/style, as opposed to its columns.

    Every earlier test of this band compared a whole layout against
    EXPECTED_DEFAULT, which only ever exercises the DEFAULT path -- so removing
    any of these three clamps, or the bool coercion, left the suite green.
    `ROW_MIN`/`ROW_MAX` are brief-declared public constants and had no test at
    all: the row height is what decides whether printed lines land on the
    pre-printed stationery's ruled rows.
    """

    @pytest.mark.parametrize('bad, expected', [
        (99999, base.ROW_MAX),      # 80 -- rows taller than this walk off the form
        (0, base.ROW_MIN),          # 8  -- a 0px row prints every line on top of itself
        (-40, base.ROW_MIN),
        ('x', 20),                  # unparseable -> the declared default
        (None, 20),
    ])
    def test_row_height_lands_on_an_exact_value(self, api, bad, expected):
        sanitize, _, _ = api
        assert sanitize({'lineItems': {'rowHeight': bad}})['lineItems']['rowHeight'] == expected

    def test_an_in_range_row_height_survives(self, api):
        """CONTROL: clamping must not swallow a legitimate row-height change."""
        sanitize, _, _ = api
        assert sanitize({'lineItems': {'rowHeight': 30}})['lineItems']['rowHeight'] == 30

    @pytest.mark.parametrize('bad, expected', [
        (-5, 0),
        (99999, base.CANVAS_H),
        ('x', 300),                 # unparseable -> the declared default
    ])
    def test_the_band_y_lands_on_an_exact_value(self, api, bad, expected):
        sanitize, _, _ = api
        assert sanitize({'lineItems': {'y': bad}})['lineItems']['y'] == expected

    def test_an_in_range_band_y_survives(self, api):
        """CONTROL for the band-y clamp."""
        sanitize, _, _ = api
        assert sanitize({'lineItems': {'y': 450}})['lineItems']['y'] == 450

    @pytest.mark.parametrize('bad, expected', [
        (999, base.FONT_MAX),
        (1, base.FONT_MIN),
        ('big', 9),                 # unparseable -> the declared default
    ])
    def test_the_band_font_size_lands_on_an_exact_value(self, api, bad, expected):
        sanitize, _, _ = api
        assert sanitize({'lineItems': {'fontSize': bad}})['lineItems']['fontSize'] == expected

    def test_an_in_range_band_font_size_survives(self, api):
        """CONTROL for the band font-size clamp."""
        sanitize, _, _ = api
        assert sanitize({'lineItems': {'fontSize': 12}})['lineItems']['fontSize'] == 12

    def test_the_band_bold_is_coerced_to_a_real_bool(self, api):
        sanitize, _, _ = api
        assert sanitize({'lineItems': {'bold': 'false'}})['lineItems']['bold'] is True
        assert sanitize({'lineItems': {'bold': 0}})['lineItems']['bold'] is False


class TestForwardCompatibility:
    """The upgrade case: a layout saved before a field existed must still render
    that field at its default rather than vanishing or raising."""

    def test_a_layout_missing_a_field_gets_it_at_default(self, api):
        sanitize, _, _ = api
        out = sanitize({'fields': {'doc_no': {'x': 50, 'y': 60}}})
        assert out['fields']['doc_date'] == \
            {'x': 300, 'y': 100, 'w': 120, 'fontSize': 10, 'bold': False, 'hidden': False}

    def test_an_empty_layout_returns_the_full_default(self, api):
        sanitize, _, _ = api
        assert sanitize({}) == EXPECTED_DEFAULT

    def test_the_defaults_echoed_back_sanitize_to_themselves(self, api):
        sanitize, _, _ = api
        assert sanitize(DEFAULT) == EXPECTED_DEFAULT

    @pytest.mark.parametrize('junk', [None, [], 'a string', 42])
    def test_a_non_dict_input_does_not_raise(self, api, junk):
        sanitize, _, _ = api
        assert sanitize(junk) == EXPECTED_DEFAULT

    @pytest.mark.parametrize('bad_page', ['Arial, sans-serif', [1], 42])
    def test_a_misshapen_page_key_does_not_raise(self, api, bad_page):
        """`{"page": "Arial, sans-serif"}` is valid JSON, so get_layout's own
        fallback never sees it -- an unguarded .get() here 500s the print page,
        which is where the designer that could fix the layout lives."""
        sanitize, _, _ = api
        assert sanitize({'page': bad_page}) == EXPECTED_DEFAULT

    @pytest.mark.parametrize('key', ['fields', 'lineItems', 'extras', 'texts'])
    def test_a_misshapen_sibling_key_does_not_raise(self, api, key):
        sanitize, _, _ = api
        assert sanitize({key: 'not a container'}) == EXPECTED_DEFAULT


class TestTheSignatoryTexts:

    def test_the_name_clean_texts_IS_the_shared_helper_object(self):
        """The spy test below monkeypatches `base.clean_texts`, which proves only
        that SOME module global by that name is called -- a reimplementation
        defined inside preprinted_base.py under the same name passes it
        unchanged. This identity check is what actually pins the brief's "reuse,
        do not reimplement"."""
        assert base.clean_texts is preprinted_texts.clean_texts

    def test_the_shared_clean_texts_helper_is_used(self, api, monkeypatch):
        """The base must REUSE app/common/preprinted_texts.clean_texts, not
        reimplement signatory sanitising."""
        calls = []

        def spy(raw, defaults):
            calls.append((raw, defaults))
            return [{'id': 'spy'}]

        monkeypatch.setattr(base, 'clean_texts', spy)
        sanitize, _, _ = api
        out = sanitize({'texts': {'preparer': {'text': 'Prepared by:'}}})
        assert out['texts'] == [{'id': 'spy'}]
        assert len(calls) == 1
        assert calls[0][0] == {'preparer': {'text': 'Prepared by:'}}

    def test_the_three_signatories_get_distinct_default_positions(self, api):
        """All three at one point printed preparer/checker/approver stacked on
        top of each other on a new branch's first print."""
        sanitize, _, _ = api
        texts = sanitize({})['texts']
        assert [(t['id'], t['x'], t['y']) for t in texts] == [
            ('preparer', 60, 720), ('checker', 340, 720), ('approver', 620, 720)]

    def test_a_stored_signatory_position_survives(self, api):
        """CONTROL: the defaults must not overwrite a user's dragged position."""
        sanitize, _, _ = api
        texts = sanitize({'texts': {'checker': {'text': 'Checked by:', 'x': 400, 'y': 800}}})['texts']
        checker = [t for t in texts if t['id'] == 'checker'][0]
        assert (checker['text'], checker['x'], checker['y']) == ('Checked by:', 400, 800)


class TestTheDeclarationIsValidated:
    """A module's OWN defaults are subscripted directly by the sanitiser and the
    print template, so a typo'd declaration is a 500 (or a silent 10px field),
    not a caught fallback. Catch it at import time instead."""

    def _build(self, layout):
        return base.build_layout_api('test_bad_layout', FIELD_KEYS, layout,
                                     'test_module', 'test_bad_layout')

    def test_a_valid_declaration_builds(self):
        """CONTROL: validation must not reject a legitimate declaration."""
        sanitize, get_layout, save_layout = self._build(DEFAULT)
        assert callable(sanitize) and callable(get_layout) and callable(save_layout)

    def test_an_unknown_paper_is_rejected(self):
        with pytest.raises(ValueError, match=r"default_layout\['paper'\]"):
            self._build(dict(DEFAULT, paper='A0'))

    def test_an_unknown_date_format_is_rejected(self):
        with pytest.raises(ValueError, match=r"default_layout\['dateFormat'\]"):
            self._build(dict(DEFAULT, dateFormat='ymd'))

    def test_an_unlisted_font_is_rejected(self):
        with pytest.raises(ValueError, match=r"fontFamily"):
            self._build(dict(DEFAULT, page={'fontFamily': 'Comic Sans MS'}))

    def test_a_missing_field_declaration_is_rejected(self):
        with pytest.raises(ValueError, match=r"\['doc_date'\] is missing"):
            self._build(dict(DEFAULT, fields={'doc_no': DEFAULT['fields']['doc_no']}))

    def test_a_field_box_without_a_width_is_rejected(self):
        """No existing clone's field boxes carry 'w'; a document declared by
        mirroring one would print every field clipped to 10px, silently."""
        no_w = {k: {p: v for p, v in box.items() if p != 'w'}
                for k, box in DEFAULT['fields'].items()}
        with pytest.raises(ValueError, match=r"is missing 'w'"):
            self._build(dict(DEFAULT, fields=no_w))

    @pytest.mark.parametrize('prop', ['y', 'rowHeight', 'fontSize', 'bold'])
    def test_an_incomplete_line_items_declaration_is_rejected(self, prop):
        li = {p: v for p, v in DEFAULT['lineItems'].items() if p != prop}
        with pytest.raises(ValueError, match=rf"lineItems'\] is missing '{prop}'"):
            self._build(dict(DEFAULT, lineItems=li))

    def test_a_column_without_a_key_is_rejected(self):
        with pytest.raises(ValueError, match=r"columns'\]\[0\] needs a 'key'"):
            self._build(dict(DEFAULT, lineItems=dict(DEFAULT['lineItems'],
                                                     columns=[{'x': 1, 'width': 2}])))

    def test_a_column_without_a_width_is_rejected(self):
        # x must be a VALID one (>= SAFE_MARGIN) or the x range check fires first and
        # this test would pass for the wrong reason.
        with pytest.raises(ValueError, match=r"is missing 'width'"):
            self._build(dict(DEFAULT, lineItems=dict(DEFAULT['lineItems'],
                                                     columns=[{'key': 'product', 'x': 92}])))

    def test_a_column_with_a_non_string_key_is_rejected(self):
        """`_clean_columns` keys its allow-list DICT on these, so an unhashable
        declared key would raise from inside the comprehension instead of naming
        itself here."""
        with pytest.raises(ValueError, match=r"columns'\]\[0\] needs a 'key'"):
            self._build(dict(DEFAULT, lineItems=dict(
                DEFAULT['lineItems'], columns=[{'key': ['product'], 'x': 1, 'width': 2}])))


class TestTheDeclarationsTypesAndRangesAreValidated:
    """Presence is not enough. `_clamp`'s fallback arm returns the DECLARED value
    untouched and is not itself clamped, so a declared `'w': 'wide'` reaches the
    template as `width:widepx` and a declared `'x': 99999` prints off the page --
    the same defect class the validator was added to close, one level down.
    """

    def _build(self, layout):
        return base.build_layout_api('test_typed_layout', FIELD_KEYS, layout,
                                     'test_module', 'test_typed_layout')

    def _with_doc_no(self, **overrides):
        return dict(DEFAULT, fields=dict(
            DEFAULT['fields'], doc_no=dict(DEFAULT['fields']['doc_no'], **overrides)))

    @pytest.mark.parametrize('prop, bad', [
        ('w', 'wide'),          # -> width:widepx
        ('w', None),            # -> width:Nonepx
        ('x', 'left'),
        ('x', None),            # -> left:Nonepx
        ('fontSize', '10'),     # a numeric STRING is still not a number
        ('y', [1]),
        # `isinstance(True, int)` is True in Python, so a bool sails through a
        # bare numeric check. `y: True` would then also sail through the RANGE
        # check (1 is inside 0..1008) and print the band at y=1 -- which is why
        # this asserts the TYPE arm's message specifically. Matching only the
        # key prefix let the range arm stand in for the type arm, and the
        # "allow a bool where a number is declared" mutation survived green.
        ('y', True),
        ('y', False),
        ('x', True),
    ])
    def test_a_non_numeric_field_prop_is_rejected(self, prop, bad):
        with pytest.raises(ValueError,
                           match=rf"\['doc_no'\]\[{prop!r}\] is .*must be a number in"):
            self._build(self._with_doc_no(**{prop: bad}))

    @pytest.mark.parametrize('prop, bad', [
        ('x', 99999),                       # past CANVAS_W - SAFE_MARGIN
        ('x', 10),                          # inside the tractor-feed margin
        ('y', -1),
        ('y', 99999),
        ('w', 0),                           # below WIDTH_MIN -- the 10px-clipped field
        ('w', 99999),
        ('fontSize', 2),
        ('fontSize', 999),
    ])
    def test_an_out_of_range_field_prop_is_rejected(self, prop, bad):
        with pytest.raises(ValueError, match=rf"\['doc_no'\]\[{prop!r}\] is {bad}"):
            self._build(self._with_doc_no(**{prop: bad}))

    @pytest.mark.parametrize('prop', ['bold', 'hidden'])
    def test_a_non_bool_field_flag_is_rejected(self, prop):
        with pytest.raises(ValueError, match=rf"\['doc_no'\]\[{prop!r}\] is 'yes'"):
            self._build(self._with_doc_no(**{prop: 'yes'}))

    def test_boundary_values_and_floats_are_accepted(self):
        """CONTROL: the range check must accept its own edges and a float --
        rejecting everything would pass every test above."""
        sanitize, _, _ = self._build(self._with_doc_no(
            x=base.SAFE_MARGIN, y=base.CANVAS_H, w=base.WIDTH_MAX,
            fontSize=base.FONT_MIN))
        assert sanitize({})['fields']['doc_no']['x'] == base.SAFE_MARGIN
        # A declared float survives VERBATIM -- `_clamp`'s fallback arm returns
        # the declared value without rounding it, which is exactly why the range
        # check above has to hold. `left:100.5px` is valid CSS, so a float is
        # accepted rather than rejected.
        sanitize, _, _ = self._build(self._with_doc_no(x=100.5))
        assert sanitize({})['fields']['doc_no']['x'] == 100.5

    def test_a_declaration_omitting_hidden_still_builds(self):
        """CONTROL: 'hidden' is OPTIONAL -- the type check must not make it
        required (every existing clone's field boxes omit it)."""
        no_hidden = {k: {p: v for p, v in box.items() if p != 'hidden'}
                     for k, box in DEFAULT['fields'].items()}
        sanitize, _, _ = self._build(dict(DEFAULT, fields=no_hidden))
        assert sanitize({})['fields']['doc_no']['hidden'] is False

    @pytest.mark.parametrize('prop, bad', [
        ('rowHeight', 500),         # past ROW_MAX
        ('rowHeight', 0),           # below ROW_MIN
        ('rowHeight', '20'),
        ('y', -1),
        ('y', 99999),
        ('fontSize', 999),
    ])
    def test_a_bad_line_items_prop_is_rejected(self, prop, bad):
        with pytest.raises(ValueError, match=rf"lineItems'\]\[{prop!r}\] is "):
            self._build(dict(DEFAULT, lineItems=dict(DEFAULT['lineItems'], **{prop: bad})))

    def test_an_in_range_line_items_declaration_builds(self):
        """CONTROL for the ROW_MIN..ROW_MAX declaration check."""
        sanitize, _, _ = self._build(dict(DEFAULT, lineItems=dict(
            DEFAULT['lineItems'], rowHeight=base.ROW_MAX)))
        assert sanitize({})['lineItems']['rowHeight'] == base.ROW_MAX

    @pytest.mark.parametrize('prop, bad', [
        ('x', 'wide'),
        ('x', 99999),                       # past CANVAS_W - SAFE_MARGIN
        # A declared column's x carries the SAME bound as a declared field's
        # (see test_an_out_of_range_field_prop_is_rejected's ('x', 10) case). It
        # used to be 0..CANVAS_W, so a declaration could put a column on the
        # tractor-feed perforations; tightened 2026-08-15 alongside _clean_columns.
        ('x', 0),                           # the bare canvas edge is no longer legal
        ('x', 10),                          # inside the tractor-feed margin
        ('x', 47),                          # one px outside the bound
        ('x', 865),                         # one px past CANVAS_W - SAFE_MARGIN
        ('width', 0),
        ('width', 99999),
        ('width', None),
    ])
    def test_a_bad_column_prop_is_rejected(self, prop, bad):
        col = dict({'key': 'product', 'x': 92, 'width': 300}, **{prop: bad})
        with pytest.raises(ValueError, match=rf"columns'\]\['product'\]\[{prop!r}\] is "):
            self._build(dict(DEFAULT, lineItems=dict(DEFAULT['lineItems'], columns=[col])))

    def test_a_valid_column_declaration_builds(self):
        """CONTROL for the column range checks."""
        sanitize, _, _ = self._build(DEFAULT_WITH_COLUMNS)
        assert [c['key'] for c in sanitize({})['lineItems']['columns']] == COLUMN_KEYS

    @pytest.mark.parametrize('x', [48, 864])
    def test_a_column_declared_exactly_on_the_bound_builds(self, x):
        """CONTROL for the tightened x bound: the check must accept its own edges,
        or every case above would pass with the validator rejecting everything."""
        col = {'key': 'product', 'x': x, 'width': 300}
        sanitize, _, _ = self._build(
            dict(DEFAULT, lineItems=dict(DEFAULT['lineItems'], columns=[col])))
        assert sanitize({})['lineItems']['columns'][0]['x'] == x


class TestTheDeclaredTextsShapeIsValidated:
    """`build_layout_api`'s docstring advertises a bare `{id: str}` map OR a full
    box list. The list form was passed to `clean_texts` UNVALIDATED, which does
    `{e['id']: e for e in defaults}` and then subscripts `base['text']`,
    `base['x']`, `base['bold']`... in `_merge_text`. A partial entry was a
    KeyError -- and `get_layout`'s unset branch sits OUTSIDE its try/except, so
    that was an uncaught 500 on the print page.
    """

    FULL = [
        {'id': 'preparer', 'text': 'Prepared by:', 'x': 60, 'y': 700,
         'fontSize': 10, 'bold': True, 'hidden': False},
        {'id': 'approver', 'text': 'Approved by:', 'x': 620, 'y': 700,
         'fontSize': 10, 'bold': False, 'hidden': False},
    ]

    def _build(self, texts):
        return base.build_layout_api('test_texts_layout', FIELD_KEYS,
                                     dict(DEFAULT, texts=texts),
                                     'test_module', 'test_texts_layout')

    def test_a_full_box_list_builds_and_sanitizes(self):
        """CONTROL: the documented list form must keep working."""
        sanitize, _, _ = self._build([dict(t) for t in self.FULL])
        assert sanitize({})['texts'] == self.FULL

    def test_a_text_box_without_an_id_is_rejected(self):
        """This exact declaration used to build fine, then KeyError('id') on the
        first sanitize."""
        with pytest.raises(ValueError, match=r"texts'\]\[0\] is missing a string 'id'"):
            self._build([{'text': 'x'}])

    @pytest.mark.parametrize('prop', ['text', 'x', 'y', 'fontSize', 'bold', 'hidden'])
    def test_a_text_box_missing_any_subscripted_prop_is_rejected(self, prop):
        """`_merge_text` subscripts every one of these on the default box."""
        partial = {p: v for p, v in self.FULL[0].items() if p != prop}
        with pytest.raises(ValueError, match=r"texts'\]\['preparer'\]"):
            self._build([partial])

    @pytest.mark.parametrize('bad', ['not a box', 42, None, ['nested']])
    def test_a_non_dict_text_entry_is_rejected(self, bad):
        with pytest.raises(ValueError, match=r"texts'\]\[0\] is "):
            self._build([bad])

    @pytest.mark.parametrize('prop, bad', [
        ('x', 'left'), ('x', 99999), ('y', -1), ('fontSize', 999), ('bold', 'yes'),
    ])
    def test_a_bad_text_box_prop_is_rejected(self, prop, bad):
        with pytest.raises(ValueError, match=rf"texts'\]\['preparer'\]\[{prop!r}\] is "):
            self._build([dict(self.FULL[0], **{prop: bad})])

    def test_a_non_string_value_in_the_bare_map_is_rejected(self):
        with pytest.raises(ValueError, match=r"texts'\]\['preparer'\] is "):
            self._build({'preparer': {'text': 'nested'}, 'checker': '', 'approver': ''})

    def test_the_bare_map_form_still_builds(self):
        """CONTROL: the common declaration form must be unaffected."""
        sanitize, _, _ = self._build({k: '' for k in base.TEXT_KEYS})
        assert sanitize({})['texts'] == EXPECTED_DEFAULT['texts']

    def test_a_declaration_omitting_texts_entirely_still_builds(self):
        """CONTROL: 'texts' is optional -- validation must not make it required."""
        no_texts = {k: v for k, v in DEFAULT.items() if k != 'texts'}
        sanitize, _, _ = base.build_layout_api('test_no_texts_layout', FIELD_KEYS, no_texts,
                                               'test_module', 'test_no_texts_layout')
        assert sanitize({})['texts'] == EXPECTED_DEFAULT['texts']


class TestPersistence:

    def test_get_returns_defaults_when_unset(self, db_session, api):
        _, get_layout, _ = api
        assert get_layout(branch_id=1) == EXPECTED_DEFAULT

    def test_get_returns_defaults_when_unset_for_a_box_list_declaration(self, db_session):
        """`get_layout`'s unset branch is the ONE sanitize call in this module
        with no fallback around it, and the full-box-list `texts` form is the
        shape that reaches `clean_texts` unmodified. Pin that pairing directly."""
        full = [{'id': 'preparer', 'text': 'Prepared by:', 'x': 60, 'y': 700,
                 'fontSize': 10, 'bold': True, 'hidden': False}]
        _, get_layout, _ = base.build_layout_api(
            'test_boxlist_layout', FIELD_KEYS, dict(DEFAULT, texts=[dict(full[0])]),
            'test_module', 'test_boxlist_layout')
        assert get_layout(branch_id=1)['texts'] == full

    def test_save_then_get_round_trips_per_branch(self, db_session, admin_user, api):
        """Layouts are PER BRANCH -- branch 2 must not see branch 1's layout."""
        _, get_layout, save_layout = api
        save_layout({'fields': {'doc_no': {'x': 222}}}, admin_user.username, branch_id=1)
        assert get_layout(branch_id=1)['fields']['doc_no']['x'] == 222
        assert get_layout(branch_id=2)['fields']['doc_no']['x'] == 100

    def test_corrupt_stored_json_falls_back_to_defaults(self, db_session, api):
        """A hand-edited or truncated settings row must not 500 the print page."""
        from app.settings import AppSettings
        _, get_layout, _ = api
        AppSettings.set_setting('test_preprinted_layout:1', '{not json')
        assert get_layout(branch_id=1) == EXPECTED_DEFAULT

    def test_valid_json_of_the_wrong_shape_falls_back(self, db_session, api):
        """json.loads succeeds here, so the try/except never fires -- the
        sanitiser itself has to survive it."""
        from app.settings import AppSettings
        _, get_layout, _ = api
        AppSettings.set_setting('test_preprinted_layout:1', '{"page": "Arial, sans-serif"}')
        assert get_layout(branch_id=1) == EXPECTED_DEFAULT

    def test_any_unexpected_read_failure_falls_back(self, db_session, api, monkeypatch):
        """The fallback must be fail-SAFE, not fail-safe-for-two-exception-types."""
        from app.settings import AppSettings

        class Boom:
            @staticmethod
            def loads(_s):
                raise RuntimeError('boom')

            dumps = staticmethod(json.dumps)

        _, get_layout, _ = api
        AppSettings.set_setting('test_preprinted_layout:1', '{"paper": "letter"}')
        monkeypatch.setattr(base, 'json', Boom)
        assert get_layout(branch_id=1) == EXPECTED_DEFAULT

    def test_save_writes_an_audit_row(self, db_session, admin_user, api):
        from app.audit.models import AuditLog
        from app.settings import AppSettings
        _, _, save_layout = api
        save_layout({'paper': 'letter'}, admin_user.username, branch_id=1)
        rows = AuditLog.query.filter_by(record_identifier='test_preprinted_layout').all()
        assert len(rows) == 1
        assert rows[0].action == 'update'
        assert rows[0].module == 'test_module'
        assert json.loads(rows[0].new_values)['branch_id'] == 1
        # log_audit reads its actor from `current_user`, which is anonymous in a
        # unit test; save_layout records the acting user on the settings row.
        setting = AppSettings.query.filter_by(key='test_preprinted_layout:1').first()
        assert setting.updated_by == admin_user.username

    def test_a_saved_layout_cannot_bloat_the_settings_row(self, db_session, admin_user, api_cols):
        """555 KB of unvalidated columns used to persist into a settings row."""
        from app.settings import AppSettings
        _, _, save_layout = api_cols
        save_layout({'lineItems': {'columns': [
            {'key': 'product', 'x': 1, 'width': 1, 'junk': 'z' * 100} for _ in range(5000)]}},
            admin_user.username, branch_id=1)
        assert len(AppSettings.get_setting('test_cols_layout:1')) < 5000
