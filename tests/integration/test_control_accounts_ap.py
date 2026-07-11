import pytest
from app.accounts.models import Account
from tests.conftest import assign_control_accounts


def _acct(db_session, code, name, atype='Liability', nb='Credit'):
    a = Account(code=code, name=name, account_type=atype,
                classification='Current Liability', normal_balance=nb)
    db_session.add(a); db_session.commit()
    return a


def test_ap_resolves_ap_trade_from_settings(db_session):
    _acct(db_session, '2110', 'AP - Trade')            # non-legacy code
    assign_control_accounts(db_session, ap='2110')
    from app.posting.control_accounts import get_control_account
    assert get_control_account('ap_trade').code == '2110'


def test_ap_unassigned_required_raises(db_session):
    from app.posting.control_accounts import get_control_account, ControlAccountError
    with pytest.raises(ControlAccountError) as exc:
        get_control_account('ap_trade')
    assert 'Accounts Payable control account' in str(exc.value)
