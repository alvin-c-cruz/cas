"""Optimistic locking for transaction documents (the lost-update guard).

Every document edit route in CAS is a replace-all: it discards the stored line
items -- and, for APV/CDV/CRV, deletes and recreates the linked journal entry --
then rebuilds everything from the submitted payload.  Nothing coordinates two
encoders working the same draft, so the second save silently destroys the
first one's work, leaving only an audit-log trace.

This module supplies the one primitive the edit routes share.  It is shared, not
copy-pasted, on purpose: a guard that drifts and fails *open* is worse than no
guard at all, because it is trusted.

Usage in an edit route, as the FIRST write, before any line or JE teardown:

    if not claim_version(AccountsPayable, ap.id, submitted_version()):
        db.session.rollback()
        flash(conflict_message('accounts_payable', ap.id), 'error')
        return _render_edit_form(request.form.get('line_items', ''))

Note `submitted_version()`, never `form.row_version.data` -- see its docstring.
"""
from wtforms import IntegerField
from wtforms.validators import Optional
from wtforms.widgets import HiddenInput

from app import db
from app.utils import format_ph_datetime


# No apostrophes: flash text is asserted against raw response bytes, and Jinja
# autoescapes ' into &#39;.
_SUFFIX = 'Your changes were NOT saved - reload the page to see the current version.'


class RowVersioned:
    """Declarative mixin contributing the optimistic-locking counter.

    A plain Column on a mixin is copied onto each subclass by SQLAlchemy, so
    the seven document headers each get their own column.
    """

    row_version = db.Column(db.Integer, nullable=False, default=1, server_default='1')


class RowVersionFormMixin:
    """Carries the version token through the edit form.

    IntegerField (not HiddenField) so WTForms coerces the submitted string.
    The HiddenInput widget means `form.hidden_tag()` -- which every document
    form.html already calls -- renders it automatically.  Do NOT also render it
    explicitly: the name would post twice and request.form would read the empty
    first copy, which pytest cannot see.

    The validator is Optional(), NOT InputRequired(), because the same form class
    serves create and edit.  On a create GET the field has no data, so hidden_tag
    renders value="", the POST sends '', IntegerField coerces that to None, and
    InputRequired would make every create invalid.

    This field is for RENDERING ONLY.  Never read the token from
    `form.row_version.data` -- use `submitted_version()`.  See its docstring.
    """

    row_version = IntegerField(widget=HiddenInput(), validators=[Optional()])


def submitted_version():
    """Read the version token from the raw POST body.  Fails closed.

    Never use `form.row_version.data` for this.  Every edit route builds its
    form as `Form(obj=doc)`, and WTForms falls back to the obj value when a
    field is absent from formdata:

        F(formdata=MultiDict({}), obj=doc).row_version.data  ->  doc.row_version

    So a POST that omitted the token entirely would yield the document's CURRENT
    version, claim_version() would succeed, and the guard would silently pass --
    failing OPEN on exactly the request it exists to stop.

    request.form.get(..., type=int) returns None for both an absent key and a
    non-numeric one, and claim_version(None) is False.
    """
    from flask import request

    return request.form.get('row_version', type=int)


def claim_version(model, doc_id, submitted):
    """Atomically claim the right to write `doc_id`, or lose to a concurrent writer.

    Returns True for exactly one of any number of racers holding the same token.

    This is a conditional UPDATE rather than a read-then-compare on purpose.
    SQLAlchemy defers BEGIN until the first write, so a comparison would read
    outside the transaction: both racers see version 3, both pass the check, and
    both write 4.  Folding the check into the WHERE clause makes the database
    the arbiter.

    The increment is computed SQL-side (`row_version + 1`), never from the
    client-supplied number.
    """
    if submitted is None:
        return False

    result = db.session.execute(
        db.update(model)
        .where(model.id == doc_id, model.row_version == submitted)
        .values(row_version=model.row_version + 1)
        .execution_options(synchronize_session=False)
    )

    if result.rowcount != 1:
        return False

    # The Core UPDATE bypassed the ORM, so the in-session attribute is stale.
    obj = db.session.get(model, doc_id)
    if obj is not None:
        db.session.expire(obj, ['row_version'])
    return True


def fresh_number_if_collision(model, number_attr, submitted_number, generate_number):
    """Check whether `submitted_number` already exists on `model`. If so, return a freshly
    generated candidate; the caller must refill the form field with it, flash an
    explanation, and RE-RENDER the create form WITHOUT committing. Returns None when there
    is no collision (proceed as normal).

    Use this — NOT `commit_with_renumber_retry` — for document numbers that are
    user-editable, pre-printed-serial-style fields (SI invoice_number, AP ap_number, CD
    cdv_number, CR crv_number: each is documented in its own forms.py as "pre-filled with a
    suggested default, but editable to match a physical pre-printed document"). Silently
    swapping a collision on one of these could mask a genuine mistake — a user who
    deliberately (re)typed a real duplicate physical serial deserves to find out, not have
    it quietly renumbered out from under them. JV's entry_number has no such meaning (a
    pure system sequence, nobody cares about a specific value) and uses the silent
    `commit_with_renumber_retry` instead.

    See docs/bug-reports/2026-07-12-jv-number-race-silent-data-loss.md.
    """
    exists = db.session.query(
        model.query.filter(getattr(model, number_attr) == submitted_number).exists()
    ).scalar()
    if not exists:
        return None
    return generate_number()


def commit_with_renumber_retry(entity, number_attr, generate_number, max_attempts=3):
    """Commit `entity` (already `db.session.add()`-ed, with any cascaded children),
    retrying up to `max_attempts` times with a freshly generated number if the commit
    fails on a numbering collision.

    The bug this closes: every document number (JV entry_number, SI invoice_number,
    etc.) is generated once when the create form is rendered (a MAX/latest scan, not
    a real sequence object) and trusted verbatim at submit. Two users who open the
    form in the same window both see the same suggested number; whoever commits
    second used to get a raw IntegrityError -> generic flash -> their whole submission
    silently discarded. This retries with a fresh number instead of failing.

    Raises the original IntegrityError if the collision isn't resolved within
    max_attempts (kept rare on purpose -- if collisions are frequent, that is its own
    bug worth surfacing, not silently retrying forever).

    See docs/bug-reports/2026-07-12-jv-number-race-silent-data-loss.md.
    """
    from sqlalchemy.exc import IntegrityError

    for attempt in range(1, max_attempts + 1):
        try:
            db.session.commit()
            return
        except IntegrityError:
            db.session.rollback()
            if attempt == max_attempts:
                raise
            # Compute the new number BEFORE re-adding `entity` to the session: the
            # generator runs its own query, and if `entity` is already pending with
            # its OLD (colliding) number, that query's autoflush re-attempts the
            # doomed insert and raises again -- immediately, not on our next commit.
            with db.session.no_autoflush:
                new_number = generate_number()
            db.session.add(entity)
            setattr(entity, number_attr, new_number)


def conflict_message(module, doc_id):
    """Name who changed the document out from under this editor, and when.

    Read from the audit log rather than an `updated_by` column, which these
    document headers do not carry.  `log_audit` swallows its own errors, so the
    row may legitimately be missing -- degrade to a nameless message.
    """
    # Imported lazily: the document models import this module at class-definition
    # time, and audit.models must not be pulled into that edge.
    from app.audit.models import AuditLog

    entry = (
        AuditLog.query
        .filter_by(module=module, action='update', record_id=doc_id)
        .order_by(AuditLog.timestamp.desc(), AuditLog.id.desc())
        .first()
    )

    if entry is not None and entry.user is not None and entry.user.full_name:
        when = format_ph_datetime(entry.timestamp)
        return f'This document was changed by {entry.user.full_name} at {when}. {_SUFFIX}'

    return f'This document was changed by another user. {_SUFFIX}'
