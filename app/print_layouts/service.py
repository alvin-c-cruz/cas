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


def create_layout(doc_type, scope_id, name, payload, user):
    from app import db
    row = PrintLayout(doc_type=doc_type, scope_id=scope_id or 0, name=name.strip(),
                      payload=payload, is_default=False,
                      created_by_id=getattr(user, 'id', None),
                      updated_by_id=getattr(user, 'id', None))
    db.session.add(row); db.session.commit()
    return row


def rename_layout(layout_id, name):
    """Raises ValueError, same as delete_layout, when layout_id names no row --
    e.g. deleted by someone else between page load and submit. This function does
    not audit on its own, so there is no audit row to avoid writing on that path;
    Task 6's route wiring this up should follow the same rule save_layout does if
    it later adds one: nothing persisted means nothing recorded."""
    from app import db
    row = db.session.get(PrintLayout, layout_id)
    if row is None:
        raise ValueError('That layout no longer exists. Refresh and try again.')
    row.name = name.strip()
    db.session.commit()
    return row


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
