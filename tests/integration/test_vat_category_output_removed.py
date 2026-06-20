"""
TDD test: VATCategory must NOT have output_vat_account_id
(Task 12 — drop output column from purchase-side VAT categories)
"""
from app.vat_categories.models import VATCategory


def test_vatcategory_has_no_output_account_attr(db_session):
    cat = VATCategory(code='VAT-12', name='Goods', rate=12.00, is_active=True)
    db_session.add(cat)
    db_session.commit()
    assert not hasattr(cat, 'output_vat_account_id')
    assert 'output_vat_account_id' not in cat.to_dict()
