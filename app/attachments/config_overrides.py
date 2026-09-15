"""Per-company overrides of attachment slot flags.

The code registry (`app/attachments/registry.py`) seeds each slot's default
`required` flag. Company Settings may, per company database, flip a seeded slot's
required flag or hide it (task 4) — but never add, rename, or reorder slots, so
labels stay consistent and the required-check stays reliable.

Task 3 ships the code-seed defaults; task 4 overlays the stored per-company
values here. Keeping the overlay behind these two functions means the resolver
(`completeness.py`) never changes when the override source is added.
"""


def is_required(document_type, slot):
    """Effective required flag for a slot in the current company. Code seed for
    now; task 4 overlays the Company Settings override."""
    return slot.required


def is_hidden(document_type, slot):
    """Whether the current company hides this slot. False by default; task 4
    overlays the Company Settings override."""
    return False
