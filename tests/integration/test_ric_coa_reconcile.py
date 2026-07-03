import os
import pytest
from app import db
from app.accounts.models import Account
from scripts.ric_coa import reconcile

pytestmark = [pytest.mark.integration]

LEGACY_DB = r"C:\envs\ric-workspace\legacy ric\accounting\instance\data.db"


def test_plan_constants_are_consistent():
    s = reconcile.summarize()
    assert s['recodes'] == 9 and s['reparents'] == 2
    assert s['drop_leaves'] == 5 and s['drop_groups'] == 9
    assert s['accounts_removed'] == 5 + 9 + 9   # drop_leaves + drop_groups + recoded-over seeds = 23
    # no code both recoded and dropped; kept-seed codes are not in any drop list
    assert not (set(reconcile.RECODES.values()) & (set(reconcile.DROP_LEAVES) | set(reconcile.DROP_GROUPS)))
    assert not (set(reconcile.REPARENTS) & set(reconcile.DROP_LEAVES) & set(reconcile.DROP_GROUPS))


def _seed_and_import(session):
    from app.seeds.seed_data import seed_minimal
    from scripts.ric_coa.import_coa import read_legacy, write_accounts
    from scripts.ric_coa.mapping import build_accounts
    seed_minimal()
    write_accounts(build_accounts(read_legacy(LEGACY_DB)), session)
    session.commit()


@pytest.mark.skipif(not os.path.exists(LEGACY_DB), reason="legacy DB not present")
def test_reconcile_retires_seed_and_recodes_legacy(db_session):
    _seed_and_import(db.session)
    before = Account.query.count()

    reconcile.validate(db.session)          # must not raise on the real seeded+imported state
    result = reconcile.apply(db.session, user_id=None)
    assert result['fk_repoints'] == 5

    # every magic code now resolves to exactly ONE account, and to RIC's LEGACY name
    expect_legacy_name = {
        '10201': 'Accounts Receivable-Trade', '20101': 'Accounts Payable-Trade',
        '10501': 'Input Tax - Capital Goods', '20201': 'Output Tax',
        '20301': 'Withholding  Tax Payable-Suppliers', '30301': 'Income & Expenses Summary',
    }
    for code, name in expect_legacy_name.items():
        rows = Account.query.filter_by(code=code).all()
        assert len(rows) == 1, f'{code} should resolve to one account, got {len(rows)}'
        assert rows[0].name == name, f'{code} -> {rows[0].name!r} (expected legacy {name!r})'

    # truly-gone codes = the dropped seed leaves + groups (magic codes persist, moved to legacy)
    for gone in reconcile.DROP_LEAVES + reconcile.DROP_GROUPS:
        assert Account.query.filter_by(code=gone).count() == 0, f'{gone} should be deleted'

    # kept seed accounts reparented under their legacy groups
    assert Account.query.filter_by(code='10212').one().parent_id == Account.query.filter_by(code='125').one().id
    assert Account.query.filter_by(code='30201').one().parent_id == Account.query.filter_by(code='311').one().id

    # VAT-category FK now points at the recoded legacy input-VAT account
    from app.vat_categories.models import VATCategory
    v = VATCategory.query.filter_by(code='V12CG').one()
    assert db.session.get(Account, v.input_vat_account_id).code == '10501'

    # net removal of 23; no duplicate codes or names remain
    assert Account.query.count() == before - 23
    codes = [a.code for a in Account.query.all()]
    names = [a.name for a in Account.query.all()]
    assert len(codes) == len(set(codes)) and len(names) == len(set(names))


@pytest.mark.skipif(not os.path.exists(LEGACY_DB), reason="legacy DB not present")
def test_reconcile_refuses_when_transactions_exist(db_session):
    from app.journal_entries.models import JournalEntry, JournalEntryLine
    from datetime import date
    from app.branches.models import Branch
    _seed_and_import(db.session)
    acct = Account.query.filter_by(code='11201').one()
    je = JournalEntry(entry_number='JE-T-1', entry_date=date(2025, 1, 1), description='t',
                      reference='t', entry_type='sale', status='posted', is_balanced=True,
                      branch_id=Branch.query.first().id, total_debit=0, total_credit=0)
    db.session.add(je); db.session.flush()
    db.session.add(JournalEntryLine(entry_id=je.id, line_number=1, account_id=acct.id,
                                    debit_amount=1, credit_amount=0))
    db.session.commit()
    with pytest.raises(RuntimeError):
        reconcile.validate(db.session)
