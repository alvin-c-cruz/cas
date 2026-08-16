"""The PR form's picker dropdowns must not be clipped or left uncompacted.

These are render assertions on the GET, not POST-contract tests: every defect
below was a pure markup/CSS-plumbing bug that a POST test structurally cannot
see, and each one shipped green.

Three separate causes, all of which produced "the list looks wrong":

  1. `.table-responsive` wrapping the grid. It is `overflow-x: auto`, and a box
     that scrolls on one axis computes `auto` on the other, so it clipped the
     absolutely-positioned dropdown VERTICALLY. All 549 options were in the DOM
     and painted nowhere -- an empty white box. AP and SI use a plain div.
  2. `.card`'s own `overflow: hidden`. Harmless on AP/SI, whose card is the whole
     voucher, but this card ends just below the last row. Hence `.card--lines`.
  3. transactions.css's compact `.choices__list--dropdown .choices__item` rule is
     specificity (0,2,0) and LOSES to Choices' own (0,3,0)
     `.choices__list[aria-expanded] .choices__item`. Hence the
     `.page-purchase-request` scope, which lifts the override to (0,3,0) -- the
     same technique accounts_payable_form.css already documents for the
     vendor/customer pickers.
"""
import pytest

pytestmark = [pytest.mark.integration, pytest.mark.purchase_requests]


def _login(client, user, branch):
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user.id)
        sess['_fresh'] = True
        sess['selected_branch_id'] = branch.id


def _enable(db_session, *keys):
    from app.settings import AppSettings
    from app.utils.cache_helpers import clear_module_config_cache
    for k in keys:
        AppSettings.set_setting(f'module_enabled:{k}', '1')
    db_session.commit()
    clear_module_config_cache()


@pytest.fixture
def pr_form(client, db_session, admin_user, main_branch):
    _enable(db_session, 'products', 'purchase_orders', 'purchase_requests')
    _login(client, admin_user, main_branch)
    resp = client.get('/purchase-requests/create')
    assert resp.status_code == 200
    return resp.data


class TestPickerDropdownNotClipped:

    def test_grid_is_not_wrapped_in_table_responsive(self, pr_form):
        """The wrapper clipped the dropdown to the table's own 63px height."""
        html = pr_form.decode()
        table_at = html.index('id="lineItemsTable"')
        # Look only at the markup immediately preceding the table -- asserting
        # `.table-responsive` is absent from the WHOLE page would also fail on an
        # unrelated list partial and would pass for the wrong reason if base.html
        # ever stopped emitting one.
        preceding = html[max(0, table_at - 600):table_at]
        assert 'table-responsive' not in preceding

    def test_line_items_card_opts_out_of_overflow_clipping(self, pr_form):
        assert b'card--lines' in pr_form

    def test_line_items_card_carries_the_page_scope(self, pr_form):
        """Without .page-purchase-request the compact dropdown rule loses the
        cascade to Choices' own (0,3,0) selector and rows render at 41px with a
        100px right gutter and a horizontal scrollbar."""
        assert b'page-purchase-request' in pr_form

    def test_shared_line_item_stylesheet_is_linked(self, pr_form):
        """accounts_payable_form.css carries #lineItemsTable, .card--lines and
        the .page-purchase-request dropdown override -- all three fixes live
        there, so a dropped link silently undoes every one of them."""
        assert b'accounts_payable_form.css' in pr_form

    def test_choices_stylesheet_is_linked(self, pr_form):
        """Without it the dropdown has no display:none and every option renders
        inline, permanently expanded."""
        assert b'choices.min.css' in pr_form

    def test_choices_scripts_load_before_the_inline_initialiser(self, pr_form):
        """addRow() runs during the inline script and calls initSearchSelect. If
        the libraries load after it, the function is undefined, enhancement
        no-ops silently, and the picker degrades to a bare select that LOOKS
        fine -- which is exactly how the missing stylesheet went unnoticed."""
        html = pr_form.decode()
        assert html.index('search-select.js') < html.index('initSearchSelect')
        assert html.index('choices.min.js') < html.index('initSearchSelect')
