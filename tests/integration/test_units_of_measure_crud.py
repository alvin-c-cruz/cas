"""Integration tests for Units of Measure CRUD blueprint (Task 3)."""
import pytest
from app import db
from app.units_of_measure.models import UnitOfMeasure
from app.audit.models import AuditLog

pytestmark = [pytest.mark.integration]


def _login(client, user, branch):
    """Log a user in and set a branch in the session (mirrors other integration tests)."""
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user.id)
        sess['_fresh'] = True
        sess['selected_branch_id'] = branch.id


def test_create_unit_of_measure_persists_and_audits(client, db_session, admin_user, main_branch):
    _login(client, admin_user, main_branch)
    resp = client.post('/units-of-measure/create',
                       data={'code': 'pcs', 'name': 'Pieces', 'is_active': '1'},
                       follow_redirects=True)
    assert resp.status_code == 200
    u = UnitOfMeasure.query.filter_by(code='pcs').first()
    assert u is not None and u.name == 'Pieces'
    assert AuditLog.query.filter_by(module='units_of_measure', action='create').count() >= 1


def test_edit_unit_of_measure_updates(client, db_session, admin_user, main_branch):
    u = UnitOfMeasure(code='kg', name='Kilogram', is_active=True)
    db.session.add(u)
    db.session.commit()
    _login(client, admin_user, main_branch)
    resp = client.post(f'/units-of-measure/{u.id}/edit',
                       data={'code': 'kg', 'name': 'Kilo', 'is_active': '0'},
                       follow_redirects=True)
    assert resp.status_code == 200
    refreshed = db.session.get(UnitOfMeasure, u.id)
    assert refreshed.name == 'Kilo' and refreshed.is_active is False
    assert AuditLog.query.filter_by(module='units_of_measure', action='update').count() >= 1


def test_list_units_of_measure_renders(client, db_session, admin_user, main_branch):
    _login(client, admin_user, main_branch)
    resp = client.get('/units-of-measure')
    assert resp.status_code == 200
    assert b'Unit' in resp.data
