"""Integration tests for the inline '+ Add Vendor' quick-add flow."""
import pytest
from decimal import Decimal

from app.vendors.models import Vendor
from app.vat_categories.models import VATCategory
from app.audit.models import AuditLog

pytestmark = [pytest.mark.vendors, pytest.mark.integration]

AJAX = {'X-Requested-With': 'XMLHttpRequest'}


def login(client, username='admin', password='admin123'):
    client.post('/login', data={'username': username, 'password': password},
                follow_redirects=True)


def make_vat_category(db_session, code='V12DG', name='Input Tax Domestic Goods', rate='12.00'):
    cat = VATCategory.query.filter_by(code=code).first()
    if not cat:
        cat = VATCategory(code=code, name=name, rate=Decimal(rate), is_active=True)
        db_session.add(cat)
        db_session.commit()
    return cat


class TestVendorQuickAddEndpoint:
    def test_ajax_create_returns_json_and_audits(self, client, db_session, admin_user, main_branch):
        login(client)
        make_vat_category(db_session)
        resp = client.post('/vendors/create', data={
            'code': 'QA001',
            'name': 'Quick Add Vendor',
            'check_payee_name': 'Quick Add Vendor',
            'payment_terms': 'Net 30',
            'default_vat_category': 'V12DG',
            'is_active': '1',
        }, headers=AJAX)
        assert resp.status_code == 200
        body = resp.get_json()
        assert body['ok'] is True
        vendor = Vendor.query.filter_by(code='QA001').first()
        assert vendor is not None
        assert body['vendor']['id'] == vendor.id
        assert body['vendor']['label'] == f'{vendor.code} - {vendor.name}'
        audit = AuditLog.query.filter_by(module='vendor', action='create',
                                         record_id=vendor.id).first()
        assert audit is not None

    def test_ajax_validation_error_returns_422(self, client, db_session, admin_user, main_branch):
        login(client)
        make_vat_category(db_session)
        resp = client.post('/vendors/create', data={
            'code': '',
            'name': '',
            'default_vat_category': 'V12DG',
            'is_active': '1',
        }, headers=AJAX)
        assert resp.status_code == 422
        body = resp.get_json()
        assert body['ok'] is False
        assert 'code' in body['errors']
        assert Vendor.query.filter_by(name='').first() is None

    def test_ajax_duplicate_code_returns_422(self, client, db_session, admin_user, main_branch):
        login(client)
        make_vat_category(db_session)
        existing = Vendor(code='DUP001', name='Existing', is_active=True, payment_terms='Net 30')
        db_session.add(existing)
        db_session.commit()
        resp = client.post('/vendors/create', data={
            'code': 'DUP001',
            'name': 'Another',
            'check_payee_name': 'Another',
            'payment_terms': 'Net 30',
            'default_vat_category': 'V12DG',
            'is_active': '1',
        }, headers=AJAX)
        assert resp.status_code == 422
        body = resp.get_json()
        assert body['ok'] is False
        assert 'code' in body['errors']

    def test_html_path_still_redirects(self, client, db_session, admin_user, main_branch):
        login(client)
        make_vat_category(db_session)
        resp = client.post('/vendors/create', data={
            'code': 'HTML01',
            'name': 'Html Path Vendor',
            'check_payee_name': 'Html Path Vendor',
            'payment_terms': 'Net 30',
            'default_vat_category': 'V12DG',
            'is_active': '1',
        }, follow_redirects=False)
        assert resp.status_code == 302
        assert '/vendors' in resp.headers['Location']

    def test_ajax_create_denied_for_viewer(self, client, db_session, viewer_user, main_branch):
        login(client, username='viewer', password='viewer123')
        make_vat_category(db_session)
        resp = client.post('/vendors/create', data={
            'code': 'VWX001', 'name': 'Nope', 'payment_terms': 'Net 30',
            'default_vat_category': 'V12DG', 'is_active': '1',
        }, headers=AJAX, follow_redirects=False)
        assert resp.status_code == 302
        assert Vendor.query.filter_by(code='VWX001').first() is None


class TestFullVendorPageRegression:
    def test_full_create_page_renders_with_choices_vat(self, client, db_session,
                                                        admin_user, main_branch):
        login(client)
        make_vat_category(db_session)
        resp = client.get('/vendors/create')
        assert resp.status_code == 200
        assert b'vendor-form-scope' in resp.data
        assert b'vat-search-input' not in resp.data
        assert b'choices.min.js' in resp.data
