"""Import the legacy customer and vendor masters.

RIC's live instance has ZERO customers and ZERO vendors, so this is a clean
insert. Codes encode the legacy id (`C001`, `V344`) which keeps them stable
across re-runs and lets a human trace a CAS record back to its legacy row.

The GL replay itself does not reference these -- `JournalEntry` has no customer or
vendor FK, and the counterparty name is snapshotted into the entry description.
They are imported because customers and vendors are core CAS modules the clients
need going forward, not least for the Sales Area.

TINs are preserved verbatim, including the '(VATABLE)' annotations RIC typed into
them; `Customer.tin` / `Vendor.tin` are String(50) and the longest legacy value is
28 characters.
"""
from dataclasses import dataclass


@dataclass
class MasterStats:
    customers_created: int = 0
    customers_existing: int = 0
    vendors_created: int = 0
    vendors_existing: int = 0


def legacy_code(prefix, legacy_id):
    return f'{prefix}{legacy_id:03d}'


def _clean(value, limit):
    if value is None:
        return None
    text = str(value).strip()
    return text[:limit] if text else None


def _import_one(session, conn, model, table, name_col, tin_col, prefix, admin_user_id):
    existing = {code for (code,) in session.query(model.code).all()}
    created = skipped = 0

    rows = conn.execute(
        f'SELECT id, "{name_col}", "{tin_col}" FROM "{table}" ORDER BY id'
    ).fetchall()

    for legacy_id, raw_name, raw_tin in rows:
        code = legacy_code(prefix, legacy_id)
        if code in existing:
            skipped += 1
            continue

        record = model(
            code=code,
            name=_clean(raw_name, 200),
            tin=_clean(raw_tin, 50),
            is_active=True,
        )
        # Vendor has no created_by_id; Customer does.
        if hasattr(model, 'created_by_id'):
            record.created_by_id = admin_user_id
        session.add(record)
        created += 1

    return created, skipped


def import_master_data(session, conn, admin_user_id):
    """Insert customers and vendors. Does not commit -- the caller owns the transaction."""
    from app.customers.models import Customer
    from app.vendors.models import Vendor

    stats = MasterStats()
    stats.customers_created, stats.customers_existing = _import_one(
        session, conn, Customer, 'customers', 'customer_name', 'customer_tin',
        'C', admin_user_id,
    )
    stats.vendors_created, stats.vendors_existing = _import_one(
        session, conn, Vendor, 'vendors', 'vendor_name', 'vendor_tin',
        'V', admin_user_id,
    )
    session.flush()
    return stats
