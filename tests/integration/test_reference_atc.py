"""Integration tests for the Withholding Tax ATC reference page."""
import pytest

pytestmark = [pytest.mark.integration]


def login(client, username='admin', password='admin123'):
    return client.post('/login', data={'username': username, 'password': password},
                       follow_redirects=True)


class TestATCReference:
    def test_page_renders_for_admin(self, client, db_session, admin_user, main_branch):
        login(client)
        resp = client.get('/reference/withholding-atc')
        assert resp.status_code == 200
        body = resp.get_data(as_text=True)
        # Key content present
        assert 'Withholding Tax ATC Reference' in body
        assert 'WI010' in body and 'WC010' in body          # EWT individual + corporate
        assert 'WI840' in body and 'WC840' in body          # RMO 46-2025 new codes
        assert 'WI202' in body                               # FWT
        assert 'RMO 46-2025' in body
        assert 'bir.gov.ph' in body                          # sources/links present

    def test_sidebar_link_present(self, client, db_session, admin_user, main_branch):
        login(client)
        resp = client.get('/dashboard')
        assert resp.status_code == 200
        assert '/reference/withholding-atc' in resp.get_data(as_text=True)

    def test_blocked_for_staff(self, client, db_session, staff_user, main_branch):
        login(client, username='staff', password='staff123')
        resp = client.get('/reference/withholding-atc', follow_redirects=False)
        # staff is redirected away (not allowed)
        assert resp.status_code in (301, 302)
