from app.seeds.construction_coa import CONSTRUCTION_COA
from app.accounts.account_types import ACCOUNT_TYPES, TYPES_NEEDING_CLASSIFICATION

MAGIC_CODES = {
    '10201': ('Asset', 'debit'), '10212': ('Asset', 'debit'),
    '20101': ('Liability', 'credit'), '20301': ('Liability', 'credit'),
    '30201': ('Equity', 'credit'), '30301': ('Equity', 'credit'),
}
POSTABLE_MAGIC_LEAVES = ['10201', '10212', '20101', '20301', '30201']


def _codes():
    return [r[0] for r in CONSTRUCTION_COA]


def _parents_used():
    return {r[5] for r in CONSTRUCTION_COA if r[5] is not None}


def test_no_duplicate_codes():
    codes = _codes()
    assert len(codes) == len(set(codes))


def test_no_duplicate_names():
    names = [r[1] for r in CONSTRUCTION_COA]
    assert len(names) == len(set(names))


def test_parents_resolve():
    codes = set(_codes())
    for code, name, atype, cl, nb, parent in CONSTRUCTION_COA:
        if parent is not None:
            assert parent in codes, f"{code}: parent {parent} not in COA"


def test_magic_codes_present_with_correct_type_and_balance():
    by_code = {r[0]: r for r in CONSTRUCTION_COA}
    for code, (atype, nb) in MAGIC_CODES.items():
        assert code in by_code, f"magic code {code} missing"
        assert by_code[code][2] == atype, f"{code}: type {by_code[code][2]} != {atype}"
        assert by_code[code][4] == nb, f"{code}: nb {by_code[code][4]} != {nb}"


def test_account_types_valid():
    for code, name, atype, cl, nb, parent in CONSTRUCTION_COA:
        assert atype in ACCOUNT_TYPES, f"{code}: invalid type {atype}"


def test_classification_rule():
    for code, name, atype, cl, nb, parent in CONSTRUCTION_COA:
        if atype in TYPES_NEEDING_CLASSIFICATION:
            assert cl in ('Current', 'Non-Current'), f"{code} needs classification"
        else:
            assert cl is None, f"{code} must have no classification"


def test_normal_balance_values():
    for code, name, atype, cl, nb, parent in CONSTRUCTION_COA:
        assert nb in ('debit', 'credit'), f"{code}: bad normal_balance {nb}"


def test_postable_magic_codes_are_leaves():
    by_code = {r[0]: r for r in CONSTRUCTION_COA}
    used = _parents_used()
    for code in POSTABLE_MAGIC_LEAVES:
        assert by_code[code][5] is not None, f"{code} must have a parent (be postable)"
        assert code not in used, f"{code} must be a leaf (no children)"


def test_no_orphan_top_level_leaves():
    used = _parents_used()
    for code, name, atype, cl, nb, parent in CONSTRUCTION_COA:
        if parent is None and code not in used:
            assert code == '30301', f"top-level {code} has no children -> non-postable orphan"


def test_ascii_only_names():
    for code, name, atype, cl, nb, parent in CONSTRUCTION_COA:
        assert name.isascii(), f"{code}: non-ASCII name {name!r}"
