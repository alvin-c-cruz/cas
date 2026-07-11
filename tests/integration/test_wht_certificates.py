import pytest
from datetime import date
from decimal import Decimal

from app import db
from app.withholding_certificates.models import WithholdingCertificateReceived
from app.audit.models import AuditLog

pytestmark = [pytest.mark.integration]

MODULE = 'withholding_certificates'


@pytest.fixture(autouse=True)
def _fresh_module_cache():
    from app.utils.cache_helpers import clear_module_config_cache
    clear_module_config_cache(); yield; clear_module_config_cache()


def _login(client):
    client.post('/login', data={'username': 'admin', 'password': 'admin123'},
                follow_redirects=True)


def _customer():
    from app.customers.models import Customer
    c = Customer(code='WC-CUST', name='Withholding Customer', tin='111-222-333-000')
    db.session.add(c); db.session.commit()
    return c


def _wt():
    from app.withholding_tax.models import WithholdingTax
    wt = WithholdingTax(code='WC158', name='WC158', rate=Decimal('2.00'), tax_type='expanded')
    db.session.add(wt); db.session.commit()
    return wt


def _form(branch, cust, wt, **over):
    data = {
        'branch_id': branch.id, 'customer_id': cust.id, 'certificate_number': '2307-0001',
        'date_received': '2025-10-05', 'period_from': '2025-07-01', 'period_to': '2025-09-30',
        'wt_id': wt.id, 'income_payment': '50000.00', 'tax_withheld': '1000.00',
        'notes': 'received by mail',
    }
    data.update(over)
    return data


def test_create_persists_and_audits(client, db_session, main_branch, admin_user):
    _login(client)
    cust, wt = _customer(), _wt()
    resp = client.post('/withholding-certificates/create',
                       data=_form(main_branch, cust, wt), follow_redirects=True)
    assert resp.status_code == 200
    rec = WithholdingCertificateReceived.query.filter_by(certificate_number='2307-0001').first()
    assert rec is not None and rec.tax_withheld == Decimal('1000.00')
    audit = AuditLog.query.filter_by(module=MODULE, action='create', record_id=rec.id).first()
    assert audit is not None


def test_edit_updates_and_audits(client, db_session, main_branch, admin_user):
    _login(client)
    cust, wt = _customer(), _wt()
    client.post('/withholding-certificates/create', data=_form(main_branch, cust, wt),
                follow_redirects=True)
    rec = WithholdingCertificateReceived.query.filter_by(certificate_number='2307-0001').first()
    client.post(f'/withholding-certificates/{rec.id}/edit',
                data=_form(main_branch, cust, wt, tax_withheld='1500.00'), follow_redirects=True)
    db.session.refresh(rec)
    assert rec.tax_withheld == Decimal('1500.00')
    assert AuditLog.query.filter_by(module=MODULE, action='update', record_id=rec.id).first()


def test_delete_removes_and_audits(client, db_session, main_branch, admin_user):
    _login(client)
    cust, wt = _customer(), _wt()
    client.post('/withholding-certificates/create', data=_form(main_branch, cust, wt),
                follow_redirects=True)
    rec = WithholdingCertificateReceived.query.filter_by(certificate_number='2307-0001').first()
    rid = rec.id
    client.post(f'/withholding-certificates/{rid}/delete', follow_redirects=True)
    assert db.session.get(WithholdingCertificateReceived, rid) is None
    assert AuditLog.query.filter_by(module=MODULE, action='delete', record_id=rid).first()


def test_list_renders_created_cert(client, db_session, main_branch, admin_user):
    _login(client)
    cust, wt = _customer(), _wt()
    client.post('/withholding-certificates/create', data=_form(main_branch, cust, wt),
                follow_redirects=True)
    resp = client.get('/withholding-certificates')
    assert resp.status_code == 200
    assert b'2307-0001' in resp.data
    assert b'Withholding Customer' in resp.data
