"""Integration tests for render-time sidebar recoloring (R-11 #231).
Follows tests/integration/test_branch_switcher.py's pattern: set
session['selected_branch_id'] directly and GET /branches (a minimal,
always-admin-accessible page) rather than exercising /dashboard's much
heavier data setup -- this task only cares about base.html's <head>."""
import pytest

pytestmark = [pytest.mark.branches, pytest.mark.integration]


def login(client, username='admin', password='admin123'):
    client.post('/login', data={'username': username, 'password': password},
                follow_redirects=True)


def test_themed_branch_renders_derived_style_block(client, db_session, admin_user, main_branch):
    main_branch.theme_color = '#0ea5e9'
    db_session.commit()

    with client.session_transaction() as s:
        s['selected_branch_id'] = main_branch.id
    login(client)
    resp = client.get('/branches')
    assert resp.status_code == 200

    from app.utils.color import derive_sidebar_theme
    derived = derive_sidebar_theme('#0ea5e9')
    body = resp.data.decode('utf-8')
    assert f'--sidebar-bg: {derived["bg"]}' in body
    assert f'--sidebar-active-border: {derived["active_border"]}' in body


def test_unthemed_branch_renders_no_override_style_block(client, db_session, admin_user, main_branch):
    assert main_branch.theme_color is None

    with client.session_transaction() as s:
        s['selected_branch_id'] = main_branch.id
    login(client)
    resp = client.get('/branches')
    assert resp.status_code == 200
    assert b'--sidebar-bg:' not in resp.data
