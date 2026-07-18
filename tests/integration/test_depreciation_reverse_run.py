from datetime import date
from decimal import Decimal
import pytest
from app import db
from app.fixed_asset_depreciation.service import post_depreciation_run, reverse_depreciation_run
from app.journal_entries.models import JournalEntry
from app.audit.models import AuditLog
from tests.integration.test_depreciation_post_run import _asset


def test_reverse_posted_run_creates_mirrored_je_and_flips_status(db_session, main_branch,
                                                                   admin_user):
    _asset(db_session, main_branch)
    run = post_depreciation_run(main_branch.id, 2026, 6, {}, admin_user.id)
    original_je = db.session.get(JournalEntry, run.journal_entry_id)

    reversal_je = reverse_depreciation_run(run, date(2026, 6, 30), admin_user.id)

    assert run.status == 'reversed'
    assert reversal_je is not None
    assert reversal_je.is_reversing is True
    assert reversal_je.reversed_entry_id == original_je.id
    assert reversal_je.total_debit == original_je.total_credit
    assert reversal_je.total_credit == original_je.total_debit

    log = AuditLog.query.filter_by(module='fixed_asset_depreciation', action='update',
                                    record_id=run.id).first()
    assert log is not None


def test_reversing_frees_the_period_for_a_new_run(db_session, main_branch, admin_user):
    _asset(db_session, main_branch)
    run = post_depreciation_run(main_branch.id, 2026, 6, {}, admin_user.id)
    reverse_depreciation_run(run, date(2026, 6, 30), admin_user.id)

    new_run = post_depreciation_run(main_branch.id, 2026, 6, {}, admin_user.id)
    assert new_run.id != run.id
    assert new_run.status == 'posted'


def test_reversed_entries_do_not_count_toward_accumulated_depreciation(db_session, main_branch,
                                                                        admin_user):
    asset, *_ = _asset(db_session, main_branch)
    run = post_depreciation_run(main_branch.id, 2026, 6, {}, admin_user.id)
    reverse_depreciation_run(run, date(2026, 6, 30), admin_user.id)
    db_session.refresh(asset)
    assert asset.accumulated_depreciation == Decimal('0')  # back to opening (0)


def test_reverse_non_posted_run_rejected(db_session, main_branch, admin_user):
    _asset(db_session, main_branch)
    run = post_depreciation_run(main_branch.id, 2026, 6, {}, admin_user.id)
    reverse_depreciation_run(run, date(2026, 6, 30), admin_user.id)  # now 'reversed'
    with pytest.raises(ValueError, match='posted'):
        reverse_depreciation_run(run, date(2026, 6, 30), admin_user.id)


def test_reverse_zero_amount_run_flips_status_with_no_je(db_session, main_branch, admin_user):
    from app.fixed_assets.models import FixedAsset
    _asset(db_session, main_branch, cost=Decimal('12000.00'), useful_life_months=12)
    fa = FixedAsset.query.filter_by(branch_id=main_branch.id).first()
    fa.opening_accumulated_depreciation = Decimal('12000.00')
    db_session.commit()
    run = post_depreciation_run(main_branch.id, 2026, 6, {}, admin_user.id)
    assert run.journal_entry_id is None

    result = reverse_depreciation_run(run, date(2026, 6, 30), admin_user.id)
    assert result is None
    assert run.status == 'reversed'
