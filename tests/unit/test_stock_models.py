from decimal import Decimal
from app import db
from app.stock_adjustments.models import StockMovement, StockBalance, MOVEMENT_TYPES


def test_movement_type_enum_reserves_all_future_sources():
    for t in ('receipt', 'issue', 'material_issue', 'production',
              'purchase_return', 'sales_return', 'adjustment'):
        assert t in MOVEMENT_TYPES


def test_stock_balance_row_version_defaults_to_one(db_session, product_tracked, branch_main):
    bal = StockBalance(product_id=product_tracked.id, branch_id=branch_main.id,
                       quantity_on_hand=Decimal('0'), average_unit_cost=Decimal('0'),
                       total_value=Decimal('0'))
    db.session.add(bal); db.session.commit()
    assert bal.row_version == 1


def test_stock_movement_is_persistable(db_session, product_tracked, branch_main):
    mv = StockMovement(product_id=product_tracked.id, branch_id=branch_main.id,
                       movement_type='adjustment', quantity=Decimal('5.0000'),
                       unit_cost=Decimal('4.00'), balance_qty_after=Decimal('5.0000'),
                       balance_avg_cost_after=Decimal('4.00'), balance_value_after=Decimal('20.00'),
                       source_document_type='stock_adjustment', source_document_id=1)
    db.session.add(mv); db.session.commit()
    assert mv.id is not None
