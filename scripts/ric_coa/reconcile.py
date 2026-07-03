"""Reconcile the RIC COA: retire the generic 25-account seed by recoding RIC's legacy
accounts onto the posting-engine magic codes, repointing VAT-category FKs, keeping the two
non-duplicated seed accounts (CWT/RE) reparented under their legacy groups, and dropping the
rest. Resolves D1-D4 (2026-07-03). Data-only; dry-run by default; --commit writes.

Target must be `ric.db`; refuses if any journal_entry_lines exist (recode/delete unsafe once
posted). BACK UP ric.db before --commit.
"""
import argparse

# recode: legacy code -> posting-engine magic code (delete the seed holding the magic code first)
# D1: WHT 20301 <- 22105 (general suppliers EWT).  D2: output VAT 20201 <- 22103-1 (Output Tax).
RECODES = {
    '11201':  '10201',   # Accounts Receivable - Trade
    '21101':  '20101',   # Accounts Payable - Trade
    '12601':  '10501',   # Input VAT - Capital Goods
    '12602':  '10502',   # Input VAT - Domestic
    '12603':  '10503',   # Input VAT - Services
    '12604':  '10504',   # Input VAT - Importation
    '22103-1':'20201',   # Output VAT - Sales            (D2)
    '22105':  '20301',   # Withholding Tax Payable        (D1)
    '33101':  '30301',   # Income & Expenses Summary
}
# D3: seed CWT/RE have no legacy twin (skipped at import) -> KEEP, reparent under the legacy group.
REPARENTS = {'10212': '125', '30201': '311'}   # seed leaf code -> legacy group code
# generic seed leaves with no recode partner -> drop
DROP_LEAVES = ['10101', '10110', '40101', '40102', '50226']
# seed group headers, empty after the ops above -> drop
DROP_GROUPS = ['10100', '10200', '10500', '20100', '20200', '20300', '30200', '40100', '50220']


def _codes_to_ids(session):
    from app.accounts.models import Account
    return {code: id_ for (id_, code) in session.query(Account.id, Account.code).all()}


def validate(session):
    """Raise RuntimeError if the reconciliation cannot run cleanly against `session`."""
    from app.accounts.models import Account
    c2i = _codes_to_ids(session)
    missing = [c for c in list(RECODES) + list(RECODES.values()) + list(REPARENTS)
               + list(REPARENTS.values()) + DROP_LEAVES + DROP_GROUPS if c not in c2i]
    if missing:
        raise RuntimeError(f'reconcile: expected accounts missing: {missing}')
    jel = session.execute(__import__('sqlalchemy').text(
        "SELECT COUNT(*) FROM journal_entry_lines")).scalar()
    if jel:
        raise RuntimeError(f'reconcile: {jel} journal_entry_lines exist — refusing (recode/delete unsafe)')
    # simulate the final code/name sets for uniqueness
    deleted = set(DROP_LEAVES) | set(DROP_GROUPS) | set(RECODES.values())
    final_codes, final_names = [], []
    for a in Account.query.all():
        if a.code in deleted:
            continue
        final_codes.append(RECODES.get(a.code, a.code))   # recode legacy -> magic
        final_names.append(a.name)
    dup_c = {c for c in final_codes if final_codes.count(c) > 1}
    dup_n = {n for n in final_names if final_names.count(n) > 1}
    if dup_c or dup_n:
        raise RuntimeError(f'reconcile: post-op collisions — codes {sorted(dup_c)[:5]} names {sorted(dup_n)[:5]}')
    return c2i


def summarize():
    return {'recodes': len(RECODES), 'reparents': len(REPARENTS),
            'drop_leaves': len(DROP_LEAVES), 'drop_groups': len(DROP_GROUPS),
            'accounts_removed': len(DROP_LEAVES) + len(DROP_GROUPS) + len(RECODES)}


def _repoint_vat_fks(session, c2i):
    from app.accounts.models import Account
    from app.vat_categories.models import VATCategory
    from app.sales_vat_categories.models import SalesVATCategory
    magic_to_legacy = {m: l for l, m in RECODES.items()}
    n = 0
    for model, col in [(VATCategory, 'input_vat_account_id'),
                       (SalesVATCategory, 'output_vat_account_id')]:
        for row in model.query.all():
            aid = getattr(row, col)
            acct = session.get(Account, aid) if aid else None
            if acct and acct.code in magic_to_legacy:
                setattr(row, col, c2i[magic_to_legacy[acct.code]])
                n += 1
    return n


def apply(session, user_id=None):
    """Execute the reconciliation on `session` (caller commits). Returns a counts dict."""
    from app.accounts.models import Account
    from app.audit.utils import log_audit
    c2i = validate(session)

    def audit(action, acct, **kw):
        log_audit(module='accounts', action=action, record_id=acct.id,
                  record_identifier=f'{acct.code} {acct.name}', user_id=user_id, **kw)

    fks = _repoint_vat_fks(session, c2i)                                    # 1. FK repoints
    for seed_code, group_code in REPARENTS.items():                        # 2. reparent kept seed
        a = session.get(Account, c2i[seed_code]); a.parent_id = c2i[group_code]
        audit('reparent', a, notes=f'reparented under {group_code}')
    session.flush()
    for code in DROP_LEAVES + list(RECODES.values()):                      # 3. delete seed leaves
        a = session.get(Account, c2i[code]); audit('delete', a, old_values={'code': a.code, 'name': a.name})
        session.delete(a)
    session.flush()
    for legacy, magic in RECODES.items():                                  # 4. recode legacy -> magic
        a = session.get(Account, c2i[legacy]); old = a.code; a.code = magic
        audit('recode', a, old_values={'code': old}, new_values={'code': magic})
    session.flush()
    for code in DROP_GROUPS:                                               # 5. delete empty seed groups
        a = session.get(Account, c2i[code]); audit('delete', a, old_values={'code': a.code, 'name': a.name})
        session.delete(a)
    session.commit()
    return {'fk_repoints': fks, **summarize()}


def _assert_target_is_ric(app):
    uri = str(app.config.get('SQLALCHEMY_DATABASE_URI', ''))
    name = uri.rsplit('/', 1)[-1].rsplit('\\', 1)[-1]
    if name != 'ric.db':
        raise SystemExit(f'SAFETY: target is not ric.db -> {uri}')


def main():
    ap = argparse.ArgumentParser(description='Reconcile RIC COA (retire seed, recode legacy)')
    ap.add_argument('--commit', action='store_true', help='write (default: dry-run)')
    args = ap.parse_args()
    from flask_app import app
    from app import db
    from app.accounts.models import Account
    from app.users.models import User
    with app.app_context():
        _assert_target_is_ric(app)
        print('TARGET :', app.config['SQLALCHEMY_DATABASE_URI'])
        validate(db.session)   # raises on any problem
        print('PLAN   :', summarize())
        print('accounts now:', Account.query.count(), '-> after:', Account.query.count() - summarize()['accounts_removed'])
        if not args.commit:
            print('DRY RUN - nothing written. Re-run with --commit (back up ric.db first).')
            return
        admin = User.query.filter_by(role='admin').first()
        result = apply(db.session, user_id=admin.id if admin else None)
        print('COMMITTED:', result, '- total accounts now:', Account.query.count())


if __name__ == '__main__':
    main()
