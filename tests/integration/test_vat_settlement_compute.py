import pytest
from decimal import Decimal
from datetime import date

from app import db
from app.accounts.models import Account
from app.settings import AppSettings
from app.journal_entries.models import JournalEntry, JournalEntryLine
from app.vat_settlement import service

pytestmark = [pytest.mark.integration]


def _acct(code, name, typ, nb):
    a = Account(code=code, name=name, account_type=typ, normal_balance=nb, is_active=True)
    db.session.add(a); db.session.flush()
    return a


def _je(branch_id, d, lines, entry_type='sale'):
    je = JournalEntry(entry_number=f'T-{d.isoformat()}-{JournalEntry.query.count()+1}',
                      entry_date=d, description='t', entry_type=entry_type,
                      branch_id=branch_id, status='posted',
                      total_debit=0, total_credit=0, is_balanced=True)
    db.session.add(je); db.session.flush()
    for i, (aid, dr, cr) in enumerate(lines, 1):
        db.session.add(JournalEntryLine(entry_id=je.id, line_number=i, account_id=aid,
                                        debit_amount=Decimal(str(dr)), credit_amount=Decimal(str(cr))))
    db.session.flush()
    return je


def _vat_world(main_branch):
    """Minimal VAT accounts + categories + settings; returns account handles."""
    from app.vat_categories.models import VATCategory
    from app.sales_vat_categories.models import SalesVATCategory
    inp = _acct('10501', 'Input VAT - Capital Goods', 'Asset', 'debit')
    out = _acct('20201', 'Output VAT - Sales', 'Liability', 'credit')
    payable = _acct('20202', 'VAT Payable', 'Liability', 'credit')
    carry = _acct('10505', 'Excess Input Tax Carry-Over', 'Asset', 'debit')
    ar = _acct('10201', 'Accounts Receivable', 'Asset', 'debit')
    ap = _acct('20101', 'Accounts Payable', 'Liability', 'credit')
    db.session.add(VATCategory(code='V12CG', name='Input 12%', rate=Decimal('12.00'),
                               is_active=True, input_vat_account_id=inp.id))
    db.session.add(SalesVATCategory(code='V12', name='Sales 12%', rate=Decimal('12.00'),
                                    transaction_nature='regular', is_active=True,
                                    output_vat_account_id=out.id))
    AppSettings.set_setting('vat_payable_account_code', '20202')
    AppSettings.set_setting('input_vat_carryover_account_code', '10505')
    db.session.flush()
    return dict(inp=inp, out=out, payable=payable, carry=carry, ar=ar, ap=ap)


def test_net_payable_position(db_session, main_branch):
    w = _vat_world(main_branch)
    # Q3 2025 output 120k (credit out), input 50k (debit inp)
    _je(main_branch.id, date(2025, 7, 10), [(w['ar'].id, 120000, 0), (w['out'].id, 0, 120000)])
    _je(main_branch.id, date(2025, 8, 10), [(w['inp'].id, 50000, 0), (w['ap'].id, 0, 50000)])
    db.session.commit()
    pos = service.compute_vat_position(2025, 3)
    assert pos['output_vat'] == Decimal('120000.00')
    assert pos['input_vat'] == Decimal('50000.00')
    assert pos['prior_carryover'] == Decimal('0.00')
    assert pos['net_payable'] == Decimal('70000.00')
    assert pos['new_carryover'] == Decimal('0.00')


def test_net_creditable_position(db_session, main_branch):
    w = _vat_world(main_branch)
    _je(main_branch.id, date(2025, 7, 10), [(w['ar'].id, 20000, 0), (w['out'].id, 0, 20000)])
    _je(main_branch.id, date(2025, 8, 10), [(w['inp'].id, 100000, 0), (w['ap'].id, 0, 100000)])
    db.session.commit()
    pos = service.compute_vat_position(2025, 3)
    assert pos['net_payable'] == Decimal('0.00')
    assert pos['new_carryover'] == Decimal('80000.00')


def test_prior_carryover_consumed_into_payable(db_session, main_branch):
    w = _vat_world(main_branch)
    # realistic prior state: a Q2 purchase (input Dr 30k) that the Q2 settlement then
    # clears, moving the 30k into carryover ahead of the quarter under test (Q3)
    _je(main_branch.id, date(2025, 5, 1), [(w['inp'].id, 30000, 0), (w['ap'].id, 0, 30000)])
    _je(main_branch.id, date(2025, 6, 1), [(w['carry'].id, 30000, 0), (w['inp'].id, 0, 30000)],
        entry_type='vat_settlement')
    _je(main_branch.id, date(2025, 7, 10), [(w['ar'].id, 100000, 0), (w['out'].id, 0, 100000)])
    _je(main_branch.id, date(2025, 8, 10), [(w['inp'].id, 10000, 0), (w['ap'].id, 0, 10000)])
    db.session.commit()
    pos = service.compute_vat_position(2025, 3)
    assert pos['prior_carryover'] == Decimal('30000.00')
    assert pos['creditable'] == Decimal('40000.00')     # 10k input + 30k prior
    assert pos['net_payable'] == Decimal('60000.00')    # 100k - 40k
    assert pos['new_carryover'] == Decimal('0.00')


def test_tieout_invariant_breaks_on_unsettled_prior_movement(db_session, main_branch):
    """A prior-quarter output posting left unsettled makes ending-balance != quarter-movement."""
    w = _vat_world(main_branch)
    _je(main_branch.id, date(2025, 4, 10), [(w['ar'].id, 99999, 0), (w['out'].id, 0, 99999)])  # Q2, unsettled
    _je(main_branch.id, date(2025, 7, 10), [(w['ar'].id, 120000, 0), (w['out'].id, 0, 120000)])  # Q3
    db.session.commit()
    with pytest.raises(ValueError):
        service.compute_vat_position(2025, 3)


def test_zero_rated_sale_contributes_no_output_vat(db_session, main_branch):
    from app.sales_vat_categories.models import SalesVATCategory
    w = _vat_world(main_branch)
    db.session.add(SalesVATCategory(code='V0', name='Zero-Rated', rate=Decimal('0.00'),
                                    transaction_nature='zero_export', is_active=True,
                                    output_vat_account_id=None))
    db.session.commit()
    assert None not in service.output_account_ids()           # V0's null account is not a source
    _je(main_branch.id, date(2025, 7, 10), [(w['ar'].id, 120000, 0), (w['out'].id, 0, 120000)])
    db.session.commit()
    pos = service.compute_vat_position(2025, 3)
    assert pos['output_vat'] == Decimal('120000.00')          # only the 12% sale; V0 added nothing


def test_resolve_target_fails_closed_when_unset(db_session, main_branch):
    _vat_world(main_branch)
    AppSettings.query.filter_by(key='vat_payable_account_code').delete()
    # also remove the account so code-default resolution can't find it either
    Account.query.filter_by(code='20202').delete()
    db.session.commit()
    with pytest.raises(ValueError):
        service.compute_vat_position(2025, 3)
