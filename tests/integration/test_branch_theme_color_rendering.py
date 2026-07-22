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
    assert f'linear-gradient(135deg, #0ea5e9 0%, {derived["hover"]} 100%)' in body
    # BUG-BRANCH-THEME-BADGE-BORDER-STALE: the badge's border/glow must also
    # follow the theme, not stay on the hardcoded default-blue values from the
    # always-present first <style> block (border-color: #1e40af; box-shadow:
    # rgba(59,130,246,.4)).
    assert f'border-color: #0ea5e9' in body
    assert f'box-shadow: 0 4px 12px {derived["badge_shadow"]}' in body


def test_unthemed_branch_renders_no_override_style_block(client, db_session, admin_user, main_branch):
    assert main_branch.theme_color is None

    with client.session_transaction() as s:
        s['selected_branch_id'] = main_branch.id
    login(client)
    resp = client.get('/branches')
    assert resp.status_code == 200
    assert b'--sidebar-bg:' not in resp.data


def test_malformed_theme_color_renders_gracefully(client, db_session, admin_user, main_branch):
    """A theme_color written out-of-band (bypassing BranchForm's regex-validated
    ColorField -- e.g. a legacy import or direct client-DB manipulation) that is
    not a well-formed '#RRGGBB' string must not 500 the whole page. base.html
    renders on every authenticated page, so derive_sidebar_theme_filter must
    degrade gracefully (render nothing) rather than let ValueError propagate."""
    main_branch.theme_color = 'not-a-color'
    db_session.commit()

    with client.session_transaction() as s:
        s['selected_branch_id'] = main_branch.id
    login(client)
    resp = client.get('/branches')
    assert resp.status_code == 200
    assert b'--sidebar-bg:' not in resp.data
