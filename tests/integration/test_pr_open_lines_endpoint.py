"""GET /purchase-requests/open-lines -- the picker's data source.

On the SOURCE module so the requisitions module's own before_request gate 404s
it when the module is off, exactly like /purchase-orders/billable.
"""
from datetime import date

import pytest

from app.purchase_requests.models import PurchaseRequest, PurchaseRequestItem

pytestmark = [pytest.mark.integration]


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
def pr(db_session, main_branch, admin_user):
    p = PurchaseRequest(pr_number='EP-1', request_date=date(2026, 8, 15),
                        date_needed_asap=True, branch_id=main_branch.id,
                        status='approved', created_by_id=admin_user.id)
    p.line_items.append(PurchaseRequestItem(line_number=1, description='Carbide', quantity=20))
    db_session.add(p)
    db_session.commit()
    return p


class TestTheEndpoint:

    def test_it_returns_open_lines(self, client, db_session, admin_user, main_branch, pr):
        _enable(db_session, 'purchase_requests', 'purchase_orders')
        _login(client, admin_user, main_branch)
        resp = client.get('/purchase-requests/open-lines')
        assert resp.status_code == 200
        lines = resp.get_json()['lines']
        assert len(lines) == 1
        assert lines[0]['pr_number'] == 'EP-1'
        assert lines[0]['open'] == '20'
        assert lines[0]['date_needed_asap'] is True

    def test_it_404s_when_requisitions_are_off(self, client, db_session, admin_user,
                                               main_branch, pr):
        """Control: a client without the module gets no route at all."""
        from app.settings import AppSettings
        from app.utils.cache_helpers import clear_module_config_cache
        _enable(db_session, 'purchase_orders')
        AppSettings.set_setting('module_enabled:purchase_requests', '0')
        db_session.commit(); clear_module_config_cache()
        _login(client, admin_user, main_branch)
        assert client.get('/purchase-requests/open-lines').status_code == 404

    def test_it_is_scoped_to_the_session_branch(self, client, db_session, admin_user,
                                                main_branch, branch_manila, pr):
        _enable(db_session, 'purchase_requests', 'purchase_orders')
        _login(client, admin_user, branch_manila)
        assert client.get('/purchase-requests/open-lines').get_json()['lines'] == []

    def test_exclude_po_id_is_honoured(self, client, db_session, admin_user,
                                       main_branch, pr):
        """Editing a draft PO asks for the lines as if its own were not there."""
        _enable(db_session, 'purchase_requests', 'purchase_orders')
        _login(client, admin_user, main_branch)
        resp = client.get('/purchase-requests/open-lines?exclude_po_id=999')
        assert resp.status_code == 200
        assert resp.get_json()['lines'][0]['open'] == '20'
