"""The administrator's override: edit or delete a document after it is approved.

Owner decision, 2026-10-06 ("give admin the ultimate power now ... document per
document, starting with CV"). It relaxes "posted documents are never edited"
(CAS-DEVELOPMENT.md) for the system administrator only, on these terms, which hold
for every document that adopts it:

* admin only (`User.is_admin`) -- chief accountants and accountants keep the normal rules;
* a reason of at least ADMIN_REASON_MIN characters, kept in the audit log;
* a closed period, a bank-reconciled JE line or a fixed-asset tag still refuses;
* delete is a hard delete and edit is in place -- each document's own module unwinds
  its links; this module holds only what is common to all of them.
"""
from app.audit.utils import log_audit

ADMIN_REASON_MIN = 10


def is_override_user(user):
    """May *user* edit or delete a document after approval?"""
    return bool(getattr(user, 'is_authenticated', False) and user.is_admin)


def clean_reason(raw):
    """The stripped reason, or None when it is missing or shorter than the minimum."""
    reason = (raw or '').strip()
    return reason if len(reason) >= ADMIN_REASON_MIN else None


REASON_REQUIRED = (f'A reason of at least {ADMIN_REASON_MIN} characters is required to '
                   'change or delete an approved document.')


def reconciled_line_count(journal_entry_id):
    """How many of the entry's lines are cleared in a bank reconciliation. Editing or
    deleting such an entry would silently change a reconciliation already done."""
    if not journal_entry_id:
        return 0
    from app.bank_reconciliation.models import ReconciliationItem
    from app.journal_entries.models import JournalEntryLine
    line_ids = [i for (i,) in JournalEntryLine.query.with_entities(JournalEntryLine.id)
                .filter_by(entry_id=journal_entry_id)]
    if not line_ids:
        return 0
    return ReconciliationItem.query.filter(ReconciliationItem.je_line_id.in_(line_ids)).count()


RECONCILED = ('This voucher is cleared in a bank reconciliation. Unclear it in the '
              'reconciliation first, then edit or delete it.')


def journal_entry_snapshot(je):
    """A JSON-safe copy of an entry and its lines, for the audit row of a delete."""
    if je is None:
        return None
    return {
        'entry_number': je.entry_number,
        'entry_date': je.entry_date.isoformat() if je.entry_date else None,
        'status': je.status,
        'description': je.description,
        'lines': [{'account': (l.account.code if l.account else l.account_id),
                   'debit': str(l.debit_amount or 0), 'credit': str(l.credit_amount or 0),
                   'description': l.description}
                  for l in je.lines],
    }


def log_override(module, action, record_id, identifier, reason, old_values=None,
                 new_values=None, extra_note=''):
    """Audit an override. *action* is 'admin_edit_posted' or 'admin_delete'."""
    note = f'Admin override ({action}). Reason: {reason}'
    if extra_note:
        note += f' | {extra_note}'
    log_audit(module=module, action=action, record_id=record_id,
              record_identifier=identifier, old_values=old_values,
              new_values=new_values, notes=note)
