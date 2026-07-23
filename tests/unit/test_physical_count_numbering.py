from datetime import date
from app import db
from app.stock_adjustments.models import PhysicalCount
from app.stock_adjustments.numbering import generate_pc_number


class TestGeneratePcNumber:
    def test_first_number_of_the_month(self, db_session):
        n = generate_pc_number()
        assert n.startswith('PC-')
        assert n.endswith('-0001')

    def test_increments_within_the_same_month(self, db_session, branch_main):
        from app.utils import ph_now
        today = ph_now().date()
        existing = PhysicalCount(pc_number=f'PC-{today.year:04d}-{today.month:02d}-0007',
                                 branch_id=branch_main.id, count_date=date(2026, 7, 23),
                                 status='draft')
        db.session.add(existing)
        db.session.commit()

        n = generate_pc_number()
        assert n == f'PC-{today.year:04d}-{today.month:02d}-0008'
