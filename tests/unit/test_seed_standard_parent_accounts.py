from app.seeds.seed_data import seed_standard_parent_accounts
from app.seeds.standard_parents_coa import STANDARD_PARENT_ACCOUNTS
from app.accounts.models import Account


def test_seed_creates_all_27_accounts(db_session):
    seed_standard_parent_accounts()
    assert Account.query.count() == 27
    assert len(STANDARD_PARENT_ACCOUNTS) == 27


def test_seed_all_accounts_are_top_level_with_no_parent(db_session):
    seed_standard_parent_accounts()
    for account in Account.query.all():
        assert account.parent_id is None


def test_seed_account_types_and_normal_balances_match_table(db_session):
    seed_standard_parent_accounts()

    cash = Account.query.filter_by(code='111000').first()
    assert cash.name == 'Cash & Cash Equivalents'
    assert cash.account_type == 'Asset'
    assert cash.classification == 'Current'
    assert cash.normal_balance == 'debit'

    accum_dep = Account.query.filter_by(code='122000').first()
    assert accum_dep.account_type == 'Asset'
    assert accum_dep.normal_balance == 'credit'  # contra-asset

    equity = Account.query.filter_by(code='311000').first()
    assert equity.account_type == 'Equity'
    assert equity.classification is None
    assert equity.normal_balance == 'credit'

    other_expense = Account.query.filter_by(code='811000').first()
    assert other_expense.name == 'Other Expenses & Losses'
    assert other_expense.account_type == 'Other Expense'
    assert other_expense.normal_balance == 'debit'


def test_seed_is_idempotent(db_session):
    seed_standard_parent_accounts()
    seed_standard_parent_accounts()
    assert Account.query.count() == 27
