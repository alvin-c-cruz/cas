"""The APV pre-printed voucher renders its particulars band, gated by lineItems.enabled.

Reverses the 2026-07-07 "intentionally NOT rendered" decision. The gate exists because
PhilGen is live on this form with a saved layout whose JE face sits at y=272 -- a band at
the default y=300 would print straight through it.
"""
import pytest

from app.settings import AppSettings
from tests.integration.test_apv_print_form import login, _posted_apv

pytestmark = [pytest.mark.integration, pytest.mark.accounts_payable]


def _render(client, db_session, main_branch, ap, *, enabled, columns=None):
    """Store a layout, then GET the pre-printed print page and return its HTML."""
    from app.accounts_payable.preprinted_layout import save_layout, get_layout
    AppSettings.set_setting('ap_print_form', 'preprinted', 'admin')
    layout = get_layout(main_branch.id)
    layout['lineItems']['enabled'] = enabled
    for key, patch in (columns or {}).items():
        col = next(c for c in layout['lineItems']['columns'] if c['key'] == key)
        col.update(patch)
    save_layout(layout, 'admin', main_branch.id)
    login(client)
    with client.session_transaction() as s:
        s['selected_branch_id'] = main_branch.id
    return client.get(f'/accounts-payable/{ap.id}/print').data.decode()


def _apv_with_three_lines(db_session, main_branch):
    """Same shape as `_posted_apv`, but with three line items (1..3) instead of one."""
    from decimal import Decimal
    from datetime import date
    from app.vendors.models import Vendor
    from app.accounts.models import Account
    from app.accounts_payable.models import AccountsPayable, AccountsPayableItem
    vendor = Vendor(code='PPV3', name='Preprint Supplier Three Inc.', tin='111-222-333-001',
                    is_active=True)
    db_session.add(vendor); db_session.commit()
    expense = Account(code='5010', name='Office Supplies', account_type='Expense',
                      normal_balance='debit', is_active=True)
    db_session.add(expense); db_session.commit()
    ap = AccountsPayable(ap_number='APV-PP-3', ap_date=date(2026, 7, 7),
                         due_date=date(2026, 8, 6), vendor_id=vendor.id,
                         vendor_name=vendor.name, vendor_tin=vendor.tin,
                         vendor_invoice_number='SUP-INV-10', branch_id=main_branch.id,
                         status='posted', subtotal=Decimal('33600'),
                         vat_amount=Decimal('3600'), total_before_wt=Decimal('33600'),
                         withholding_tax_amount=Decimal('600'),
                         total_amount=Decimal('33000'))
    for n in (1, 2, 3):
        ap.line_items.append(AccountsPayableItem(line_number=n, description=f'Bond paper {n}',
                                                  quantity=Decimal('10'), unit_price=Decimal('1120'),
                                                  line_total=Decimal('11200'),
                                                  account_id=expense.id))
    db_session.add(ap); db_session.commit()
    return ap


class TestBandGate:
    """A disabled band must never reach paper.

    HOW that is enforced changed on 2026-09-06 and these tests changed with it. The band
    used to be omitted server-side (`{% if li.enabled %}`), which meant ticking "Show line
    items" in the designer produced no markup and therefore no visible change until the
    layout was saved AND the page reloaded -- the columns could not be dragged into
    position in the same sitting they were turned on. The band is now always rendered and
    switched off with the `pp-band-off` class, so the toggle is a live class flip.

    The REQUIREMENT is unchanged, so it is still asserted below -- just against the class
    and the rule that acts on it rather than against the absence of markup.
    """

    def test_a_disabled_band_is_marked_off(self, client, db_session, admin_user,
                                           main_branch):
        """`_render` sets `layout['lineItems']['enabled'] = enabled` directly, so this pins
        the explicit-False path, not the absent-key (legacy blob) path -- that one is
        covered at the unit layer by
        `TestLineItemBandGate::test_enabled_defaults_false_on_a_legacy_blob` in
        `tests/unit/test_apv_preprinted_layout.py`, which sanitizes a blob with no
        `enabled` key at all and asserts it defaults to False."""
        ap = _posted_apv(db_session, main_branch)
        html = _render(client, db_session, main_branch, ap, enabled=False)
        marker = html.split('data-el="lineItems"')[0].rsplit('<div', 1)[1]
        assert 'pp-band-off' in marker

    def test_a_disabled_band_is_not_displayed_and_not_printed(self, client, db_session,
                                                              admin_user, main_branch):
        """The class only means something if a rule acts on it. Without this, renaming or
        dropping the CSS would leave an off band printing on a client's stationery with
        every assertion above still green.

        Asserted on the applied declaration rather than the bare class name: the class
        appears in the markup too, so a substring check for `pp-band-off` alone could
        never fail (see the scoped-absence rule in the workspace conventions)."""
        ap = _posted_apv(db_session, main_branch)
        html = _render(client, db_session, main_branch, ap, enabled=False)
        assert '.pp-band-off { display: none; }' in html
        # ...and it stays hidden if somebody prints while still in edit mode, where the
        # .pp-editing rule would otherwise reveal it at 40% opacity.
        assert '.pp-canvas.pp-editing .pp-band-off,' in html
        assert '.pp-canvas.pp-editing .pp-je-inactive { display: none !important; }' in html

    def test_an_enabled_band_is_not_marked_off(self, client, db_session, admin_user,
                                               main_branch):
        """CONTROL. Without this the off-marker assertion above passes vacuously -- a
        template that emitted `pp-band-off` unconditionally would satisfy it."""
        ap = _posted_apv(db_session, main_branch)
        html = _render(client, db_session, main_branch, ap, enabled=True)
        marker = html.split('data-el="lineItems"')[0].rsplit('<div', 1)[1]
        assert 'pp-band-off' not in marker

    def test_band_present_when_enabled(self, client, db_session, admin_user, main_branch):
        ap = _posted_apv(db_session, main_branch)
        html = _render(client, db_session, main_branch, ap, enabled=True)
        assert 'data-el="lineItems"' in html
        assert 'data-col="line_number"' in html


class TestColumnVisibility:
    def test_hidden_column_carries_pp_col_hidden(self, client, db_session, admin_user,
                                                 main_branch):
        ap = _posted_apv(db_session, main_branch)
        html = _render(client, db_session, main_branch, ap, enabled=True,
                       columns={'account_code': {'visible': False}})
        assert 'data-col="account_code"' in html          # still emitted...
        marker = html.split('data-col="account_code"')[0].rsplit('<div', 1)[1]
        assert 'pp-col-hidden' in marker                  # ...but hidden

    def test_visible_column_has_no_hidden_class(self, client, db_session, admin_user,
                                                main_branch):
        ap = _posted_apv(db_session, main_branch)
        html = _render(client, db_session, main_branch, ap, enabled=True,
                       columns={'account_code': {'visible': True}})
        marker = html.split('data-col="account_code"')[0].rsplit('<div', 1)[1]
        assert 'pp-col-hidden' not in marker


class TestAccountSplitRendering:
    def test_code_and_name_render_in_separate_columns(self, client, db_session, admin_user,
                                                      main_branch):
        ap = _posted_apv(db_session, main_branch)
        html = _render(client, db_session, main_branch, ap, enabled=True)
        assert 'data-col="account_code"' in html
        assert 'data-col="account_name"' in html
        assert '5010' in html and 'Office Supplies' in html

    def test_the_concatenated_form_is_gone(self, client, db_session, admin_user, main_branch):
        """The standard print emits `code : name` in one cell; the band must not.

        _posted_apv's account is code 5010 / name 'Office Supplies'.
        """
        ap = _posted_apv(db_session, main_branch)
        html = _render(client, db_session, main_branch, ap, enabled=True)
        assert '5010 : Office Supplies' not in html


class TestAlignmentInvariant:
    def test_every_column_emits_one_cell_per_line_item(self, client, db_session, admin_user,
                                                       main_branch):
        """Equal-length stacks are what keep columns registered against the paper boxes."""
        ap = _apv_with_three_lines(db_session, main_branch)
        html = _render(client, db_session, main_branch, ap, enabled=True)
        # All 9 columns, not just 5 -- product/qty/uom/unit_price carry conditionals in
        # their cell bodies (e.g. `{% if item.product %}`) and are exactly the ones most
        # likely to emit a blank/short stack instead of one cell per line item.
        for key in ('line_number', 'product', 'description', 'qty', 'uom', 'unit_price',
                    'amount', 'account_code', 'account_name'):
            # Slice from this column's marker to the start of the next column div.
            block = html.split(f'data-col="{key}"')[1].split('<div class="pp-col')[0]
            assert block.count('class="pp-cell"') == 3, f'{key} emitted != 3 cells'


class TestLineItemsToggle:
    """The designer's enable checkbox and the server-values script block it reads on save."""

    def test_toggle_checked_when_enabled(self, client, db_session, admin_user, main_branch):
        ap = _posted_apv(db_session, main_branch)
        html = _render(client, db_session, main_branch, ap, enabled=True)
        assert 'id="ppLineItemsToggle"' in html
        tag = html.split('id="ppLineItemsToggle"')[1].split('>')[0]
        assert 'checked' in tag

    def test_toggle_not_checked_when_disabled(self, client, db_session, admin_user, main_branch):
        """CONTROL. Without this the checked-when-enabled assertion above passes vacuously
        (e.g. if the checkbox were unconditionally `checked`)."""
        ap = _posted_apv(db_session, main_branch)
        html = _render(client, db_session, main_branch, ap, enabled=False)
        assert 'id="ppLineItemsToggle"' in html
        tag = html.split('id="ppLineItemsToggle"')[1].split('>')[0]
        assert 'checked' not in tag


class TestServerLineItemsJSON:
    """`#ppServerLineItems` is what `collect()` falls back to instead of client-side
    constants -- see BUG-APV-CDV-DESIGNER-SAVE-OVERWRITES-COLUMN-LAYOUT."""

    def test_server_line_items_json_has_nine_columns(self, client, db_session, admin_user,
                                                      main_branch):
        import json
        ap = _posted_apv(db_session, main_branch)
        html = _render(client, db_session, main_branch, ap, enabled=True)
        assert 'id="ppServerLineItems"' in html
        block = html.split('id="ppServerLineItems"')[1].split('>', 1)[1].split('</script>')[0]
        data = json.loads(block)
        assert len(data['columns']) == 9


class TestJEFaceUntouched:
    def test_je_face_still_renders_at_its_saved_coordinates(self, client, db_session,
                                                            admin_user, main_branch):
        """CONTROL: enabling the band does not change the JE face's rendered coordinates.

        Sets the JE face's saved position to PhilGen's real live coordinates
        (x=75, y=272 -- see this file's module docstring) BEFORE enabling the band,
        then asserts the rendered `data-je="combined"` element's inline style still
        carries that exact `left:`/`top:`. Both elements are absolutely positioned
        from `layout.journalEntry.combined`/`layout.lineItems`, so nothing at render
        time can "shove" one from the other -- this can only fail if someone rewrites
        the JE block to stop reading its own saved coordinates. It does NOT check for
        visual overlap between the band and the JE face at distinct coordinates; that
        is a real layout risk (e.g. a saved band y that lands on top of the JE face)
        and no test in this suite covers it -- catching it requires a live/visual
        check of the printed page.
        """
        from app.accounts_payable.preprinted_layout import save_layout, get_layout
        from tests.integration.test_apv_print_form import _apv_with_je
        AppSettings.set_setting('ap_print_form', 'preprinted', 'admin')
        layout = get_layout(main_branch.id)
        layout['journalEntry']['combined']['x'] = 75
        layout['journalEntry']['combined']['y'] = 272
        save_layout(layout, 'admin', main_branch.id)

        ap = _apv_with_je(db_session, main_branch, balanced=True)
        html = _render(client, db_session, main_branch, ap, enabled=True)
        # The JE face renders from its own saved coords, untouched by the band.
        assert 'data-je="combined"' in html
        tag = html.split('data-je="combined"')[1].split('>')[0].replace(' ', '')
        assert 'left:75px' in tag
        assert 'top:272px' in tag


def _css_rule(html, selector):
    """The declaration block for `selector` in the page's inline stylesheet.

    Asserting a whole rule as one literal is what broke when `tab-size` was added to
    `.pp-el` -- a test about newlines failed over an unrelated property. Pin the
    declaration you actually mean instead.
    """
    i = html.index(selector + ' {')
    return html[i:html.index('}', i) + 1]


def _open_tag(html, needle):
    """The WHOLE opening <div ...> carrying `needle`.

    Not `html.split(needle)[0].rsplit('<div', 1)[1]` -- that stops AT the needle and so
    sees only the attributes written before it. `class` precedes `data-el` but `style`
    follows it, so the shorter form silently cannot observe width/left/top at all.
    """
    start = html.rindex('<div', 0, html.index(needle))
    return html[start:html.index('>', start) + 1]


class TestAFieldCanWrapOntoMultipleLines:
    """Owner, 2026-09-06: "multi-line should be supported."

    A long Notes value -- PhilGen's are a particulars string built from the PO/SI/RR
    references, so they are long by construction -- ran off the right edge of the page
    as a single line, because `.pp-el` is `white-space: nowrap`.

    "Multi-line" is two things, and both are asserted here:
      1. WRAPPING at a width the client chooses, and
      2. honouring newlines already typed into the record.
    Only (1) needs a setting; (2) follows from `pre-wrap` and would be silently lost
    under plain `normal` wrapping, which collapses a newline to a space.
    """

    def _render_notes(self, client, db_session, main_branch, notes, width=None):
        from app.accounts_payable.preprinted_layout import get_layout, save_layout
        ap = _posted_apv(db_session, main_branch)
        ap.notes = notes
        db_session.commit()
        lay = get_layout(main_branch.id)
        if width is not None:
            lay['fields']['notes']['width'] = width
        save_layout(lay, 'admin', main_branch.id)
        db_session.commit()
        AppSettings.set_setting('ap_print_form', 'preprinted', 'admin')
        login(client)
        with client.session_transaction() as sess:
            sess['selected_branch_id'] = main_branch.id
        resp = client.get(f'/accounts-payable/{ap.id}/print')
        assert resp.status_code == 200
        return resp.get_data(as_text=True)

    def test_a_field_with_no_width_is_unchanged(self, client, db_session, admin_user,
                                                main_branch):
        """THE backward-compatibility guarantee. Every layout saved before today has no
        width, and these are coordinates onto real stationery -- such a voucher must
        print exactly as it did yesterday."""
        html = self._render_notes(client, db_session, main_branch, 'Short note')
        tag = _open_tag(html, 'data-el="notes"')
        assert 'pp-wrap' not in tag
        assert 'width:' not in tag

    def test_a_width_makes_the_field_wrap(self, client, db_session, admin_user,
                                          main_branch):
        html = self._render_notes(client, db_session, main_branch,
                                  'A rather long particulars string', width=340)
        tag = _open_tag(html, 'data-el="notes"')
        assert 'pp-wrap' in tag
        assert 'width:340px' in tag

    def test_wrapping_is_backed_by_a_real_rule(self, client, db_session, admin_user,
                                               main_branch):
        """Scoped to the applied declaration, not the bare class name -- the name is in
        the markup, so a substring check for it alone could never fail."""
        html = self._render_notes(client, db_session, main_branch, 'x', width=340)
        assert '.pp-el.pp-wrap { white-space: pre-wrap; overflow-wrap: break-word; }' in html

    def test_a_newline_prints_WITHOUT_any_width_being_set(self, client, db_session,
                                                          admin_user, main_branch):
        """THE owner report, 2026-09-06: "Notes (Particulars) accepted multi line ...
        print should too."

        A newline typed into the record is DATA, not layout: the edit form stores it, so
        the voucher prints it, and no designer setting should be needed to make that
        happen. `.pp-el` was `white-space: nowrap`, which collapsed it to a space.

        Asserted with NO width, because requiring one would have made a data property
        depend on a layout property -- the shape of the bug, not a fix for it.
        """
        html = self._render_notes(client, db_session, main_branch,
                                  'First line\nSecond line')
        assert 'First line\nSecond line' in html          # value reaches the page...
        assert 'white-space: pre;' in _css_rule(html, '.pp-el')             # ...as breaks

    def test_the_default_does_not_reflow_text_nobody_asked_to_wrap(self, client,
                                                                   db_session, admin_user,
                                                                   main_branch):
        """`pre`, not `pre-line`. Both honour a typed newline, but pre-line ALSO wraps at
        whatever edge the box happens to have -- on an absolutely-positioned field that
        is the canvas edge, a boundary nobody chose. On pre-printed stationery a line
        that silently reflows lands on top of the next printed box. Wrapping stays
        opt-in, via a width.
        """
        html = self._render_notes(client, db_session, main_branch, 'x' * 300)
        assert 'white-space: pre-line' not in html
        assert 'pp-wrap' not in _open_tag(html, 'data-el="notes"')

    def test_a_newline_still_prints_when_a_width_IS_set(self, client, db_session,
                                                        admin_user, main_branch):
        """pre-wrap keeps both behaviours; a wrapped field must not lose its breaks."""
        html = self._render_notes(client, db_session, main_branch,
                                  'First line\nSecond line', width=340)
        assert 'First line\nSecond line' in html
        assert 'pp-wrap' in _open_tag(html, 'data-el="notes"')

    def test_an_unbroken_token_cannot_escape_the_box(self, client, db_session, admin_user,
                                                     main_branch):
        """A long reference with no spaces (PhilGen's particulars carry PO/SI/RR numbers
        run together) would overflow a wrapped box under pre-wrap alone -- which is the
        very failure being fixed, just narrower. overflow-wrap is what stops it."""
        html = self._render_notes(client, db_session, main_branch, 'x' * 200, width=200)
        assert 'overflow-wrap: break-word' in html


class TestEveryElementCanBeSized:
    """Owner, 2026-09-06: "all elements should have resizable width."

    Width had reached fields and duplicated copies; layout texts were the element that
    could be moved but never sized, because the shared text sanitiser had no width key.
    The JE bands already stored one but the designer offered no way to drag it.
    """

    def _render(self, client, db_session, main_branch, *, text_width=None):
        from app.accounts_payable.preprinted_layout import get_layout, save_layout
        ap = _posted_apv(db_session, main_branch)
        lay = get_layout(main_branch.id)
        if text_width is not None:
            lay['texts'][0]['width'] = text_width
        save_layout(lay, 'admin', main_branch.id)
        db_session.commit()
        AppSettings.set_setting('ap_print_form', 'preprinted', 'admin')
        login(client)
        with client.session_transaction() as sess:
            sess['selected_branch_id'] = main_branch.id
        resp = client.get(f'/accounts-payable/{ap.id}/print')
        assert resp.status_code == 200
        return resp.get_data(as_text=True), lay['texts'][0]['id']

    def test_a_layout_text_with_no_width_is_unchanged(self, client, db_session,
                                                      admin_user, main_branch):
        """The backward-compatibility guarantee, on the shared module this time: every
        stored layout in every document predates the key."""
        html, tid = self._render(client, db_session, main_branch)
        tag = _open_tag(html, 'data-text="%s"' % tid)
        assert 'pp-wrap' not in tag
        assert 'width:' not in tag

    def test_a_layout_text_can_be_given_a_width(self, client, db_session, admin_user,
                                                main_branch):
        html, tid = self._render(client, db_session, main_branch, text_width=220)
        tag = _open_tag(html, 'data-text="%s"' % tid)
        assert 'pp-wrap' in tag
        assert 'width:220px' in tag


class TestFiguresCanBeLinedUpInTheParticulars:
    """Owner, 2026-09-06: "the goal is to type in number adding up" -- a small tally
    typed into Notes whose figures line up in a column.

    Two things carry that, and neither is the wrap width:
      * `white-space: pre` keeps the runs of spaces or tabs that do the aligning
        (`nowrap` collapsed them, which is why columns could not be held before), and
      * the layout font is monospace, so equal character counts are equal widths.
    """

    def _print(self, client, db_session, main_branch, notes):
        from app.accounts_payable.preprinted_layout import get_layout, save_layout
        ap = _posted_apv(db_session, main_branch)
        ap.notes = notes
        db_session.commit()
        save_layout(get_layout(main_branch.id), 'admin', main_branch.id)
        db_session.commit()
        AppSettings.set_setting('ap_print_form', 'preprinted', 'admin')
        login(client)
        with client.session_transaction() as sess:
            sess['selected_branch_id'] = main_branch.id
        resp = client.get(f'/accounts-payable/{ap.id}/print')
        assert resp.status_code == 200
        return resp.get_data(as_text=True)

    def test_a_tab_reaches_the_page_intact(self, client, db_session, admin_user,
                                           main_branch):
        """Nothing between the textarea and the voucher strips it: the field has no
        filters and `form.notes.data` is assigned to the column as typed."""
        html = self._print(client, db_session, main_branch, 'ITEM A	1,200.00')
        assert 'ITEM A	1,200.00' in html

    def test_runs_of_spaces_are_not_collapsed(self, client, db_session, admin_user,
                                              main_branch):
        """The other way to hold a column, and the one that needs no Tab key at all.
        HTML collapses whitespace by default; `pre` is what preserves it."""
        html = self._print(client, db_session, main_branch, 'ITEM A     1,200.00')
        assert 'ITEM A     1,200.00' in html

    def test_a_tab_has_a_stated_column_stop(self, client, db_session, admin_user,
                                            main_branch):
        """Left to the browser, tab-size is merely conventional. Stating it is what makes
        the column reproducible across browsers -- and this prints onto a client's
        pre-printed pad, where a shifted column lands in the wrong box."""
        html = self._print(client, db_session, main_branch, 'x	y')
        assert 'tab-size: 8' in _css_rule(html, '.pp-el')

    def test_the_layout_font_is_monospace(self, client, db_session, admin_user,
                                          main_branch):
        """The alignment rests on this. Under a proportional face, equal character counts
        are NOT equal widths and every column silently drifts -- so the default font
        ships monospace and this pins that it stays so."""
        from app.accounts_payable.preprinted_layout import DEFAULT_APV_PREPRINTED_LAYOUT
        assert 'monospace' in DEFAULT_APV_PREPRINTED_LAYOUT['page']['fontFamily']
