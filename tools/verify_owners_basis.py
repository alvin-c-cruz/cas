"""Print the owners'-basis reconciliation for a database COPY, so the owners can confirm the
numbers before the switch goes on in production.

    cp instance/ric.db /tmp/ric-verify.db
    SQLALCHEMY_DATABASE_URI=sqlite:////tmp/ric-verify.db python tools/verify_owners_basis.py 2025 2026

Read-only against the copy; never point it at the live file while the server runs.
"""
import os
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parents[1] / '.env')

from app import create_app                                      # noqa: E402
from app.reports.basis import GAAP, OWNERS, owners_basis_enabled, unmapped_categories  # noqa: E402
from app.reports.financial import generate_income_statement, generate_balance_sheet  # noqa: E402
from app.utils import ph_now                                    # noqa: E402


def main(years):
    app = create_app(os.environ.get('FLASK_ENV', 'development'))
    with app.app_context():
        print(f"Owners' basis enabled: {owners_basis_enabled()}")
        print('Unmapped categories:', ', '.join(c.name for c in unmapped_categories()) or 'none')
        today = ph_now().date()
        for y in years:
            end = date(y, 12, 31) if y < today.year else today
            gaap = generate_income_statement(date(y, 1, 1), end, reporting_basis=GAAP)
            own = generate_income_statement(date(y, 1, 1), end, reporting_basis=OWNERS)
            s = own['basis_summary']
            print(f"\n=== FY{y} to {end} ===")
            print(f"GAAP net income                 {gaap['net_income']:>18,.2f}")
            print(f"+ Output VAT moved to income    {s['moved_to_income']:>18,.2f}")
            print(f"- Input VAT moved to expense    {s['moved_to_expense']:>18,.2f}")
            print(f"  Input VAT moved to assets     {s['moved_to_balance_sheet']:>18,.2f}")
            print(f"- VAT expense recognised        {s['vat_expense_total']:>18,.2f}")
            print(f"Untraced VAT (flagged)          {s['untraced_total']:>18,.2f}")
            print(f"= Owners' net income            {own['net_income']:>18,.2f}")
            diff = own['net_income'] - gaap['net_income'] - s['net_income_effect']
            print(f"identity check (should be 0)    {diff:>18,.2f}")
            bs = generate_balance_sheet(end, reporting_basis=OWNERS)
            print(f"Owners' balance sheet balanced: {bs['is_balanced']} (diff {bs['difference']:,.2f})")
            for u in s['untraced'][:20]:
                print(f"  untraced {u['entry_number']} {u['account_code']} {u['amount']:,.2f} {u['reason']}")
            if len(s['untraced']) > 20:
                print(f"  ... {len(s['untraced']) - 20} more")


if __name__ == '__main__':
    main([int(a) for a in sys.argv[1:]] or [ph_now().year])
