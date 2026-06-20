"""WithholdingTax carries per-ATC payable/receivable GL account FKs.

payable_account  -> used on APV/CDV (what we withhold from a vendor)
receivable_account -> used on SI/CRV (creditable WHT a customer withholds from us)
"""
import pytest
from app.withholding_tax.models import WithholdingTax
from app.accounts.models import Account

pytestmark = [pytest.mark.unit]


def test_wht_maps_payable_and_receivable_accounts(db_session):
    pay = Account(code='22105-4', name='WHT Payable 10%', account_type='Liability',
                  normal_balance='credit', is_active=True)
    recv = Account(code='10212', name='Creditable WHT Receivable', account_type='Asset',
                   normal_balance='debit', is_active=True)
    db_session.add_all([pay, recv])
    db_session.commit()

    wht = WithholdingTax(code='WC010', name='Professional Fees', rate=10, is_active=True,
                         payable_account_id=pay.id, receivable_account_id=recv.id)
    db_session.add(wht)
    db_session.commit()

    got = WithholdingTax.query.filter_by(code='WC010').first()
    assert got.payable_account.code == '22105-4'
    assert got.receivable_account.code == '10212'
    d = got.to_dict()
    assert d['payable_account_code'] == '22105-4'
    assert d['receivable_account_code'] == '10212'
