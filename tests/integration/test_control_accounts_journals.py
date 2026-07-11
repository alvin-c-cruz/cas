"""Feature tests for BUG-POSTING-HARDCODED-CONTROL-ACCOUNTS Task 6: the
columnar-journal report grouping helpers (_gl_account_ids, _si_gl_account_ids,
_cr_gl_account_ids) must resolve control accounts via settings
(get_control_account(key, required=False)), not hardcoded legacy codes."""
from app.accounts.models import Account
from tests.conftest import assign_control_accounts


def _acct(db_session, code, name, atype='Liability', nb='Credit'):
    a = Account(code=code, name=name, account_type=atype,
                classification='Current Liability', normal_balance=nb)
    db_session.add(a); db_session.commit()
    return a


def test_ap_journal_ids_resolve_from_settings(db_session, app):
    ap = _acct(db_session, '2110', 'AP - Trade')
    assign_control_accounts(db_session, ap='2110')
    with app.test_request_context():
        from app.journals.views import _gl_account_ids
        ap_id, wt_id, vat_ids = _gl_account_ids()
    assert ap_id == ap.id  # resolved via setting, not the missing legacy 20101


def test_ap_journal_ids_none_when_unassigned(db_session, app):
    with app.test_request_context():
        from app.journals.views import _gl_account_ids
        ap_id, wt_id, vat_ids = _gl_account_ids()
    assert ap_id is None and wt_id is None  # degrades, does not raise
