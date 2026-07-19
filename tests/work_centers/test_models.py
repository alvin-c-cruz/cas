"""Unit tests for the WorkCenter model (R-07 Discrete Track slice D1)."""
from decimal import Decimal
import pytest
from app import db
from app.work_centers.models import WorkCenter

pytestmark = [pytest.mark.integration]


def test_defaults(db_session, main_branch):
    wc = WorkCenter(branch_id=main_branch.id, code='WC-1', name='Can Line 1')
    db.session.add(wc)
    db.session.commit()
    assert wc.is_active is True
    assert wc.hourly_rate is None


def test_hourly_rate_settable(db_session, main_branch):
    wc = WorkCenter(branch_id=main_branch.id, code='WC-2', name='Can Line 2',
                    hourly_rate=Decimal('150.00'))
    db.session.add(wc)
    db.session.commit()
    assert wc.hourly_rate == Decimal('150.00')


def test_to_dict(db_session, main_branch):
    wc = WorkCenter(branch_id=main_branch.id, code='WC-3', name='Can Line 3',
                    hourly_rate=Decimal('99.50'))
    db.session.add(wc)
    db.session.commit()
    d = wc.to_dict()
    assert d['code'] == 'WC-3'
    assert d['hourly_rate'] == 99.5
