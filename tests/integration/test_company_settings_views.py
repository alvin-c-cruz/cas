"""Integration tests for Company Settings views — access control, save + audit, logo route."""
import io
import json
import os
import struct
import zlib

import pytest

from app.settings import AppSettings
from app.audit.models import AuditLog
pytestmark = [pytest.mark.settings, pytest.mark.integration]




def make_minimal_png():
    """Build a real, valid 1x1 transparent PNG (passes the magic-number check)."""
    def chunk(tag, data):
        return (struct.pack('>I', len(data)) + tag + data
                + struct.pack('>I', zlib.crc32(tag + data) & 0xffffffff))

    ihdr = struct.pack('>IIBBBBB', 1, 1, 8, 6, 0, 0, 0)  # 1x1, 8-bit RGBA
    idat = zlib.compress(b'\x00\x00\x00\x00\x00')  # filter byte + 1 RGBA pixel
    return (b'\x89PNG\r\n\x1a\n'
            + chunk(b'IHDR', ihdr) + chunk(b'IDAT', idat) + chunk(b'IEND', b''))


def _logo_disk_path(app, stored_name):
    return os.path.join(app.config['UPLOAD_FOLDER'], 'company', stored_name)


def login(client, username='admin', password='admin123'):
    client.post('/login', data={'username': username, 'password': password},
                follow_redirects=True)


VALID_FORM_DATA = {
    'company_name': 'Acme Trading Corp.',
    'trade_name': 'Acme',
    'company_tin': '123-456-789-000',
    'tin_branch_code': '000',
    'rdo_code': '050',
    'vat_registration_type': 'VAT',
    'company_address': '123 Rizal Ave, Manila',
    'postal_code': '1000',
    'phone': '02-8123-4567',
    'email': 'info@acme.ph',
    'fiscal_year_start': '01',
    'officer_president': 'Juan Dela Cruz',
    'officer_treasurer': 'Maria Santos',
    'officer_secretary': 'Pedro Reyes',
}


class TestCompanySettingsAccess:
    def test_admin_can_get_settings_page(self, client, db_session, admin_user, main_branch):
        login(client)
        resp = client.get('/settings')
        assert resp.status_code == 200
        assert b'Company Settings' in resp.data
        assert b'Save Settings' in resp.data
        # Section headings
        assert b'Company Identity' in resp.data
        assert b'BIR Registration' in resp.data
        assert b'Company Officers' in resp.data

    def test_accountant_blocked_from_get(self, client, db_session, accountant_user, main_branch):
        login(client, username='accountant', password='accountant123')
        resp = client.get('/settings')
        assert resp.status_code == 302  # redirected away

        resp = client.get('/settings', follow_redirects=True)
        assert b'Only administrators' in resp.data

    def test_accountant_blocked_from_post(self, client, db_session, accountant_user, main_branch):
        login(client, username='accountant', password='accountant123')
        resp = client.post('/settings', data=VALID_FORM_DATA)
        assert resp.status_code == 302
        # Settings must not have been written
        assert AppSettings.get_setting('company_name') is None

    def test_anonymous_redirected_to_login(self, client, db_session):
        resp = client.get('/settings')
        assert resp.status_code == 302
        assert '/login' in resp.headers['Location']


class TestCompanySettingsSave:
    def test_admin_post_saves_settings_and_audits(self, client, db_session, admin_user, main_branch):
        login(client)
        resp = client.post('/settings', data=VALID_FORM_DATA, follow_redirects=True)
        assert resp.status_code == 200
        assert b'saved successfully' in resp.data

        # Settings persisted
        assert AppSettings.get_setting('company_name') == 'Acme Trading Corp.'
        assert AppSettings.get_setting('vat_registration_type') == 'VAT'
        assert AppSettings.get_setting('fiscal_year_start') == '01'
        assert AppSettings.get_setting('officer_president') == 'Juan Dela Cruz'

        # One audit entry with the changed keys
        entry = AuditLog.query.filter_by(
            module='settings', action='update',
            record_identifier='company_settings'
        ).order_by(AuditLog.id.desc()).first()
        assert entry is not None
        assert entry.user_id == admin_user.id

        new_values = json.loads(entry.new_values)
        assert new_values['company_name'] == 'Acme Trading Corp.'
        assert new_values['company_tin'] == '123-456-789-000'

        old_values = json.loads(entry.old_values)
        assert old_values['company_name'] is None  # was unset before

    def test_audit_contains_only_changed_keys(self, client, db_session, admin_user, main_branch):
        login(client)
        AppSettings.set_setting('company_name', 'Acme Trading Corp.', 'admin')
        AppSettings.set_setting('phone', '02-8123-4567', 'admin')

        data = dict(VALID_FORM_DATA)
        data['phone'] = '02-9999-0000'  # the only real change to phone
        client.post('/settings', data=data, follow_redirects=True)

        entry = AuditLog.query.filter_by(
            module='settings', action='update',
            record_identifier='company_settings'
        ).order_by(AuditLog.id.desc()).first()
        assert entry is not None

        new_values = json.loads(entry.new_values)
        old_values = json.loads(entry.old_values)
        # Unchanged keys are excluded
        assert 'company_name' not in new_values
        # Changed key is present with old and new value
        assert new_values['phone'] == '02-9999-0000'
        assert old_values['phone'] == '02-8123-4567'

    def test_no_changes_writes_no_audit(self, client, db_session, admin_user, main_branch):
        login(client)
        client.post('/settings', data=VALID_FORM_DATA, follow_redirects=True)
        count_before = AuditLog.query.filter_by(
            module='settings', record_identifier='company_settings').count()

        # Re-submit identical data
        resp = client.post('/settings', data=VALID_FORM_DATA, follow_redirects=True)
        assert b'No changes' in resp.data
        count_after = AuditLog.query.filter_by(
            module='settings', record_identifier='company_settings').count()
        assert count_after == count_before

    def test_company_name_required(self, client, db_session, admin_user, main_branch):
        login(client)
        data = dict(VALID_FORM_DATA)
        data['company_name'] = ''
        resp = client.post('/settings', data=data, follow_redirects=True)
        assert resp.status_code == 200
        assert b'Company name is required' in resp.data
        assert AppSettings.get_setting('company_name') is None


class TestCompanyLogo:
    def test_logo_route_requires_login(self, client, db_session):
        resp = client.get('/settings/logo')
        assert resp.status_code == 302
        assert '/login' in resp.headers['Location']

    def test_logo_route_404_when_no_logo(self, client, db_session, admin_user, main_branch):
        login(client)
        resp = client.get('/settings/logo')
        assert resp.status_code == 404

    def test_logo_upload_rejects_bad_extension(self, client, db_session, admin_user, main_branch):
        login(client)
        resp = client.post(
            '/settings/logo/upload',
            data={'logo': (io.BytesIO(b'<svg></svg>'), 'logo.svg')},
            content_type='multipart/form-data',
            follow_redirects=True
        )
        assert b'is not allowed' in resp.data
        assert AppSettings.get_setting('company_logo') is None

    def test_logo_upload_rejects_content_not_matching_extension(
            self, client, db_session, admin_user, main_branch):
        login(client)
        # .png extension but not PNG content — magic-number check must reject it
        resp = client.post(
            '/settings/logo/upload',
            data={'logo': (io.BytesIO(b'GIF89a not really a png'), 'logo.png')},
            content_type='multipart/form-data',
            follow_redirects=True
        )
        assert b'does not match' in resp.data
        assert AppSettings.get_setting('company_logo') is None

    def test_logo_remove_blocked_for_accountant(self, client, db_session, accountant_user, main_branch):
        login(client, username='accountant', password='accountant123')
        resp = client.post('/settings/logo/remove')
        assert resp.status_code == 302

    def test_admin_uploads_logo_persists_audits_and_serves(
            self, client, app, db_session, admin_user, main_branch):
        login(client)
        resp = client.post(
            '/settings/logo/upload',
            data={'logo': (io.BytesIO(make_minimal_png()), 'logo.png')},
            content_type='multipart/form-data',
            follow_redirects=True
        )
        assert resp.status_code == 200
        assert b'uploaded successfully' in resp.data

        # Setting persisted with the stored (UUID) filename
        stored = AppSettings.get_setting('company_logo')
        assert stored is not None
        assert stored.endswith('.png')

        # Audit entry written with correct module, action, and actor
        entry = AuditLog.query.filter_by(
            module='settings', action='update',
            record_identifier='company_logo'
        ).order_by(AuditLog.id.desc()).first()
        assert entry is not None
        assert entry.user_id == admin_user.id
        assert json.loads(entry.new_values)['company_logo'] == stored

        # Logo is served to authenticated users with PNG content
        resp = client.get('/settings/logo')
        assert resp.status_code == 200
        assert resp.data.startswith(b'\x89PNG\r\n\x1a\n')
        resp.close()  # release the file handle (Windows) before cleanup

        # Clean up the uploaded file
        file_path = _logo_disk_path(app, stored)
        if os.path.isfile(file_path):
            os.remove(file_path)

    def test_admin_removes_logo_deletes_setting_and_audits_delete(
            self, client, app, db_session, admin_user, main_branch):
        login(client)
        client.post(
            '/settings/logo/upload',
            data={'logo': (io.BytesIO(make_minimal_png()), 'logo.png')},
            content_type='multipart/form-data',
            follow_redirects=True
        )
        stored = AppSettings.get_setting('company_logo')
        assert stored is not None

        resp = client.post('/settings/logo/remove', follow_redirects=True)
        assert resp.status_code == 200
        assert b'Company logo removed' in resp.data

        # Setting row gone and file deleted from disk
        assert AppSettings.get_setting('company_logo') is None
        assert not os.path.isfile(_logo_disk_path(app, stored))

        # Removal audited as a delete (project convention)
        entry = AuditLog.query.filter_by(
            module='settings', action='delete',
            record_identifier='company_logo'
        ).order_by(AuditLog.id.desc()).first()
        assert entry is not None
        assert entry.user_id == admin_user.id
        assert json.loads(entry.old_values)['company_logo'] == stored

        # Serving route now 404s
        resp = client.get('/settings/logo')
        assert resp.status_code == 404


class TestPrintAccessSettings:
    def test_sv_print_access_saved_when_posted(
            self, client, db_session, admin_user, main_branch):
        login(client)
        data = dict(VALID_FORM_DATA)
        data['apv_print_access'] = 'posted_only'
        data['sv_print_access'] = 'draft_and_posted'
        data['cd_print_access'] = 'draft_and_posted'
        data['cd_check_print_access'] = 'draft_and_posted'
        data['cr_print_access'] = 'draft_and_posted'
        resp = client.post('/settings', data=data, follow_redirects=True)
        assert resp.status_code == 200
        assert b'saved successfully' in resp.data
        assert AppSettings.get_setting('sv_print_access') == 'draft_and_posted'
        assert AppSettings.get_setting('cd_print_access') == 'draft_and_posted'
        assert AppSettings.get_setting('cr_print_access') == 'draft_and_posted'

    def test_sv_cd_print_access_fields_rendered_on_settings_page(
            self, client, db_session, admin_user, main_branch):
        login(client)
        resp = client.get('/settings')
        html = resp.data.decode()
        assert 'sv_print_access' in html
        assert 'cd_print_access' in html
        assert 'cr_print_access' in html

    def test_sv_print_form_saved(self, client, db_session, admin_user, main_branch):
        login(client)
        data = dict(VALID_FORM_DATA)
        data['sv_print_form'] = 'hidden'
        resp = client.post('/settings', data=data, follow_redirects=True)
        assert resp.status_code == 200
        assert b'saved successfully' in resp.data
        assert AppSettings.get_setting('sv_print_form') == 'hidden'

    def test_sv_print_form_field_rendered_on_settings_page(
            self, client, db_session, admin_user, main_branch):
        login(client)
        resp = client.get('/settings')
        assert 'sv_print_form' in resp.data.decode()
