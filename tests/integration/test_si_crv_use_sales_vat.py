"""
TDD test: SI and CRV must source their VAT dropdown choices from SalesVATCategory,
not from the purchase-side VATCategory.

RED: fails when _vat_categories_for_form() still reads VATCategory.
GREEN: passes after repoint to SalesVATCategory.
"""
from app.sales_invoices.views import _vat_categories_for_form
from app.sales_vat_categories.models import SalesVATCategory
from app.vat_categories.models import VATCategory


def test_si_vat_choices_come_from_sales_table(db_session, app):
    db_session.add(SalesVATCategory(code='SVAT-G', name='Goods', rate=12.00,
                                    transaction_nature='regular', is_active=True))
    db_session.add(VATCategory(code='VAT-12', name='Purchase Goods', rate=12.00, is_active=True))
    db_session.commit()
    with app.test_request_context():
        codes = {c['code'] for c in _vat_categories_for_form()}
    assert 'SVAT-G' in codes
    assert 'VAT-12' not in codes  # purchase codes must NOT appear on SI
