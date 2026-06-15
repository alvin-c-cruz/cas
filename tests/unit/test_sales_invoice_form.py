import pytest


def test_sales_invoice_form_has_customer_po_fields(app):
    """Form must have customer_po_number and customer_po_date fields."""
    with app.app_context():
        from app.sales_invoices.forms import SalesInvoiceForm
        form = SalesInvoiceForm()
        assert hasattr(form, 'customer_po_number')
        assert hasattr(form, 'customer_po_date')
        assert hasattr(form, 'customer_id')
        assert hasattr(form, 'invoice_number')
        assert hasattr(form, 'payment_terms')


def test_sales_invoice_form_no_item_subform(app):
    """SalesInvoiceItemForm should not exist in the module."""
    with app.app_context():
        import app.sales_invoices.forms as forms_module
        assert not hasattr(forms_module, 'SalesInvoiceItemForm'), \
            "SalesInvoiceItemForm should be removed — line items use JSON"
