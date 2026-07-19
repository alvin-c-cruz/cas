"""WorkCenter CRUD + module gating tests (R-07 D1)."""
import pytest
from app.settings import AppSettings
from app.utils.cache_helpers import clear_module_config_cache

pytestmark = [pytest.mark.integration]


def _login(client, user, branch):
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user.id); sess['_fresh'] = True
        sess['selected_branch_id'] = branch.id


def _enable(db_session):
    AppSettings.set_setting('module_enabled:work_centers', '1')
    db_session.commit(); clear_module_config_cache()


def test_routes_404_when_module_off(client, admin_user, db_session, main_branch):
    clear_module_config_cache()
    _login(client, admin_user, main_branch)
    resp = client.get('/work-centers')
    assert resp.status_code == 404


def test_every_endpoint_404_when_module_off(client, accountant_user, db_session, main_branch):
    from app import db
    from app.work_centers.models import WorkCenter
    # Module is deliberately left OFF (not enabled) for this whole test.
    clear_module_config_cache()
    wc = WorkCenter(branch_id=main_branch.id, code='WC-OFF', name='Off Line')
    db.session.add(wc); db.session.commit()
    _login(client, accountant_user, main_branch)
    assert client.get('/work-centers').status_code == 404
    assert client.get('/work-centers/create').status_code == 404
    assert client.post('/work-centers/create', data={}).status_code == 404
    assert client.get(f'/work-centers/{wc.id}/edit').status_code == 404
    assert client.post(f'/work-centers/{wc.id}/edit', data={}).status_code == 404


def test_create_work_center(client, accountant_user, db_session, main_branch):
    _enable(db_session)
    _login(client, accountant_user, main_branch)
    resp = client.post('/work-centers/create', data={
        'code': 'WC-CREATE', 'name': 'Assembly Line', 'hourly_rate': '120.00',
        'is_active': '1',
    }, follow_redirects=True)
    assert resp.status_code == 200
    from app.work_centers.models import WorkCenter
    wc = WorkCenter.query.filter_by(code='WC-CREATE').one()
    assert wc.branch_id == main_branch.id
    assert wc.hourly_rate == 120


def test_list_scoped_to_current_branch(client, admin_user, db_session, main_branch, branch_manila):
    # admin_user (has_full_access) so the session branch switch isn't reset by the
    # before_request branch-validation guard -- an accountant with only main_branch
    # assigned would have selected_branch_id silently reverted back to it.
    _enable(db_session)
    _login(client, admin_user, main_branch)
    client.post('/work-centers/create', data={
        'code': 'WC-MAIN', 'name': 'Main Line', 'hourly_rate': '100.00', 'is_active': '1',
    }, follow_redirects=True)
    with client.session_transaction() as sess:
        sess['selected_branch_id'] = branch_manila.id
    resp = client.get('/work-centers')
    assert b'WC-MAIN' not in resp.data
