"""The PR printout carries the line's Remarks (the paper form's Purpose/Remarks).

A PR line has ONE free-text field, `description`, and the Item cell already falls
back to it when there is no product. So the Remarks cell must render it only when
a product occupies the Item cell -- otherwise a product-less line prints the same
sentence twice across the row.
"""
from datetime import date

import pytest

from app.products.models import Product
from app.purchase_requests.models import PurchaseRequest, PurchaseRequestItem

pytestmark = [pytest.mark.integration]

REMARK = 'FOR GINACA SPARE PARTS, DAILY USE'
FREE_TEXT = 'Hand-written item with no product record'


def _login(client, user, branch):
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user.id)
        sess['_fresh'] = True
        sess['selected_branch_id'] = branch.id


def _enable(db_session):
    from app.settings import AppSettings
    from app.utils.cache_helpers import clear_module_config_cache
    for k in ('products', 'purchase_orders', 'purchase_requests'):
        AppSettings.set_setting(f'module_enabled:{k}', '1')
    db_session.commit()
    clear_module_config_cache()


@pytest.fixture
def printed(client, db_session, admin_user, main_branch):
    _enable(db_session)
    product = Product(code='S-C71-4-14', name='SEAL', is_active=True)
    db_session.add(product)
    db_session.commit()

    pr = PurchaseRequest(pr_number='REMARK-1', request_date=date(2026, 7, 30),
                         branch_id=main_branch.id, status='draft',
                         created_by_id=admin_user.id)
    db_session.add(pr)
    db_session.flush()
    db_session.add(PurchaseRequestItem(purchase_request_id=pr.id, line_number=1,
                                       product_id=product.id, description=REMARK,
                                       quantity=3))
    db_session.add(PurchaseRequestItem(purchase_request_id=pr.id, line_number=2,
                                       description=FREE_TEXT, quantity=1))
    db_session.commit()

    _login(client, admin_user, main_branch)
    resp = client.get(f'/purchase-requests/{pr.id}/print')
    assert resp.status_code == 200
    return resp.data


class TestRemarksColumn:

    def test_column_heading_present(self, printed):
        # Heading renamed to "Purpose/Remarks" (owner directive 2026-08-14, with
        # the column order). Updated rather than loosened to a substring match:
        # `b'Remarks' in printed` would also pass if the heading were dropped and
        # the word survived only in a comment or another cell.
        assert b'>Purpose/Remarks<' in printed

    def test_remark_prints_for_a_product_line(self, printed):
        assert REMARK.encode() in printed

    def test_product_name_still_prints(self, printed):
        """Control: the new column must not displace the Item cell."""
        assert b'SEAL' in printed

    def test_free_text_line_is_not_duplicated(self, printed):
        """A line with no product uses `description` AS the item. Printing it in
        Remarks as well repeats the same sentence twice on one row."""
        assert printed.count(FREE_TEXT.encode()) == 1
