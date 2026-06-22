# tests/integration/test_cash_flow_closing.py
import pytest
from decimal import Decimal
from datetime import date

from app import db
from app.reports.financial import generate_cash_flow
from tests.integration.test_year_end_close import _world

pytestmark = [pytest.mark.integration]


def test_cash_flow_excludes_closing_entries(db_session, admin_user, main_branch):
    from app.year_end import service
    _world(main_branch.id)
    db.session.commit()
    cf_before = generate_cash_flow(date(2025, 1, 1), date(2025, 12, 31),
                                   branch_id=main_branch.id, method='indirect')
    service.close_fiscal_year(2025, admin_user.id)
    db.session.commit()
    cf_after = generate_cash_flow(date(2025, 1, 1), date(2025, 12, 31),
                                  branch_id=main_branch.id, method='indirect')
    # The closing entries (dated 2025-12-31) must NOT change the cash-flow statement.
    # Actual return keys: net_change (not net_change_in_cash), financing['total'] (not financing_total)
    assert cf_after['net_change'] == cf_before['net_change']
    assert cf_after['financing']['total'] == cf_before['financing']['total']
