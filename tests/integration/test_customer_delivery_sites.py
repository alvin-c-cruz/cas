"""Integration tests for the Customer Delivery Sites tab (Task 4).

Covers: the "Delivery Sites" tab on the customer detail page, add/edit/
deactivate/reactivate via the nested routes, audit logging for each write,
a read-only view for non-privileged roles, and the AJAX create branch that
Task 5's Sales Order quick-add modal will reuse.
"""
import pytest

from app.customers.models import Customer, CustomerDeliverySite
from app.audit.models import AuditLog


def _customer(db_session, code='C001', name='Acme Trading'):
    c = Customer(code=code, name=name, payment_terms='Net 30', is_active=True)
    db_session.add(c)
    db_session.commit()
    return c


def _login_accountant(client, accountant_user, main_branch):
    with client.session_transaction() as sess:
        sess['selected_branch_id'] = main_branch.id
    client.post('/login', data={'username': accountant_user.username,
                                'password': 'accountant123'}, follow_redirects=True)


def _login_admin(client, admin_user, main_branch):
    with client.session_transaction() as sess:
        sess['selected_branch_id'] = main_branch.id
    client.post('/login', data={'username': admin_user.username,
                                'password': 'admin123'}, follow_redirects=True)


def _login_viewer(client, viewer_user, main_branch, db_session):
    viewer_user.add_branch(main_branch)
    db_session.commit()
    with client.session_transaction() as sess:
        sess['selected_branch_id'] = main_branch.id
    client.post('/login', data={'username': viewer_user.username,
                                'password': 'viewer123'}, follow_redirects=True)


def _login_staff(client, staff_user, main_branch, db_session):
    staff_user.set_branches([main_branch])
    db_session.commit()
    with client.session_transaction() as sess:
        sess['selected_branch_id'] = main_branch.id
    client.post('/login', data={'username': staff_user.username,
                                'password': 'staff123'}, follow_redirects=True)


@pytest.mark.integration
def test_delivery_sites_tab_renders_empty_state(client, db_session, accountant_user, main_branch):
    c = _customer(db_session)
    _login_accountant(client, accountant_user, main_branch)

    resp = client.get(f'/customers/{c.id}?tab=delivery_sites')

    assert resp.status_code == 200
    body = resp.data.decode()
    assert 'Delivery Sites' in body
    assert 'No delivery sites found.' in body
    assert '+ Add Delivery Site' in body


@pytest.mark.integration
def test_accountant_can_add_delivery_site(client, db_session, accountant_user, main_branch):
    c = _customer(db_session)
    _login_accountant(client, accountant_user, main_branch)

    resp = client.post(f'/customers/{c.id}/delivery-sites/create',
                       data={'name': 'MY SAN CAINTA'}, follow_redirects=True)

    assert resp.status_code == 200
    site = CustomerDeliverySite.query.filter_by(customer_id=c.id).first()
    assert site is not None
    assert site.name == 'MY SAN CAINTA'
    assert site.is_active is True
    body = resp.data.decode()
    assert 'MY SAN CAINTA' in body

    log = AuditLog.query.filter_by(module='customer_delivery_site', action='create').first()
    assert log is not None
    assert log.record_id == site.id
    assert 'MY SAN CAINTA' in log.record_identifier


@pytest.mark.integration
def test_add_delivery_site_requires_name(client, db_session, accountant_user, main_branch):
    c = _customer(db_session)
    _login_accountant(client, accountant_user, main_branch)

    resp = client.post(f'/customers/{c.id}/delivery-sites/create',
                       data={'name': ''}, follow_redirects=True)

    assert resp.status_code == 200
    assert CustomerDeliverySite.query.filter_by(customer_id=c.id).count() == 0


@pytest.mark.integration
def test_delivery_sites_tab_lists_sites_ordered_by_name(client, db_session, accountant_user, main_branch):
    c = _customer(db_session)
    db_session.add_all([
        CustomerDeliverySite(customer_id=c.id, name='MY SAN STA. ROSA', is_active=False),
        CustomerDeliverySite(customer_id=c.id, name='MY SAN CAINTA', is_active=True),
        CustomerDeliverySite(customer_id=c.id, name='MY SAN CALAMBA', is_active=True),
    ])
    db_session.commit()
    _login_accountant(client, accountant_user, main_branch)

    resp = client.get(f'/customers/{c.id}?tab=delivery_sites')

    body = resp.data.decode()
    assert resp.status_code == 200
    idx_cainta = body.index('MY SAN CAINTA')
    idx_calamba = body.index('MY SAN CALAMBA')
    idx_starosa = body.index('MY SAN STA. ROSA')
    assert idx_cainta < idx_calamba < idx_starosa
    assert 'Reactivate' in body  # the inactive site shows Reactivate, not Deactivate


@pytest.mark.integration
def test_accountant_can_edit_delivery_site(client, db_session, accountant_user, main_branch):
    c = _customer(db_session)
    site = CustomerDeliverySite(customer_id=c.id, name='MY SAN CAINTA', is_active=True)
    db_session.add(site)
    db_session.commit()
    _login_accountant(client, accountant_user, main_branch)

    resp = client.post(f'/customers/{c.id}/delivery-sites/{site.id}/edit',
                       data={'name': 'MY SAN CAINTA (RENAMED)'}, follow_redirects=True)

    assert resp.status_code == 200
    db_session.refresh(site)
    assert site.name == 'MY SAN CAINTA (RENAMED)'

    log = AuditLog.query.filter_by(module='customer_delivery_site', action='update').first()
    assert log is not None
    assert log.record_id == site.id


@pytest.mark.integration
def test_accountant_can_deactivate_and_reactivate_delivery_site(
        client, db_session, accountant_user, main_branch):
    c = _customer(db_session)
    site = CustomerDeliverySite(customer_id=c.id, name='MY SAN CAINTA', is_active=True)
    db_session.add(site)
    db_session.commit()
    _login_accountant(client, accountant_user, main_branch)

    resp = client.post(f'/customers/{c.id}/delivery-sites/{site.id}/toggle-active',
                       follow_redirects=True)
    assert resp.status_code == 200
    db_session.refresh(site)
    assert site.is_active is False

    resp2 = client.post(f'/customers/{c.id}/delivery-sites/{site.id}/toggle-active',
                        follow_redirects=True)
    assert resp2.status_code == 200
    db_session.refresh(site)
    assert site.is_active is True

    logs = AuditLog.query.filter_by(module='customer_delivery_site', action='update').all()
    assert len(logs) == 2


@pytest.mark.integration
def test_admin_can_manage_delivery_sites(client, db_session, admin_user, main_branch):
    """Admin (full_access) is allowed too, not just accountant."""
    c = _customer(db_session)
    _login_admin(client, admin_user, main_branch)

    resp = client.post(f'/customers/{c.id}/delivery-sites/create',
                       data={'name': 'MY SAN CAINTA'}, follow_redirects=True)

    assert resp.status_code == 200
    assert CustomerDeliverySite.query.filter_by(customer_id=c.id).count() == 1


@pytest.mark.integration
def test_viewer_cannot_create_delivery_site(client, db_session, viewer_user, main_branch):
    c = _customer(db_session)
    _login_viewer(client, viewer_user, main_branch, db_session)

    resp = client.post(f'/customers/{c.id}/delivery-sites/create',
                       data={'name': 'SHOULD NOT EXIST'}, follow_redirects=False)

    assert resp.status_code == 302
    assert '/dashboard' in resp.headers.get('Location', '')
    assert CustomerDeliverySite.query.filter_by(customer_id=c.id).count() == 0


@pytest.mark.integration
def test_staff_cannot_create_delivery_site(client, db_session, staff_user, main_branch):
    """Staff can view/manage customers via staff_or_above_required elsewhere, but
    delivery-site writes mirror customers.edit's accountant-or-admin gate."""
    c = _customer(db_session)
    _login_staff(client, staff_user, main_branch, db_session)

    resp = client.post(f'/customers/{c.id}/delivery-sites/create',
                       data={'name': 'SHOULD NOT EXIST'}, follow_redirects=False)

    assert resp.status_code == 302
    assert '/dashboard' in resp.headers.get('Location', '')
    assert CustomerDeliverySite.query.filter_by(customer_id=c.id).count() == 0


@pytest.mark.integration
def test_viewer_sees_read_only_delivery_sites_tab(client, db_session, viewer_user, main_branch):
    c = _customer(db_session)
    site = CustomerDeliverySite(customer_id=c.id, name='MY SAN CAINTA', is_active=True)
    db_session.add(site)
    db_session.commit()
    _login_viewer(client, viewer_user, main_branch, db_session)

    resp = client.get(f'/customers/{c.id}?tab=delivery_sites')

    assert resp.status_code == 200
    body = resp.data.decode()
    assert 'MY SAN CAINTA' in body
    assert '+ Add Delivery Site' not in body
    assert 'ds-edit-btn' not in body
    assert 'Deactivate' not in body
    assert 'Reactivate' not in body


@pytest.mark.integration
def test_viewer_cannot_toggle_delivery_site(client, db_session, viewer_user, main_branch):
    c = _customer(db_session)
    site = CustomerDeliverySite(customer_id=c.id, name='MY SAN CAINTA', is_active=True)
    db_session.add(site)
    db_session.commit()
    _login_viewer(client, viewer_user, main_branch, db_session)

    resp = client.post(f'/customers/{c.id}/delivery-sites/{site.id}/toggle-active',
                       follow_redirects=False)

    assert resp.status_code == 302
    db_session.refresh(site)
    assert site.is_active is True


@pytest.mark.integration
def test_create_delivery_site_ajax_branch_returns_json(client, db_session, accountant_user, main_branch):
    """The create route's AJAX branch (X-Requested-With) is Task 5's quick-add
    contract -- returns {ok, site} on success."""
    c = _customer(db_session)
    _login_accountant(client, accountant_user, main_branch)

    resp = client.post(f'/customers/{c.id}/delivery-sites/create',
                       data={'name': 'MY SAN CAINTA'},
                       headers={'X-Requested-With': 'XMLHttpRequest'})

    assert resp.status_code == 200
    payload = resp.get_json()
    assert payload['ok'] is True
    assert payload['site']['name'] == 'MY SAN CAINTA'
    assert payload['site']['customer_id'] == c.id
    assert payload['site']['is_active'] is True
    assert 'id' in payload['site']


@pytest.mark.integration
def test_create_delivery_site_ajax_branch_returns_errors_on_blank_name(
        client, db_session, accountant_user, main_branch):
    c = _customer(db_session)
    _login_accountant(client, accountant_user, main_branch)

    resp = client.post(f'/customers/{c.id}/delivery-sites/create',
                       data={'name': ''},
                       headers={'X-Requested-With': 'XMLHttpRequest'})

    assert resp.status_code != 200 or resp.get_json().get('ok') is False
    payload = resp.get_json()
    assert payload['ok'] is False
    assert 'name' in payload['errors']


@pytest.mark.integration
def test_delivery_site_not_belonging_to_customer_404s(client, db_session, accountant_user, main_branch):
    c1 = _customer(db_session, code='C001', name='Acme Trading')
    c2 = _customer(db_session, code='C002', name='Other Corp')
    site = CustomerDeliverySite(customer_id=c2.id, name='MY SAN CAINTA', is_active=True)
    db_session.add(site)
    db_session.commit()
    _login_accountant(client, accountant_user, main_branch)

    resp = client.post(f'/customers/{c1.id}/delivery-sites/{site.id}/edit',
                       data={'name': 'HIJACKED'}, follow_redirects=False)

    assert resp.status_code == 404
