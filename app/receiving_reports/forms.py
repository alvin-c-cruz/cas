"""Forms for Receiving Report management. Buy-side mirror of DeliveryReceiptForm."""
from datetime import date
from flask_wtf import FlaskForm
from wtforms import DateField, TextAreaField, SelectField, StringField
from wtforms.validators import DataRequired, Length, Optional
from app.utils.concurrency import RowVersionFormMixin


class ReceivingReportForm(RowVersionFormMixin, FlaskForm):
    rr_number = StringField('RR #', validators=[
        DataRequired(message='RR number is required.'), Length(max=50)])

    # Populated in the view with active vendors; validate_choice off so a freshly
    # quick-added vendor id is accepted. One receipt covers one vendor -- the PO
    # picker (eligible purchase orders) is scoped by whichever vendor is chosen
    # here, mirroring PurchaseOrderForm.vendor_id.
    vendor_id = SelectField('Vendor', coerce=int, validate_choice=False,
                            validators=[DataRequired(message='Vendor is required.')])

    receipt_date = DateField('Receipt Date', validators=[
        DataRequired(message='Receipt date is required.')], format='%Y-%m-%d', default=date.today)
    remarks = TextAreaField('Remarks', validators=[Optional()])

    def set_vendor_choices(self, vendors):
        self.vendor_id.choices = [(0, '-- Select vendor --')] + [(v.id, v.name) for v in vendors]
