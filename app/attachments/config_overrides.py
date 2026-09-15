"""Per-company overrides of attachment slot flags.

The code registry (`app/attachments/registry.py`) seeds each slot's default
`required` flag. Company Settings may, per company database, flip a seeded slot's
required flag or hide it — but never add, rename, or reorder slots, so labels
stay consistent and the required-check stays reliable.

Overrides are stored in the per-company key-value `AppSettings` table (the same
mechanism as control accounts and module toggles), so no new table is needed and
philgen and ric diverge naturally by living in separate databases. Keys:

    attachment_required:<document_type>:<slot_key>   '1' | '0'
    attachment_hidden:<document_type>:<slot_key>     '1' | '0'

Absent key → the code seed. Reads are guarded by `has_app_context()` so the pure
completeness unit tests (which drive the resolver with no app/DB) fall back to
the seed instead of erroring.
"""
from flask import has_app_context


def _setting(key):
    # An override is optional: if it cannot be read (no app context, or the
    # settings store is unavailable), fall back to the code seed rather than
    # error. In production the table always exists; this guard only matters to
    # resolver calls made outside a live request/DB.
    if not has_app_context():
        return None
    try:
        from app.settings import AppSettings
        return AppSettings.get_setting(key)
    except Exception:
        return None


def required_key(document_type, slot_key):
    return f'attachment_required:{document_type}:{slot_key}'


def hidden_key(document_type, slot_key):
    return f'attachment_hidden:{document_type}:{slot_key}'


def is_required(document_type, slot):
    """Effective required flag: the per-company override if set, else the code
    seed (`slot.required`)."""
    value = _setting(required_key(document_type, slot.key))
    if value is None:
        return slot.required
    return value == '1'


def is_hidden(document_type, slot):
    """Whether the current company hides this slot (default: not hidden)."""
    return _setting(hidden_key(document_type, slot.key)) == '1'
