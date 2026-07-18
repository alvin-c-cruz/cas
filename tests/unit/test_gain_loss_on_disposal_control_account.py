import pytest
from app.posting.control_accounts import (
    CONTROL_ACCOUNTS, get_control_account, ControlAccountError,
)


def test_gain_loss_on_disposal_key_registered():
    assert 'gain_loss_on_disposal' in CONTROL_ACCOUNTS
    setting_key, label = CONTROL_ACCOUNTS['gain_loss_on_disposal']
    assert setting_key == 'gain_loss_on_disposal_account_code'
    assert 'Gain' in label and 'Loss' in label


def test_unassigned_gain_loss_account_raises_when_required(db_session):
    with pytest.raises(ControlAccountError):
        get_control_account('gain_loss_on_disposal', required=True)


def test_unassigned_gain_loss_account_returns_none_when_not_required(db_session):
    assert get_control_account('gain_loss_on_disposal', required=False) is None


def test_assigned_gain_loss_account_resolves(db_session):
    from app.accounts.models import Account
    from app.settings import AppSettings
    account = Account(code='80101', name='Gain/Loss on Disposal of Fixed Assets',
                      account_type='Other Income', normal_balance='Credit')
    db_session.add(account)
    db_session.commit()
    AppSettings.set_setting('gain_loss_on_disposal_account_code', '80101')
    db_session.commit()
    resolved = get_control_account('gain_loss_on_disposal', required=True)
    assert resolved.id == account.id
