"""Form for Purchase Request -- a thin requisition (mirror QuotationForm, minus pricing)."""
from datetime import date
from flask_wtf import FlaskForm
from wtforms import DateField, TextAreaField, StringField, BooleanField
from wtforms.validators import DataRequired, Length, Optional
from app.utils.concurrency import RowVersionFormMixin


class PurchaseRequestForm(RowVersionFormMixin, FlaskForm):
    pr_number = StringField('PR #', validators=[
        DataRequired(message='PR number is required.'), Length(max=50)])
    request_date = DateField('Request Date', validators=[
        DataRequired(message='Request date is required.')], format='%Y-%m-%d', default=date.today)
    # Optional and deliberately NOT checked against request_date -- owner
    # directive, matching PurchaseOrder.expected_date. A requestor who does not
    # yet know when the goods are wanted must still be able to raise the
    # requisition.
    date_needed = DateField('Date Needed', validators=[Optional()], format='%Y-%m-%d')
    # Wanted immediately, no specific date. Mutually exclusive with
    # date_needed -- the views clear the date when this is set. NOT a
    # form-level validator: a requisition must never be REFUSED for carrying
    # both, it just resolves to ASAP.
    date_needed_asap = BooleanField('ASAP')
    # Labelled Note, stored as `reason`. The column keeps its name -- renaming
    # it would mean a migration, and touching SNAPSHOT_HEADER_FIELDS, the audit
    # payloads and the export columns, for a change the user only ever reads.
    reason = TextAreaField('Note', validators=[Optional()])


class PurchaseRequestAmendForm(PurchaseRequestForm):
    """The PR form plus the reason a post-approval amendment must record.

    Mirrors PurchaseOrderAmendForm's rule (>=10 chars, matching cancel's). The
    inherited pr_number field is deliberately kept -- the amend template renders
    it readonly and the route never reassigns it, so the value round-trips for
    display without becoming editable.
    """
    amend_reason = TextAreaField('Reason for amendment', validators=[
        DataRequired(message='Please provide a reason for this amendment.'),
        Length(min=10, message='Please provide a reason (at least 10 characters).')])


class PurchaseRequestAmendmentRequestForm(PurchaseRequestForm):
    """What STAFF submits to ask for an amendment.

    Extends the ordinary PR form so the line-item widget, its validators and its
    hidden `line_items` payload are identical to the screens staff already use --
    a separate form would drift from the applier's expected shape.

    `request_reason` mirrors PurchaseRequestAmendForm.amend_reason's >=10 rule
    because it becomes the reason on the DocumentRevision if the request is
    approved; the shared amendment service requires that length there.
    """
    request_reason = TextAreaField('Reason for amendment', validators=[
        DataRequired(message='Please give a reason for this amendment request.'),
        Length(min=10, message='Please give a reason (at least 10 characters).')])
