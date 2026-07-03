"""Import the RIC legacy accounting COA into the CAS ric.db (via the app factory)."""
import argparse, sqlite3
from collections import Counter
from scripts.ric_coa.mapping import build_accounts, GROUPS

LEGACY_DEFAULT = r"C:\envs\ric-workspace\legacy ric\accounting\instance\data.db"


def read_legacy(db_path):
    con = sqlite3.connect(db_path)
    try:
        rows = con.execute(
            "SELECT a.account_number, a.account_title, t.account_type "
            "FROM accounts a JOIN account_type t ON a.account_type_id = t.id "
            "ORDER BY a.account_number").fetchall()
    finally:
        con.close()
    return [(str(n), ti, t) for n, ti, t in rows]


def assert_importable(session):
    from app.accounts.models import Account
    existing = {c for (c,) in session.query(Account.code).all()}
    clash = existing & set(GROUPS.keys())          # any group header already present?
    if clash:
        raise RuntimeError(f'{len(clash)} target group codes already exist '
                           f'(rebuild = clear first): {sorted(clash)[:5]}')
    return None


def write_accounts(specs, session):
    from app.accounts.models import Account
    from app.audit.utils import log_audit
    ordered = [s for s in specs if s.is_group] + [s for s in specs if not s.is_group]
    code_to_id = {}
    for s in ordered:
        acct = Account(code=s.code, name=s.name, account_type=s.account_type,
                       classification=s.classification, normal_balance=s.normal_balance,
                       parent_id=(code_to_id[s.parent_code] if s.parent_code else None),
                       is_active=True)
        session.add(acct); session.flush()
        code_to_id[s.code] = acct.id
    session.commit()                                   # accounts land atomically
    for s in ordered:                                  # audit after (log_audit self-commits)
        log_audit(module='accounts', action='import', record_id=code_to_id[s.code],
                  record_identifier=f'{s.code} {s.name}', new_values=s.as_dict())
    n_groups = sum(1 for s in specs if s.is_group)
    return {'groups': n_groups, 'leaves': len(specs) - n_groups}


def summarize(specs):
    leaves = [s for s in specs if not s.is_group]
    by_section = Counter((s.account_type, s.classification) for s in leaves)
    return {
        'groups': sum(1 for s in specs if s.is_group),
        'leaves': len(leaves),
        'contra': sum(1 for s in leaves if s.normal_balance == 'credit' and s.account_type == 'Asset'),
        'by_section': {f'{t}/{c}': n for (t, c), n in sorted(by_section.items())},
    }


def _assert_target_is_ric(app):
    uri = str(app.config.get('SQLALCHEMY_DATABASE_URI', ''))
    name = uri.rsplit('/', 1)[-1].rsplit('\\', 1)[-1]   # db filename component
    if name != 'ric.db':
        raise SystemExit(f'SAFETY: target is not ric.db -> {uri}')


def main():
    ap = argparse.ArgumentParser(description='Import RIC legacy COA into CAS ric.db')
    ap.add_argument('--commit', action='store_true', help='write (default: dry-run)')
    ap.add_argument('--legacy', default=LEGACY_DEFAULT)
    args = ap.parse_args()

    from flask_app import app
    from app import db
    from app.accounts.models import Account

    rows = read_legacy(args.legacy)
    specs = build_accounts(rows)
    with app.app_context():
        _assert_target_is_ric(app)
        print('TARGET :', app.config['SQLALCHEMY_DATABASE_URI'])
        print('SUMMARY:', summarize(specs))
        assert_importable(db.session)
        # per-run leaf-code clash guard
        leaf_codes = [s.code for s in specs if not s.is_group]
        clash = {c for (c,) in db.session.query(Account.code)
                 .filter(Account.code.in_(leaf_codes)).all()}
        if clash:
            raise SystemExit(f'{len(clash)} legacy codes already present -> refusing '
                             f'(rebuild = clear first): {sorted(clash)[:5]}')
        if not args.commit:
            print('DRY RUN - nothing written. Re-run with --commit.')
            return
        result = write_accounts(specs, db.session)
        db.session.commit()
        print('COMMITTED:', result, '- total accounts now:', Account.query.count())


if __name__ == '__main__':
    main()
