"""BUG-MODULE-TOGGLE-FULL-PAGE-RELOAD: the Packages tab's Enable/Disable button did a plain
form POST -- full page reload, scroll reset to top. Fix: the same
company_settings.modules_toggle view now also serves a JSON contract when called with an
X-Requested-With: XMLHttpRequest header, so the front end can flip the row in place. The
existing redirect+flash behavior for a plain (non-AJAX) POST is unchanged -- asserted by the
pre-existing tests in tests/bank_accounts/test_autoseed.py.
"""
from app.settings import AppSettings
from app.utils.cache_helpers import clear_module_config_cache


def _ajax_post(client, key, enable):
    return client.post(
        '/settings/modules/toggle',
        data={'key': key, 'enable': '1' if enable else '0'},
        headers={'X-Requested-With': 'XMLHttpRequest'},
    )


def test_ajax_toggle_on_returns_json_no_redirect(client, db_session, admin_user, main_branch, login_user):
    try:
        login_user(client, 'admin', 'admin123')
        resp = _ajax_post(client, 'units_of_measure', True)

        assert resp.status_code == 200
        assert resp.content_type.startswith('application/json')
        body = resp.get_json()
        assert body['ok'] is True
        assert body['key'] == 'units_of_measure'
        assert body['enabled'] is True
        assert AppSettings.get_setting('module_enabled:units_of_measure') == '1'
    finally:
        clear_module_config_cache()


def test_ajax_toggle_off_returns_json_disabled_false(client, db_session, admin_user, main_branch, login_user):
    try:
        login_user(client, 'admin', 'admin123')
        _ajax_post(client, 'units_of_measure', True)
        resp = _ajax_post(client, 'units_of_measure', False)

        assert resp.status_code == 200
        body = resp.get_json()
        assert body['ok'] is True
        assert body['enabled'] is False
        assert AppSettings.get_setting('module_enabled:units_of_measure') == '0'
    finally:
        clear_module_config_cache()


def test_ajax_toggle_rejects_missing_dependency_without_redirect(client, db_session, admin_user, main_branch, login_user):
    """products depends_on=['units_of_measure'] -- enabling products first must fail closed,
    the same validation the existing plain-POST path already enforces via can_toggle()."""
    try:
        login_user(client, 'admin', 'admin123')
        resp = _ajax_post(client, 'products', True)

        assert resp.status_code == 200
        body = resp.get_json()
        assert body['ok'] is False
        assert 'units_of_measure' in body['reason']
        assert AppSettings.get_setting('module_enabled:products', '0') != '1'
    finally:
        clear_module_config_cache()


def test_plain_post_still_redirects_unchanged(client, db_session, admin_user, main_branch, login_user):
    """Non-AJAX callers (or JS-disabled) keep the original redirect+flash contract."""
    try:
        login_user(client, 'admin', 'admin123')
        resp = client.post('/settings/modules/toggle',
                            data={'key': 'units_of_measure', 'enable': '1'})

        assert resp.status_code == 302
        assert resp.headers['Location'].endswith('/settings')
    finally:
        clear_module_config_cache()
