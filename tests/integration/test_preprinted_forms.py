"""Integration tests for the pre-printed voucher forms designer backend (P-69 Task 4).

Covers the blueprint's permission decorators (_module_required, _edit_required,
_admin_required) and the save/toggle routes.
"""
import json
import pytest
from app import db
from app.settings import AppSettings
from app.utils.cache_helpers import clear_module_config_cache
from app.audit.models import AuditLog
from app.preprinted_forms.models import PrintLayout

pytestmark = [pytest.mark.integration]


def _login(client, user):
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user.id)
        sess['_fresh'] = True


def _select_branch(client, branch_id):
    with client.session_transaction() as sess:
        sess['selected_branch_id'] = branch_id


@pytest.fixture
def preprinted_module_enabled(db_session):
    """Enable the (as-yet-unregistered) preprinted_forms module flag.

    The module_access registry entry for 'preprinted_forms' doesn't exist until
    Task 6, so module_enabled() currently treats it as an unknown/core key and
    always returns True — this setting is a no-op today but is set anyway so the
    test intent (module enabled) is explicit and the test keeps working once the
    Task 6 registry entry lands.
    """
    AppSettings.set_setting('module_enabled:preprinted_forms', '1')
    db.session.commit()
    clear_module_config_cache()
    yield
    clear_module_config_cache()


def test_accountant_can_save_layout(client, db_session, accountant_user, main_branch,
                                     preprinted_module_enabled):
    _login(client, accountant_user)
    _select_branch(client, main_branch.id)
    fields = json.dumps([{'key': 'number', 'x': 10, 'y': 20}])
    line_band = json.dumps({'y_start': 100, 'row_height': 12})
    resp = client.post('/preprinted-forms/JV/save',
                        data={'fields_json': fields, 'line_band_json': line_band},
                        follow_redirects=True)
    assert resp.status_code == 200
    layout = PrintLayout.query.filter_by(voucher_type='JV').first()
    assert layout is not None
    assert layout.get_fields() == [{'key': 'number', 'x': 10, 'y': 20}]
    assert layout.get_line_band() == {'y_start': 100, 'row_height': 12}
    assert AuditLog.query.filter_by(module='preprinted_forms', action='update').count() >= 1


def test_ungranted_staff_cannot_save_layout(client, db_session, staff_user, main_branch,
                                             preprinted_module_enabled):
    staff_user.set_branches([main_branch])
    db.session.commit()
    _login(client, staff_user)
    _select_branch(client, main_branch.id)
    resp = client.post('/preprinted-forms/JV/save',
                        data={'fields_json': '[]', 'line_band_json': '{}'},
                        follow_redirects=True)
    assert resp.status_code == 200
    assert PrintLayout.query.filter_by(voucher_type='JV').first() is None


def test_granted_staff_can_save_layout(client, db_session, staff_user, main_branch,
                                        preprinted_module_enabled):
    """Positive staff-delegation: a staff user explicitly granted print_layouts can save."""
    staff_user.set_branches([main_branch])
    perms = staff_user.get_book_permissions()
    perms['print_layouts'] = True
    staff_user.set_book_permissions(perms)
    db.session.commit()
    _login(client, staff_user)
    _select_branch(client, main_branch.id)
    resp = client.post('/preprinted-forms/JV/save',
                        data={'fields_json': '[]', 'line_band_json': '{}'},
                        follow_redirects=True)
    assert resp.status_code == 200
    assert PrintLayout.query.filter_by(voucher_type='JV').first() is not None


def test_viewer_cannot_save_layout(client, db_session, viewer_user, main_branch,
                                    preprinted_module_enabled):
    viewer_user.set_branches([main_branch])
    db.session.commit()
    _login(client, viewer_user)
    _select_branch(client, main_branch.id)
    resp = client.post('/preprinted-forms/JV/save',
                        data={'fields_json': '[]', 'line_band_json': '{}'},
                        follow_redirects=True)
    assert resp.status_code == 200
    assert PrintLayout.query.filter_by(voucher_type='JV').first() is None
    assert b'You do not have permission to design pre-printed forms.' in resp.data


def test_admin_can_toggle_layout(client, db_session, admin_user, main_branch,
                                  preprinted_module_enabled):
    _login(client, admin_user)
    _select_branch(client, main_branch.id)
    resp = client.post('/preprinted-forms/JV/toggle', follow_redirects=True)
    assert resp.status_code == 200
    layout = PrintLayout.query.filter_by(voucher_type='JV').first()
    assert layout is not None
    assert layout.active is True


def test_non_admin_cannot_toggle_layout(client, db_session, accountant_user, main_branch,
                                         preprinted_module_enabled):
    _login(client, accountant_user)
    _select_branch(client, main_branch.id)
    resp = client.post('/preprinted-forms/JV/toggle', follow_redirects=True)
    assert resp.status_code == 200
    layout = PrintLayout.query.filter_by(voucher_type='JV').first()
    assert layout is None  # never created; toggle refused before get-or-create


def test_chief_accountant_can_save_layout(client, db_session, chief_accountant_user,
                                           main_branch, preprinted_module_enabled):
    """Chief Accountant has full access and can save layouts."""
    _login(client, chief_accountant_user)
    _select_branch(client, main_branch.id)
    fields = json.dumps([{'key': 'invoice_number', 'x': 15, 'y': 25}])
    line_band = json.dumps({'y_start': 110, 'row_height': 14})
    resp = client.post('/preprinted-forms/JV/save',
                        data={'fields_json': fields, 'line_band_json': line_band},
                        follow_redirects=True)
    assert resp.status_code == 200
    layout = PrintLayout.query.filter_by(voucher_type='JV').first()
    assert layout is not None
    assert layout.get_fields() == [{'key': 'invoice_number', 'x': 15, 'y': 25}]
    assert layout.get_line_band() == {'y_start': 110, 'row_height': 14}


def test_chief_accountant_cannot_toggle(client, db_session, chief_accountant_user,
                                         main_branch, preprinted_module_enabled):
    """Chief Accountant cannot toggle (admin-only)."""
    _login(client, chief_accountant_user)
    _select_branch(client, main_branch.id)
    resp = client.post('/preprinted-forms/JV/toggle', follow_redirects=True)
    assert resp.status_code == 200
    assert b'Only administrators can enable pre-printed forms.' in resp.data
    layout = PrintLayout.query.filter_by(voucher_type='JV').first()
    assert layout is None  # never created; toggle refused before get-or-create


@pytest.mark.skip(reason='TODO(P-69 Task 6): module_enabled() returns True for any key not yet '
                         'in MODULE_REGISTRY (core/unknown -> True, override ignored) — see '
                         'app/users/module_access.py::module_enabled. The preprinted_forms '
                         'registry entry ships in Task 6; until then this disabled-module case '
                         'cannot be exercised through the real registry lookup without faking it.')
def test_designer_and_save_denied_when_module_disabled(client, db_session, accountant_user,
                                                        main_branch):
    AppSettings.set_setting('module_enabled:preprinted_forms', '0')
    db.session.commit()
    clear_module_config_cache()
    try:
        _login(client, accountant_user)
        _select_branch(client, main_branch.id)
        resp = client.get('/preprinted-forms/JV/design', follow_redirects=True)
        assert b'not enabled' in resp.data.lower()
        resp = client.post('/preprinted-forms/JV/save',
                            data={'fields_json': '[]', 'line_band_json': '{}'},
                            follow_redirects=True)
        assert PrintLayout.query.filter_by(voucher_type='JV').first() is None
    finally:
        clear_module_config_cache()
