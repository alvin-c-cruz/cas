"""P6 Task 1 -- the expected-loss column on the BOM.

`normal_loss_pct` is the fraction of units STARTED that this process is expected to
lose. Loss up to it is normal and stays absorbed by the good units (as it has been
since P3); loss beyond it is abnormal and gets costed out.

**NULL is not zero, and the distinction is the whole backward-compatibility
guarantee.** NULL means "nobody has set an expectation", so there is no allowance to
exceed and all loss stays absorbed -- exactly today's behaviour, for every existing
run and every live client. 0.00 means "this process is expected to lose nothing", so
ALL loss is abnormal. A default of 0 instead of NULL would silently reclassify every
historical run's shrinkage as an abnormal loss.
"""
from decimal import Decimal

import pytest

from app import db
from app.bill_of_materials.models import BillOfMaterial
from app.products.models import Product

pytestmark = [pytest.mark.unit, pytest.mark.bill_of_materials]


def _bom(code, **kw):
    out = Product(code=code, name='Dried Mango', track_inventory=True,
                  costing_method='moving_average', is_active=True)
    db.session.add(out); db.session.commit()
    bom = BillOfMaterial(product_id=out.id, manufacturing_mode='process', **kw)
    db.session.add(bom); db.session.commit()
    return bom


class TestNormalLossPct:
    def test_defaults_to_NULL_not_zero(self, db_session):
        """The backward-compatibility guarantee. A 0 default would reclassify every
        historical run's ordinary shrinkage as abnormal loss."""
        bom = _bom('NL-A')
        assert bom.normal_loss_pct is None

    def test_round_trips_a_percentage(self, db_session):
        bom = _bom('NL-B', normal_loss_pct=Decimal('3.50'))
        bom_id = bom.id          # read BEFORE expunging -- afterwards it is detached
        db.session.expunge_all()
        fresh = db.session.get(BillOfMaterial, bom_id)
        assert fresh.normal_loss_pct == Decimal('3.50')

    def test_zero_is_distinct_from_null(self, db_session):
        """0.00 is an explicit expectation of no loss; NULL is no expectation at all.
        They must not collapse into each other."""
        explicit_id = _bom('NL-C', normal_loss_pct=Decimal('0.00')).id
        absent_id = _bom('NL-D').id
        db.session.expunge_all()
        assert db.session.get(BillOfMaterial, explicit_id).normal_loss_pct == Decimal('0.00')
        assert db.session.get(BillOfMaterial, absent_id).normal_loss_pct is None

    def test_accepts_a_fractional_percentage(self, db_session):
        bom_id = _bom('NL-E', normal_loss_pct=Decimal('12.75')).id
        db.session.expunge_all()
        assert db.session.get(BillOfMaterial, bom_id).normal_loss_pct == Decimal('12.75')
