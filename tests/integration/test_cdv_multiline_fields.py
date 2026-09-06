"""CDV fields print multi-line, wrap at a chosen width, and hold a column of figures.

The APV twin's 2026-09-06 work, ported. A long Notes (Particulars) value ran off the
right edge of the page as a single line, because `.pp-el` was `white-space: nowrap`.

"Multi-line" turned out to be two separate things, and both are asserted here:

  1. newlines already typed into the record print as breaks. That is DATA -- the edit
     form stores them, so the voucher prints them -- and needs no layout setting.
  2. WRAPPING at a width the client chooses. That is layout, therefore opt-in, and
     absent from every blob saved before today (0 = unset = one line).

A third thing rides on (1): with whitespace preserved and a monospace layout font, a
tally typed into Particulars holds its columns -- which is what the owner actually wanted
("the goal is to type in number adding up").
"""
import pytest

from app.settings import AppSettings
from tests.integration.test_cdv_print_form import login, _cdv_with_je

pytestmark = [pytest.mark.integration, pytest.mark.cash_disbursements]


def _open_tag(html, needle):
    """The WHOLE opening <div ...> carrying `needle`.

    Not `html.split(needle)[0].rsplit('<div', 1)[1]` -- that stops AT the needle and so
    sees only the attributes written before it. `class` precedes `data-el` but `style`
    follows it, so the shorter form cannot observe both.
    """
    start = html.rindex('<div', 0, html.index(needle))
    return html[start:html.index('>', start) + 1]


def _css_rule(html, selector):
    """The declaration block for `selector` in the page's inline stylesheet.

    Asserting a whole rule as one literal string is brittle: on the APV side, adding
    `tab-size` to `.pp-el` broke a test about newlines over an unrelated property. Pin
    the declaration actually meant.
    """
    i = html.index(selector + ' {')
    return html[i:html.index('}', i) + 1]


def _render(client, db_session, main_branch, notes=None, width=None, text_width=None):
    """Store a layout (and optionally a notes value), then GET the overlay."""
    from app.cash_disbursements.preprinted_layout import get_layout, save_layout
    cdv = _cdv_with_je(db_session, main_branch)
    if notes is not None:
        cdv.notes = notes
        db_session.commit()
    lay = get_layout(main_branch.id)
    if width is not None:
        lay['fields']['notes']['width'] = width
    if text_width is not None:
        lay['texts'][0]['width'] = text_width
    save_layout(lay, 'admin', main_branch.id)
    db_session.commit()
    AppSettings.set_setting('cd_print_form', 'preprinted', 'admin')
    login(client)
    with client.session_transaction() as sess:
        sess['selected_branch_id'] = main_branch.id
    resp = client.get('/cash-disbursements/%s/print' % cdv.id)
    assert resp.status_code == 200, resp.headers.get('Location')
    return resp.get_data(as_text=True), lay['texts'][0]['id']


class TestTypedNewlinesPrint:

    def test_a_newline_prints_without_any_width_being_set(self, client, db_session,
                                                          admin_user, main_branch):
        """Requiring a width for this would make a DATA property depend on a LAYOUT
        property -- the shape of the bug, not a fix for it."""
        html, _ = _render(client, db_session, main_branch,
                          notes='First line\nSecond line')
        assert 'First line\nSecond line' in html            # value reaches the page...
        assert 'white-space: pre;' in _css_rule(html, '.pp-el')   # ...and renders as breaks

    def test_the_default_does_not_reflow_text_nobody_asked_to_wrap(self, client,
                                                                   db_session, admin_user,
                                                                   main_branch):
        """`pre`, not `pre-line`. Both honour a typed newline, but pre-line ALSO wraps at
        whatever edge the box happens to have -- on an absolutely-positioned field that is
        the canvas edge, a boundary nobody chose. On pre-printed stock a line that
        silently reflows lands on top of the next printed box.
        """
        html, _ = _render(client, db_session, main_branch, notes='x' * 300)
        assert 'white-space: pre-line' not in html
        assert 'pp-wrap' not in _open_tag(html, 'data-el="notes"')


class TestFiguresCanBeLinedUpInAColumn:
    """Two mechanisms hold a column, and neither is the wrap width."""

    def test_runs_of_spaces_are_not_collapsed(self, client, db_session, admin_user,
                                              main_branch):
        """HTML collapses whitespace by default; `pre` is what preserves it. This is the
        way that needs no Tab key at all."""
        html, _ = _render(client, db_session, main_branch,
                          notes='ITEM A     1,200.00')
        assert 'ITEM A     1,200.00' in html

    def test_a_tab_reaches_the_page_intact(self, client, db_session, admin_user,
                                           main_branch):
        """Nothing between the textarea and the voucher strips it: the field has no
        filters and form.notes.data is assigned to the column as typed."""
        html, _ = _render(client, db_session, main_branch, notes='ITEM A\t1,200.00')
        assert 'ITEM A\t1,200.00' in html

    def test_a_tab_has_a_stated_column_stop(self, client, db_session, admin_user,
                                            main_branch):
        """Left to the browser, tab-size is merely conventional. Stating it is what makes
        the column reproducible across browsers -- and this prints onto a client's pad,
        where a shifted column lands in the wrong box."""
        html, _ = _render(client, db_session, main_branch, notes='x\ty')
        assert 'tab-size: 8' in _css_rule(html, '.pp-el')

    def test_the_layout_font_is_monospace(self):
        """The alignment rests on this. Under a proportional face, equal character counts
        are NOT equal widths and every column silently drifts -- so the default font ships
        monospace and this pins that it stays so."""
        from app.cash_disbursements.preprinted_layout import (
            DEFAULT_CDV_PREPRINTED_LAYOUT)
        assert 'monospace' in DEFAULT_CDV_PREPRINTED_LAYOUT['page']['fontFamily']


class TestTheWrapWidth:

    def test_a_field_with_no_width_is_unchanged(self, client, db_session, admin_user,
                                                main_branch):
        """THE backward-compatibility guarantee. Every layout saved before today has no
        width, and these are coordinates onto real stationery."""
        html, _ = _render(client, db_session, main_branch, notes='Short note')
        tag = _open_tag(html, 'data-el="notes"')
        assert 'pp-wrap' not in tag
        assert 'width:' not in tag

    def test_a_width_makes_the_field_wrap(self, client, db_session, admin_user,
                                          main_branch):
        html, _ = _render(client, db_session, main_branch,
                          notes='A rather long particulars string', width=340)
        tag = _open_tag(html, 'data-el="notes"')
        assert 'pp-wrap' in tag
        assert 'width:340px' in tag

    def test_wrapping_is_backed_by_a_real_rule(self, client, db_session, admin_user,
                                               main_branch):
        """Scoped to the applied declaration, not the bare class name -- the name is in
        the markup, so a substring check for it alone could never fail."""
        html, _ = _render(client, db_session, main_branch, notes='x', width=340)
        assert '.pp-el.pp-wrap { white-space: pre-wrap; overflow-wrap: break-word; }' in html

    def test_a_wrapped_field_still_keeps_its_newlines(self, client, db_session,
                                                      admin_user, main_branch):
        """pre-wrap holds both behaviours; a wrapped field must not lose its breaks."""
        html, _ = _render(client, db_session, main_branch,
                          notes='First line\nSecond line', width=340)
        assert 'First line\nSecond line' in html
        assert 'pp-wrap' in _open_tag(html, 'data-el="notes"')


class TestALayoutTextCanBeSized:
    """Layout texts had no width anywhere -- the one element that could be moved but never
    sized. The key lives in the shared app/common/preprinted_texts.py, so CDV inherits it
    rather than declaring its own.
    """

    def test_a_layout_text_with_no_width_is_unchanged(self, client, db_session,
                                                      admin_user, main_branch):
        html, tid = _render(client, db_session, main_branch)
        tag = _open_tag(html, 'data-text="%s"' % tid)
        assert 'pp-wrap' not in tag
        assert 'width:' not in tag

    def test_a_layout_text_can_be_given_a_width(self, client, db_session, admin_user,
                                                main_branch):
        html, tid = _render(client, db_session, main_branch, text_width=220)
        tag = _open_tag(html, 'data-text="%s"' % tid)
        assert 'pp-wrap' in tag
        assert 'width:220px' in tag
