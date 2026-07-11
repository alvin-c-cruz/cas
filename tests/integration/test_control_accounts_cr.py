import pytest
from app.accounts.models import Account
from tests.conftest import assign_control_accounts


def _acct(db_session, code, name, atype='Asset', nb='Debit'):
    a = Account(code=code, name=name, account_type=atype,
                classification='Current Asset', normal_balance=nb)
    db_session.add(a); db_session.commit()
    return a


def test_cr_resolves_ar_from_settings(db_session):
    # AR on a non-legacy code; resolver must find it via the setting
    _acct(db_session, '1210', 'AR - Trade')
    assign_control_accounts(db_session, ar='1210')
    from app.posting.control_accounts import get_control_account
    assert get_control_account('ar_trade').code == '1210'


def test_cr_unassigned_ar_optional_none(db_session):
    from app.posting.control_accounts import get_control_account
    assert get_control_account('ar_trade', required=False) is None
