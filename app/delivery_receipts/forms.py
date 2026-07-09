from flask_wtf import FlaskForm
from wtforms import SelectField, DateField, TextAreaField, HiddenField
from wtforms.validators import DataRequired, Optional
from datetime import date


class DeliveryReceiptForm(FlaskForm):
    sales_order_id = SelectField('Sales Order', coerce=int, validators=[DataRequired()],
                                 validate_choice=False)
    delivery_date = DateField('Delivery Date', validators=[DataRequired()],
                              format='%Y-%m-%d', default=date.today)
    salesperson_id = SelectField('Salesperson', coerce=int, validators=[Optional()],
                                 validate_choice=False)
    remarks = TextAreaField('Remarks', validators=[Optional()])
    lines = HiddenField('Lines JSON')
