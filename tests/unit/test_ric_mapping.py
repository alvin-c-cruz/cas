import pytest
from scripts.ric_coa.mapping import assign_group, build_accounts, GROUPS

pytestmark = [pytest.mark.unit]

# a small legacy fixture: (account_number, account_title, legacy_type)
ROWS = [
    ("11101", "CASH ON HAND/CASH SALES",        "Cash and Cash Equivalents"),
    ("11201", "ACCOUNTS RECEIVABLE-TRADE",      "Trade Receivable"),
    ("11202", "ALLOWANCE FOR BAD DEBTS",        "Other Current Assets"),
    ("11301", "RAW MATERIALS INVENTORY-TINCAN", "Other Current Assets"),
    ("12201", "OFFICE FCTY - TAGUIG",           "Fixed Assets"),
    ("12301", "ACC. DEP'N-OFFICE FCTY",         "Fixed Assets"),
    ("12501", "CREDITABLE WITHHOLDING TAX",     "Other Assets"),
    ("64101", "INDIRECT LABOR - Tincan/Plastic","Factory Overhead"),
    ("65101", "FO - TELEPHONE & POSTAGE",       "Factory Overhead"),
]

def test_assign_group_routes_by_type_and_prefix():
    assert assign_group("Cash and Cash Equivalents", "11101") == "111"
    assert assign_group("Trade Receivable", "11201") == "112"
    assert assign_group("Other Current Assets", "11202") == "112N"   # advances, not trade
    assert assign_group("Other Current Assets", "11301") == "113"
    assert assign_group("Fixed Assets", "12201") == "122"
    assert assign_group("Fixed Assets", "12301") == "123"            # accumulated depreciation
    assert assign_group("Other Assets", "12501") == "125"
    assert assign_group("Factory Overhead", "64101") == "641"
    assert assign_group("Factory Overhead", "65101") == "651"

def test_build_accounts_shapes_groups_and_leaves():
    specs = build_accounts(ROWS)
    groups = [s for s in specs if s.is_group]
    leaves = [s for s in specs if not s.is_group]
    assert len(leaves) == len(ROWS)
    # groups precede leaves, one per used code
    assert all(g.is_group for g in specs[:len(groups)])
    assert {g.code for g in groups} == {"111","112","112N","113","122","123","125","641","651"}
    # leaf name is proper-cased; parent is its group
    cash = next(l for l in leaves if l.code == "11101")
    assert cash.name == "Cash on Hand/Cash Sales"
    assert cash.parent_code == "111" and cash.account_type == "Asset" and cash.classification == "Current"

def test_contra_override_to_credit():
    specs = build_accounts(ROWS)
    accdep = next(s for s in specs if s.code == "12301")   # accumulated depreciation leaf
    allow  = next(s for s in specs if s.code == "11202")   # allowance for bad debts leaf
    assert accdep.normal_balance == "credit"
    assert allow.normal_balance == "credit"
    # a normal asset leaf stays debit
    assert next(s for s in specs if s.code == "11101").normal_balance == "debit"
    # the 123 GROUP header is NOT contra-overridden
    assert next(s for s in specs if s.is_group and s.code == "123").normal_balance == "debit"

def test_classification_override_125_current():
    specs = build_accounts(ROWS)
    g125 = next(s for s in specs if s.is_group and s.code == "125")
    l125 = next(s for s in specs if s.code == "12501")
    assert g125.classification == "Current" and l125.classification == "Current"

def test_group_registry_has_28_entries():
    assert len(GROUPS) == 28
