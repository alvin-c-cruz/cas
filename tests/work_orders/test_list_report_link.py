"""Work Orders list -> Costing & Variance Report link (R-07 D5 Task 6).

Both pre-existing /work-orders GET tests (test_crud_gating.py) run with the
module deliberately OFF and assert 404, so the suite never actually RENDERS
work_orders/list.html. A bad url_for() endpoint name in that template raises
BuildError -> 500 on the real page while both of those tests stay green, and
this link is the ONLY navigation into the D5 report -- if it breaks, the report
is reachable only by typing its URL. So the render is pinned here.
"""
import pytest

from app.settings import AppSettings
from app.utils.cache_helpers import clear_module_config_cache

pytestmark = [pytest.mark.integration, pytest.mark.work_orders]


def _login(client, user, branch_id):
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user.id)
        sess['_fresh'] = True
        sess['selected_branch_id'] = branch_id


def _enable(db_session):
    AppSettings.set_setting('module_enabled:work_orders', '1')
    AppSettings.set_setting('module_enabled:bill_of_materials', '1')
    db_session.commit(); clear_module_config_cache()


def test_list_renders_and_links_to_the_costing_variance_report(
        client, db_session, main_branch, accountant_user):
    _enable(db_session)
    _login(client, accountant_user, main_branch.id)

    resp = client.get('/work-orders')
    assert resp.status_code == 200, 'list template failed to render (BuildError?)'

    body = resp.data.decode('utf-8')
    assert '/reports/work-order-costing-variance' in body, (
        'Work Orders list is missing its link to the D5 Costing & Variance report')
    assert 'Costing &amp; Variance Report' in body
