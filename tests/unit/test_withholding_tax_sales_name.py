from decimal import Decimal
from app.withholding_tax.models import WithholdingTax


def test_sales_name_persists_and_in_to_dict(db_session):
    wt = WithholdingTax(code='WC010', name='Professional Fees - Individuals',
                        sales_name='Professional Fees Income - Individual',
                        rate=Decimal('10.00'), is_active=True)
    db_session.add(wt)
    db_session.commit()
    assert wt.sales_name == 'Professional Fees Income - Individual'
    assert wt.to_dict()['sales_name'] == 'Professional Fees Income - Individual'


def test_sales_name_is_optional(db_session):
    wt = WithholdingTax(code='WC999', name='Buyer only', rate=Decimal('1.00'))
    db_session.add(wt)
    db_session.commit()
    assert wt.sales_name is None
    assert wt.to_dict()['sales_name'] is None
