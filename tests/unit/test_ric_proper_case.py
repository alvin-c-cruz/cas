import pytest
from scripts.ric_coa.proper_case import proper_case

pytestmark = [pytest.mark.unit]

@pytest.mark.parametrize("src,expect", [
    ("CASH ON HAND/CASH SALES",              "Cash on Hand/Cash Sales"),
    ("CASH IN BANK - TIME DEPOSIT (RCC)",    "Cash in Bank - Time Deposit (RCC)"),
    ("BPI-00008-85",                          "BPI-00008-85"),
    ("CHINA BANK-361-0",                      "China Bank-361-0"),
    ("CHINA BANK $ 520000577",                "China Bank $ 520000577"),
    ("ACC. DEP'N-OFFICE FCTY Q.C. (TAGUIG)",  "Acc. Dep'n-Office Fcty Q.C. (Taguig)"),
    ("13TH MO. PAY - TINCAN",                 "13th Mo. Pay - Tincan"),
    ("VAT PAYABLE",                           "VAT Payable"),
    ("X'MAS T-SHIRT",                         "X'mas T-Shirt"),
    ("PHILHEALTH PREMIUM PAYABLE",            "PhilHealth Premium Payable"),
    ("FO - LIGHTS & WATER - TINCAN",          "FO - Lights & Water - Tincan"),
    ("WITHHOLDING TAX PAYABLE-SUPPLIERS - 1/2%", "Withholding Tax Payable-Suppliers - 1/2%"),
    ("ACCOUNTS RECEIVABLE-PDC",               "Accounts Receivable-PDC"),
    ("SSS SALARY LOAN PAYABLE",               "SSS Salary Loan Payable"),
])
def test_proper_case_cases(src, expect):
    assert proper_case(src) == expect

def test_proper_case_is_case_only():
    # transform must never add/drop/reorder characters — only change case
    for s in ["ACC. DEP'N-MOLDS & DIES - PLASTIC", "INPUT TAX - CAPITAL GOODS", "13TH MO. PAY"]:
        assert proper_case(s).upper() == s.upper()
