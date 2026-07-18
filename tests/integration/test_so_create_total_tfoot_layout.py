"""Regression test for BUG-SO-CREATE-TOTAL-LAYOUT-MISMATCH: the SO create/edit form must
render its running total as a <tfoot> row inside #lineItemsTable, matching detail.html's
existing pattern, instead of a separate summary panel below the table."""

import pytest

pytestmark = [pytest.mark.integration, pytest.mark.sales_orders]


@pytest.fixture(autouse=True)
def sales_orders_module_enabled(db_session):
    """Enable the optional sales_orders module for all SO tests."""
    from app.settings import AppSettings
    from app.utils.cache_helpers import clear_module_config_cache
    AppSettings.set_setting('module_enabled:sales_orders', '1')
    db_session.commit()
    clear_module_config_cache()
    yield
    clear_module_config_cache()


def test_total_display_lives_inside_tfoot_in_lineitemstable(client, accountant_user, branch_manila):
    """Test that the SO create form renders the total in a <tfoot> row, not a separate panel."""
    # Log in the user via session
    with client.session_transaction() as sess:
        sess['_user_id'] = str(accountant_user.id)
        sess['_fresh'] = True
        sess['selected_branch_id'] = branch_manila.id

    resp = client.get('/sales-orders/create')
    assert resp.status_code == 200
    body = resp.data.decode('utf-8')

    # Verify the table exists and contains a <tfoot>
    table_start = body.index('id="lineItemsTable"')
    table_end = body.index('</table>', table_start)
    table_html = body[table_start:table_end]
    assert '<tfoot>' in table_html, '#lineItemsTable must contain a <tfoot>'

    # Verify #totalDisplay lives inside the <tfoot>
    tfoot_start = table_html.index('<tfoot>')
    assert 'id="totalDisplay"' in table_html[tfoot_start:], (
        '#totalDisplay must live inside the <tfoot>, not a separate summary panel')

    # Verify the old summary panel is gone
    assert 'bill-summary-panel' not in body, (
        'the old separate .bill-summary-panel wrapper must be removed'
    )
