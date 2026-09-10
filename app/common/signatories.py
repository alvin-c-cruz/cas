"""Per-document printed signatories, shared by Purchase Requisition and Receiving Report.

Owner directive 2026-08-21: these names live ON the document, as PurchaseOrder
already does, instead of in one company-wide setting where a one-off signatory
became permanent for every future printout.

The company setting does NOT go away -- it becomes the DEFAULT a new document
pre-fills from. That is what keeps an install printing exactly what it printed
before the values moved, and it is why `for_print` falls back to it: a document
saved before this shipped has NULL columns and must still print the configured
names rather than three blank lines.

NEVER derive a signatory from created_by / submitted_by / approved_by_id. The
people who sign these documents are frequently not CAS users; deriving them once
printed "System Administrator" three times on a single requisition
(app/company_settings/views.py records that incident).
"""


def defaults_for(prefix, roles):
    """[(role, name), ...] from the company-wide setting for `prefix` ('pr'/'rr').

    Thin wrapper over company_settings.get_signatories so callers here never
    need to know the app_settings key layout.
    """
    from app.company_settings.views import get_signatories
    return get_signatories(prefix, roles)


def prefill_form(form, fields, prefix, roles):
    """Seed a NEW document's signatory inputs from the company default.

    Only fills a field the user has not already typed into, so a re-render after
    a validation failure never discards what they entered.
    """
    for field_name, (_role, name) in zip(fields, defaults_for(prefix, roles)):
        field = getattr(form, field_name, None)
        if field is not None and not (field.data or '').strip():
            field.data = name


def prefill_form_from_last(form, fields, prefix, roles, model, user_id):
    """Seed a NEW document's signatories from THIS user's most recent one.

    Owner, 2026-09-10: "signatories should autofill based on what the user
    encoded last time." Seeding from the company default meant anyone whose crew
    differs from the configured names retyped every line on every document.

    PER USER, not per company and not per branch. Two receivers hand the goods
    to different people; seeding from whoever saved most recently would give
    each of them the other's crew. Same reasoning as next_po_number_for(), which
    scopes a purchaser's number pad to the purchaser.

    The company default remains the fallback PER SLOT -- for a first-ever
    document, and for any signatory the last document left blank. Falling back
    slot by slot rather than all-or-nothing matches for_print()'s behaviour.

    This does NOT derive a name from created_by. The module docstring above
    records why: the people who sign are frequently not CAS users, and deriving
    them once printed "System Administrator" three times on one requisition.
    The name is read from what the user TYPED on their last document.

    Only fills a field the user has not already typed into, so a re-render after
    a validation failure never discards what they entered.
    """
    last = None
    if user_id:
        last = (model.query
                .filter(model.created_by_id == user_id)
                .order_by(model.id.desc())     # insertion order, never a date
                .first())

    for field_name, (_role, default_name) in zip(fields, defaults_for(prefix, roles)):
        field = getattr(form, field_name, None)
        if field is None or (field.data or '').strip():
            continue
        previous = (getattr(last, field_name, None) or '').strip() if last else ''
        field.data = previous or default_name


def assign(document, form, fields):
    """Copy the submitted signatory names onto the document.

    Blank stays blank -- an empty name prints an empty ruled line to sign by
    hand, which is a legitimate choice, not missing data to be back-filled from
    the company setting at save time.
    """
    for field_name in fields:
        field = getattr(form, field_name, None)
        if field is not None:
            setattr(document, field_name, (field.data or '').strip() or None)


def for_print(document, fields, roles, prefix):
    """[(role, name), ...] for the printout.

    Reads the DOCUMENT first and falls back to the company setting per slot, so:
      * a document saved with its own names prints those;
      * a document predating this feature (all NULL) still prints the configured
        company names instead of three blank lines.
    The fallback is per-slot rather than all-or-nothing: a document that names
    only its approver should not lose the other two.
    """
    fallback = defaults_for(prefix, roles)
    out = []
    for field_name, (role, default_name) in zip(fields, fallback):
        own = (getattr(document, field_name, None) or '').strip()
        out.append((role, own or default_name))
    return out
