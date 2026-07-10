"""Resolve legacy `accounts.id` -> CAS `Account.id`.

`scripts/ric_coa/reconcile.py` recoded eleven legacy account numbers onto CAS's
magic posting codes when it built the reconciled chart. A plain join on
account_number therefore silently drops Accounts Receivable, Accounts Payable,
Output/Input VAT, Creditable Withholding Tax, WHT-payable and Retained Earnings
-- the highest-value accounts in the book -- while appearing to work for the
other 261. So the map applies the recode overlay and FAILS CLOSED on anything it
cannot resolve.

The overlay is derived from `reconcile.py` rather than retyped, so the two cannot
drift apart. Nine codes come from its RECODES; the remaining two are the seed
leaves it KEEPS (via REPARENTS) whose legacy twins were skipped at import.
"""
from scripts.ric_coa.reconcile import RECODES as _RIC_RECODES

# Legacy 12501/32101 were skipped when the COA was imported; the generic seed's
# own CWT (10212) and Retained Earnings (30201) leaves were kept and reparented
# under the legacy groups instead. So legacy lines pointing at 12501/32101 must
# land on those seed accounts.
_SKIPPED_SEED_LEAVES = {
    '12501': '10212',   # Creditable Withholding Tax
    '32101': '30201',   # Retained Earnings - Unappropriated
}

ACCOUNT_RECODES = {**_RIC_RECODES, **_SKIPPED_SEED_LEAVES}


class LegacyAccountError(RuntimeError):
    """Raised when a legacy account used by a document will not resolve."""


def resolve_account_map(used_ids, legacy_id_to_code, live_code_to_id, recodes):
    """Map every USED legacy account id to a CAS account id, or raise.

    Only accounts actually referenced by a document line need to resolve -- a
    legacy chart carries accounts that were never posted to.
    """
    mapping = {}
    unresolved = []

    for legacy_id in sorted(used_ids):
        raw_code = legacy_id_to_code.get(legacy_id)
        if raw_code is None:
            unresolved.append((legacy_id, None, 'no such legacy account'))
            continue

        code = str(raw_code).strip()
        target = recodes.get(code, code)
        cas_id = live_code_to_id.get(target)
        if cas_id is None:
            note = f'code {code!r}'
            if target != code:
                note += f' recoded to {target!r}'
            unresolved.append((legacy_id, code, f'{note} absent from the CAS chart'))
            continue

        mapping[legacy_id] = cas_id

    if unresolved:
        lines = '\n'.join(
            f'  legacy account_id={lid} {reason}' for lid, _code, reason in unresolved
        )
        raise LegacyAccountError(
            f'{len(unresolved)} used legacy account(s) do not resolve:\n{lines}'
        )

    return mapping


# --- adapters over the two databases -------------------------------------------------

def used_account_ids(legacy_conn):
    """Every `account_id` referenced by any line, across all ten books."""
    from scripts.legacy_import.schema import BOOKS

    used = set()
    for book in BOOKS:
        rows = legacy_conn.execute(
            f'SELECT DISTINCT account_id FROM "{book.entry_table}"'
        )
        used.update(row[0] for row in rows)
    used.discard(None)
    return used


def legacy_account_codes(legacy_conn):
    return {
        row[0]: str(row[1]).strip()
        for row in legacy_conn.execute('SELECT id, account_number FROM accounts')
    }


def live_account_codes(session):
    from app.accounts.models import Account
    return {
        str(code).strip(): account_id
        for account_id, code in session.query(Account.id, Account.code).all()
    }


def build_account_map(legacy_conn, session, recodes=None):
    """Convenience wrapper: read both sides, resolve, or raise."""
    return resolve_account_map(
        used_ids=used_account_ids(legacy_conn),
        legacy_id_to_code=legacy_account_codes(legacy_conn),
        live_code_to_id=live_account_codes(session),
        recodes=ACCOUNT_RECODES if recodes is None else recodes,
    )
