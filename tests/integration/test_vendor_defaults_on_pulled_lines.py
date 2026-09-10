"""A line ADDED or PULLED starts on the vendor's default VAT (and WT).

Owner, 2026-09-10, two reports with one cause:
  * /purchase-orders/create  -- "default VT is not working when adding or
    pulling a line item"
  * /accounts-payable/create -- "default VT and WT is not working when pulling
    a PO/R"

The order form had NO vendor payload at all, so every new line opened on '--'
however the vendor was configured; and the AP billing picker read the VAT
category only off the source line while hardcoding wt_id/wt_rate to null, so a
pulled line arrived bare. Because the order lines carried no category, the
receipts and bills downstream inherited nothing either -- one gap fed the other.
"""
import pathlib
import re

import pytest

pytestmark = [pytest.mark.integration]

PO_FORM = pathlib.Path('app/purchase_orders/templates/purchase_orders/form.html')
AP_PULL = pathlib.Path('app/static/ap_po_billing.js')
AP_FORM = pathlib.Path('app/accounts_payable/templates/accounts_payable/form.html')


class TestThePurchaseOrderForm:

    def test_the_view_ships_the_vendor_default_vat_map(self, db_session):
        """The payload the form needs. Asserted against a REAL vendor carrying a
        default, so an empty map cannot pass for a working one."""
        from app import db
        from app.vendors.models import Vendor
        from app.purchase_orders.views import _common_form_ctx
        v = Vendor(code='VD-1', name='Defaulted Vendor',
                   default_vat_category='V12DG', is_active=True)
        db.session.add(v); db.session.commit()
        ctx = _common_form_ctx()
        assert 'vendor_default_vat' in ctx
        assert ctx['vendor_default_vat'].get(v.id) == 'V12DG'

    def test_a_vendor_without_a_default_is_not_invented(self, db_session):
        """Control: the map carries only real configuration, never a guess."""
        from app import db
        from app.vendors.models import Vendor
        from app.purchase_orders.views import _common_form_ctx
        v = Vendor(code='VD-2', name='Bare Vendor', is_active=True)
        db.session.add(v); db.session.commit()
        assert v.id not in _common_form_ctx()['vendor_default_vat']

    def test_a_new_row_falls_back_to_the_vendor_default(self):
        """The row builder must consult the vendor when the line has no category
        of its own -- which is every line a requisition pull brings across."""
        src = PO_FORM.read_text(encoding='utf-8')
        assert 'vatOptions(d.vat_category || vendorDefaultVat())' in src

    def test_the_lookup_reads_the_picker_live(self):
        """Not a value captured at page load: on a converted requisition the
        vendor is chosen on this very page, after the script has run."""
        src = PO_FORM.read_text(encoding='utf-8')
        m = re.search(r'function vendorDefaultVat\(\)\s*\{(.*?)\n  \}', src, re.S)
        assert m, 'vendorDefaultVat() is not defined'
        assert "getElementById('vendorSelect')" in m.group(1)


class TestTheAPBillingPull:

    def test_the_pull_applies_the_vendor_defaults(self):
        src = AP_PULL.read_text(encoding='utf-8')
        assert 'vendorDefaults.vat_category' in src
        assert 'wt_id: vendorDefaults.wt_id' in src

    def test_it_no_longer_hardcodes_a_null_withholding_tax(self):
        """The specific defect: whatever the vendor was configured with, a
        pulled line arrived with no withholding at all.

        Scoped to the ROW being built, not the whole file: the fallback object
        a few lines above legitimately reads wt_id: null, for the case where
        the form never exposed its helper. An earlier draft of this assertion
        searched the whole file and failed against correct code.
        """
        src = AP_PULL.read_text(encoding='utf-8')
        row = src[src.index('window.addLineItem({'):]
        row = row[:row.index('});')]
        assert 'wt_id: null' not in row, row

    def test_the_source_line_still_wins_when_it_has_a_category(self):
        """The vendor default is a FALLBACK. A PO line billed under a specific
        category must keep it, or billing would silently rewrite the order."""
        src = AP_PULL.read_text(encoding='utf-8')
        assert 'ln.vat_category || vendorDefaults.vat_category' in src

    def test_the_helper_is_exposed_by_the_form(self):
        src = AP_FORM.read_text(encoding='utf-8')
        assert 'window.vendorLineDefaults = function ()' in src

    def test_the_helper_keeps_the_single_withholding_tax_rule(self):
        """Mirrors addLineItem: a vendor with several withholding taxes is
        ambiguous, and guessing one would book the wrong rate silently."""
        src = AP_FORM.read_text(encoding='utf-8')
        m = re.search(r'window\.vendorLineDefaults = function \(\) \{(.*?)\n\};', src, re.S)
        assert m, 'the helper is not defined'
        assert 'currentVendorWHTs.length === 1' in m.group(1)
