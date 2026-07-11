"""Forms for Purchase Order management. Buy-side mirror of SalesOrderForm.
Operational only -- no GL/WHT/payment fields. vat_treatment mirrors Quotation."""
from datetime import date
from flask_wtf import FlaskForm
from wtforms import StringField, DateField, TextAreaField, SelectField
from wtforms.validators import DataRequired, Length, Optional
from app.utils.concurrency import RowVersionFormMixin
from app.purchase_orders.models import VAT_TREATMENTS


class PurchaseOrderForm(RowVersionFormMixin, FlaskForm):
    po_number = StringField('PO #', validators=[
        DataRequired(message='PO number is required.'), Length(max=50)])

    order_date = DateField('Order Date', validators=[
        DataRequired(message='Order date is required.')], format='%Y-%m-%d', default=date.today)

    expected_date = DateField('Expected Date', validators=[Optional()], format='%Y-%m-%d')

    # Populated in the view with active vendors; validate_choice off so a freshly
    # quick-added vendor id is accepted.
    vendor_id = SelectField('Vendor', coerce=int, validate_choice=False,
                            validators=[DataRequired(message='Vendor is required.')])

    vat_treatment = SelectField('VAT Treatment', choices=[
        ('inclusive', 'VAT Inclusive'), ('exclusive', 'VAT Exclusive'),
        ('zero_rated', 'Zero-Rated'),
    ], default='inclusive', validators=[DataRequired()])

    payment_terms = SelectField('Payment Terms', validators=[DataRequired()], choices=[
        ('Net 15', 'Net 15'), ('Net 30', 'Net 30'), ('Net 45', 'Net 45'),
        ('Net 60', 'Net 60'), ('Cash on Delivery', 'Cash on Delivery'),
        ('Advance Payment', 'Advance Payment'),
    ], default='Net 30')

    reference = StringField('Reference', validators=[Optional(), Length(max=100)])

    notes = TextAreaField('Notes', validators=[Optional()])

    def set_vendor_choices(self, vendors):
        self.vendor_id.choices = [(0, '-- Select vendor --')] + [(v.id, v.name) for v in vendors]

    @staticmethod
    def vat_treatment_values():
        return VAT_TREATMENTS
