import pytest
from decimal import Decimal
from datetime import date
from app import db
from app.stock_adjustments.models import PhysicalCount, PhysicalCountLine


class TestPhysicalCountModels:
    def test_create_physical_count_with_lines(self, db_session, branch_main, product_moving_avg):
        pc = PhysicalCount(pc_number='PC-2026-07-0001', branch_id=branch_main.id,
                           count_date=date(2026, 7, 23), status='draft')
        pc.lines.append(PhysicalCountLine(product_id=product_moving_avg.id,
                                          book_qty_snapshot=Decimal('10.0000')))
        db.session.add(pc)
        db.session.commit()

        saved = db.session.get(PhysicalCount, pc.id)
        assert saved.pc_number == 'PC-2026-07-0001'
        assert saved.status == 'draft'
        assert saved.row_version == 1
        assert len(saved.lines) == 1
        assert saved.lines[0].book_qty_snapshot == Decimal('10.0000')
        assert saved.lines[0].counted_qty is None

    def test_deleting_count_cascades_lines(self, db_session, branch_main, product_moving_avg):
        pc = PhysicalCount(pc_number='PC-2026-07-0002', branch_id=branch_main.id,
                           count_date=date(2026, 7, 23), status='draft')
        pc.lines.append(PhysicalCountLine(product_id=product_moving_avg.id,
                                          book_qty_snapshot=Decimal('5.0000')))
        db.session.add(pc)
        db.session.commit()
        line_id = pc.lines[0].id

        db.session.delete(pc)
        db.session.commit()

        assert db.session.get(PhysicalCountLine, line_id) is None

    def test_physical_count_reason_type_registered(self):
        from app.stock_adjustments.models import REASON_TYPES
        assert 'physical_count' in REASON_TYPES
