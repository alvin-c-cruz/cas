# tests/integration/test_balance_sheet_closing.py
import pytest
from decimal import Decimal
from datetime import date

from app import db
from app.accounts.models import Account
from app.reports.financial import generate_balance_sheet
from tests.integration.test_year_end_close import _world

pytestmark = [pytest.mark.integration]


def _classify_world():
    """Set classification on Asset/Liability accounts created by _world so the
    type-driven BS generator can place them in Current/Non-Current divisions."""
    for code, cls in [('10101', 'Current')]:
        a = Account.query.filter_by(code=code).first()
        if a:
            a.classification = cls
    db.session.flush()


def test_bs_before_close_unchanged(db_session, admin_user, main_branch):
    """Before any close, equity carries computed Net Income — backward compatible."""
    _world(main_branch.id)
    _classify_world()
    db.session.commit()
    bs = generate_balance_sheet(date(2025, 12, 31), branch_id=main_branch.id)
    eq = next(s for s in bs['sections'] if s['key'] == 'equity')
    names = [line['name'] for div in eq['divisions'] for line in div['lines']]
    assert any('Net Income (current year)' in n for n in names)
    assert bs['is_balanced']


def test_bs_after_close_uses_posted_re_and_no_double_count(db_session, admin_user, main_branch):
    from app.year_end import service
    _world(main_branch.id)
    _classify_world()
    db.session.commit()
    service.close_fiscal_year(2025, admin_user.id)
    db.session.commit()

    # Balance sheet as of the close date: RE posted = 700, no computed current-year line
    bs = generate_balance_sheet(date(2025, 12, 31), branch_id=main_branch.id)
    eq = next(s for s in bs['sections'] if s['key'] == 'equity')
    re_total = eq['total']
    # equity should be exactly the posted RE (700), not 1400 (double-count)
    assert re_total == 700.0
    assert bs['is_balanced']
