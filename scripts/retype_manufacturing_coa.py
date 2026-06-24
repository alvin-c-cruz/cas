"""One-off script: re-type the manufacturing COA in cas_demo.db to the new FS taxonomy.

Usage (from repo root, AFTER reviewing the maps below):
    PYTHONPATH=. python scripts/retype_manufacturing_coa.py

DO NOT run this against a production DB without a backup.

The 10 synthetic "classification-wrapper" accounts (10000, 11000, 20000, 21000,
30000, 40000, 50100, 50200, 50300, 50400) are deleted; their direct children are
re-parented to top-level (parent_id=None).

The remaining 146 accounts are re-typed per TYPE_BY_CODE / CLASS_BY_CODE.
"""

# ---------------------------------------------------------------------------
# The 10 wrapper codes to delete
# ---------------------------------------------------------------------------
WRAPPER_CODES = {
    '10000',  # CURRENT ASSETS (synthetic wrapper)
    '11000',  # NON-CURRENT ASSETS (synthetic wrapper)
    '20000',  # CURRENT LIABILITIES (synthetic wrapper)
    '21000',  # NON-CURRENT LIABILITIES (synthetic wrapper)
    '30000',  # SHAREHOLDERS' EQUITY (synthetic wrapper)
    '40000',  # REVENUE (synthetic wrapper)
    '50100',  # COST OF GOODS SOLD (synthetic wrapper)
    '50200',  # OPERATING EXPENSES (synthetic wrapper)
    '50300',  # FINANCIAL EXPENSES (synthetic wrapper)
    '50400',  # INCOME TAX EXPENSE (synthetic wrapper)
}

# ---------------------------------------------------------------------------
# TYPE_BY_CODE — new account_type for each of the 146 surviving accounts
# ---------------------------------------------------------------------------
TYPE_BY_CODE = {
    # -----------------------------------------------------------------------
    # ASSETS — Current (10xxx)
    # -----------------------------------------------------------------------
    # Cash and Cash Equivalents group + children
    '10100': 'Asset',
    '10101': 'Asset',
    '10102': 'Asset',
    '10110': 'Asset',
    '10111': 'Asset',
    '10112': 'Asset',
    # Trade and Other Receivables group + children
    '10200': 'Asset',
    '10201': 'Asset',
    '10202': 'Asset',
    '10205': 'Asset',
    '10210': 'Asset',
    '10211': 'Asset',
    '10212': 'Asset',
    # Inventories group + children
    '10300': 'Asset',
    '10301': 'Asset',
    '10302': 'Asset',
    '10303': 'Asset',
    '10304': 'Asset',
    '10305': 'Asset',
    # Prepaid Expenses and Other Current Assets group + children
    '10400': 'Asset',
    '10401': 'Asset',
    '10402': 'Asset',
    '10403': 'Asset',
    # Input VAT group + children
    '10500': 'Asset',
    '10501': 'Asset',
    '10502': 'Asset',
    '10503': 'Asset',
    '10504': 'Asset',
    '10505': 'Asset',
    '10506': 'Asset',

    # -----------------------------------------------------------------------
    # ASSETS — Non-Current (11xxx)
    # -----------------------------------------------------------------------
    # Property, Plant and Equipment group + children
    '11100': 'Asset',
    '11101': 'Asset',
    '11110': 'Asset',
    '11111': 'Asset',
    '11120': 'Asset',
    '11121': 'Asset',
    '11130': 'Asset',
    '11131': 'Asset',
    '11140': 'Asset',
    '11141': 'Asset',
    '11150': 'Asset',
    '11151': 'Asset',
    '11160': 'Asset',
    '11161': 'Asset',
    '11170': 'Asset',
    '11171': 'Asset',
    '11180': 'Asset',
    # Intangible Assets group + children
    '11200': 'Asset',
    '11201': 'Asset',
    '11202': 'Asset',
    # Other Non-Current Assets group + children
    '11300': 'Asset',
    '11301': 'Asset',
    '11302': 'Asset',

    # -----------------------------------------------------------------------
    # LIABILITIES — Current (20xxx)
    # -----------------------------------------------------------------------
    # Trade and Other Payables group + children
    '20100': 'Liability',
    '20101': 'Liability',
    '20102': 'Liability',
    '20103': 'Liability',
    '20104': 'Liability',
    '20105': 'Liability',
    '20106': 'Liability',
    '20107': 'Liability',
    '20108': 'Liability',
    '20109': 'Liability',
    # Output VAT group + child
    '20200': 'Liability',
    '20201': 'Liability',
    # Withholding and Other Taxes Payable group + children
    '20300': 'Liability',
    '20301': 'Liability',
    '20302': 'Liability',
    '20303': 'Liability',
    '20304': 'Liability',
    '20305': 'Liability',
    # Statutory Payables group + children
    '20400': 'Liability',
    '20401': 'Liability',
    '20402': 'Liability',
    '20403': 'Liability',
    '20404': 'Liability',

    # -----------------------------------------------------------------------
    # LIABILITIES — Non-Current (21xxx)
    # -----------------------------------------------------------------------
    '21100': 'Liability',
    '21200': 'Liability',
    '21300': 'Liability',
    '21400': 'Liability',

    # -----------------------------------------------------------------------
    # EQUITY (30xxx) — no classification
    # -----------------------------------------------------------------------
    '30100': 'Equity',
    '30101': 'Equity',
    '30102': 'Equity',
    '30103': 'Equity',
    '30104': 'Equity',
    '30110': 'Equity',
    '30120': 'Equity',
    '30200': 'Equity',
    '30201': 'Equity',
    '30202': 'Equity',
    '30301': 'Equity',
    '30401': 'Equity',

    # -----------------------------------------------------------------------
    # REVENUE (40xxx)
    # -----------------------------------------------------------------------
    # Sales group
    '40100': 'Revenue',
    '40101': 'Revenue',            # Sales - Finished Goods
    '40102': 'Revenue',            # Sales - Job Orders/Services
    '40103': 'Contra-Revenue',     # Sales Returns and Allowances
    '40104': 'Contra-Revenue',     # Sales Discounts
    # Other Income group
    '40200': 'Other Income',
    '40201': 'Other Income',       # Interest Income
    '40202': 'Other Income',       # Scrap Sales
    '40203': 'Other Income',       # Gain on Sale of Property and Equipment
    '40204': 'Other Income',       # Foreign Exchange Gain
    '40205': 'Other Income',       # Rental Income
    '40206': 'Other Income',       # Miscellaneous Income

    # -----------------------------------------------------------------------
    # COST OF GOODS SOLD (50101, 50110, 50111, 50120–50130)
    # -----------------------------------------------------------------------
    '50101': 'Cost of Goods Sold',
    '50110': 'Cost of Goods Sold',
    '50111': 'Cost of Goods Sold',
    '50120': 'Cost of Goods Sold',  # Manufacturing Overhead (group)
    '50121': 'Cost of Goods Sold',
    '50122': 'Cost of Goods Sold',
    '50123': 'Cost of Goods Sold',
    '50124': 'Cost of Goods Sold',
    '50125': 'Cost of Goods Sold',
    '50126': 'Cost of Goods Sold',
    '50127': 'Cost of Goods Sold',
    '50128': 'Cost of Goods Sold',
    '50129': 'Cost of Goods Sold',
    '50130': 'Cost of Goods Sold',

    # -----------------------------------------------------------------------
    # SELLING EXPENSE (50210–50214)
    # -----------------------------------------------------------------------
    '50210': 'Selling Expense',     # Selling and Distribution Expenses (group)
    '50211': 'Selling Expense',
    '50212': 'Selling Expense',
    '50213': 'Selling Expense',
    '50214': 'Selling Expense',

    # -----------------------------------------------------------------------
    # ADMINISTRATIVE EXPENSE (50220–50236)
    # -----------------------------------------------------------------------
    '50220': 'Administrative Expense',  # General and Administrative Expenses (group)
    '50221': 'Administrative Expense',
    '50222': 'Administrative Expense',
    '50223': 'Administrative Expense',
    '50224': 'Administrative Expense',
    '50225': 'Administrative Expense',
    '50226': 'Administrative Expense',
    '50227': 'Administrative Expense',
    '50228': 'Administrative Expense',
    '50229': 'Administrative Expense',
    '50230': 'Administrative Expense',
    '50231': 'Administrative Expense',
    '50232': 'Administrative Expense',
    '50233': 'Administrative Expense',
    '50234': 'Administrative Expense',
    '50235': 'Administrative Expense',
    '50236': 'Administrative Expense',

    # -----------------------------------------------------------------------
    # OTHER EXPENSE (50301–50304)
    # -----------------------------------------------------------------------
    '50301': 'Other Expense',       # Interest Expense
    '50302': 'Other Expense',       # Bank Charges
    '50303': 'Other Expense',       # Foreign Exchange Loss
    '50304': 'Other Expense',       # Loss on Sale of Property and Equipment

    # -----------------------------------------------------------------------
    # INCOME TAX EXPENSE (50401–50402)
    # -----------------------------------------------------------------------
    '50401': 'Income Tax Expense',
    '50402': 'Income Tax Expense',
}

# ---------------------------------------------------------------------------
# CLASS_BY_CODE — classification for Asset and Liability accounts only
# Codes in 10xxx → Current; 11xxx → Non-Current
# Codes in 20xxx → Current; 21xxx → Non-Current
# ---------------------------------------------------------------------------
CLASS_BY_CODE = {code: 'Current'
                 for code in TYPE_BY_CODE
                 if code.startswith('10')}
CLASS_BY_CODE.update({code: 'Non-Current'
                       for code in TYPE_BY_CODE
                       if code.startswith('11')})
CLASS_BY_CODE.update({code: 'Current'
                       for code in TYPE_BY_CODE
                       if code.startswith('20')})
CLASS_BY_CODE.update({code: 'Non-Current'
                       for code in TYPE_BY_CODE
                       if code.startswith('21')})


# ---------------------------------------------------------------------------
# main() — live DB mutation (guarded; controller runs this, not CI)
# ---------------------------------------------------------------------------
def main():
    """Re-type the manufacturing COA in cas_demo.db.

    Steps:
    1. Re-parent direct children of the 10 wrapper accounts to top-level.
    2. Delete the 10 wrapper accounts.
    3. Set account_type / classification per TYPE_BY_CODE / CLASS_BY_CODE.
    4. Print verification summary.
    5. Run IS / BS / CF generators to confirm no exception.
    """
    from flask_app import app
    from app import db
    from app.accounts.models import Account
    from app.reports.financial import (
        generate_income_statement,
        generate_balance_sheet,
        generate_cash_flow,
    )
    from datetime import date

    with app.app_context():
        # ---- Step 1: find the 10 wrapper accounts ---------------------
        wrappers = Account.query.filter(Account.code.in_(WRAPPER_CODES)).all()
        if len(wrappers) != 10:
            found = {a.code for a in wrappers}
            missing = WRAPPER_CODES - found
            extra = found - WRAPPER_CODES
            raise RuntimeError(
                f"Expected 10 wrapper accounts, found {len(wrappers)}. "
                f"Missing: {missing}  Extra: {extra}"
            )

        wrapper_ids = {a.id: a.code for a in wrappers}
        print(f"Found {len(wrappers)} wrapper accounts to delete.")

        # ---- Step 2: re-parent direct children to top-level -----------
        children = Account.query.filter(
            Account.parent_id.in_(wrapper_ids.keys())
        ).all()
        for child in children:
            child.parent_id = None
        db.session.flush()
        print(f"Re-parented {len(children)} direct children to top-level.")

        # ---- Step 3: delete wrappers -----------------------------------
        for wrapper in wrappers:
            db.session.delete(wrapper)
        db.session.flush()
        print("Deleted 10 wrapper accounts.")

        # ---- Step 4: re-type surviving accounts ------------------------
        all_accounts = Account.query.order_by(Account.code).all()
        typed = 0
        skipped = []
        for acct in all_accounts:
            new_type = TYPE_BY_CODE.get(acct.code)
            if new_type is None:
                skipped.append(acct.code)
                continue
            acct.account_type = new_type
            new_class = CLASS_BY_CODE.get(acct.code)
            acct.classification = new_class  # None for non-Asset/Liability
            typed += 1

        if skipped:
            raise RuntimeError(
                f"Found {len(skipped)} accounts not in TYPE_BY_CODE: {skipped}. "
                "Aborting — resolve the map before committing."
            )

        db.session.commit()
        print(f"Re-typed {typed} accounts.")

        # ---- Step 5: verification summary -----------------------------
        all_accounts = Account.query.order_by(Account.code).all()
        total = len(all_accounts)
        type_counts = {}
        for a in all_accounts:
            type_counts[a.account_type] = type_counts.get(a.account_type, 0) + 1

        print()
        print("=" * 60)
        print(f"VERIFICATION SUMMARY")
        print("=" * 60)
        print(f"Total accounts remaining: {total}")
        print()
        print("Counts per account_type:")
        for t, count in sorted(type_counts.items()):
            print(f"  {t:<30} {count:>3}")

        # Required-code check
        required = {
            '10201': 'Asset',
            '10212': 'Asset',
            '20101': 'Liability',
            '20301': 'Liability',
            '30201': 'Equity',
            '30301': 'Equity',
        }
        print()
        print("Required-code check:")
        all_ok = True
        for code, expected_type in required.items():
            acct = Account.query.filter_by(code=code).first()
            if acct is None:
                print(f"  MISSING  {code}")
                all_ok = False
            elif acct.account_type != expected_type:
                print(f"  WRONG    {code}: expected={expected_type} actual={acct.account_type}")
                all_ok = False
            else:
                print(f"  OK       {code} -> {acct.account_type}")
        if all_ok:
            print("  All required codes present and correctly typed.")

        # Run generators
        print()
        print("Running report generators (should not raise):")
        today = date.today()
        start = date(today.year, 1, 1)

        try:
            is_data = generate_income_statement(start, today)
            print(f"  generate_income_statement: OK ({len(is_data.get('sections', []))} sections)")
        except Exception as e:
            print(f"  generate_income_statement: FAILED — {e}")

        try:
            bs_data = generate_balance_sheet(today)
            print(f"  generate_balance_sheet: OK")
        except Exception as e:
            print(f"  generate_balance_sheet: FAILED — {e}")

        try:
            cf_data = generate_cash_flow(start, today)
            print(f"  generate_cash_flow: OK")
        except Exception as e:
            print(f"  generate_cash_flow: FAILED — {e}")

        print()
        print("Done.")


if __name__ == '__main__':
    main()
