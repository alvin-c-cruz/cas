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

    # ISO-4217 codes. A short list of what this client plausibly transacts in, not the
    # full 180-entry table -- an unusable select is also a data-entry hazard. The value
    # is a printed LABEL only; see PurchaseOrder.currency for why nothing converts.
    currency = SelectField('Currency', choices=[
        ('PHP', 'PHP - Philippine Peso'), ('USD', 'USD - US Dollar'),
        ('EUR', 'EUR - Euro'), ('JPY', 'JPY - Japanese Yen'),
        ('CNY', 'CNY - Chinese Yuan'), ('SGD', 'SGD - Singapore Dollar'),
        ('HKD', 'HKD - Hong Kong Dollar'), ('AUD', 'AUD - Australian Dollar'),
    ], default='PHP', validators=[DataRequired()])

    vat_treatment = SelectField('VAT Treatment', choices=[
        ('inclusive', 'VAT Inclusive'), ('exclusive', 'VAT Exclusive'),
        ('zero_rated', 'Zero-Rated'),
    ], default='inclusive', validators=[DataRequired()])

    payment_terms = SelectField('Payment Terms', validators=[DataRequired()], choices=[
        ('Net 15', 'Net 15'), ('Net 30', 'Net 30'), ('Net 45', 'Net 45'),
        ('Net 60', 'Net 60'), ('Net 90', 'Net 90'),
        ('Cash on Delivery', 'Cash on Delivery'),
        ('Advance Payment', 'Advance Payment'),
    ], default='Net 30')

    reference = StringField('Reference', validators=[Optional(), Length(max=100)])
    # What the order is FOR ("FOR PRODUCTION USE") -- printed once above the
    # line items, not as a per-line column. See migration popurp_0001.
    purpose = StringField('Purpose', validators=[Optional(), Length(max=200)])

    notes = TextAreaField('Notes', validators=[Optional()])

    # Typed per ORDER and carried onto the printout. Optional throughout: an
    # order may be raised before it is known who will check or approve it, and a
    # blank simply prints an empty ruled line to sign by hand. The view pre-fills
    # these from this PURCHASER's own last order (see next_po_signatories_for),
    # which is a suggestion -- overwriting one here must not change any other PO.
    prepared_by = StringField('Prepared by', validators=[Optional(), Length(max=100)])
    checked_by = StringField('Checked by', validators=[Optional(), Length(max=100)])
    approved_by = StringField('Approved by', validators=[Optional(), Length(max=100)])

    SIGNATORY_FIELDS = ('prepared_by', 'checked_by', 'approved_by')

    def set_vendor_choices(self, vendors):
        self.vendor_id.choices = [(0, '-- Select vendor --')] + [(v.id, v.name) for v in vendors]

    @staticmethod
    def vat_treatment_values():
        return VAT_TREATMENTS


class PurchaseOrderAmendForm(PurchaseOrderForm):
    """The PO form plus the reason a post-approval amendment must record.

    Mirrors SalesOrderAmendForm's reason rule (>=10 chars, the same bar cancel()
    already applies): an approved PO is a commitment to a vendor, so changing it
    has to say why. There is no PO analogue of SalesOrderAmendForm's
    authorizing_po_number -- that field records the CUSTOMER's authority for a
    sell-side change, and on the buy side we are the party issuing the document.
    """
    amend_reason = TextAreaField('Reason for amendment', validators=[
        DataRequired(message='Please provide a reason for this amendment.'),
        Length(min=10, message='Please provide a reason (at least 10 characters).')])
