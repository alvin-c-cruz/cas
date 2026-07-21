"""Render assertions for the branch-color-theme form fields (R-11 #231)."""
import pytest

pytestmark = [pytest.mark.branches, pytest.mark.integration]


def login(client, username='admin', password='admin123'):
    client.post('/login', data={'username': username, 'password': password},
                follow_redirects=True)


def test_create_form_renders_theme_checkbox_and_color_input(client, db_session, admin_user, main_branch):
    with client:
        login(client)
        resp = client.get('/branches/create', follow_redirects=True)
        assert resp.status_code == 200
        assert b'name="use_custom_theme"' in resp.data
        assert b'name="theme_color"' in resp.data
        assert b'type="color"' in resp.data


def test_edit_form_checkbox_is_checked_when_branch_has_a_theme(client, db_session, admin_user, main_branch):
    main_branch.theme_color = '#0ea5e9'
    db_session.commit()

    with client:
        login(client)
        resp = client.get(f'/branches/{main_branch.id}/edit')
        assert resp.status_code == 200
        # WTForms renders boolean HTML attrs alphabetically -- "checked" precedes
        # "id"/"name" in the emitted tag, e.g. <input checked id="..." name="...">.
        assert b'checked id="use-custom-theme-field"' in resp.data


def test_edit_form_checkbox_is_unchecked_when_branch_has_no_theme(client, db_session, admin_user, main_branch):
    with client:
        login(client)
        resp = client.get(f'/branches/{main_branch.id}/edit')
        assert resp.status_code == 200
        assert b'id="use-custom-theme-field"' in resp.data
        assert b'checked id="use-custom-theme-field"' not in resp.data
