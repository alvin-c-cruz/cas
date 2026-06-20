import glob
import importlib.util
import os

import sqlalchemy as sa

from app import db
from app.customers.models import Customer
from app.withholding_tax.models import WithholdingTax


def _backfill_sql():
    """Load the real backfill SQL from the migration so the test can't drift from it."""
    path = glob.glob(os.path.join('migrations', 'versions', '*backfill_customer_wht*.py'))[0]
    spec = importlib.util.spec_from_file_location('_backfill_mig', path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod._BACKFILL_SQL


def test_backfill_maps_default_wt_code_to_m2m_active_only_idempotent(db_session):
    """The migration backfill seeds the M2M from default_wt_code, skips inactive
    codes, and is idempotent."""
    active = WithholdingTax(code='WC158', name='Goods', rate=1.00, is_active=True)
    retired = WithholdingTax(code='WC999', name='Retired', rate=9.00, is_active=False)
    db_session.add_all([active, retired])
    has_code = Customer(code='C100', name='Has Code', default_wt_code='WC158', is_active=True)
    inactive_code = Customer(code='C101', name='Inactive Code', default_wt_code='WC999', is_active=True)
    no_code = Customer(code='C102', name='No Code', is_active=True)
    db_session.add_all([has_code, inactive_code, no_code])
    db_session.commit()

    sql = _backfill_sql()
    db.session.execute(sa.text(sql))
    db.session.commit()

    assert [w.code for w in has_code.withholding_taxes] == ['WC158']
    assert inactive_code.withholding_taxes == []   # inactive code not mapped
    assert no_code.withholding_taxes == []

    # Idempotent: re-running adds no duplicate
    db.session.execute(sa.text(sql))
    db.session.commit()
    assert [w.code for w in has_code.withholding_taxes] == ['WC158']


def test_customer_withholding_taxes_relationship(db_session):
    wt1 = WithholdingTax(code='WC158', name='Goods', rate=1.00, is_active=True)
    wt2 = WithholdingTax(code='WC160', name='Services', rate=2.00, is_active=True)
    db_session.add_all([wt1, wt2])
    c = Customer(code='C001', name='Acme', is_active=True)
    c.withholding_taxes = [wt1, wt2]
    db_session.add(c)
    db_session.commit()

    fetched = Customer.query.filter_by(code='C001').first()
    codes = sorted(w.code for w in fetched.withholding_taxes)
    assert codes == ['WC158', 'WC160']
    d = fetched.to_dict()
    assert sorted(w['code'] for w in d['withholding_taxes']) == ['WC158', 'WC160']
