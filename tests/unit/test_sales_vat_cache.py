from decimal import Decimal
from app.utils.cache_helpers import get_sales_vat_categories, clear_sales_vat_cache
from app.sales_vat_categories.models import SalesVATCategory


def test_get_and_clear_sales_vat_cache(db_session):
    clear_sales_vat_cache()
    db_session.add(SalesVATCategory(code='SVAT-G', name='Goods', rate=Decimal('12.00'),
                                    transaction_nature='regular', is_active=True))
    db_session.commit()
    rows = get_sales_vat_categories()
    assert any(r.code == 'SVAT-G' for r in rows)
    clear_sales_vat_cache()  # must not raise
