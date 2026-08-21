"""The PO form's summary shows Total Amount only (owner directive, 2026-08-21).

Gross Amount and Less: Input VAT were removed from the panel. The TOTAL still
depends on the VAT arithmetic -- an `exclusive` order is gross + VAT -- so only
the display rows go; recalcTotals() keeps computing VAT to produce the total.

Render assertions on the real form. Asserting on the JS source alone would not
prove what the page shows.
"""
from datetime import date

import pytest

from app import db
from app.settings import AppSettings

pytestmark = [pytest.mark.integration, pytest.mark.purchase_orders]


@pytest.fixture(autouse=True)
def _open_gates(db_session, admin_user):
    from app.utils.cache_helpers import clear_module_config_cache
    for key in ('purchase_orders', 'purchase_requests', 'products'):
        AppSettings.set_setting('module_enabled:%s' % key, '1')
    clear_module_config_cache()
    db_session.commit()
    yield
    clear_module_config_cache()


def _login(client, admin_user, branch):
    with client.session_transaction() as sess:
        sess['selected_branch_id'] = branch.id
    client.post('/login', data={'username': admin_user.username, 'password': 'admin123'},
                follow_redirects=True)


def test_the_create_form_shows_only_the_total(client, db_session, admin_user, main_branch):
    _login(client, admin_user, main_branch)
    resp = client.get('/purchase-orders/create')

    assert resp.status_code == 200
    assert b'Total Amount' in resp.data, 'anti-vacuity: the summary panel is gone entirely'
    assert b'Gross Amount' not in resp.data
    assert b'Less: Input VAT' not in resp.data


def test_the_total_still_reflects_the_vat_treatment_branches(client, db_session,
                                                             admin_user, main_branch):
    """The rows were removed from the PANEL, not the arithmetic. If the exclusive
    branch were stripped along with the labels, an exclusive order would total
    net instead of net + VAT -- a wrong number, not a missing one."""
    _login(client, admin_user, main_branch)
    html = client.get('/purchase-orders/create').data.decode('utf-8', 'replace')

    assert 'totalDisplay' in html, 'the total display element was removed'
    assert "treatment === 'exclusive'" in html, \
        'the exclusive branch went with the labels -- the total would be wrong'
    assert 'total = gross + vatShown' in html, \
        'the exclusive total no longer adds VAT'
