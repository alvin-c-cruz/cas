"""Required/labeled attachment completeness: which required slots a document is
still missing.

Spans both attachment tables (spec D4): the four shared documents live in
`document_attachments`, AP lives in `accounts_payable_attachments`. The effective
required set is the code-seeded `Slot.required`, overlaid per company by
`config_overrides` (task 4), and narrowed to the slots that apply to the given
document (the CV check-copy conditional).

`incomplete_map` is the batched form used by Action Items and the badge count:
one query per document type, no per-document N+1.
"""
from app.attachments.models import DocumentAttachment
from app.attachments.registry import slots_for


def _required_flag(document_type, slot):
    """Effective required flag for a slot: the code seed, overlaid by any
    per-company override. Task 4 fills `config_overrides`; until then this is the
    code seed."""
    from app.attachments import config_overrides
    return config_overrides.is_required(document_type, slot)


def required_slots(document_type, doc):
    """Slots that are required for *doc* right now: seeded-or-overridden required,
    and applicable to this document (resolves the CV check-copy conditional)."""
    return [s for s in slots_for(document_type)
            if s.applies_to(doc) and _required_flag(document_type, s)]


def visible_slots(document_type, doc):
    """Slots to show on *doc*'s panel: every slot that applies to it (required or
    not). A hidden slot (task 4) or an inapplicable conditional is dropped."""
    from app.attachments import config_overrides
    return [s for s in slots_for(document_type)
            if s.applies_to(doc) and not config_overrides.is_hidden(document_type, s)]


def _present_kinds(document_type, document_id):
    """Set of slot keys that have at least one file on this document."""
    if document_type == 'accounts_payable':
        from app.accounts_payable.models import AccountsPayableAttachment
        rows = (AccountsPayableAttachment.query
                .filter_by(ap_id=document_id)
                .with_entities(AccountsPayableAttachment.kind).all())
    else:
        rows = (DocumentAttachment.query
                .filter_by(document_type=document_type, document_id=document_id)
                .with_entities(DocumentAttachment.kind).all())
    return {r[0] for r in rows if r[0]}


def missing_required(document_type, doc):
    """Required slots (Slot objects) with no file on *doc*. Empty = complete."""
    present = _present_kinds(document_type, doc.id)
    return [s for s in required_slots(document_type, doc) if s.key not in present]


def approved_incomplete(document_type, doc):
    """For an approved/posted document: the snapshot slots (from
    `approved_incomplete_slots`) that STILL have no file. Empty list when the
    document was approved complete, was not approved with anything missing, or
    has since been completed (the badge self-heals). Required-ness is frozen at
    approval — this reads the snapshot, not current config — so later config
    changes never rewrite which past approvals look incomplete.
    """
    import json
    raw = getattr(doc, 'approved_incomplete_slots', None)
    if not raw:
        return []
    try:
        snapshot = json.loads(raw)
    except (ValueError, TypeError):
        return []
    if not snapshot:
        return []
    present = _present_kinds(document_type, doc.id)
    return [k for k in snapshot if k not in present]


def incomplete_map(document_type, docs):
    """{doc_id: [missing Slot, ...]} for the docs that are missing a required
    slot. One grouped query over the attachment table for the whole set."""
    ids = [d.id for d in docs]
    if not ids:
        return {}

    if document_type == 'accounts_payable':
        from app.accounts_payable.models import AccountsPayableAttachment
        rows = (AccountsPayableAttachment.query
                .filter(AccountsPayableAttachment.ap_id.in_(ids),
                        AccountsPayableAttachment.kind.isnot(None))
                .with_entities(AccountsPayableAttachment.ap_id,
                               AccountsPayableAttachment.kind).all())
    else:
        rows = (DocumentAttachment.query
                .filter(DocumentAttachment.document_type == document_type,
                        DocumentAttachment.document_id.in_(ids),
                        DocumentAttachment.kind.isnot(None))
                .with_entities(DocumentAttachment.document_id,
                               DocumentAttachment.kind).all())

    present_by_doc = {}
    for doc_id, kind in rows:
        present_by_doc.setdefault(doc_id, set()).add(kind)

    out = {}
    for d in docs:
        present = present_by_doc.get(d.id, set())
        miss = [s for s in required_slots(document_type, d) if s.key not in present]
        if miss:
            out[d.id] = miss
    return out
