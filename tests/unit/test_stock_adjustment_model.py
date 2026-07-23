from decimal import Decimal
from app import db
from app.stock_adjustments.models import StockAdjustment, StockAdjustmentLine, REASON_TYPES
from app.stock_adjustments.numbering import generate_sa_number

def test_reason_types():
    assert set(REASON_TYPES) == {'correction', 'opening', 'physical_count'}

def test_sa_number_format(db_session):
    n = generate_sa_number()
    assert n.startswith('SA-')
    assert len(n.split('-')) == 4  # SA-YYYY-MM-####

def test_adjustment_with_lines_persists(db_session, product_tracked, branch_main):
    adj = StockAdjustment(sa_number=generate_sa_number(), branch_id=branch_main.id,
                          adjustment_date=__import__('datetime').date(2026, 7, 21),
                          reason_type='correction', status='draft')
    adj.lines.append(StockAdjustmentLine(product_id=product_tracked.id,
                                         quantity_delta=Decimal('5'), unit_cost=Decimal('4.00')))
    db.session.add(adj); db.session.commit()
    assert adj.id is not None and adj.row_version == 1
    assert len(adj.lines) == 1
