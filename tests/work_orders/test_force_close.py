"""force_close_work_order() (R-07 D4)."""
from decimal import Decimal
import pytest
from app import db
from app.journal_entries.models import JournalEntry
from tests.work_orders.test_completion_batch import _ready_wo

pytestmark = [pytest.mark.integration, pytest.mark.work_orders]


def test_force_close_writes_off_leftover_pool_and_completes(
        db_session, main_branch, accountant_user, wo_control_accounts):
    from app.work_orders.service import complete_work_order_batch, force_close_work_order
    wo = _ready_wo(main_branch, accountant_user, qty_to_produce='10')
    complete_work_order_batch(wo, Decimal('4'), accountant_user)
    db.session.commit()

    je = force_close_work_order(wo, 'Lost yield on final batch, scrapped 6 units.', accountant_user)
    db.session.commit()

    assert wo.status == 'completed'
    assert wo.qty_completed_to_date == Decimal('4')   # shortfall stays visible
    assert wo.force_closed_at is not None
    assert wo.force_close_note == 'Lost yield on final batch, scrapped 6 units.'
    assert je.is_balanced
    assert je.lines.count() == 3   # variance / WIP / Labor-Applied


def test_force_close_blocked_when_nothing_completed_yet(
        db_session, main_branch, accountant_user, wo_control_accounts):
    from app.work_orders.service import force_close_work_order
    wo = _ready_wo(main_branch, accountant_user)
    with pytest.raises(ValueError, match='at least one'):
        force_close_work_order(wo, 'A valid note here.', accountant_user)


def test_force_close_blocked_when_already_fully_completed(
        db_session, main_branch, accountant_user, wo_control_accounts):
    from app.work_orders.service import complete_work_order_batch, force_close_work_order
    wo = _ready_wo(main_branch, accountant_user, qty_to_produce='10')
    complete_work_order_batch(wo, Decimal('10'), accountant_user)
    db.session.commit()
    with pytest.raises(ValueError, match='at least one'):
        force_close_work_order(wo, 'A valid note here.', accountant_user)


def test_force_close_requires_a_note(db_session, main_branch, accountant_user, wo_control_accounts):
    from app.work_orders.service import complete_work_order_batch, force_close_work_order
    wo = _ready_wo(main_branch, accountant_user, qty_to_produce='10')
    complete_work_order_batch(wo, Decimal('4'), accountant_user)
    db.session.commit()
    with pytest.raises(ValueError, match='note'):
        force_close_work_order(wo, 'short', accountant_user)
