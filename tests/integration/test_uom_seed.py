"""Integration tests for seed_units_of_measure helper."""
from app.units_of_measure.models import UnitOfMeasure
from app.seeds.seed_data import seed_units_of_measure


def test_seed_units_creates_defaults(db_session):
    seed_units_of_measure()
    codes = {u.code for u in UnitOfMeasure.query.all()}
    assert {'pcs', 'kg', 'hr', 'lot', 'set'} <= codes


def test_seed_units_idempotent(db_session):
    seed_units_of_measure()
    seed_units_of_measure()
    assert UnitOfMeasure.query.filter_by(code='pcs').count() == 1


def test_seed_units_all_ten_defaults(db_session):
    seed_units_of_measure()
    codes = {u.code for u in UnitOfMeasure.query.all()}
    expected = {'pcs', 'unit', 'kg', 'g', 'L', 'hr', 'day', 'lot', 'box', 'set'}
    assert expected == codes
