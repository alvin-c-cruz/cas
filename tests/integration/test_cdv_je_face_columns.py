"""The CDV pre-printed JE face can be positioned column by column.

Owner request 2026-09-06, porting the APV twin (088dccab) to the CDV voucher: the
journal entry should be split by column -- Account Code, Account Title, Debit, Credit.

It already rendered those four as cells, but inside ONE positioned band: a single
auto-width HTML table at journalEntry.combined.x/y/width. The browser sized the columns,
so they could be moved only as a block and never registered against the voucher's own
printed boxes.

OPT-IN, exactly as lineItems.enabled is. `columnsEnabled` is absent from every layout
blob saved before today, so an existing client layout renders byte-identically until
somebody turns it on -- which matters because these are coordinates onto a client's real
pre-printed stationery.

The default column x/width are PLACEHOLDERS, never measured against a real CDV pad
(owner: "If user can do the adjustment, let them be"). They are pinned here only for the
properties that must hold whatever the numbers are -- distinct, ordered, on-canvas -- NOT
for the values themselves, which are expected to be dragged.

ALIGNMENT INVARIANT: every column emits exactly ONE cell per JE line, blank where it has
nothing to say (a debit row's credit cell, and the reverse). Equal-length stacks are what
hold the columns in registration; a column that skipped its blank cells would climb the
page relative to the others.
"""
import pytest

from app.settings import AppSettings
from tests.integration.test_cdv_print_form import login, _cdv_with_je

pytestmark = [pytest.mark.integration, pytest.mark.cash_disbursements]


def _open_tag(html, needle):
    """The WHOLE opening <div ...> carrying `needle` -- `class` precedes `data-*` but
    `style` follows it, so a split that stops at the needle sees only half the tag."""
    start = html.rindex('<div', 0, html.index(needle))
    return html[start:html.index('>', start) + 1]


@pytest.fixture
def render_overlay(client, db_session, admin_user, main_branch):
    """The CDV overlay page, rendered with the column face enabled by default.

    The voucher is BUILT here rather than looked up: an earlier draft of the APV twin did
    `.query.first()` and SKIPPED when it found none, so every assertion below proved
    nothing. A balanced entry is required twice over -- the view builds je_lines from the
    stored legs, and the face refuses to draw an untied entry at all.
    """
    from app.cash_disbursements.preprinted_layout import get_layout, save_layout
    cdv = _cdv_with_je(db_session, main_branch)

    def _render(columns_enabled=True, columns=None):
        AppSettings.set_setting('cd_print_form', 'preprinted', 'admin')
        lay = get_layout(main_branch.id)
        lay['journalEntry']['columnsEnabled'] = columns_enabled
        for col in lay['journalEntry']['columns']:
            col.update((columns or {}).get(col['key'], {}))
        save_layout(lay, 'admin', main_branch.id)
        db_session.commit()
        login(client)
        with client.session_transaction() as sess:
            sess['selected_branch_id'] = main_branch.id
        resp = client.get(f'/cash-disbursements/{cdv.id}/print')
        assert resp.status_code == 200, (
            'the overlay did not render (-> %s); every assertion below would be vacuous'
            % resp.headers.get('Location'))
        return resp.get_data(as_text=True)

    return _render


@pytest.fixture
def overlay(render_overlay):
    return render_overlay(columns_enabled=True)


class TestTheSchema:

    def test_the_four_columns_are_defined_in_print_order(self):
        from app.cash_disbursements.preprinted_layout import JE_COLUMN_KEYS
        assert JE_COLUMN_KEYS == ('account_code', 'account_title', 'debit', 'credit')

    def test_each_column_carries_its_own_x(self):
        """THE point of the change -- a shared band could not do this.

        The VALUES are placeholders to be dragged; what must hold whatever they are is
        that they are distinct and ordered, so the first drag is a fit rather than a hunt
        for columns stacked on top of each other.
        """
        from app.cash_disbursements.preprinted_layout import sanitize_layout
        cols = sanitize_layout({})['journalEntry']['columns']
        xs = [c['x'] for c in cols]
        assert len(set(xs)) == 4, 'columns share an x and would print on top of each other'
        assert xs == sorted(xs), 'default columns should read left to right'

    def test_every_column_has_a_label(self):
        from app.cash_disbursements.preprinted_layout import (JE_COLUMN_KEYS,
                                                              JE_COLUMN_LABELS)
        for key in JE_COLUMN_KEYS:
            assert JE_COLUMN_LABELS.get(key), key


class TestItIsOptIn:

    def test_it_is_off_by_default(self):
        from app.cash_disbursements.preprinted_layout import sanitize_layout
        assert sanitize_layout({})['journalEntry']['columnsEnabled'] is False

    def test_a_layout_saved_before_this_still_gets_every_column(self):
        """A blob written before today carries no `columns` key at all. It must come back
        fully populated rather than empty, or the face would render nothing the moment
        somebody enabled it."""
        from app.cash_disbursements.preprinted_layout import sanitize_layout
        je = sanitize_layout({'journalEntry': {'mode': 'combined',
                                               'combined': {'x': 120, 'y': 20,
                                                            'width': 300}}})['journalEntry']
        assert len(je['columns']) == 4
        assert je['columnsEnabled'] is False           # still off
        assert je['combined']['x'] == 120              # and its own band survives


class TestTheSanitiser:

    def test_a_saved_position_is_kept(self):
        """The whole point of shipping placeholders: what the user drags must stick."""
        from app.cash_disbursements.preprinted_layout import sanitize_layout
        je = sanitize_layout({'journalEntry': {'columnsEnabled': True, 'columns': [
            {'key': 'debit', 'x': 500, 'width': 90, 'visible': False}]}})['journalEntry']
        debit = [c for c in je['columns'] if c['key'] == 'debit'][0]
        assert (debit['x'], debit['width'], debit['visible']) == (500, 90, False)

    def test_an_unknown_column_cannot_be_introduced(self):
        from app.cash_disbursements.preprinted_layout import sanitize_layout
        je = sanitize_layout({'journalEntry': {'columns': [
            {'key': 'sneaky', 'x': 1, 'width': 10}]}})['journalEntry']
        assert [c['key'] for c in je['columns']] == [
            'account_code', 'account_title', 'debit', 'credit']

    def test_a_wild_coordinate_is_clamped_not_trusted(self):
        """These are coordinates onto real stationery; an off-canvas value would print
        nothing and look like a data problem."""
        from app.cash_disbursements.preprinted_layout import sanitize_layout
        je = sanitize_layout({'journalEntry': {'columns': [
            {'key': 'account_code', 'x': 99999, 'width': 99999}]}})['journalEntry']
        code = [c for c in je['columns'] if c['key'] == 'account_code'][0]
        assert code['x'] < 99999 and code['width'] < 99999

    def test_the_three_original_bands_survive(self):
        """The combined/separated faces are not removed -- a client already positioned on
        them keeps working until they opt in."""
        from app.cash_disbursements.preprinted_layout import sanitize_layout
        je = sanitize_layout({})['journalEntry']
        for band in ('combined', 'debit', 'credit'):
            assert set(je[band]) == {'x', 'y', 'width'}
        assert je['mode'] in ('combined', 'separated')


class TestTheOverlayMarkup:
    """The contract between the rendered overlay and preprinted_je_designer.js."""

    def test_the_band_uses_its_own_classes(self, overlay):
        """NOT .pp-lineitems / .pp-col. The designer selects line-item columns with
        querySelectorAll('.pp-col'); sharing the class made collect() save these four as
        lineItems.columns, and the sanitiser then reset the client's real line-item
        positions -- BUG-APV-CDV-DESIGNER-SAVE-OVERWRITES-COLUMN-LAYOUT."""
        assert 'class="pp-jecols"' in overlay
        assert 'pp-jecol' in overlay

    def test_each_column_is_individually_addressable(self, overlay):
        for key in ('account_code', 'account_title', 'debit', 'credit'):
            assert 'data-jecol="%s"' % key in overlay, key

    def test_each_column_carries_a_label_for_the_empty_state(self, overlay):
        """An empty column renders nothing, so the designer shows data-label in its place
        -- without it a column with no value is invisible and cannot be grabbed."""
        for label in ('Account Code', 'Account Title', 'Debit', 'Credit'):
            assert 'data-label="%s"' % label in overlay, label

    def test_the_toggle_is_present(self, overlay):
        assert 'id="ppJEColsToggle"' in overlay

    def test_the_designer_offers_a_strip_for_these_columns(self, overlay):
        """What makes `visible` reachable at all. Without it the flag is storable,
        round-trippable and completely unsettable."""
        assert 'id="ppJEColControls"' in overlay

    def test_the_strip_is_separate_from_the_line_item_one(self, overlay):
        assert 'id="ppColControls"' in overlay
        assert 'id="ppJEColControls"' in overlay

    def test_the_server_layout_is_exposed_for_round_tripping(self, overlay):
        assert 'id="ppJELayout"' in overlay

    def test_the_overlay_declares_where_to_save(self, overlay):
        """The designer is SHARED with APV since 2026-09-06 and reads its POST endpoint
        from the canvas. A missing attribute makes it bail rather than guess, so if this
        is ever dropped the CDV designer silently stops working -- no Edit, no Save."""
        assert 'data-save-url="/cash-disbursements/print-layout"' in overlay


class TestExactlyOneFaceIsEverVisible:
    """The column face and the two legacy bands draw the SAME figures. If both showed, a
    voucher would print its journal entry twice, overlapping, on a client's pre-printed
    pad -- a failure discovered on paper, after the fact.

    Server-side this used to be structural ({% if %} / {% else %}). It is now a rule
    expressed in hiding classes, so that the designer toggle previews live -- and a rule
    CAN be got wrong.
    """

    def test_the_column_face_suppresses_the_combined_band(self, overlay):
        assert 'pp-je-inactive' in _open_tag(overlay, 'data-je="combined"')

    def test_the_column_face_suppresses_both_separated_bands(self, overlay):
        for band in ('debit', 'credit'):
            assert 'pp-je-inactive' in _open_tag(overlay, 'data-je="%s"' % band), band

    def test_the_column_face_itself_is_not_marked_off_when_enabled(self, overlay):
        assert 'pp-band-off' not in _open_tag(overlay, 'data-el="journalEntryColumns"')

    def test_with_columns_off_the_face_is_marked_off(self, render_overlay):
        html = render_overlay(columns_enabled=False)
        assert 'pp-band-off' in _open_tag(html, 'data-el="journalEntryColumns"')

    def test_with_columns_off_a_legacy_band_comes_back(self, render_overlay):
        """CONTROL for the three suppression tests above: without it, a template marking
        the legacy bands inactive unconditionally would satisfy them while printing
        nothing at all."""
        html = render_overlay(columns_enabled=False)
        assert 'pp-je-inactive' not in _open_tag(html, 'data-je="combined"')

    def test_an_off_face_is_hidden_by_a_real_rule(self, render_overlay):
        html = render_overlay(columns_enabled=False)
        assert '.pp-band-off { display: none; }' in html


class TestAColumnCanBeHidden:

    def test_a_hidden_column_is_marked_hidden(self, render_overlay):
        html = render_overlay(columns={'account_code': {'visible': False}})
        assert 'pp-col-hidden' in _open_tag(html, 'data-jecol="account_code"')

    def test_a_hidden_column_still_emits_its_cells(self, render_overlay):
        """ALIGNMENT INVARIANT. Hiding is a CSS concern; the column keeps one cell per JE
        line so the rest stay in registration, and re-showing it needs no stack rebuild --
        the band top is shared across all four."""
        html = render_overlay(columns={'account_code': {'visible': False}})
        assert 'data-jecol="account_code"' in html
        assert 'pp-col-hidden' not in _open_tag(html, 'data-jecol="account_title"')

    def test_a_visible_column_is_not_marked_hidden(self, render_overlay):
        """CONTROL. Without it a template emitting pp-col-hidden unconditionally would
        satisfy the assertion above."""
        html = render_overlay(columns={'account_code': {'visible': True}})
        assert 'pp-col-hidden' not in _open_tag(html, 'data-jecol="account_code"')
