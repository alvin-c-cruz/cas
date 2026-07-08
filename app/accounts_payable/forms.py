"""
Forms for Accounts Payable management.
"""
from flask_wtf import FlaskForm
from wtforms import StringField, DateField, TextAreaField, SelectField
from wtforms.validators import DataRequired, Length, Optional, ValidationError
from datetime import date


class AccountsPayableForm(FlaskForm):
    """Form for creating and editing accounts payable."""

    # User-typed serial (mirrors SI invoice_number). Pre-filled with the next suggested
    # number (AP-YYYY-MM-NNNN) on a fresh form, but EDITABLE while the form is editable
    # (create / draft-edit); the server respects the typed value and enforces uniqueness.
    ap_number = StringField('AP Number', validators=[
        DataRequired(message='AP number is required.'),
        Length(max=50, message='AP number must be 50 characters or less.')
    ])

    ap_date = DateField('Voucher Date', validators=[
        DataRequired(message='AP date is required.')
    ], format='%Y-%m-%d', default=date.today)

    due_date = DateField('Due Date', validators=[
        DataRequired(message='Due date is required.')
    ], format='%Y-%m-%d')

    def validate_due_date(self, field):
        if self.ap_date.data and field.data and field.data < self.ap_date.data:
            raise ValidationError('Due date cannot be earlier than the voucher date.')

    # Combined payee: "vendor:<id>" or "employee:<id>" (parsed in the view).
    # The new AP form submits this instead of vendor_id.
    payee = StringField('Payee', validators=[Optional()])

    # Legacy vendor select — kept for back-compat (older callers/tests POST
    # vendor_id directly). Optional now; the view treats a bare vendor_id as a
    # vendor payee when no `payee` value is present. Tolerant coerce so an empty
    # submission (new payee path) doesn't raise.
    vendor_id = SelectField('Vendor', validators=[Optional()],
                            coerce=lambda v: int(v) if v not in (None, '') else None,
                            validate_choice=False)

    vendor_invoice_number = StringField('Vendor Invoice #', validators=[
        Optional(),
        Length(max=100, message='Vendor invoice number must be 100 characters or less.')
    ])

    vendor_invoice_date = DateField('Vendor Invoice Date', validators=[
        Optional()
    ], format='%Y-%m-%d')

    payment_terms = SelectField('Payment Terms', choices=[
        ('Net 15', 'Net 15'),
        ('Net 30', 'Net 30'),
        ('Net 45', 'Net 45'),
        ('Net 60', 'Net 60'),
        ('Cash on Delivery', 'Cash on Delivery'),
        ('Advance Payment', 'Advance Payment')
    ], default='Net 30')

    reference = StringField('Reference/PO Number', validators=[
        Optional(),
        Length(max=100, message='Reference must be 100 characters or less.')
    ])

    notes = TextAreaField('Notes (Particulars)', validators=[
        DataRequired(message='Notes are required — this becomes the Particulars in the AP Journal.')
    ])
