import pytest
from datetime import date
from decimal import Decimal

from app import db
from app.withholding_certificates.models import WithholdingCertificateReceived

pytestmark = [pytest.mark.unit]


def test_table_and_columns():
    t = WithholdingCertificateReceived.__table__
    assert t.name == 'withholding_certificates_received'
    for col, nullable in [('branch_id', False), ('customer_id', False),
                          ('certificate_number', False), ('date_received', False),
                          ('period_from', False), ('period_to', False),
                          ('wt_id', False), ('income_payment', False),
                          ('tax_withheld', False), ('attachment_path', True),
                          ('notes', True)]:
        assert t.c[col].nullable is nullable, col


def test_persist_and_to_dict(db_session, main_branch):
    from app.customers.models import Customer
    from app.withholding_tax.models import WithholdingTax
    cust = Customer(code='SAWT-C', name='SAWT Customer', tin='111-222-333-000')
    wt = WithholdingTax(code='WC158', name='WC158', rate=Decimal('2.00'), tax_type='expanded')
    db.session.add_all([cust, wt]); db.session.commit()
    cert = WithholdingCertificateReceived(
        branch_id=main_branch.id, customer_id=cust.id, certificate_number='2307-0001',
        date_received=date(2025, 10, 5), period_from=date(2025, 7, 1),
        period_to=date(2025, 9, 30), wt_id=wt.id,
        income_payment=Decimal('50000.00'), tax_withheld=Decimal('1000.00'),
        created_by='admin')
    db.session.add(cert); db.session.commit()
    d = cert.to_dict()
    assert d['certificate_number'] == '2307-0001'
    assert d['tax_withheld'] == 1000.0
    assert d['period_from'] == '2025-07-01'
