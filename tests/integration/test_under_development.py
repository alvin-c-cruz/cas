"""Under Development page renders for authenticated users (sidebar nav)."""


def login(client, username='admin', password='admin123'):
    client.post('/login', data={'username': username, 'password': password},
                follow_redirects=True)


class TestUnderDevelopmentPage:
    def test_redirects_unauthenticated_to_login(self, client, db_session, admin_user):
        resp = client.get('/under-development', follow_redirects=False)
        assert resp.status_code == 302
        assert '/login' in resp.headers['Location']

    def test_renders_for_authenticated_user(self, client, db_session, admin_user, main_branch):
        admin_user.add_branch(main_branch)
        db_session.commit()
        login(client)
        resp = client.get('/under-development')
        assert resp.status_code == 200
        assert b'Under Development' in resp.data

    def test_feature_name_shown_when_provided(self, client, db_session, admin_user, main_branch):
        admin_user.add_branch(main_branch)
        db_session.commit()
        login(client)
        resp = client.get('/under-development?feature=Cash+Flow')
        assert resp.status_code == 200
        assert b'Cash Flow' in resp.data

    def test_generic_message_when_no_feature(self, client, db_session, admin_user, main_branch):
        admin_user.add_branch(main_branch)
        db_session.commit()
        login(client)
        resp = client.get('/under-development')
        assert resp.status_code == 200
        # Generic fallback heading rendered as title-case "This Feature"
        assert b'This Feature' in resp.data


class TestDeadLinksWired:
    def test_general_ledger_link_points_to_real_route(self, client, db_session, admin_user, main_branch):
        # General Ledger is now a real page, not an under-development stub.
        admin_user.add_branch(main_branch)
        db_session.commit()
        login(client)
        resp = client.get('/under-development')
        html = resp.data.decode()
        # The GL link in the sidebar should now point at /reports/general-ledger, not under-development.
        assert '/reports/general-ledger' in html
        assert 'feature=General+Ledger' not in html
        assert 'feature=General%20Ledger' not in html

    def test_cash_flow_not_hash(self, client, db_session, admin_user, main_branch):
        admin_user.add_branch(main_branch)
        db_session.commit()
        login(client)
        resp = client.get('/under-development')
        html = resp.data.decode()
        cash_flow_idx = html.find('Cash Flow')
        snippet = html[max(0, cash_flow_idx - 100):cash_flow_idx]
        assert 'href="#"' not in snippet
