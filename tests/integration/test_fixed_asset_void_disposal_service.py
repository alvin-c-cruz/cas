from datetime import date
from decimal import Decimal
import pytest
from app import db
from app.fixed_asset_disposal.service import dispose_fixed_asset, void_fixed_asset_disposal
from app.fixed_assets.models import FixedAsset
from app.journal_entries.models import JournalEntry
from app.audit.models import AuditLog
from tests.integration.test_fixed_asset_dispose_service import _asset, _assign_gain_loss_account, \
    _cash_account


def test_void_posted_disposal_creates_mirrored_je_and_restores_asset(db_session, main_branch,
                                                                       admin_user):
    asset, *_ = _asset(db_session, main_branch, cost=Decimal('800000.00'), useful_life_months=60,
                       opening_accum=Decimal('320000.00'))
    _assign_gain_loss_account(db_session)
    cash_acct = _cash_account(db_session)
    disposal = dispose_fixed_asset(asset.id, date(2026, 6, 30), 'sale', Decimal('600000.00'),
                                   cash_acct.id, admin_user.id)
    original_je = db.session.get(JournalEntry, disposal.journal_entry_id)

    reversal_je = void_fixed_asset_disposal(disposal, date(2026, 6, 30), admin_user.id)

    assert disposal.status == 'void'
    assert reversal_je is not None
    assert reversal_je.is_reversing is True
    assert reversal_je.reversed_entry_id == original_je.id
    assert reversal_je.total_debit == original_je.total_credit
    assert reversal_je.total_credit == original_je.total_debit

    db_session.refresh(asset)
    assert asset.status == 'active'

    log = AuditLog.query.filter_by(module='fixed_asset_disposal', action='update',
                                    record_id=disposal.id).first()
    assert log is not None


def test_voiding_frees_the_asset_for_a_new_disposal(db_session, main_branch, admin_user):
    asset, *_ = _asset(db_session, main_branch)
    _assign_gain_loss_account(db_session)
    cash_acct = _cash_account(db_session)
    disposal = dispose_fixed_asset(asset.id, date(2026, 6, 30), 'scrap', Decimal('0'), None,
                                   admin_user.id)
    void_fixed_asset_disposal(disposal, date(2026, 6, 30), admin_user.id)

    new_disposal = dispose_fixed_asset(asset.id, date(2026, 7, 1), 'sale', Decimal('50000.00'),
                                       cash_acct.id, admin_user.id)
    assert new_disposal.id != disposal.id
    assert new_disposal.status == 'posted'


def test_void_non_posted_disposal_rejected(db_session, main_branch, admin_user):
    asset, *_ = _asset(db_session, main_branch)
    _assign_gain_loss_account(db_session)
    disposal = dispose_fixed_asset(asset.id, date(2026, 6, 30), 'scrap', Decimal('0'), None,
                                   admin_user.id)
    void_fixed_asset_disposal(disposal, date(2026, 6, 30), admin_user.id)  # now 'void'
    with pytest.raises(ValueError, match='posted'):
        void_fixed_asset_disposal(disposal, date(2026, 6, 30), admin_user.id)
