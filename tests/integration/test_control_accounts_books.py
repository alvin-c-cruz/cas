"""Feature tests for BUG-POSTING-HARDCODED-CONTROL-ACCOUNTS (sweep gap): the
BIR books-of-accounts report grouping helpers (_ap_cd_account_ids,
_si_cr_account_ids in app/reports/books_data.py) must resolve control accounts
via settings (get_control_account(key, required=False)), not hardcoded legacy
codes -- mirrors tests/integration/test_control_accounts_journals.py."""
from app.accounts.models import Account
from tests.conftest import assign_control_accounts


def _acct(db_session, code, name, atype='Liability', nb='Credit'):
    a = Account(code=code, name=name, account_type=atype,
                classification='Current Liability', normal_balance=nb)
    db_session.add(a); db_session.commit()
    return a


def test_ap_cd_ids_resolve_from_settings_non_legacy_coa(db_session, app):
    """AP/CD grouping resolves ap_trade + wht_payable from settings on a
    non-legacy chart (codes that don't match the old hardcoded 20101/20301)."""
    ap = _acct(db_session, '2110', 'AP - Trade')
    wt = _acct(db_session, '2130', 'Withholding Tax Payable')
    assign_control_accounts(db_session, ap='2110', wht_payable='2130')
    with app.test_request_context():
        from app.reports.books_data import _ap_cd_account_ids
        ap_id, wt_id, vat_ids = _ap_cd_account_ids()
    assert ap_id == ap.id
    assert wt_id == wt.id


def test_si_cr_ids_resolve_from_settings_non_legacy_coa(db_session, app):
    """SI/CR grouping resolves ar_trade + creditable_wht from settings on a
    non-legacy chart (codes that don't match the old hardcoded 10201/10212)."""
    ar = _acct(db_session, '1210', 'AR - Trade', atype='Asset',
               nb='Debit')
    wht_recv = _acct(db_session, '1230', 'Creditable Withholding Tax',
                      atype='Asset', nb='Debit')
    assign_control_accounts(db_session, ar='1210', creditable_wht='1230')
    with app.test_request_context():
        from app.reports.books_data import _si_cr_account_ids
        ar_id, wht_recv_id, vat_ids = _si_cr_account_ids()
    assert ar_id == ar.id
    assert wht_recv_id == wht_recv.id


def test_ap_cd_ids_none_when_unassigned(db_session, app):
    """Report path degrades to None (no column) rather than raising when the
    control accounts are unassigned."""
    with app.test_request_context():
        from app.reports.books_data import _ap_cd_account_ids
        ap_id, wt_id, vat_ids = _ap_cd_account_ids()
    assert ap_id is None and wt_id is None


def test_si_cr_ids_none_when_unassigned(db_session, app):
    """Report path degrades to None (no column) rather than raising when the
    control accounts are unassigned."""
    with app.test_request_context():
        from app.reports.books_data import _si_cr_account_ids
        ar_id, wht_recv_id, vat_ids = _si_cr_account_ids()
    assert ar_id is None and wht_recv_id is None
