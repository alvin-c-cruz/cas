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


@pytest.fixture
def uom_module_enabled(db_session):
    """Enable the optional units_of_measure module for the duration of the test.

    units_of_measure is default_enabled=False (optional); tests that hit UOM endpoints
    need it enabled or the before_request hook aborts with 404.  The fixture clears the
    memoize cache on both setup and teardown so the enabled state does not bleed into
    subsequent tests that assert the default-off behaviour.
    """
    from app.settings import AppSettings
    from app.utils.cache_helpers import clear_module_config_cache
    AppSettings.set_setting('module_enabled:units_of_measure', '1')
    db.session.commit()
    clear_module_config_cache()
    yield
    clear_module_config_cache()


def test_create_unit_of_measure_persists_and_audits(client, db_session, admin_user, main_branch,
                                                    uom_module_enabled):
    _login(client, admin_user, main_branch)
    resp = client.post('/units-of-measure/create',
                       data={'code': 'pcs', 'name': 'Pieces', 'is_active': '1'},
                       follow_redirects=True)
    assert resp.status_code == 200
    u = UnitOfMeasure.query.filter_by(code='pcs').first()
    assert u is not None and u.name == 'Pieces'
    assert AuditLog.query.filter_by(module='units_of_measure', action='create').count() >= 1


def test_edit_unit_of_measure_updates(client, db_session, admin_user, main_branch,
                                      uom_module_enabled):
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


def test_list_units_of_measure_renders(client, db_session, admin_user, main_branch,
                                       uom_module_enabled):
    _login(client, admin_user, main_branch)
    resp = client.get('/units-of-measure')
    assert resp.status_code == 200
    assert b'Units of Measure' in resp.data


def test_staff_cannot_create_unit_of_measure(client, db_session, staff_user, main_branch,
                                             uom_module_enabled):
    """Staff users must be blocked from UOM endpoints (module is admin-only when enabled)."""
    import html as html_mod
    staff_user.set_branches([main_branch])
    db_session.commit()
    _login(client, staff_user, main_branch)
    resp = client.post('/units-of-measure/create',
                       data={'code': 'blk', 'name': 'Block', 'is_active': '1'},
                       follow_redirects=True)
    assert resp.status_code == 200
    # No row must have been inserted
    assert UnitOfMeasure.query.filter_by(code='blk').first() is None
    # Module-access block flash (before_request gate fires before the view)
    text = html_mod.unescape(resp.data.decode())
    assert 'do not have access to this module' in text.lower()
