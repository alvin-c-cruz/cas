import calendar
import pytest
from app.utils import ph_now

pytestmark = [pytest.mark.integration]


def login(client, username, password):
    client.post('/login', data={'username': username, 'password': password},
                follow_redirects=True)


def expected_eom():
    """End of the current PH month, as the view computes it."""
    n = ph_now().date()
    return n.replace(day=calendar.monthrange(n.year, n.month)[1])


@pytest.fixture
def logged_in_admin(client, db_session, admin_user, main_branch):
    admin_user.add_branch(main_branch)
    db_session.commit()
    login(client, 'admin', 'admin123')
    return client


class TestDashboardAsOfDefault:
    def test_default_is_end_of_current_month(self, logged_in_admin):
        resp = logged_in_admin.get('/dashboard')
        assert resp.status_code == 200
        eom = expected_eom().strftime('%Y-%m-%d')
        assert f'value="{eom}"'.encode() in resp.data

    def test_invalid_as_of_date_falls_back_to_eom(self, logged_in_admin):
        resp = logged_in_admin.get('/dashboard?as_of_date=not-a-date')
        assert resp.status_code == 200
        eom = expected_eom().strftime('%Y-%m-%d')
        assert f'value="{eom}"'.encode() in resp.data

    def test_explicit_valid_as_of_date_is_honored(self, logged_in_admin):
        resp = logged_in_admin.get('/dashboard?as_of_date=2026-03-15')
        assert resp.status_code == 200
        assert b'value="2026-03-15"' in resp.data

    def test_reset_button_is_month_end_not_today(self, logged_in_admin):
        resp = logged_in_admin.get('/dashboard')
        assert resp.status_code == 200
        body = resp.data.decode('utf-8')
        # Button label changed
        assert 'Month End' in body
        assert '📅 Today' not in body
        # Button resets to the EOM value
        eom = expected_eom().strftime('%Y-%m-%d')
        assert f".value='{eom}'" in body
