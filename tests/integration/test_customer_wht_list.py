from app.customers.models import Customer
from app.withholding_tax.models import WithholdingTax


def test_customer_withholding_taxes_relationship(db_session):
    wt1 = WithholdingTax(code='WC158', name='Goods', rate=1.00, is_active=True)
    wt2 = WithholdingTax(code='WC160', name='Services', rate=2.00, is_active=True)
    db_session.add_all([wt1, wt2])
    c = Customer(code='C001', name='Acme', is_active=True)
    c.withholding_taxes = [wt1, wt2]
    db_session.add(c)
    db_session.commit()

    fetched = Customer.query.filter_by(code='C001').first()
    codes = sorted(w.code for w in fetched.withholding_taxes)
    assert codes == ['WC158', 'WC160']
    d = fetched.to_dict()
    assert sorted(w['code'] for w in d['withholding_taxes']) == ['WC158', 'WC160']
