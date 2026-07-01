"""Integration tests for the pre-printed voucher forms designer backend (P-69 Task 4)
and the designer UI + test-print route (P-69 Task 5).

Covers the blueprint's permission decorators (_module_required, _edit_required,
_admin_required) and the save/toggle/design/test-print routes.
"""
import json
from datetime import date
from io import BytesIO

import pytest
from app import db
from app.settings import AppSettings
from app.utils.cache_helpers import clear_module_config_cache
from app.audit.models import AuditLog
from app.preprinted_forms.models import PrintLayout
from app.journal_entries.models import JournalEntry, JournalEntryLine

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
    # viewer_user's conftest fixture grants default_all_permissions() (every
    # non-optional/core registry key) for unrelated tests' convenience. Now that
    # 'print_layouts' is a core key (P-69 Task 6), that blanket grant would
    # include it too — explicitly deny it here so this test actually exercises
    # an ungranted viewer, matching its name/intent.
    perms = viewer_user.get_book_permissions()
    perms['print_layouts'] = False
    viewer_user.set_book_permissions(perms)
    db.session.commit()
    _login(client, viewer_user)
    _select_branch(client, main_branch.id)
    resp = client.post('/preprinted-forms/JV/save',
                        data={'fields_json': '[]', 'line_band_json': '{}'},
                        follow_redirects=True)
    assert resp.status_code == 200
    assert PrintLayout.query.filter_by(voucher_type='JV').first() is None
    assert b'You do not have permission to design pre-printed forms.' in resp.data


def test_granted_viewer_still_cannot_edit(client, db_session, viewer_user, main_branch,
                                           preprinted_module_enabled):
    """Fix pass 2 (P-69 review): even a viewer explicitly GRANTED the
    print_layouts book permission must be denied — _edit_required now requires
    role == 'staff' (not just any role) to honor the grant, so viewers can
    never edit regardless of what's in their permission dict. Decisive test
    for Fix 1."""
    viewer_user.set_branches([main_branch])
    perms = viewer_user.get_book_permissions()
    perms['print_layouts'] = True
    viewer_user.set_book_permissions(perms)
    db.session.commit()
    _login(client, viewer_user)
    _select_branch(client, main_branch.id)

    resp = client.get('/preprinted-forms/JV/design', follow_redirects=True)
    assert resp.status_code == 200
    assert b'You do not have permission to design pre-printed forms.' in resp.data

    resp = client.post('/preprinted-forms/JV/save',
                        data={'fields_json': '[]', 'line_band_json': '{}'},
                        follow_redirects=True)
    assert resp.status_code == 200
    assert b'You do not have permission to design pre-printed forms.' in resp.data
    assert PrintLayout.query.filter_by(voucher_type='JV').first() is None


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


def test_designer_and_save_denied_when_module_disabled_by_default(client, db_session,
                                                                    accountant_user, main_branch):
    """P-69 Task 6: 'preprinted_forms' is now a real MODULE_REGISTRY entry with
    optional=True, default_enabled=False. With NO AppSettings override at all,
    module_enabled('preprinted_forms') must resolve to False (not the old
    core/unknown -> True fallback), and the designer/save routes must deny."""
    _login(client, accountant_user)
    _select_branch(client, main_branch.id)
    resp = client.get('/preprinted-forms/JV/design', follow_redirects=True)
    assert b'not enabled' in resp.data.lower()
    resp = client.post('/preprinted-forms/JV/save',
                        data={'fields_json': '[]', 'line_band_json': '{}'},
                        follow_redirects=True)
    assert PrintLayout.query.filter_by(voucher_type='JV').first() is None


def test_designer_and_save_denied_when_module_explicitly_disabled(client, db_session,
                                                                   accountant_user, main_branch):
    """An admin who explicitly set the override to '0' (e.g. after having enabled it)
    also denies — mirrors test above but through an explicit AppSettings row rather
    than relying on default_enabled."""
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


# ---------------------------------------------------------------------------
# Designer UI + test-print route (P-69 Task 5)
# ---------------------------------------------------------------------------

def test_designer_page_renders_palette_and_controls(client, db_session, accountant_user,
                                                      main_branch, preprinted_module_enabled):
    """Designer GET returns 200 and contains a catalog field label, the Save
    control, the Upload control, the Test-print control, and the versioned JS
    link (?v=1)."""
    _login(client, accountant_user)
    _select_branch(client, main_branch.id)
    resp = client.get('/preprinted-forms/JV/design')
    assert resp.status_code == 200
    body = resp.data
    # A real catalog label for JV (FIELD_CATALOG['JV']['header'])
    assert b'JV Number' in body
    # Save control
    assert b'Save' in body
    # Upload control
    assert b'Upload' in body
    # Test-print control: assert the actual test-print URL fragment, not the
    # word "Test" -- base.html's env-badge script always contains "Testing",
    # which makes a bare b'Test' in body assertion vacuously true on any page.
    assert b'/preprinted-forms/JV/test-print' in body
    # JS asset, versioned
    assert b'preprinted_designer.js?v=1' in body


def _build_je(main_branch, cash_account, revenue_account, number='JV-2026-01-0500'):
    je = JournalEntry(
        entry_number=number,
        entry_date=date(2026, 1, 20),
        description='Test-print JE',
        entry_type='adjustment',
        branch_id=main_branch.id,
        status='draft',
    )
    db.session.add(je)
    db.session.flush()
    line1 = JournalEntryLine(entry_id=je.id, line_number=1, account_id=cash_account.id,
                              debit_amount=500, credit_amount=0)
    line2 = JournalEntryLine(entry_id=je.id, line_number=2, account_id=revenue_account.id,
                              debit_amount=0, credit_amount=500)
    db.session.add_all([line1, line2])
    db.session.commit()
    return je


def test_test_print_redirects_when_no_record(client, db_session, accountant_user,
                                               main_branch, preprinted_module_enabled):
    _login(client, accountant_user)
    _select_branch(client, main_branch.id)
    resp = client.get('/preprinted-forms/JV/test-print')
    assert resp.status_code == 302
    assert '/preprinted-forms/JV/design' in resp.headers['Location']


def test_test_print_returns_pdf_when_record_exists(client, db_session, accountant_user,
                                                     main_branch, cash_account, revenue_account,
                                                     preprinted_module_enabled):
    _build_je(main_branch, cash_account, revenue_account)
    _login(client, accountant_user)
    _select_branch(client, main_branch.id)
    resp = client.get('/preprinted-forms/JV/test-print')
    assert resp.status_code == 200
    assert resp.headers['Content-Type'] == 'application/pdf'
    assert resp.data.startswith(b'%PDF')


def test_test_print_is_branch_scoped(client, db_session, accountant_user, main_branch,
                                      branch_manila, cash_account, revenue_account,
                                      preprinted_module_enabled):
    """A branch-scoped accountant hitting test-print for JV must only ever see
    the latest record from their OWN selected branch, never another branch's
    (regression for the system-wide `.order_by(id.desc()).first()` bug)."""
    # A layout with the 'particulars' field visible so the JE description
    # (the marker) actually appears in the rendered PDF text.
    layout = PrintLayout(voucher_type='JV', active=True,
                          page_width_mm=215.9, page_height_mm=279.4)
    layout.set_fields([
        {'key': 'particulars', 'x_mm': 20, 'y_mm': 20, 'font_size': 10, 'align': 'L', 'visible': True},
    ])
    layout.set_line_band({})
    db.session.add(layout)
    db.session.commit()

    # Manila JE created (and thus the newest row by id) AFTER the main-branch
    # JE, so a system-wide "latest record" query would pick Manila's data.
    _build_je(main_branch, cash_account, revenue_account, number='JV-2026-01-0501')
    main_je = JournalEntry.query.filter_by(entry_number='JV-2026-01-0501').first()
    main_je.description = 'BR-MAIN-DESC'
    db.session.commit()

    manila_je = JournalEntry(
        entry_number='JV-2026-01-0502',
        entry_date=date(2026, 1, 21),
        description='BR-MANILA-DESC',
        entry_type='adjustment',
        branch_id=branch_manila.id,
        status='draft',
    )
    db.session.add(manila_je)
    db.session.flush()
    line1 = JournalEntryLine(entry_id=manila_je.id, line_number=1, account_id=cash_account.id,
                              debit_amount=750, credit_amount=0)
    line2 = JournalEntryLine(entry_id=manila_je.id, line_number=2, account_id=revenue_account.id,
                              debit_amount=0, credit_amount=750)
    db.session.add_all([line1, line2])
    db.session.commit()
    assert manila_je.id > main_je.id  # Manila IS the system-wide "latest" row

    accountant_user.set_branches([main_branch])
    db.session.commit()
    _login(client, accountant_user)
    _select_branch(client, main_branch.id)

    resp = client.get('/preprinted-forms/JV/test-print')
    assert resp.status_code == 200
    assert resp.headers['Content-Type'] == 'application/pdf'

    from pypdf import PdfReader
    reader = PdfReader(BytesIO(resp.data))
    text = ' '.join(page.extract_text() for page in reader.pages)
    normalized = ' '.join(text.split())

    assert 'BR-MAIN-DESC' in normalized
    assert 'BR-MANILA-DESC' not in normalized


# ---------------------------------------------------------------------------
# Manual nav link + admin toggles page (P-69 Task 6)
# ---------------------------------------------------------------------------

def test_nav_link_visible_for_accountant_when_module_enabled(client, db_session, accountant_user,
                                                               main_branch, preprinted_module_enabled):
    _login(client, accountant_user)
    _select_branch(client, main_branch.id)
    html = client.get('/dashboard').data.decode()
    assert 'Pre-Printed Forms' in html


def test_nav_link_hidden_for_viewer_even_when_module_enabled(client, db_session, viewer_user,
                                                               main_branch, preprinted_module_enabled):
    """viewer_user's fixture grants default_all_permissions() (every core key,
    now including print_layouts) for unrelated tests' convenience — explicitly
    deny print_layouts here so the viewer is truly ungranted."""
    perms = viewer_user.get_book_permissions()
    perms['print_layouts'] = False
    viewer_user.set_book_permissions(perms)
    viewer_user.set_branches([main_branch])
    db.session.commit()
    _login(client, viewer_user)
    _select_branch(client, main_branch.id)
    html = client.get('/dashboard').data.decode()
    assert 'Pre-Printed Forms' not in html


def test_nav_link_hidden_for_granted_viewer_when_module_enabled(client, db_session, viewer_user,
                                                                   main_branch, preprinted_module_enabled):
    """Fix pass 2 (P-69 review): a viewer explicitly GRANTED print_layouts must
    still never see the nav link — the nav gate mirrors _edit_required and
    only honors the grant for role == 'staff'."""
    perms = viewer_user.get_book_permissions()
    perms['print_layouts'] = True
    viewer_user.set_book_permissions(perms)
    viewer_user.set_branches([main_branch])
    db.session.commit()
    _login(client, viewer_user)
    _select_branch(client, main_branch.id)
    html = client.get('/dashboard').data.decode()
    assert 'Pre-Printed Forms' not in html


def test_nav_link_hidden_for_ungranted_staff_when_module_enabled(client, db_session, staff_user,
                                                                   main_branch, preprinted_module_enabled):
    staff_user.set_branches([main_branch])
    db.session.commit()
    _login(client, staff_user)
    _select_branch(client, main_branch.id)
    html = client.get('/dashboard').data.decode()
    assert 'Pre-Printed Forms' not in html


def test_nav_link_visible_for_granted_staff_when_module_enabled(client, db_session, staff_user,
                                                                  main_branch, preprinted_module_enabled):
    staff_user.set_branches([main_branch])
    perms = staff_user.get_book_permissions()
    perms['print_layouts'] = True
    staff_user.set_book_permissions(perms)
    db.session.commit()
    _login(client, staff_user)
    _select_branch(client, main_branch.id)
    html = client.get('/dashboard').data.decode()
    assert 'Pre-Printed Forms' in html


def test_nav_link_hidden_for_accountant_when_module_disabled(client, db_session, accountant_user,
                                                               main_branch):
    """Module is default-off (no preprinted_module_enabled fixture here) — even an
    accountant, who would otherwise pass the per-user gate, must not see the link."""
    _login(client, accountant_user)
    _select_branch(client, main_branch.id)
    html = client.get('/dashboard').data.decode()
    assert 'Pre-Printed Forms' not in html


def test_admin_toggles_page_renders_five_voucher_rows(client, db_session, admin_user, main_branch,
                                                        preprinted_module_enabled):
    _login(client, admin_user)
    _select_branch(client, main_branch.id)
    resp = client.get('/preprinted-forms')
    assert resp.status_code == 200
    body = resp.data
    for vt in ('SI', 'CR', 'CD', 'AP', 'JV'):
        assert vt.encode() in body
    # Admin sees the toggle action and the designer link
    assert b'/preprinted-forms/SI/toggle' in body
    assert b'/preprinted-forms/SI/design' in body
