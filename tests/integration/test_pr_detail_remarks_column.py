"""The requisition detail page must show each line's Remarks.

Its Item cell rendered `product.name if product else description`, and there was
no Remarks column at all -- so on a line carrying BOTH a product and remarks the
remarks were invisible. PhilGen's requisition 25-0909 is exactly that shape: two
lines, each a real product with "FOR PRODUCTION USE" as its remarks, none of
which appeared on screen.

The printed form already splits them correctly (Item = product, Remarks =
description, with the description promoted to Item only when there is no
product). These tests pin the detail page to that same split, and a control
keeps print honest so the two surfaces cannot drift apart again.
"""
from datetime import date

import pytest

from app.purchase_requests.models import PurchaseRequest, PurchaseRequestItem

pytestmark = [pytest.mark.integration]


@pytest.fixture(autouse=True)
def pr_enabled(db_session):
    from app.settings import AppSettings
    from app.utils.cache_helpers import clear_module_config_cache
    for k in ('products', 'purchase_requests', 'units_of_measure'):
        AppSettings.set_setting(f'module_enabled:{k}', '1')
    db_session.commit()
    clear_module_config_cache()
    yield
    clear_module_config_cache()


def _login(client, user, branch):
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user.id)
        sess['_fresh'] = True
        sess['selected_branch_id'] = branch.id


@pytest.fixture
def product(db_session):
    from app.products.models import Product
    p = Product(code='RM0003', name='CARBIDE', is_active=True)
    db_session.add(p)
    db_session.commit()
    return p


@pytest.fixture
def pr(db_session, admin_user, main_branch, product):
    """Mirrors 25-0909: a real product PLUS remarks on the same line."""
    p = PurchaseRequest(pr_number='REM-1', request_date=date(2026, 8, 14),
                        branch_id=main_branch.id, status='draft',
                        created_by_id=admin_user.id)
    p.line_items.append(PurchaseRequestItem(
        line_number=1, product_id=product.id, description='FOR PRODUCTION USE',
        quantity=20))
    db_session.add(p)
    db_session.commit()
    return p


@pytest.fixture
def textonly_pr(db_session, admin_user, main_branch):
    """A line with NO product -- its text is the item itself."""
    p = PurchaseRequest(pr_number='REM-2', request_date=date(2026, 8, 14),
                        branch_id=main_branch.id, status='draft',
                        created_by_id=admin_user.id)
    p.line_items.append(PurchaseRequestItem(
        line_number=1, description='Assorted fasteners', quantity=5))
    db_session.add(p)
    db_session.commit()
    return p


class TestTheDetailPage:

    def test_it_has_a_remarks_header(self, client, admin_user, main_branch, pr):
        _login(client, admin_user, main_branch)
        html = client.get(f'/purchase-requests/{pr.id}').data.decode()
        assert 'Remarks' in html, 'the line table has no Remarks column'

    def test_remarks_are_shown_alongside_the_product(self, client, admin_user,
                                                     main_branch, pr):
        """The regression itself: both values must be readable on one line."""
        _login(client, admin_user, main_branch)
        html = client.get(f'/purchase-requests/{pr.id}').data.decode()
        assert 'CARBIDE' in html
        assert 'FOR PRODUCTION USE' in html, (
            'the remarks are still swallowed by the Item cell')

    def test_a_text_only_line_reads_as_the_item(self, client, admin_user,
                                                main_branch, textonly_pr):
        """Control: a line with no product keeps its text as the Item, matching
        the printed form -- it must not vanish into Remarks and leave Item blank."""
        _login(client, admin_user, main_branch)
        html = client.get(f'/purchase-requests/{textonly_pr.id}').data.decode()
        assert 'Assorted fasteners' in html


class TestPrintKeepsTheSameSplit:
    """Control on the surface that was already correct -- so a later edit to one
    template cannot silently diverge from the other."""

    def test_print_shows_product_and_remarks_separately(self, client, admin_user,
                                                        main_branch, pr):
        _login(client, admin_user, main_branch)
        html = client.get(f'/purchase-requests/{pr.id}/print').data.decode()
        assert 'CARBIDE' in html
        assert 'FOR PRODUCTION USE' in html

    def test_print_promotes_a_text_only_line_to_item(self, client, admin_user,
                                                     main_branch, textonly_pr):
        _login(client, admin_user, main_branch)
        html = client.get(f'/purchase-requests/{textonly_pr.id}/print').data.decode()
        assert 'Assorted fasteners' in html
