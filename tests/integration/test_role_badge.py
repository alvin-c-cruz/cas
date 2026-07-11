"""The /users list must render chief_accountant as a proper humanized, colored
pill -- not the raw 'Chief_Accountant' token with an undefined badge class
(BUG-USERLIST-CA-ROLE-BADGE).
"""
import pytest

pytestmark = [pytest.mark.integration, pytest.mark.users]


def test_users_list_renders_chief_accountant_pill(client, db_session, admin_user,
                                                  chief_accountant_user, main_branch):
    client.post('/login', data={'username': 'admin', 'password': 'admin123'},
                follow_redirects=True)
    resp = client.get('/users')
    assert resp.status_code == 200
    # humanized label (not the raw |title token 'Chief_Accountant')
    assert b'Chief Accountant' in resp.data
    assert b'Chief_Accountant' not in resp.data
    # the pill has a defined colour rule (CSS selector, note the leading dot)
    assert b'.badge-role-chief_accountant' in resp.data
