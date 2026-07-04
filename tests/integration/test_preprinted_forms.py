"""Integration tests for the pre-printed voucher forms designer backend (P-69 Task 4)
and the designer UI + test-print route (P-69 Task 5).

Covers the blueprint's permission decorators (_module_required, _edit_required,
_admin_required) and the save/toggle/design/test-print routes.
"""
import json
from datetime import date
from decimal import Decimal
from io import BytesIO

import pytest
from app import db
from app.settings import AppSettings
from app.utils.cache_helpers import clear_module_config_cache
from app.audit.models import AuditLog
from app.preprinted_forms.models import PrintLayout
from app.journal_entries.models import JournalEntry, JournalEntryLine
from app.customers.models import Customer
from app.vendors.models import Vendor
from app.sales_invoices.models import SalesInvoice
from app.accounts_payable.models import AccountsPayable
from app.cash_receipts.models import CashReceiptVoucher
from app.cash_disbursements.models import CashDisbursementVoucher

pytestmark = [pytest.mark.integration]


def _login(client, user):
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user.id)
        sess['_fresh'] = True
    # Every test in this module shares one long-lived app context (pushed once by
    # the db_session fixture's `with app.app_context():`), so Flask's test client
    # reuses that same context -- and therefore the same `flask.g` -- across every
    # simulated request in a test. Flask-Login caches the resolved user on
    # `g._login_user` for the lifetime of the app context, so a test that logs in
    # as one user and later switches to another (Task 8's full-flow test does
    # this: accountant saves, then admin toggles) would otherwise keep seeing the
    # FIRST user on every subsequent request even though the session cookie's
    # _user_id has genuinely changed. Popping the cache here makes _login() a
    # true identity switch regardless of how many logins happen in one test.
    from flask import g
    if hasattr(g, '_login_user'):
        del g._login_user


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


def _build_je(main_branch, cash_account, revenue_account, number='JV-2026-01-0500', status='draft'):
    je = JournalEntry(
        entry_number=number,
        entry_date=date(2026, 1, 20),
        description='Test-print JE',
        entry_type='adjustment',
        branch_id=main_branch.id,
        status=status,
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


def test_admin_toggles_page_renders_six_voucher_rows(client, db_session, admin_user, main_branch,
                                                       preprinted_module_enabled):
    _login(client, admin_user)
    _select_branch(client, main_branch.id)
    resp = client.get('/preprinted-forms')
    assert resp.status_code == 200
    body = resp.data
    for vt in ('SI', 'CR', 'CD', 'AP', 'JV', 'CD_CHECK'):
        assert vt.encode() in body
    # Admin sees the toggle action and the designer link
    assert b'/preprinted-forms/SI/toggle' in body
    assert b'/preprinted-forms/SI/design' in body


# ---------------------------------------------------------------------------
# Server-side print-access guard + PDF/HTML routing (P-69 Task 7)
# ---------------------------------------------------------------------------

# HTML print templates for all five documents share this marker (the on-screen
# Print button), which never appears in a PDF response -- a reliable "we got
# the HTML fallback, not the pre-printed PDF" signal.
_HTML_PRINT_MARKER = b'onclick="window.print()"'

VT_INFO = {
    'SI': {'setting': 'sv_print_access', 'print_path': lambda id: f'/sales-invoices/{id}/print'},
    'AP': {'setting': 'apv_print_access', 'print_path': lambda id: f'/accounts-payable/{id}/print'},
    'CR': {'setting': 'cr_print_access', 'print_path': lambda id: f'/cash-receipts/{id}/print'},
    'CD': {'setting': 'cd_print_access', 'print_path': lambda id: f'/cash-disbursements/{id}/print'},
}


def _build_record(vt, main_branch, cash_account, status):
    """Build a minimal SI/AP/CR/CD record in the given status. Each call uses a
    status-qualified code/number so draft+posted records built in the same test
    don't collide on unique constraints."""
    if vt == 'SI':
        customer = Customer(code=f'PPC-{status}', name='PP Customer', is_active=True)
        db.session.add(customer)
        db.session.commit()
        rec = SalesInvoice(
            branch_id=main_branch.id, invoice_number=f'SI-PP-{status}',
            invoice_date=date(2026, 1, 15), due_date=date(2026, 2, 15),
            customer_id=customer.id, customer_name=customer.name,
            notes='', status=status, amount_paid=Decimal('0.00'),
        )
    elif vt == 'AP':
        vendor = Vendor(code=f'PPV-{status}', name='PP Vendor',
                         check_payee_name='PP Vendor', is_active=True)
        db.session.add(vendor)
        db.session.commit()
        today = date(2026, 1, 15)
        rec = AccountsPayable(
            ap_number=f'AP-PP-{status}', vendor_id=vendor.id, vendor_name=vendor.name,
            branch_id=main_branch.id, ap_date=today, due_date=today,
            notes='', status=status,
        )
    elif vt == 'CR':
        customer = Customer(code=f'PPC2-{status}', name='PP Customer 2', is_active=True)
        db.session.add(customer)
        db.session.commit()
        rec = CashReceiptVoucher(
            branch_id=main_branch.id, crv_number=f'CR-PP-{status}',
            crv_date=date(2026, 1, 15), customer_id=customer.id, customer_name=customer.name,
            payment_method='cash', cash_account_id=cash_account.id, notes='', status=status,
        )
    elif vt == 'CD':
        vendor = Vendor(code=f'PPV2-{status}', name='PP Vendor 2',
                         check_payee_name='PP Vendor 2', is_active=True)
        db.session.add(vendor)
        db.session.commit()
        rec = CashDisbursementVoucher(
            branch_id=main_branch.id, cdv_number=f'CD-PP-{status}',
            cdv_date=date(2026, 1, 15), vendor_id=vendor.id, vendor_name=vendor.name,
            payment_method='cash', cash_account_id=cash_account.id, notes='', status=status,
        )
    else:
        raise ValueError(vt)
    db.session.add(rec)
    db.session.commit()
    return rec


@pytest.mark.parametrize('vt', ['SI', 'AP', 'CR', 'CD'])
def test_print_guard_denies_draft_under_posted_only(client, db_session, admin_user, main_branch,
                                                      cash_account, vt):
    """Default posted_only + a draft record -> the print route refuses (302,
    redirect + flash), with the pre-printed module OFF (plain HTML path)."""
    info = VT_INFO[vt]
    AppSettings.set_setting(info['setting'], 'posted_only', 'system')
    rec = _build_record(vt, main_branch, cash_account, status='draft')
    _login(client, admin_user)
    _select_branch(client, main_branch.id)

    resp = client.get(info['print_path'](rec.id))
    assert resp.status_code == 302

    resp = client.get(info['print_path'](rec.id), follow_redirects=True)
    assert resp.status_code == 200
    assert b'Printing is not available' in resp.data


@pytest.mark.parametrize('vt', ['SI', 'AP', 'CR', 'CD'])
def test_print_guard_allows_posted_status(client, db_session, admin_user, main_branch,
                                           cash_account, vt):
    """Default posted_only + a posted record -> the print route succeeds (200,
    HTML fallback since the pre-printed module is OFF here)."""
    info = VT_INFO[vt]
    AppSettings.set_setting(info['setting'], 'posted_only', 'system')
    rec = _build_record(vt, main_branch, cash_account, status='posted')
    _login(client, admin_user)
    _select_branch(client, main_branch.id)

    resp = client.get(info['print_path'](rec.id))
    assert resp.status_code == 200
    assert _HTML_PRINT_MARKER in resp.data


def test_jv_print_default_allows_any_status_no_setting(client, db_session, admin_user, main_branch,
                                                        cash_account, revenue_account):
    """JV has no *_print_access setting -- can_print('JV', ...) always allows,
    even for a draft entry."""
    je = _build_je(main_branch, cash_account, revenue_account, number='JV-PP-0001', status='draft')
    _login(client, admin_user)
    _select_branch(client, main_branch.id)

    resp = client.get(f'/journal-entries/{je.id}/print')
    assert resp.status_code == 200
    assert _HTML_PRINT_MARKER in resp.data


def test_guard_fires_before_pdf_path(client, db_session, admin_user, main_branch, cash_account,
                                      preprinted_module_enabled):
    """A draft SI under posted_only is redirected even when the module is
    enabled AND an active layout with a background image exists -- the guard
    must run before the pre-printed branch, not after."""
    AppSettings.set_setting('sv_print_access', 'posted_only', 'system')
    layout = PrintLayout(voucher_type='SI', active=True, background_image='x.png',
                          page_width_mm=215.9, page_height_mm=279.4)
    db.session.add(layout)
    db.session.commit()
    rec = _build_record('SI', main_branch, cash_account, status='draft')
    _login(client, admin_user)
    _select_branch(client, main_branch.id)

    resp = client.get(f'/sales-invoices/{rec.id}/print', follow_redirects=True)
    assert resp.status_code == 200
    assert b'Printing is not available' in resp.data
    assert resp.headers['Content-Type'].startswith('text/html')


@pytest.mark.parametrize('vt', ['SI', 'AP', 'CR', 'CD'])
def test_pdf_routing_when_module_enabled_and_layout_active(client, db_session, admin_user, main_branch,
                                                            cash_account, preprinted_module_enabled, vt):
    """Module enabled + an active layout with a background_image -> the print
    route returns a PDF instead of the HTML template."""
    layout = PrintLayout(voucher_type=vt, active=True, background_image='x.png',
                          page_width_mm=215.9, page_height_mm=279.4)
    db.session.add(layout)
    db.session.commit()
    rec = _build_record(vt, main_branch, cash_account, status='posted')
    _login(client, admin_user)
    _select_branch(client, main_branch.id)

    resp = client.get(VT_INFO[vt]['print_path'](rec.id))
    assert resp.status_code == 200
    assert resp.headers['Content-Type'] == 'application/pdf'


def test_jv_pdf_routing_when_module_enabled_and_layout_active(client, db_session, admin_user, main_branch,
                                                               cash_account, revenue_account,
                                                               preprinted_module_enabled):
    """New /journal-entries/<id>/print route: module on + active JV layout +
    background_image -> PDF."""
    layout = PrintLayout(voucher_type='JV', active=True, background_image='x.png',
                          page_width_mm=215.9, page_height_mm=279.4)
    db.session.add(layout)
    db.session.commit()
    je = _build_je(main_branch, cash_account, revenue_account, number='JV-PP-0002')
    _login(client, admin_user)
    _select_branch(client, main_branch.id)

    resp = client.get(f'/journal-entries/{je.id}/print')
    assert resp.status_code == 200
    assert resp.headers['Content-Type'] == 'application/pdf'


@pytest.mark.parametrize('vt', ['SI', 'AP', 'CR', 'CD', 'JV'])
def test_html_fallback_when_layout_inactive(client, db_session, admin_user, main_branch,
                                             cash_account, revenue_account,
                                             preprinted_module_enabled, vt):
    """Module enabled but the layout is inactive (active=False) -> falls back
    to the existing HTML print template (marker present, HTML content-type)."""
    layout = PrintLayout(voucher_type=vt, active=False, background_image='x.png',
                          page_width_mm=215.9, page_height_mm=279.4)
    db.session.add(layout)
    db.session.commit()

    if vt == 'JV':
        rec = _build_je(main_branch, cash_account, revenue_account, number='JV-PP-0003')
        url = f'/journal-entries/{rec.id}/print'
    else:
        rec = _build_record(vt, main_branch, cash_account, status='posted')
        url = VT_INFO[vt]['print_path'](rec.id)

    _login(client, admin_user)
    _select_branch(client, main_branch.id)

    resp = client.get(url)
    assert resp.status_code == 200
    assert resp.headers['Content-Type'].startswith('text/html')
    assert _HTML_PRINT_MARKER in resp.data


# ---------------------------------------------------------------------------
# End-to-end acceptance tests + module-off default (P-69 Task 8)
# ---------------------------------------------------------------------------
#
# Module-off default HTML behavior and the "draft JV still prints / draft SI
# under posted_only still redirects even with an active layout" guard+PDF
# interplay are already exercised by Task 7's tests above:
#   - test_print_guard_allows_posted_status (SI/AP/CR/CD, module OFF -> HTML)
#   - test_jv_print_default_allows_any_status_no_setting (JV, module OFF -> HTML)
#   - test_guard_fires_before_pdf_path (draft SI, posted_only, active layout -> redirect)
#   - test_jv_pdf_routing_when_module_enabled_and_layout_active (draft JV, active
#     layout -> PDF; _build_je's default status is 'draft')
# so they are not duplicated here. What's added below: a compact parametrized
# sweep of all 5 routes (module off, no settings overrides at all) as a single
# belt-and-suspenders check; admin-index/toggle denial when the module is off
# (not covered above -- only design/save were); the full JV designer->print
# flow; and per-voucher PDF text-content smoke tests for SI/AP/CR/CD.

def test_module_off_default_all_five_print_routes_return_html(client, db_session, admin_user,
                                                                main_branch, cash_account,
                                                                revenue_account):
    """(a) Module-off default, no AppSettings overrides at all: every one of the
    5 print routes (SI/AP/CR/CD/JV) returns the existing HTML print template,
    never a PDF."""
    _login(client, admin_user)
    _select_branch(client, main_branch.id)

    si = _build_record('SI', main_branch, cash_account, status='posted')
    ap = _build_record('AP', main_branch, cash_account, status='posted')
    cr = _build_record('CR', main_branch, cash_account, status='posted')
    cd = _build_record('CD', main_branch, cash_account, status='posted')
    je = _build_je(main_branch, cash_account, revenue_account, number='JV-PP-0900', status='posted')

    paths = {
        'SI': f'/sales-invoices/{si.id}/print',
        'AP': f'/accounts-payable/{ap.id}/print',
        'CR': f'/cash-receipts/{cr.id}/print',
        'CD': f'/cash-disbursements/{cd.id}/print',
        'JV': f'/journal-entries/{je.id}/print',
    }
    for vt, path in paths.items():
        resp = client.get(path)
        assert resp.status_code == 200, vt
        assert resp.headers['Content-Type'].startswith('text/html'), vt
        assert _HTML_PRINT_MARKER in resp.data, vt


def test_admin_index_denied_when_module_disabled_by_default(client, db_session, admin_user,
                                                              main_branch):
    """(a) The admin toggles list (/preprinted-forms) is also gated by
    _module_required -- denied when the module is off by default."""
    _login(client, admin_user)
    _select_branch(client, main_branch.id)
    resp = client.get('/preprinted-forms', follow_redirects=True)
    assert resp.status_code == 200
    assert b'not enabled' in resp.data.lower()


def test_toggle_denied_when_module_disabled_by_default(client, db_session, admin_user, main_branch):
    """(a) The toggle route is gated by _admin_required, which checks the
    module flag first -- denied (and no layout row created) when off by default."""
    _login(client, admin_user)
    _select_branch(client, main_branch.id)
    resp = client.post('/preprinted-forms/JV/toggle', follow_redirects=True)
    assert resp.status_code == 200
    assert b'not enabled' in resp.data.lower()
    assert PrintLayout.query.filter_by(voucher_type='JV').first() is None


def test_full_flow_jv_designer_to_pdf(client, db_session, accountant_user, admin_user, main_branch,
                                       cash_account, revenue_account, preprinted_module_enabled):
    """(b) Full flow: module enabled (fixture) -> accountant saves a JV layout
    with visible 'number' + 'particulars' header fields, a hidden 'reference'
    field, and a debit/credit line band -> background_image set directly ->
    admin toggles active -> a posted JV prints as application/pdf whose
    extracted text contains the JV number, the description, and a line's
    account code/debit amount -- and the hidden field's value does NOT appear."""
    _login(client, accountant_user)
    _select_branch(client, main_branch.id)

    fields = json.dumps([
        {'key': 'number', 'x_mm': 20, 'y_mm': 15, 'font_size': 10, 'align': 'L', 'visible': True},
        {'key': 'particulars', 'x_mm': 20, 'y_mm': 25, 'font_size': 10, 'align': 'L', 'visible': True},
        {'key': 'reference', 'x_mm': 20, 'y_mm': 35, 'font_size': 10, 'align': 'L', 'visible': False},
    ])
    line_band = json.dumps({
        'anchor_y_mm': 100, 'row_height_mm': 8, 'font_size': 9,
        'columns': [
            {'key': 'account_code', 'x_mm': 10, 'align': 'L'},
            {'key': 'account_name', 'x_mm': 40, 'align': 'L'},
            {'key': 'debit', 'x_mm': 100, 'align': 'R'},
            {'key': 'credit', 'x_mm': 130, 'align': 'R'},
        ],
    })
    resp = client.post('/preprinted-forms/JV/save',
                        data={'fields_json': fields, 'line_band_json': line_band},
                        follow_redirects=True)
    assert resp.status_code == 200
    layout = PrintLayout.query.filter_by(voucher_type='JV').first()
    assert layout is not None
    assert layout.get_fields()[0]['key'] == 'number'
    assert layout.get_line_band()['columns'][0]['key'] == 'account_code'

    # Set background_image directly (bypassing the upload route, per brief).
    layout.background_image = 'jv-background.png'
    db.session.commit()

    # Admin toggles active.
    _login(client, admin_user)
    _select_branch(client, main_branch.id)
    resp = client.post('/preprinted-forms/JV/toggle', follow_redirects=True)
    assert resp.status_code == 200
    db.session.refresh(layout)
    assert layout.active is True

    # A posted JV with a distinct description + a hidden reference + account lines.
    je = _build_je(main_branch, cash_account, revenue_account, number='JV-2026-07-0900',
                    status='posted')
    je.description = 'FULL-FLOW-JV-DESCRIPTION'
    je.reference = 'HIDDEN-REF-999'
    db.session.commit()

    resp = client.get(f'/journal-entries/{je.id}/print')
    assert resp.status_code == 200
    assert resp.headers['Content-Type'] == 'application/pdf'

    from pypdf import PdfReader
    reader = PdfReader(BytesIO(resp.data))
    text = ' '.join(page.extract_text() for page in reader.pages)
    normalized = ' '.join(text.split())

    assert 'JV-2026-07-0900' in normalized
    assert 'FULL-FLOW-JV-DESCRIPTION' in normalized
    assert '1001' in normalized       # cash_account code, via the line band
    assert '500.00' in normalized     # line debit amount, via the line band
    assert 'HIDDEN-REF-999' not in normalized


@pytest.mark.parametrize('vt', ['SI', 'AP', 'CR', 'CD'])
def test_per_voucher_smoke_pdf_contains_document_number(client, db_session, admin_user, main_branch,
                                                          cash_account, preprinted_module_enabled, vt):
    """(c) Per-voucher smoke: an active layout (one visible 'number' field +
    background set) -> the doc's print route returns a PDF whose extracted
    text contains the document's own number."""
    layout = PrintLayout(voucher_type=vt, active=True, background_image='x.png',
                          page_width_mm=215.9, page_height_mm=279.4)
    layout.set_fields([
        {'key': 'number', 'x_mm': 20, 'y_mm': 20, 'font_size': 10, 'align': 'L', 'visible': True},
    ])
    layout.set_line_band({})
    db.session.add(layout)
    db.session.commit()

    rec = _build_record(vt, main_branch, cash_account, status='posted')
    _login(client, admin_user)
    _select_branch(client, main_branch.id)

    resp = client.get(VT_INFO[vt]['print_path'](rec.id))
    assert resp.status_code == 200
    assert resp.headers['Content-Type'] == 'application/pdf'

    from pypdf import PdfReader
    reader = PdfReader(BytesIO(resp.data))
    text = ' '.join(page.extract_text() for page in reader.pages)
    normalized = ' '.join(text.split())

    # NOTE: not a dict-literal lookup -- each SI/AP/CR/CD model only defines its
    # own number attribute, so building a dict of all four eagerly would raise
    # AttributeError on the branches not taken (e.g. a SalesInvoice has no
    # ap_number).
    if vt == 'SI':
        expected_number = rec.invoice_number
    elif vt == 'AP':
        expected_number = rec.ap_number
    elif vt == 'CR':
        expected_number = rec.crv_number
    else:
        expected_number = rec.cdv_number
    assert expected_number in normalized
