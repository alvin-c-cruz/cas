"""The voucher's own print button says "Print Voucher" where other print buttons sit beside it
(owner, 10 Nov 2026, on CDV 1731: "the Print button should be Print Voucher"). The CDV page has
Print Check and Print Deposit Slip beside it; the CRV page has Print Deposit Slip."""
import pytest

from tests.integration.test_cd_check_print import _check_cdv, _open
from tests.integration.test_deposit_slip_crv import cheque_crv  # noqa: F401 (fixture)

pytestmark = [pytest.mark.integration, pytest.mark.cash_disbursements]


def test_the_cdv_page_says_print_voucher(client, db_session, admin_user, main_branch):
    cdv = _check_cdv(db_session, main_branch)
    _open(client, main_branch)
    html = client.get(f'/cash-disbursements/{cdv.id}').get_data(as_text=True)
    assert f'href="/cash-disbursements/{cdv.id}/print"' in html
    assert 'class="btn btn-secondary">Print Voucher</a>' in html
    assert 'class="btn btn-secondary">Print</a>' not in html
    assert '>Print Check</a>' in html and '>Print Deposit Slip</a>' in html


def test_the_crv_page_says_print_voucher(client, db_session, admin_user, main_branch, cheque_crv):
    _open(client, main_branch)
    html = client.get(f'/cash-receipts/{cheque_crv.id}').get_data(as_text=True)
    assert f'href="/cash-receipts/{cheque_crv.id}/print"' in html
    assert 'class="btn btn-secondary">Print Voucher</a>' in html
    assert 'class="btn btn-secondary">Print</a>' not in html
