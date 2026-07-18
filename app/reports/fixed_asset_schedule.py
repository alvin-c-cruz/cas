"""Fixed Asset Schedule report (R-05 Slice 2): subledger totals grouped by
AssetCategory, reconciled to the actual GL balance of each cost/accumulated-
depreciation account -- same discipline as generate_trial_balance's
debit-minus-credit query (app/reports/financial.py)."""
from collections import defaultdict
from decimal import Decimal
from app import db
from app.journal_entries.models import JournalEntry, JournalEntryLine


def _account_gl_balance(account_id, branch_id, as_of_date):
    debit_sum = db.session.query(db.func.sum(JournalEntryLine.debit_amount)).join(
        JournalEntry).filter(
        JournalEntry.status == 'posted', JournalEntry.entry_date <= as_of_date,
        JournalEntry.branch_id == branch_id, JournalEntryLine.account_id == account_id,
    ).scalar() or Decimal('0.00')
    credit_sum = db.session.query(db.func.sum(JournalEntryLine.credit_amount)).join(
        JournalEntry).filter(
        JournalEntry.status == 'posted', JournalEntry.entry_date <= as_of_date,
        JournalEntry.branch_id == branch_id, JournalEntryLine.account_id == account_id,
    ).scalar() or Decimal('0.00')
    return debit_sum - credit_sum


def generate_fixed_asset_schedule(branch_id, as_of_date):
    """For a branch + as-of date: every non-disposed FixedAsset grouped by
    AssetCategory (uncategorized assets grouped under 'Unassigned'), plus a
    reconciliation banner comparing each distinct cost/accumulated-
    depreciation account's SUBLEDGER total (summed from FixedAsset rows) to
    its actual GL balance as of the same date."""
    from app.fixed_assets.models import FixedAsset

    assets = FixedAsset.query.filter_by(branch_id=branch_id, status='active') \
        .filter(FixedAsset.acquisition_date <= as_of_date) \
        .order_by(FixedAsset.code).all()

    by_category = defaultdict(list)
    for asset in assets:
        category_name = asset.category.name if asset.category else 'Unassigned'
        by_category[category_name].append(asset)

    categories = []
    grand_total = {'cost': Decimal('0'), 'accumulated_depreciation': Decimal('0'),
                   'net_book_value': Decimal('0')}
    cost_account_totals = defaultdict(Decimal)
    accum_account_totals = defaultdict(Decimal)

    for category_name in sorted(by_category.keys()):
        rows = []
        subtotal = {'cost': Decimal('0'), 'accumulated_depreciation': Decimal('0'),
                   'net_book_value': Decimal('0')}
        for asset in by_category[category_name]:
            cost = Decimal(str(asset.acquisition_cost))
            accumulated = asset.accumulated_depreciation
            nbv = asset.net_book_value
            rows.append({'code': asset.code, 'name': asset.name, 'cost': cost,
                        'accumulated_depreciation': accumulated, 'net_book_value': nbv})
            subtotal['cost'] += cost
            subtotal['accumulated_depreciation'] += accumulated
            subtotal['net_book_value'] += nbv
            cost_account_totals[asset.cost_account_id] += cost
            accum_account_totals[asset.accumulated_depreciation_account_id] += accumulated

        categories.append({'category_name': category_name, 'assets': rows, 'subtotal': subtotal})
        grand_total['cost'] += subtotal['cost']
        grand_total['accumulated_depreciation'] += subtotal['accumulated_depreciation']
        grand_total['net_book_value'] += subtotal['net_book_value']

    from app.accounts.models import Account
    reconciliation_lines = []
    is_reconciled = True

    for account_id, subledger_total in cost_account_totals.items():
        gl_balance = _account_gl_balance(account_id, branch_id, as_of_date)
        variance = subledger_total - gl_balance
        if variance != Decimal('0'):
            is_reconciled = False
        account = db.session.get(Account, account_id)
        reconciliation_lines.append({
            'account_code': account.code, 'account_name': account.name,
            'subledger_total': subledger_total, 'gl_balance': gl_balance, 'variance': variance,
        })
    for account_id, subledger_total in accum_account_totals.items():
        # Accumulated depreciation is a credit-normal contra-asset; the GL
        # balance query returns debit-minus-credit, so a GL balance that
        # matches the subledger total (also stored/compared as a positive
        # magnitude here) will be NEGATIVE from _account_gl_balance's
        # perspective -- flip sign for the comparison.
        gl_balance = -_account_gl_balance(account_id, branch_id, as_of_date)
        variance = subledger_total - gl_balance
        if variance != Decimal('0'):
            is_reconciled = False
        account = db.session.get(Account, account_id)
        reconciliation_lines.append({
            'account_code': account.code, 'account_name': account.name,
            'subledger_total': subledger_total, 'gl_balance': gl_balance, 'variance': variance,
        })

    return {
        'as_of_date': as_of_date, 'branch_id': branch_id, 'categories': categories,
        'grand_total': grand_total,
        'reconciliation': {'is_reconciled': is_reconciled, 'lines': reconciliation_lines},
    }
