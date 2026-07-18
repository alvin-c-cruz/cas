from datetime import date
from decimal import Decimal
from app import db
from app.accounts.models import Account
from app.fixed_assets.models import FixedAsset, AssetCategory
from app.reports.fixed_asset_schedule import generate_fixed_asset_schedule


def _asset_with_category(db_session, main_branch, category, code, cost, opening_accum=Decimal('0')):
    cost_acct = Account(code=f'175{code[-2:]}1', name=f'{code} Cost', account_type='Asset',
                        normal_balance='Debit')
    accum_acct = Account(code=f'175{code[-2:]}2', name=f'{code} Accum', account_type='Asset',
                         normal_balance='Credit')
    exp_acct = Account(code=f'608{code[-2:]}', name=f'{code} Dep Exp', account_type='Expense',
                       normal_balance='Debit')
    db_session.add_all([cost_acct, accum_acct, exp_acct])
    db_session.commit()
    asset = FixedAsset(
        branch_id=main_branch.id, code=code, name=code, category_id=category.id if category else None,
        acquisition_source_type='opening', acquisition_source_id=None,
        acquisition_source_line_id=None, acquisition_date=date(2024, 1, 1), acquisition_cost=cost,
        cost_account_id=cost_acct.id, accumulated_depreciation_account_id=accum_acct.id,
        depreciation_expense_account_id=exp_acct.id, depreciation_method='straight_line',
        useful_life_months=60, salvage_value=Decimal('0'),
        opening_accumulated_depreciation=opening_accum, created_by_id=1,
    )
    db_session.add(asset)
    db_session.commit()
    return asset


def test_report_groups_assets_by_category(db_session, main_branch):
    machinery = AssetCategory(name='Machinery')
    db_session.add(machinery)
    db_session.commit()
    _asset_with_category(db_session, main_branch, machinery, 'FA-S01', Decimal('60000.00'))
    _asset_with_category(db_session, main_branch, None, 'FA-S02', Decimal('30000.00'))

    report = generate_fixed_asset_schedule(main_branch.id, date(2026, 6, 30))
    category_names = {c['category_name'] for c in report['categories']}
    assert 'Machinery' in category_names
    assert 'Unassigned' in category_names or None in category_names


def test_report_excludes_disposed_assets(db_session, main_branch):
    asset = _asset_with_category(db_session, main_branch, None, 'FA-S03', Decimal('10000.00'))
    asset.status = 'disposed'
    db_session.commit()
    report = generate_fixed_asset_schedule(main_branch.id, date(2026, 6, 30))
    all_codes = [a['code'] for cat in report['categories'] for a in cat['assets']]
    assert 'FA-S03' not in all_codes


def test_grand_total_sums_all_categories(db_session, main_branch):
    machinery = AssetCategory(name='Machinery')
    db_session.add(machinery)
    db_session.commit()
    _asset_with_category(db_session, main_branch, machinery, 'FA-S04', Decimal('60000.00'))
    _asset_with_category(db_session, main_branch, None, 'FA-S05', Decimal('30000.00'))
    report = generate_fixed_asset_schedule(main_branch.id, date(2026, 6, 30))
    assert report['grand_total']['cost'] == Decimal('90000.00')


def test_reconciliation_ties_subledger_cost_to_gl_when_untouched(db_session, main_branch):
    """No JE has ever posted to the cost account in this test (opening-source
    asset, no tagged AP/CDV/JV line) -- the GL balance for that account is 0,
    so the reconciliation is expected to show a variance (0 GL vs a nonzero
    subledger), not falsely claim is_reconciled=True. This proves the banner
    reads a REAL GL query, not just echoing the subledger total back."""
    _asset_with_category(db_session, main_branch, None, 'FA-S06', Decimal('60000.00'))
    report = generate_fixed_asset_schedule(main_branch.id, date(2026, 6, 30))
    assert report['reconciliation']['is_reconciled'] is False
    line = next(l for l in report['reconciliation']['lines'] if l['subledger_total'] != 0)
    assert line['gl_balance'] == Decimal('0')
    assert line['variance'] == line['subledger_total']
