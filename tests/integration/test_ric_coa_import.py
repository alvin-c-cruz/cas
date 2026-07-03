import pytest
from app import db
from app.accounts.models import Account
from scripts.ric_coa.mapping import build_accounts
from scripts.ric_coa.import_coa import write_accounts, assert_importable, summarize

pytestmark = [pytest.mark.integration]

ROWS = [
    ("11101", "CASH ON HAND/CASH SALES",   "Cash and Cash Equivalents"),
    ("11202", "ALLOWANCE FOR BAD DEBTS",   "Other Current Assets"),
    ("12301", "ACC. DEP'N-OFFICE FCTY",    "Fixed Assets"),
    ("65101", "FO - TELEPHONE & POSTAGE",  "Factory Overhead"),
]

def test_write_creates_groups_then_postable_leaves(db_session):
    specs = build_accounts(ROWS)
    result = write_accounts(specs, db.session)
    db.session.commit()
    assert result == {'groups': 4, 'leaves': 4}   # groups 111,112N,123,651
    # leaf is postable: has a parent and no children
    leaf = Account.query.filter_by(code="11101").one()
    assert leaf.parent_id is not None
    assert leaf.name == "Cash on Hand/Cash Sales"
    # group is non-postable: top-level
    grp = Account.query.filter_by(code="111").one()
    assert grp.parent_id is None
    # contra leaf stored credit
    assert Account.query.filter_by(code="12301").one().normal_balance == "credit"

def test_write_audits_each_account(db_session):
    from app.audit.models import AuditLog
    write_accounts(build_accounts(ROWS), db.session)
    db.session.commit()
    imported = AuditLog.query.filter_by(module='accounts', action='import').count()
    assert imported == 4 + 4   # groups + leaves

def test_assert_importable_blocks_on_existing_code(db_session):
    write_accounts(build_accounts(ROWS), db.session)
    db.session.commit()
    with pytest.raises(RuntimeError):
        assert_importable(db.session)   # 11101 now exists

def test_summarize_counts(db_session):
    s = summarize(build_accounts(ROWS))
    assert s['leaves'] == 4 and s['contra'] == 2   # 11202 + 12301
