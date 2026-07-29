from flask_wtf import FlaskForm
from wtforms import SelectField, DateField, TextAreaField, HiddenField, StringField
from wtforms.validators import DataRequired, Optional, Length
from app.utils.concurrency import RowVersionFormMixin
from datetime import date


class DeliveryReceiptForm(RowVersionFormMixin, FlaskForm):
    # Pre-filled with a generated DR-YYYY-MM-#### value on GET (see create()/edit() views),
    # but overridable -- lets a real/pre-printed legacy DR number be entered instead, same
    # pattern as SalesOrderForm.so_number. Optional (not DataRequired): a blank submission
    # falls back to server-side auto-generation, same as before this field existed.
    dr_number = StringField('DR #', validators=[Optional(), Length(max=50)])

    sales_order_id = SelectField('Sales Order', coerce=int, validators=[DataRequired()],
                                 validate_choice=False)
    delivery_date = DateField('Delivery Date', validators=[DataRequired()],
                              format='%Y-%m-%d', default=date.today)
    salesperson_id = SelectField('Salesperson', coerce=int, validators=[Optional()],
                                 validate_choice=False)
    remarks = TextAreaField('Remarks', validators=[Optional()])
    # Legacy-mirroring free-text blocks -- feed the DR pre-printed layout's positioned
    # multiline fields (e.g. RIC's packing/lot breakdown and BO/CO delivery-window notes).
    packing_notes = TextAreaField('Packing / Lot Breakdown', validators=[Optional(), Length(max=2000)])
    schedule_notes = TextAreaField('Delivery Schedule (BO/CO)', validators=[Optional(), Length(max=2000)])
    lines = HiddenField('Lines JSON')
