import json
import pytest
from app.accounts.models import Account
from app.customers.models import Customer
from app.cash_receipts.models import CashReceiptVoucher
from app.utils import ph_now
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


def _login(client):
    client.post('/login', data={'username': 'admin', 'password': 'admin123'},
                follow_redirects=True)


def test_create_crv_with_ar_trade_unassigned_shows_friendly_flash_not_500(
        client, db_session, admin_user, main_branch):
    """FIX 2 (BUG-POSTING-HARDCODED-CONTROL-ACCOUNTS): _post_crv_je resolves
    ar_trade with required=True even for a revenue-only draft CRV (it always
    creates the CRVArLine credit legs off it). Before the fix, create()'s
    except CRVLineError / except Exception (no except ControlAccountError in
    between) swallowed the friendly ControlAccountError message and surfaced
    the generic 'unexpected error occurred' flash instead. Assert the
    friendly message renders and the request does not 500."""
    _login(client)
    cash = _acct(db_session, '1001', 'Cash on Hand')
    revenue = Account(code='4001', name='Service Revenue', account_type='Income',
                       classification='Operating Revenue', normal_balance='Credit')
    db_session.add(revenue); db_session.commit()
    customer = Customer(code='CRVX01', name='Unassigned AR Customer', is_active=True)
    db_session.add(customer); db_session.commit()

    # WHT/AP/creditable-WHT are irrelevant here; leave ar_trade unassigned.
    assign_control_accounts(db_session, ar='', ap='', creditable_wht='', wht_payable='')

    today = ph_now().date().isoformat()
    resp = client.post('/cash-receipts/create', data={
        'crv_number': 'CR-UNASSIGNED-0001',
        'crv_date': today,
        'customer_id': customer.id,
        'payment_method': 'cash',
        'cash_account_id': cash.id,
        'notes': 'Unassigned control account test',
        'ar_lines': json.dumps([]),
        'revenue_lines': json.dumps([{
            'description': 'Misc revenue',
            'amount': 500,
            'line_total': 500,
            'vat_category': None,
            'vat_rate': 0,
            'vat_amount': 0,
            'account_id': revenue.id,
        }]),
        'vat_override': '0', 'vat_override_value': '0',
        'wt_override': '0', 'wt_override_value': '0',
    }, follow_redirects=True)

    assert resp.status_code == 200  # not a 500
    body = resp.data.decode()
    assert 'Assign the Accounts Receivable control account' in body
    assert 'unexpected error' not in body.lower()
    assert CashReceiptVoucher.query.filter_by(crv_number='CR-UNASSIGNED-0001').first() is None
