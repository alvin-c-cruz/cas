"""Shared helpers for the master-data approval workflow.

Withholding Tax and VAT Categories are deterministic mirrors of each other on
the *create* path (same change-request schema: action / proposed_data /
requested_by_id; same auto-approve-vs-pending branch + audit + flash). This
module factors that shared flow out of both views so a fix to one is a fix to
both. Chart of Accounts is intentionally NOT routed through here — it uses a
different change-request schema (change_type / change_data / requested_by
username) and is kept separate.
"""
import json

from flask import flash, redirect, url_for
from flask_login import current_user

from app import db
from app.audit.utils import log_audit
from app.utils import ph_now

PENDING_SUBMITTED_MESSAGE = ('Change request submitted — pending review. '
                             'It will appear under Action Items until approved or rejected.')


def process_create_change_request(*, model_cls, cr_cls, module, noun,
                                  change_data, auto_approve, list_endpoint,
                                  approved_note='Auto-approved (single accountant)'):
    """Apply a master-data *create*: either directly (sole-accountant
    auto-approve) or as a pending change request, with the matching audit entry
    and flash. Commits and returns a redirect to ``list_endpoint``.

    ``change_data`` keys must map 1:1 to ``model_cls`` columns (true for both
    WithholdingTax and VATCategory). Callers handle their own duplicate checks
    and wrap this in their try/except.

    ``approved_note`` allows customizing the audit note for the auto-approve branch
    (defaults to 'Auto-approved (single accountant)' for backward compatibility).
    """
    if auto_approve:
        record = model_cls(**change_data,
                           created_by_id=current_user.id,
                           updated_by_id=current_user.id)
        db.session.add(record)
        db.session.flush()  # Get the ID before commit
        log_audit(
            module=module,
            action='create',
            record_id=record.id,
            record_identifier=f'{record.code} - {record.name}',
            new_values=change_data,
            notes=approved_note
        )
        db.session.commit()
        flash(f'{noun} "{record.name}" has been created successfully.', 'success')
    else:
        change_request = cr_cls(
            action='create',
            status='pending',
            proposed_data=json.dumps(change_data),
            requested_by_id=current_user.id,
            requested_at=ph_now()
        )
        db.session.add(change_request)
        db.session.flush()  # Get the ID before commit
        log_audit(
            module=module,
            action='create',
            record_id=change_request.id,
            record_identifier=f'Change Request: {change_data["code"]} - {change_data["name"]}',
            new_values=change_data,
            notes='Pending approval.'
        )
        db.session.commit()
        flash(PENDING_SUBMITTED_MESSAGE, 'success')

    return redirect(url_for(list_endpoint))
