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
