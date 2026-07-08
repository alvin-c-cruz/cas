import pytest
from decimal import Decimal
from app import db
from app.vat_settlement.models import VatSettlement

pytestmark = [pytest.mark.integration]


def test_create_and_roundtrip_entry_ids(db_session, admin_user):
    s = VatSettlement(fiscal_year=2025, quarter=3, status='settled',
                      output_vat=Decimal('120000.00'), input_vat=Decimal('50000.00'),
                      prior_carryover=Decimal('0.00'), net_payable=Decimal('70000.00'),
                      new_carryover=Decimal('0.00'), settled_by_id=admin_user.id)
    s.set_settlement_entry_ids([11, 12])
    db.session.add(s); db.session.commit()
    got = VatSettlement.query.filter_by(fiscal_year=2025, quarter=3).first()
    assert got is not None
    assert got.get_settlement_entry_ids() == [11, 12]
    assert got.net_payable == Decimal('70000.00')


def test_unique_year_quarter(db_session, admin_user):
    db.session.add(VatSettlement(fiscal_year=2025, quarter=3, settled_by_id=admin_user.id))
    db.session.commit()
    db.session.add(VatSettlement(fiscal_year=2025, quarter=3, settled_by_id=admin_user.id))
    with pytest.raises(Exception):
        db.session.commit()
    db.session.rollback()


def test_blueprint_importable():
    from app.vat_settlement.views import vat_settlement_bp
    assert vat_settlement_bp.name == 'vat_settlement'
