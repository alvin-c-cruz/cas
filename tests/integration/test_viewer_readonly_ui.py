import pytest
pytestmark = [pytest.mark.users, pytest.mark.integration]


"""Viewer read-only UI gating (B-010).

Server-side write routes were always gated, but write CTAs still rendered for
viewers: the topbar "+ New" quick-create menu and the Enter/Create buttons on
the transaction list pages. Viewers must see no write buttons at all.
"""


def login(client, username, password):
    client.post('/login', data={'username': username, 'password': password},
                follow_redirects=True)


class TestViewerReadOnlyUI:
    def test_viewer_sees_no_write_ctas_on_transaction_lists(self, client, db_session,
                                                            viewer_user, main_branch):
        viewer_user.add_branch(main_branch)
        db_session.commit()
        login(client, 'viewer', 'viewer123')

        checks = {
            '/purchase-bills': ['Enter APV', 'Enter First APV'],
            '/sales-invoices': ['Enter Invoice', 'Enter First Invoice'],
            '/receipts': ['Enter Receipt', 'Enter Payment'],
            '/journal-entries': ['Enter Journal Entry', 'Enter First Entry'],
        }
        for url, labels in checks.items():
            resp = client.get(url, follow_redirects=True)
            html = resp.data.decode('utf-8')
            for label in labels:
                assert label not in html, f'viewer sees "{label}" on {url}'
            assert 'id="topbarNewBtn"' not in html, f'viewer sees + New menu on {url}'

    def test_accountant_still_sees_write_ctas(self, client, db_session,
                                              accountant_user, main_branch):
        accountant_user.add_branch(main_branch)
        db_session.commit()
        login(client, 'accountant', 'accountant123')

        resp = client.get('/purchase-bills', follow_redirects=True)
        html = resp.data.decode('utf-8')
        assert 'Enter APV' in html or 'Enter First APV' in html
        assert 'id="topbarNewBtn"' in html
