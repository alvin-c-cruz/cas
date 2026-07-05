"""Integration tests for the sv_print_form setting on Sales Invoices.

sv_print_form selects the SI print mode:
  'current' -> use the current printable form (Print button shown, subject to sv_print_access)
  'hidden'  -> no printing: Print button hidden AND the /print route refuses (redirects)

Unset defaults to 'current'. This is a separate axis from sv_print_access
(which governs WHICH statuses may print); 'hidden' overrides it entirely.
"""
import pytest
from decimal import Decimal
from datetime import date

from app.settings import AppSettings
from app.customers.models import Customer
from app.sales_invoices.models import SalesInvoice

pytestmark = [pytest.mark.sales_invoices, pytest.mark.integration]


def login(client, username='admin', password='admin123'):
    client.post('/login', data={'username': username, 'password': password},
                follow_redirects=True)


@pytest.fixture
def _customer(db_session):
    c = Customer(code='C001', name='Test Customer', is_active=True)
    db_session.add(c)
    db_session.commit()
    return c


@pytest.fixture
def _invoice(db_session, main_branch, _customer):
    inv = SalesInvoice(
        branch_id=main_branch.id,
        invoice_number='SI-2026-0001',
        invoice_date=date(2026, 6, 14),
        due_date=date(2026, 7, 14),
        customer_id=_customer.id,
        customer_name='Test Customer',
        notes='',
        status='draft',
        amount_paid=Decimal('0.00'),
    )
    db_session.add(inv)
    db_session.commit()
    return inv


class TestSvPrintFormButton:
    def test_hidden_hides_print_button_even_when_access_allows(
            self, client, db_session, admin_user, main_branch, _customer, _invoice):
        # Access would allow the button (draft_and_posted, draft invoice) ...
        AppSettings.set_setting('sv_print_access', 'draft_and_posted', 'system')
        # ... but the print form is Hidden, so the button must be gone.
        AppSettings.set_setting('sv_print_form', 'hidden', 'system')
        login(client)
        resp = client.get(f'/sales-invoices/{_invoice.id}')
        assert resp.status_code == 200
        assert f'/sales-invoices/{_invoice.id}/print' not in resp.data.decode()

    def test_current_shows_print_button_when_access_allows(
            self, client, db_session, admin_user, main_branch, _customer, _invoice):
        AppSettings.set_setting('sv_print_access', 'draft_and_posted', 'system')
        AppSettings.set_setting('sv_print_form', 'current', 'system')
        login(client)
        resp = client.get(f'/sales-invoices/{_invoice.id}')
        assert resp.status_code == 200
        assert f'/sales-invoices/{_invoice.id}/print' in resp.data.decode()

    def test_default_current_when_unset(
            self, client, db_session, admin_user, main_branch, _customer, _invoice):
        AppSettings.set_setting('sv_print_access', 'draft_and_posted', 'system')
        # sv_print_form intentionally unset -> defaults to 'current'
        login(client)
        resp = client.get(f'/sales-invoices/{_invoice.id}')
        assert resp.status_code == 200
        assert f'/sales-invoices/{_invoice.id}/print' in resp.data.decode()


class TestSvPrintFormRoute:
    def test_hidden_blocks_print_route(
            self, client, db_session, admin_user, main_branch, _customer, _invoice):
        AppSettings.set_setting('sv_print_form', 'hidden', 'system')
        login(client)
        resp = client.get(f'/sales-invoices/{_invoice.id}/print')
        assert resp.status_code == 302  # refused -> redirect, no PDF/print page
        followed = client.get(f'/sales-invoices/{_invoice.id}/print', follow_redirects=True)
        assert b'not available' in followed.data or b'not enabled' in followed.data

    def test_current_allows_print_route(
            self, client, db_session, admin_user, main_branch, _customer, _invoice):
        AppSettings.set_setting('sv_print_form', 'current', 'system')
        login(client)
        resp = client.get(f'/sales-invoices/{_invoice.id}/print')
        assert resp.status_code == 200

    def test_default_current_allows_print_route(
            self, client, db_session, admin_user, main_branch, _customer, _invoice):
        # unset -> 'current' -> route works
        login(client)
        resp = client.get(f'/sales-invoices/{_invoice.id}/print')
        assert resp.status_code == 200


class TestSvPrintFormPreprinted:
    def test_preprinted_renders_preprinted_template(
            self, client, db_session, admin_user, main_branch, _customer, _invoice):
        AppSettings.set_setting('sv_print_form', 'preprinted', 'system')
        login(client)
        resp = client.get(f'/sales-invoices/{_invoice.id}/print')
        assert resp.status_code == 200
        html = resp.data.decode()
        assert 'pp-canvas' in html   # marker unique to the pre-printed template
        assert 'sv-header' not in html    # letterhead is stripped (paper has it pre-printed)

    def test_current_renders_standard_template(
            self, client, db_session, admin_user, main_branch, _customer, _invoice):
        AppSettings.set_setting('sv_print_form', 'current', 'system')
        login(client)
        resp = client.get(f'/sales-invoices/{_invoice.id}/print')
        assert resp.status_code == 200
        html = resp.data.decode()
        assert 'sv-header' in html         # standard form keeps the letterhead
        assert 'pp-canvas' not in html


class TestPreprintedLayoutRender:
    def _prep(self, client):
        AppSettings.set_setting('sv_print_form', 'preprinted', 'system')
        login(client)

    def test_field_positioned_from_layout(self, client, db_session, admin_user,
                                          main_branch, _customer, _invoice):
        import json as _json
        from app.sales_invoices.preprinted_layout import get_layout
        layout = get_layout()
        layout['fields']['invoice_no']['x'] = 654
        AppSettings.set_setting('sv_preprinted_layout', _json.dumps(layout), 'system')
        self._prep(client)
        html = client.get(f'/sales-invoices/{_invoice.id}/print').data.decode()
        assert 'data-el="invoice_no"' in html
        assert 'left:654px' in html or 'left: 654px' in html

    def test_hidden_column_absent_visible_present(self, client, db_session, admin_user,
                                                  main_branch, _customer, _invoice):
        import json as _json
        from app.sales_invoices.preprinted_layout import get_layout
        layout = get_layout()
        for c in layout['lineItems']['columns']:
            if c['key'] == 'uom':
                c['visible'] = False
        AppSettings.set_setting('sv_preprinted_layout', _json.dumps(layout), 'system')
        self._prep(client)
        html = client.get(f'/sales-invoices/{_invoice.id}/print').data.decode()
        import re as _re
        # all columns render as positioned .pp-col blocks; the hidden one carries
        # pp-col-hidden (present but not printed)
        uom = _re.search(r'<div class="([^"]*)"\s+data-col="uom"', html)
        amt = _re.search(r'<div class="([^"]*)"\s+data-col="amount"', html)
        assert uom and 'pp-col-hidden' in uom.group(1)
        assert amt and 'pp-col-hidden' not in amt.group(1)

    def test_edit_button_admin_only(self, client, db_session, admin_user,
                                    main_branch, _customer, _invoice):
        self._prep(client)                       # logged in as admin
        html = client.get(f'/sales-invoices/{_invoice.id}/print').data.decode()
        assert 'id="editLayoutBtn"' in html

    def test_bir_summary_fields_present(self, client, db_session, admin_user,
                                        main_branch, _customer, _invoice):
        self._prep(client)
        html = client.get(f'/sales-invoices/{_invoice.id}/print').data.decode()
        for key in ('gross_sales', 'output_vat', 'net_of_vat', 'wht_amount'):
            assert f'data-el="{key}"' in html

    def test_font_picker_grouped_with_dotmatrix_fonts(self, client, db_session, admin_user,
                                                      main_branch, _customer, _invoice):
        self._prep(client)
        html = client.get(f'/sales-invoices/{_invoice.id}/print').data.decode()
        assert '<optgroup label="Dot-matrix friendly"' in html
        assert 'Consolas' in html            # a newly added monospace option

    def test_paper_dropdown_default_continuous(self, client, db_session, admin_user,
                                               main_branch, _customer, _invoice):
        self._prep(client)                   # no layout saved -> default continuous
        html = client.get(f'/sales-invoices/{_invoice.id}/print').data.decode()
        assert 'id="ppPaper"' in html
        assert '9.5 x 10.5 continuous paper' in html
        assert 'Letter 8.5 x 11' in html
        assert 'data-paper="continuous"' in html
        assert 'width:912px;height:1008px' in html   # continuous canvas

    def test_letter_paper_resizes_canvas_and_page(self, client, db_session, admin_user,
                                                  main_branch, _customer, _invoice):
        import json as _json
        from app.sales_invoices.preprinted_layout import get_layout
        layout = get_layout()
        layout['paper'] = 'letter'
        AppSettings.set_setting('sv_preprinted_layout', _json.dumps(layout), 'system')
        self._prep(client)
        html = client.get(f'/sales-invoices/{_invoice.id}/print').data.decode()
        assert 'data-paper="letter"' in html
        assert 'width:816px;height:1056px' in html   # letter canvas
        assert '8.5in 11in' in html                   # @page size

    def test_date_format_applied(self, client, db_session, admin_user,
                                 main_branch, _customer, _invoice):
        import json as _json, re as _re
        from app.sales_invoices.preprinted_layout import get_layout
        layout = get_layout()
        layout['dateFormat'] = 'iso'
        AppSettings.set_setting('sv_preprinted_layout', _json.dumps(layout), 'system')
        self._prep(client)
        html = client.get(f'/sales-invoices/{_invoice.id}/print').data.decode()
        assert 'id="ppDateFormat"' in html
        # _invoice.invoice_date is 2026-06-14 -> renders ISO when dateFormat='iso'
        m = _re.search(r'data-el="invoice_date"[^>]*>([^<]+)</div>', html)
        assert m and m.group(1).strip() == '2026-06-14'

    def test_hidden_field_marked(self, client, db_session, admin_user,
                                 main_branch, _customer, _invoice):
        import json as _json, re as _re
        from app.sales_invoices.preprinted_layout import get_layout
        layout = get_layout()
        layout['fields']['terms']['hidden'] = True
        AppSettings.set_setting('sv_preprinted_layout', _json.dumps(layout), 'system')
        self._prep(client)
        html = client.get(f'/sales-invoices/{_invoice.id}/print').data.decode()
        assert 'id="ppFieldControls"' in html
        terms = _re.search(r'<div class="([^"]*)" data-el="terms"', html)
        invno = _re.search(r'<div class="([^"]*)" data-el="invoice_no"', html)
        assert terms and 'pp-field-hidden' in terms.group(1)
        assert invno and 'pp-field-hidden' not in invno.group(1)
