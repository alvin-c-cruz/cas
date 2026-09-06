"""The APV pre-printed JE face can be positioned column by column.

Owner request 2026-09-06: the journal entry should be split by column --
Account Code, Account Title, Debit, Credit.

It already rendered those four as cells, but inside ONE positioned band: a
single auto-width HTML table at journalEntry.combined.x/y/width. The browser
sized the columns, so they could be moved only as a block and never registered
against the voucher's own printed boxes. The line-item band had already been
given per-column x (2026-09-02); the JE face had not.

OPT-IN, exactly as lineItems.enabled is. `columnsEnabled` is absent from every
layout blob saved before today, so an existing client layout renders
byte-identically until somebody turns it on -- which matters because these are
coordinates onto a client's real pre-printed stationery.

ALIGNMENT INVARIANT: every column emits exactly ONE cell per JE line, blank
where it has nothing to say (a debit row's credit cell, and the reverse). Equal
-length stacks are what hold the columns in registration; a column that skipped
its blank cells would climb the page relative to the others.
"""
import pytest

pytestmark = [pytest.mark.integration, pytest.mark.accounts_payable]


class TestTheSchema:

    def test_the_four_columns_are_defined_in_print_order(self):
        from app.accounts_payable.preprinted_layout import JE_COLUMN_KEYS
        assert JE_COLUMN_KEYS == ('account_code', 'account_title', 'debit', 'credit')

    def test_each_column_carries_its_own_x(self):
        """THE point of the change -- a shared band could not do this."""
        from app.accounts_payable.preprinted_layout import sanitize_layout
        cols = sanitize_layout({})['journalEntry']['columns']
        xs = [c['x'] for c in cols]
        assert len(set(xs)) == 4, 'columns share an x and would print on top of each other'
        assert xs == sorted(xs), 'default columns should read left to right'

    def test_every_column_has_a_label(self):
        from app.accounts_payable.preprinted_layout import (JE_COLUMN_KEYS,
                                                            JE_COLUMN_LABELS)
        for key in JE_COLUMN_KEYS:
            assert JE_COLUMN_LABELS.get(key), key


class TestItIsOptIn:

    def test_it_is_off_by_default(self):
        from app.accounts_payable.preprinted_layout import sanitize_layout
        assert sanitize_layout({})['journalEntry']['columnsEnabled'] is False

    def test_a_layout_saved_before_this_still_gets_every_column(self):
        """A blob written before today carries no `columns` key at all. It must
        come back fully populated rather than empty, or the face would render
        nothing the moment somebody enabled it."""
        from app.accounts_payable.preprinted_layout import sanitize_layout
        je = sanitize_layout({'journalEntry': {'mode': 'combined',
                                               'combined': {'x': 120, 'y': 20,
                                                            'width': 300}}})['journalEntry']
        assert len(je['columns']) == 4
        assert je['columnsEnabled'] is False          # still off
        # x=120 is inside SAFE_MARGIN..CANVAS_W-SAFE_MARGIN, so it survives
        # untouched -- a value below the margin would be clamped, which is what
        # an earlier draft of this test tripped over.
        assert je['combined']['x'] == 120             # and its own band survives


class TestTheSanitiser:

    def test_a_saved_position_is_kept(self):
        from app.accounts_payable.preprinted_layout import sanitize_layout
        je = sanitize_layout({'journalEntry': {'columnsEnabled': True, 'columns': [
            {'key': 'debit', 'x': 500, 'width': 90, 'visible': False}]}})['journalEntry']
        debit = [c for c in je['columns'] if c['key'] == 'debit'][0]
        assert (debit['x'], debit['width'], debit['visible']) == (500, 90, False)

    def test_an_unknown_column_cannot_be_introduced(self):
        """Columns are rebuilt from JE_COLUMN_KEYS, so a blob naming something
        else is discarded rather than rendered."""
        from app.accounts_payable.preprinted_layout import sanitize_layout
        je = sanitize_layout({'journalEntry': {'columns': [
            {'key': 'sneaky', 'x': 1, 'width': 10}]}})['journalEntry']
        assert [c['key'] for c in je['columns']] == [
            'account_code', 'account_title', 'debit', 'credit']

    def test_a_wild_coordinate_is_clamped_not_trusted(self):
        """These are coordinates onto real stationery; an off-canvas value would
        print nothing and look like a data problem."""
        from app.accounts_payable.preprinted_layout import sanitize_layout
        je = sanitize_layout({'journalEntry': {'columns': [
            {'key': 'account_code', 'x': 99999, 'width': 99999}]}})['journalEntry']
        code = [c for c in je['columns'] if c['key'] == 'account_code'][0]
        assert code['x'] < 99999 and code['width'] < 99999

    def test_the_three_original_bands_survive(self):
        """The combined/separated faces are not removed -- a client already
        positioned on them keeps working until they opt in."""
        from app.accounts_payable.preprinted_layout import sanitize_layout
        je = sanitize_layout({})['journalEntry']
        for band in ('combined', 'debit', 'credit'):
            assert set(je[band]) == {'x', 'y', 'width'}
        assert je['mode'] in ('combined', 'separated')


@pytest.fixture
def render_overlay(client, db_session, admin_user, main_branch, make_account,
                   login_user):
    """The APV overlay page, rendered with the column face ENABLED.

    The voucher is BUILT here rather than looked up. An earlier draft did
    `AccountsPayable.query.first()` and skipped when it found none -- so
    every assertion below was skipped and proved nothing.

    A balanced journal entry is required twice over: print_ap builds
    je_lines from ap.journal_entry, and the face refuses to draw an untied
    entry at all (it prints an UNBALANCED notice instead).
    """
    from datetime import date
    from decimal import Decimal
    from app.users.models import User
    from app.accounts_payable.models import AccountsPayable
    from app.accounts_payable.preprinted_layout import get_layout, save_layout
    from app.journal_entries.models import JournalEntry, JournalEntryLine
    from app.vendors.models import Vendor
    from app.settings import AppSettings
    # A REAL login (POST /login), not a forged session. Writing _user_id by
    # hand did not authenticate here: Flask-Login memoises the resolved user
    # on g._login_user and conftest keeps one app context pushed for the whole
    # test, so the memo outlives every request. Going through the login route
    # sidesteps that entirely and is what conftest's own helper exists for.
    login_user(client, 'admin', 'admin123')
    with client.session_transaction() as sess:
        sess['selected_branch_id'] = main_branch.id

    AppSettings.set_setting('ap_print_form', 'preprinted')
    AppSettings.set_setting('apv_print_access', 'draft_and_posted')

    v = Vendor(code='JEC-V', name='JE Columns Vendor')
    db_session.add(v); db_session.commit()

    je = JournalEntry(entry_number='JEC-0001', entry_date=date(2026, 9, 6),
                      description='APV JE', branch_id=main_branch.id,
                      total_debit=Decimal('100.00'), total_credit=Decimal('100.00'),
                      is_balanced=True, status='posted')
    db_session.add(je); db_session.commit()
    dr, cr = make_account('19001'), make_account('29001')
    db_session.add(JournalEntryLine(entry_id=je.id, line_number=1,
                                    account_id=dr.id,
                                    debit_amount=Decimal('100.00'),
                                    credit_amount=Decimal('0.00')))
    db_session.add(JournalEntryLine(entry_id=je.id, line_number=2,
                                    account_id=cr.id,
                                    debit_amount=Decimal('0.00'),
                                    credit_amount=Decimal('100.00')))
    db_session.commit()

    ap = AccountsPayable(branch_id=main_branch.id, ap_number='JEC-AP-1',
                         ap_date=date(2026, 9, 6), due_date=date(2026, 10, 6),
                         payee_type='vendor', payee_id=v.id,
                         vendor_id=v.id, vendor_name=v.name,
                         notes='', status='posted', journal_entry_id=je.id)
    db_session.add(ap); db_session.commit()
    u = admin_user

    def _render(columns_enabled=True, columns=None):
        lay = get_layout(ap.branch_id)
        lay['journalEntry']['columnsEnabled'] = columns_enabled
        for col in lay['journalEntry']['columns']:
            col.update((columns or {}).get(col['key'], {}))
        save_layout(lay, u.username, ap.branch_id)  # (raw, username, branch_id)
        db_session.commit()
        resp = client.get(f'/accounts-payable/{ap.id}/print')
        assert resp.status_code == 200, (
            'the overlay did not render (-> %s); every assertion below would be '
            'vacuous' % resp.headers.get('Location'))
        return resp.get_data(as_text=True)

    return _render

@pytest.fixture
def overlay(render_overlay):
    return render_overlay(columns_enabled=True)


class TestTheDesignerCanDriveIt:
    """The columns are coordinates onto a client's real stationery, so they have
    to be draggable -- editing JSON by hand is not a workflow. These assert the
    contract between the overlay markup and apv_preprinted_designer.js.
    """


    def test_the_band_uses_its_own_classes(self, overlay):
        """NOT .pp-lineitems / .pp-col. The designer selects line-item columns
        with querySelectorAll('.pp-col'); sharing the class made collect() save
        these four as lineItems.columns, and the sanitiser then reset the
        client's real line-item positions to defaults."""
        assert 'class="pp-jecols"' in overlay
        assert 'pp-jecol' in overlay

    def test_each_column_is_individually_addressable(self, overlay):
        """data-jecol is what the designer reads back on save."""
        for key in ('account_code', 'account_title', 'debit', 'credit'):
            assert f'data-jecol="{key}"' in overlay, key

    def test_each_column_carries_a_label_for_the_empty_state(self, overlay):
        """An empty column renders nothing, so the designer shows data-label in
        its place -- without it a column with no value is invisible and cannot
        be grabbed."""
        for label in ('Account Code', 'Account Title', 'Debit', 'Credit'):
            assert f'data-label="{label}"' in overlay, label

    def test_the_toggle_is_present(self, overlay):
        assert 'id="ppJEColsToggle"' in overlay

    def test_the_server_layout_is_exposed_for_round_tripping(self, overlay):
        """The designer starts from the SERVER's journalEntry and overrides only
        what the DOM shows, so a save while the band is hidden preserves stored
        values instead of writing client-side defaults."""
        assert 'id="ppJELayout"' in overlay


def _marker_for(html, needle):
    """The opening <div ...> that carries `needle`, so class assertions are scoped to
    that one element instead of matching anywhere in the page."""
    return html.split(needle)[0].rsplit('<div', 1)[1]


class TestExactlyOneFaceIsEverVisible:
    """The column face and the two legacy bands draw the SAME figures. If both showed,
    a voucher would print its journal entry twice, overlapping, on a client's pre-printed
    pad -- the failure would be discovered on paper, after the fact.

    Server-side this used to be structural: `{% if columnsEnabled %} ... {% else %} ...`
    made two faces impossible. On 2026-09-06 all three bands became always-rendered (so
    the designer toggle previews live) and the choice moved into hiding classes, which is
    a rule that CAN be got wrong. Hence these tests.
    """

    def test_the_column_face_suppresses_the_combined_band(self, overlay):
        assert 'pp-je-inactive' in _marker_for(overlay, 'data-je="combined"')

    def test_the_column_face_suppresses_both_separated_bands(self, overlay):
        for band in ('debit', 'credit'):
            assert 'pp-je-inactive' in _marker_for(overlay, 'data-je="%s"' % band), band

    def test_the_column_face_itself_is_not_marked_off_when_enabled(self, overlay):
        assert 'pp-band-off' not in _marker_for(overlay, 'data-el="journalEntryColumns"')

    def test_with_columns_off_the_face_is_marked_off(self, render_overlay):
        html = render_overlay(columns_enabled=False)
        assert 'pp-band-off' in _marker_for(html, 'data-el="journalEntryColumns"')

    def test_with_columns_off_a_legacy_band_comes_back(self, render_overlay):
        """CONTROL for the three suppression tests above: without it, a template that
        marked the legacy bands inactive unconditionally would satisfy them while
        printing nothing at all."""
        html = render_overlay(columns_enabled=False)
        assert 'pp-je-inactive' not in _marker_for(html, 'data-je="combined"')

    def test_an_off_face_is_hidden_by_a_real_rule(self, render_overlay):
        """The class needs a declaration acting on it, asserted as the applied rule
        rather than the bare name -- the name is in the markup, so a substring check
        for it alone could never fail."""
        html = render_overlay(columns_enabled=False)
        assert '.pp-band-off { display: none; }' in html


class TestAColumnCanBeHidden:
    """Owner, 2026-09-06: "I have checked the JE as Columns, but there is no way to hide
    the account code."

    `visible` was in the schema from the start -- the sanitiser stored it, the template
    honoured it, collect() read it back -- but the designer built its show/hide strip from
    `cols()` (.pp-col / data-col), which cannot see the JE band. The flag was therefore
    settable only by editing stored JSON. These pin the strip that closes that, and the
    render path it drives.
    """

    def test_a_hidden_column_is_marked_hidden(self, render_overlay):
        html = render_overlay(columns={'account_code': {'visible': False}})
        assert 'pp-col-hidden' in _marker_for(html, 'data-jecol="account_code"')

    def test_a_hidden_column_still_emits_its_cells(self, render_overlay):
        """ALIGNMENT INVARIANT. Hiding is a CSS concern; the column keeps one cell per JE
        line so the remaining columns stay in registration, and so re-showing it later
        needs no stack rebuild -- the band top is shared across all four."""
        html = render_overlay(columns={'account_code': {'visible': False}})
        assert 'data-jecol="account_code"' in html     # still rendered, just hidden
        # control: hiding one column must not hide its neighbours
        assert 'pp-col-hidden' not in _marker_for(html, 'data-jecol="account_title"')

    def test_a_visible_column_is_not_marked_hidden(self, render_overlay):
        """CONTROL. Without it a template emitting pp-col-hidden unconditionally would
        satisfy the assertion above."""
        html = render_overlay(columns={'account_code': {'visible': True}})
        assert 'pp-col-hidden' not in _marker_for(html, 'data-jecol="account_code"')

    def test_the_hidden_class_is_backed_by_a_real_rule(self, overlay):
        assert '.pp-col-hidden { display: none; }' in overlay

    def test_the_designer_offers_a_strip_for_these_columns(self, overlay):
        """The strip is what makes `visible` reachable at all. Without it the flag is
        storable, round-trippable and completely unsettable -- which is the bug."""
        assert 'id="ppJEColControls"' in overlay

    def test_the_strip_is_separate_from_the_line_item_one(self, overlay):
        """Sharing #ppColControls would have meant one builder sweeping both bands --
        the same class of mistake as the shared .pp-col selector, which silently reset a
        client's stored line-item positions once already."""
        assert 'id="ppColControls"' in overlay
        assert 'id="ppJEColControls"' in overlay
