"""A no-PO line is flagged when the vendor has an open order line for that product.

Owner request 2026-09-07. PO-less receipts are expected weekly or more, so the mismatch
is caught at ENTRY rather than only repaired afterwards.

It WARNS, it does not block. The match is a heuristic: it knows this vendor has an open
line for this product, not that this carton came off that order. A free replacement, a
sample, or a second delivery are all legitimate direct receipts against an open order,
and blocking would make them unrecordable.

KNOWN LIMIT, by owner decision: the warning fires at pick time in the browser, and the
server stores the override reason WITHOUT refusing a line that lacks one. A raw POST, or
an order approved between picking and saving, gets past it. Recorded here so it is not
mistaken for an oversight.
"""
from datetime import date
from decimal import Decimal

import pytest

from app.receiving_reports.models import ReceivingReport
from tests.integration.test_rr_submit import _login, rr_enabled  # noqa: F401

pytestmark = [pytest.mark.integration, pytest.mark.receiving_reports]


@pytest.fixture
def vendor(db_session):
    from app.vendors.models import Vendor
    v = Vendor(code='WARN-V', name='Warning Test Supplier', is_active=True)
    db_session.add(v); db_session.commit()
    return v


@pytest.fixture
def other_vendor(db_session):
    from app.vendors.models import Vendor
    v = Vendor(code='WARN-V2', name='Other Supplier', is_active=True)
    db_session.add(v); db_session.commit()
    return v


@pytest.fixture
def product(db_session):
    from app.products.models import Product
    p = Product(code='WARN-P', name='Warned Item', track_inventory=False, is_active=True)
    db_session.add(p); db_session.commit()
    return p


def _open_po(db_session, branch, vendor, product, user, number='PO-WARN-1', qty='10'):
    from app.purchase_orders.models import PurchaseOrder, PurchaseOrderItem
    po = PurchaseOrder(branch_id=branch.id, po_number=number,
                       order_date=date(2026, 9, 1), vendor_id=vendor.id,
                       vendor_name=vendor.name, status='approved',
                       vat_treatment='inclusive', created_by_id=user.id)
    po.line_items.append(PurchaseOrderItem(
        line_number=1, description='Ordered thing', quantity=Decimal(qty),
        unit_price=Decimal('100'), amount=Decimal(qty) * 100,
        product_id=product.id, vat_rate=Decimal('12')))
    db_session.add(po); db_session.commit()
    return po


class TestThePayloadCarriesTheProduct:

    def test_open_lines_name_their_product_id(self, client, db_session, main_branch,
                                              vendor, product, admin_user):
        """Without product_id the browser cannot match a chosen product to an open
        order line at all -- product_code is display text, not an identity.

        Asserted against the ENDPOINT, not the create page. On a fresh GET of
        /receiving-reports/create the view sets `eligible = []` deliberately -- there is
        no vendor until the receiver picks one -- so the page-load payload is empty and
        proves nothing. The endpoint is what the browser actually reads.
        """
        _open_po(db_session, main_branch, vendor, product, admin_user)
        _login(client, admin_user, main_branch)
        rows = client.get('/receiving-reports/open-lines?vendor_id=%s'
                          % vendor.id).get_json()['lines']
        assert rows, 'the endpoint offered no open lines'
        assert rows[0]['product_id'] == product.id

    def test_another_vendors_open_line_is_not_offered(self, client, db_session,
                                                      main_branch, other_vendor,
                                                      vendor, product, admin_user):
        """CONTROL, and the reason the warning needs no vendor check of its own: the
        endpoint is already scoped, so a match can only ever be this vendor's."""
        _open_po(db_session, main_branch, other_vendor, product, admin_user,
                 number='PO-WARN-OTHER')
        _login(client, admin_user, main_branch)
        rows = client.get('/receiving-reports/open-lines?vendor_id=%s'
                          % vendor.id).get_json()['lines']
        assert rows == []
