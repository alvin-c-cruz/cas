"""
Forms for Sales Order management.
"""
from flask_wtf import FlaskForm
from wtforms import StringField, DateField, TextAreaField, SelectField, HiddenField, ValidationError
from wtforms.validators import DataRequired, Length, Optional
from app.utils.concurrency import RowVersionFormMixin
from datetime import date


class SalesOrderForm(RowVersionFormMixin, FlaskForm):
    """Form for creating and editing sales orders. Operational only — no GL/WHT/payment fields."""

    so_number = StringField('SO #', validators=[
        DataRequired(message='SO number is required.'),
        Length(max=50)
    ])

    order_date = DateField('Order Date', validators=[
        DataRequired(message='Order date is required.')
    ], format='%Y-%m-%d', default=date.today)

    expected_delivery_date = DateField('Expected Delivery Date', validators=[Optional()],
                                       format='%Y-%m-%d')

    # Customer fields — customer_id is a hidden field managed by the JS customer picker;
    # customer_name/tin/address are populated client-side from the picker.
    customer_id = HiddenField('Customer ID', validators=[
        DataRequired(message='Customer is required.')
    ])

    customer_name = HiddenField('Customer Name')
    customer_tin = HiddenField('Customer TIN')
    customer_address = HiddenField('Customer Address')

    customer_po_number = StringField('Customer PO #', validators=[
        Optional(), Length(max=100)
    ])

    customer_po_date = DateField('Customer PO Date', validators=[Optional()],
                                 format='%Y-%m-%d')

    payment_terms = SelectField('Payment Terms', validators=[DataRequired()], choices=[
        ('Net 15', 'Net 15'), ('Net 30', 'Net 30'), ('Net 45', 'Net 45'),
        ('Net 60', 'Net 60'), ('Cash on Delivery', 'Cash on Delivery'),
        ('Advance Payment', 'Advance Payment'),
    ], default='Net 30')

    reference = StringField('Reference', validators=[Optional(), Length(max=100)])

    salesperson_id = SelectField('Salesperson', coerce=int, validators=[Optional()],
                                 validate_choice=False)

    notes = TextAreaField('Notes', validators=[Optional()])

    # Hidden JSON blob carrying the line items submitted from the JS line-item grid.
    line_items_json = HiddenField('Line Items JSON')


class SalesOrderAmendForm(SalesOrderForm):
    """The SO form plus the two fields a post-confirm amendment must record.

    Reason mirrors cancel_reason's >=10-char rule. The authorizing PO is
    conditionally required -- see validate_authorizing_po_number below.
    """
    amend_reason = TextAreaField('Reason for amendment', validators=[
        DataRequired(message='Please provide a reason for this amendment.'),
        Length(min=10, message='Please provide a reason (at least 10 characters).')])
    # NOTE: deliberately NO Optional() here. WTForms' Optional() raises
    # StopValidation on empty input, which aborts the ENTIRE remaining chain --
    # including the inline validate_authorizing_po_number below (WTForms appends
    # validate_<field> methods to the *same* chain as the declared validators,
    # so a StopValidation from an earlier validator skips it too). That would
    # silently disable the one check this field exists for: catching a blank PO
    # when the customer requires one. Length(max=100) alone already tolerates
    # an empty string (its default min is 0), so Optional() adds nothing here.
    authorizing_po_number = StringField('Authorizing customer PO #',
                                        validators=[Length(max=100)])

    def __init__(self, *args, po_required=False, **kwargs):
        super().__init__(*args, **kwargs)
        self._po_required = po_required

    def validate_authorizing_po_number(self, field):
        if self._po_required and not (field.data or '').strip():
            raise ValidationError(
                'This customer requires a Purchase Order number, so an amendment '
                'must record the PO that authorizes it.')
