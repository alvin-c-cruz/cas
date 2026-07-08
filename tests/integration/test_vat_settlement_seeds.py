import pytest
from app.seeds import construction_coa, firm_coa
from app.seeds.seed_data import BASELINE_COA

pytestmark = [pytest.mark.integration]


def _codes(coa):
    return {row[0] for row in coa}


def _row(coa, code):
    return next(r for r in coa if r[0] == code)


def test_construction_has_carryover_candidate_at_10507():
    coa = construction_coa.CONSTRUCTION_COA
    assert '10507' in _codes(coa), 'construction chart needs an Excess Input Tax Carry-Over account'
    code, name, atype, cls, nb, parent = _row(coa, '10507')
    assert name == 'Excess Input Tax Carry-Over'
    assert atype == 'Asset' and nb == 'debit' and parent == '10500'
    # 10505 must stay Deferred Input VAT (not repurposed)
    assert _row(coa, '10505')[1] == 'Deferred Input VAT'


@pytest.mark.xfail(
    strict=True,
    reason=(
        "Pre-existing gap, out of Task 1 scope: firm_coa.FIRM_COA currently has no code "
        "'10505' (list stops at 10504 'Input VAT - Importation'), so it does NOT yet have "
        "an Excess Input Tax Carry-Over candidate despite the design brief's premise that "
        "'firm already has both'. Task 1 is construction-chart-only and is explicitly "
        "forbidden from modifying firm_coa.py; closing this gap needs its own approved "
        "seed change. Remove this xfail once firm_coa gains a 10505 carry-over row."
    ),
)
def test_firm_already_has_both_targets():
    coa = firm_coa.FIRM_COA
    assert _row(coa, '20202')[1] == 'VAT Payable'
    assert _row(coa, '10505')[1] == 'Excess Input Tax Carry-Over'


def test_baseline_coa_unchanged_no_new_vat_payable_name():
    # RIC import name-clash guard: the default chart must NOT introduce a 'VAT Payable' name.
    names = {row[1] for row in BASELINE_COA}
    assert 'VAT Payable' not in names
