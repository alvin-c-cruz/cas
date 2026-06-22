import pytest
from decimal import Decimal

pytestmark = [pytest.mark.integration]


def test_create_and_roundtrip_closing_entry_ids(db_session, admin_user, main_branch):
    from app.year_end.models import FiscalYearClose
    fc = FiscalYearClose(
        fiscal_year=2025, branch_id=main_branch.id, status='closed',
        net_income=Decimal('1000.00'), closed_by_id=admin_user.id,
    )
    fc.set_closing_entry_ids([11, 22, 33])
    db_session.add(fc)
    db_session.commit()

    again = FiscalYearClose.query.filter_by(fiscal_year=2025, branch_id=main_branch.id).first()
    assert again is not None
    assert again.status == 'closed'
    assert again.net_income == Decimal('1000.00')
    assert again.get_closing_entry_ids() == [11, 22, 33]


def test_unique_year_branch(db_session, admin_user, main_branch):
    from app import db
    from app.year_end.models import FiscalYearClose
    db_session.add(FiscalYearClose(fiscal_year=2025, branch_id=main_branch.id,
                                   status='closed', net_income=Decimal('0'),
                                   closed_by_id=admin_user.id))
    db_session.commit()
    db_session.add(FiscalYearClose(fiscal_year=2025, branch_id=main_branch.id,
                                   status='closed', net_income=Decimal('0'),
                                   closed_by_id=admin_user.id))
    with pytest.raises(Exception):
        db_session.commit()
    db_session.rollback()
