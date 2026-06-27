from app import db
from app.units_of_measure.models import UnitOfMeasure
from app.utils.cache_helpers import get_active_units, clear_uom_cache


def test_get_active_units_excludes_inactive_and_caches(db_session):
    db.session.add(UnitOfMeasure(code='pcs', name='Pieces', is_active=True))
    db.session.add(UnitOfMeasure(code='old', name='Old', is_active=False))
    db.session.commit()
    clear_uom_cache()
    codes = [u.code for u in get_active_units()]
    assert 'pcs' in codes and 'old' not in codes
