"""Which stored layout applies, and the library listing behind the dropdowns.

Returns RAW payload strings. Sanitizing stays where it already is, in
preprinted_base.sanitize_layout, so there is exactly one place a layout is
validated no matter which store it came from.
"""
from app.print_layouts.models import PrintLayout, PrintLayoutDevicePref


def list_layouts(doc_type, scope_id):
    """The library for one scope, defaults first then by name -- the dropdown order."""
    return (PrintLayout.query
            .filter_by(doc_type=doc_type, scope_id=scope_id or 0)
            .order_by(PrintLayout.is_default.desc(), PrintLayout.name.asc())
            .all())


def default_layout_row(doc_type, scope_id):
    return PrintLayout.query.filter_by(doc_type=doc_type, scope_id=scope_id or 0,
                                       is_default=True).first()


def resolve_layout(doc_type, scope_id, device_id=None):
    """The PrintLayout that applies here, or None. Device pref, then default, then
    the first row. A pref whose layout was deleted holds layout_id NULL and falls
    through rather than raising -- that is AC 4."""
    scope_id = scope_id or 0
    if device_id:
        pref = PrintLayoutDevicePref.query.filter_by(
            device_id=device_id, doc_type=doc_type, scope_id=scope_id).first()
        if pref is not None and pref.layout is not None:
            return pref.layout
    row = default_layout_row(doc_type, scope_id)
    if row is not None:
        return row
    return (PrintLayout.query
            .filter_by(doc_type=doc_type, scope_id=scope_id)
            .order_by(PrintLayout.id.asc()).first())


def resolve_payload(doc_type, scope_id, device_id=None):
    row = resolve_layout(doc_type, scope_id, device_id)
    return row.payload if row is not None else None


def _commit_or_refuse_duplicate(row, name):
    """Shared by create_layout and rename_layout: the UNIQUE (doc_type,
    scope_id, name) constraint is DB-enforced, so a name collision surfaces as
    an IntegrityError, not a ValueError -- and this app's generic error
    handlers are disabled, so an uncaught one is a 500 where every other
    refusal on these routes is a friendly 400. Converted here, in one place,
    so both callers get the same message shape without each having to guard
    against it separately.

    This is also what closes the check-then-act race a pre-check alone
    leaves open: save_as_print_layout's own `existing_names` check stays (it
    is the fast, friendly path for the common case), but this is the
    correctness backstop for a genuinely simultaneous double-submit -- the
    same reason a pre-check alone was rejected for document numbering
    (docs/bug-reports/2026-07-12-jv-number-race-silent-data-loss.md).
    """
    from app import db
    from sqlalchemy.exc import IntegrityError
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        raise ValueError(f'A layout named "{name.strip()}" already exists.')
    return row


def create_layout(doc_type, scope_id, name, payload, user):
    from app import db
    scope_id = scope_id or 0
    row = PrintLayout(
        doc_type=doc_type, scope_id=scope_id, name=name.strip(), payload=payload,
        # The FIRST layout ever created in a scope with no default yet (no
        # migrated legacy key -- on the real philgen DB, only branch 1 has
        # one) becomes the default itself. Without this, resolve_layout only
        # ever reaches that scope's rows via its step-3 "first row by id"
        # fallback, and delete_layout's "refuse to delete the default" guard
        # protects nothing there: there IS no default row to refuse deleting,
        # so an admin can delete the very row every workstation at that
        # branch currently resolves to. Checked, not assumed -- a scope that
        # already has a default (the common, migrated case) must not get a
        # second; the partial unique index (uq_named_print_layouts_one_default)
        # would refuse that anyway, but this avoids relying on it here.
        is_default=(default_layout_row(doc_type, scope_id) is None),
        created_by_id=getattr(user, 'id', None),
        updated_by_id=getattr(user, 'id', None))
    db.session.add(row)
    return _commit_or_refuse_duplicate(row, name)


def rename_layout(layout_id, name, user_id=None):
    """Raises ValueError, same as delete_layout, when layout_id names no row --
    e.g. deleted by someone else between page load and submit. This function does
    not audit on its own, so there is no audit row to avoid writing on that path;
    the route wiring this up follows the same rule save_layout does: nothing
    persisted means nothing recorded.

    `user_id`, when given, sets `updated_by_id` -- previously only
    `create_layout` did, leaving the column stale for every edit after
    creation."""
    from app import db
    row = db.session.get(PrintLayout, layout_id)
    if row is None:
        raise ValueError('That layout no longer exists. Refresh and try again.')
    row.name = name.strip()
    if user_id is not None:
        row.updated_by_id = user_id
    return _commit_or_refuse_duplicate(row, name)


def delete_layout(layout_id):
    """Refuse to delete the default: resolution step 2 would have nothing to answer
    with, and every stranded workstation would fall to an arbitrary first row.

    SQLite foreign keys are NOT enforced in this app (no `PRAGMA foreign_keys=ON`
    anywhere in app/, config.py or tests/conftest.py), so the `ON DELETE SET NULL`
    declared on `PrintLayoutDevicePref.layout_id` never fires. Without the explicit
    UPDATE below, every workstation pref pointing at this row would be left holding
    a layout_id for a row that no longer exists, and `resolve_layout`'s
    `pref.layout` would silently be None forever instead of falling through to the
    default on THIS delete. Do the null-out ourselves, in the same transaction.
    """
    from app import db
    row = db.session.get(PrintLayout, layout_id)
    if row is None:
        return None
    if row.is_default:
        raise ValueError('The default layout cannot be deleted. '
                         'Make another layout the default first.')
    PrintLayoutDevicePref.query.filter_by(layout_id=row.id).update(
        {'layout_id': None}, synchronize_session=False)
    db.session.delete(row); db.session.commit()
    return row


def set_device_layout(device_id, doc_type, scope_id, layout_id):
    from app import db
    scope_id = scope_id or 0
    pref = PrintLayoutDevicePref.query.filter_by(
        device_id=device_id, doc_type=doc_type, scope_id=scope_id).first()
    if pref is None:
        pref = PrintLayoutDevicePref(device_id=device_id, doc_type=doc_type,
                                     scope_id=scope_id)
        db.session.add(pref)
    pref.layout_id = layout_id
    db.session.commit()
    return pref
