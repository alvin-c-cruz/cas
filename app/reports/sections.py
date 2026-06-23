"""Declarative FS section tables + parent roll-up, shared by the generators."""

IS_SECTIONS = [
    {'key': 'revenue',        'label': 'Sales',                           'types': ['Revenue'],                'sign': 1,  'subtotal': None},
    {'key': 'contra_revenue', 'label': 'Less: Sales Returns & Discounts', 'types': ['Contra-Revenue'],         'sign': -1, 'subtotal': 'Net Sales'},
    {'key': 'cogs',           'label': 'Cost of Goods Sold',              'types': ['Cost of Goods Sold'],     'sign': -1, 'subtotal': 'Gross Profit'},
    {'key': 'selling',        'label': 'Selling Expenses',                'types': ['Selling Expense'],        'sign': -1, 'subtotal': None},
    {'key': 'admin',          'label': 'Administrative Expenses',         'types': ['Administrative Expense'], 'sign': -1, 'subtotal': 'Operating Income'},
    {'key': 'other_income',   'label': 'Other Income',                    'types': ['Other Income'],           'sign': 1,  'subtotal': None},
    {'key': 'other_expense',  'label': 'Other Expenses',                  'types': ['Other Expense'],          'sign': -1, 'subtotal': 'Income Before Tax'},
    {'key': 'income_tax',     'label': 'Income Tax Expense',              'types': ['Income Tax Expense'],     'sign': -1, 'subtotal': 'Net Income'},
]

BS_SECTIONS = [
    {'key': 'assets',      'label': 'ASSETS',      'type': 'Asset',     'credit_positive': False, 'divisions': ['Current', 'Non-Current']},
    {'key': 'liabilities', 'label': 'LIABILITIES', 'type': 'Liability', 'credit_positive': True,  'divisions': ['Current', 'Non-Current']},
    {'key': 'equity',      'label': 'EQUITY',      'type': 'Equity',    'credit_positive': True,  'divisions': None},
]


def rollup(rows, accounts):
    """Group contributing leaf rows under their top-level ancestor account.

    rows: [{'account_id','code','name','amount'}]; accounts: all active Account rows.
    Returns [{'code','name','account_id','total','children':[...]}] sorted by code.
    A leaf whose top-level ancestor is itself becomes a single line, children=[].
    """
    by_id = {a.id: a for a in accounts}

    def top_ancestor(acc):
        seen = set()
        while acc.parent_id and acc.parent_id in by_id and acc.id not in seen:
            seen.add(acc.id)
            acc = by_id[acc.parent_id]
        return acc

    groups = {}
    for r in rows:
        acc = by_id.get(r['account_id'])
        top = top_ancestor(acc) if acc else None
        gid = top.id if top else r['account_id']
        gcode = top.code if top else r['code']
        gname = top.name if top else r['name']
        g = groups.setdefault(gid, {'code': gcode, 'name': gname, 'account_id': gid,
                                    'total': 0.0, 'children': []})
        g['total'] = round(g['total'] + r['amount'], 2)
        if not (top and top.id == r['account_id']):
            g['children'].append({'code': r['code'], 'name': r['name'],
                                  'account_id': r['account_id'], 'amount': r['amount']})
    out = sorted(groups.values(), key=lambda x: x['code'] or '')
    for g in out:
        g['children'].sort(key=lambda c: c['code'] or '')
    return out
