# tests/integration/test_year_end_views.py
import pytest

from app import db
from tests.integration.test_year_end_close import _world

pytestmark = [pytest.mark.integration]


def login(client, username='admin', password='admin123'):
    client.post('/login', data={'username': username, 'password': password},
                follow_redirects=True)


def test_list_page_renders(client, db_session, admin_user, main_branch):
    login(client)
    resp = client.get('/year-end')
    assert resp.status_code == 200
    assert b'Year-End Close' in resp.data


def test_close_via_route_posts_and_lists(client, db_session, admin_user, main_branch):
    from app.year_end.models import FiscalYearClose
    _world(main_branch.id)
    db.session.commit()
    login(client)
    resp = client.post('/year-end/close', data={'year': '2025'}, follow_redirects=True)
    assert resp.status_code == 200
    fc = FiscalYearClose.query.filter_by(fiscal_year=2025, branch_id=main_branch.id).first()
    assert fc is not None and fc.status == 'closed'


def test_close_denied_for_staff(client, db_session, staff_user, main_branch):
    _world(main_branch.id)
    db.session.commit()
    login(client, username=staff_user.username, password='staff123')
    resp = client.post('/year-end/close', data={'year': '2025'}, follow_redirects=True)
    from app.year_end.models import FiscalYearClose
    assert FiscalYearClose.query.filter_by(fiscal_year=2025).first() is None


def test_close_and_reopen_buttons_present(client, db_session, admin_user, main_branch):
    from app.year_end import service
    from tests.integration.test_year_end_close import _world
    _world(main_branch.id)
    db.session.commit()
    login(client)
    # eligible year offered with a Close action
    resp = client.get('/year-end')
    assert b'name="year"' in resp.data
    # after closing, a Reopen control appears
    client.post('/year-end/close', data={'year': '2025'}, follow_redirects=True)
    resp2 = client.get('/year-end')
    assert b'Reopen' in resp2.data


def test_reopen_denied_for_staff(client, db_session, staff_user, admin_user, main_branch):
    from app.year_end.models import FiscalYearClose
    from app.year_end import service
    _world(main_branch.id)
    db.session.commit()
    # Close the year as admin first
    login(client, username=admin_user.username, password='admin123')
    client.post('/year-end/close', data={'year': '2025'}, follow_redirects=True)
    # Confirm it's closed
    fc = FiscalYearClose.query.filter_by(fiscal_year=2025).first()
    assert fc is not None and fc.status == 'closed'
    # Now attempt reopen as staff — should be denied
    client.get('/logout', follow_redirects=True)
    login(client, username=staff_user.username, password='staff123')
    client.post('/year-end/reopen', data={'year': '2025'}, follow_redirects=True)
    # Status should remain 'closed'
    db.session.refresh(fc)
    assert fc.status == 'closed'
