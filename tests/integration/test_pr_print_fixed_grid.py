"""The printed requisition pads to a fixed number of line rows.

Every sheet is then the same shape: the signature block lands in the same place
whatever the requisition holds, and the spare ruled rows give somewhere to add an
item by hand.

The padding is a MINIMUM, never a cap. Truncating a long requisition to a tidy
page would hide ordered items from the person signing for them.
"""
import re
from datetime import date

import pytest

from app.purchase_requests.models import PurchaseRequest, PurchaseRequestItem
from app.purchase_requests.views import PRINT_MIN_ROWS

pytestmark = [pytest.mark.integration]


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


def _print_with_lines(client, db_session, admin_user, main_branch, n, number):
    _enable(db_session)
    pr = PurchaseRequest(pr_number=number, request_date=date(2026, 7, 30),
                         branch_id=main_branch.id, status='draft',
                         created_by_id=admin_user.id)
    db_session.add(pr)
    db_session.flush()
    for i in range(1, n + 1):
        db_session.add(PurchaseRequestItem(purchase_request_id=pr.id, line_number=i,
                                           description=f'ITEM-{i}', quantity=i))
    db_session.commit()
    _login(client, admin_user, main_branch)
    resp = client.get(f'/purchase-requests/{pr.id}/print')
    assert resp.status_code == 200
    return resp.data.decode()


def _body_rows(html):
    """Rows inside the line-items tbody only -- the meta table has rows too."""
    body = re.search(r'<table class="lines">.*?<tbody>(.*?)</tbody>', html, re.S)
    assert body, 'line-items tbody not found'
    return re.findall(r'<tr[^>]*>', body.group(1))


class TestGridIsPaddedToAFixedHeight:

    def test_short_requisition_is_padded(self, client, db_session, admin_user, main_branch):
        html = _print_with_lines(client, db_session, admin_user, main_branch, 3, 'GRID-3')
        assert len(_body_rows(html)) == PRINT_MIN_ROWS

    def test_padding_rows_carry_no_data(self, client, db_session, admin_user, main_branch):
        """Filler must be blank -- not a repeated last line, and not numbered,
        which would imply a line exists."""
        html = _print_with_lines(client, db_session, admin_user, main_branch, 3, 'GRID-B')
        assert html.count('<tr class="filler">') == PRINT_MIN_ROWS - 3
        assert '<tr class="filler"><td class="idx"></td><td></td><td></td><td></td><td></td></tr>' in html

    def test_real_lines_still_render(self, client, db_session, admin_user, main_branch):
        """Control: padding must not displace the actual items."""
        html = _print_with_lines(client, db_session, admin_user, main_branch, 3, 'GRID-R')
        for i in (1, 2, 3):
            assert f'ITEM-{i}' in html

    def test_exactly_full_requisition_gets_no_padding(self, client, db_session,
                                                      admin_user, main_branch):
        html = _print_with_lines(client, db_session, admin_user, main_branch,
                                 PRINT_MIN_ROWS, 'GRID-EXACT')
        assert len(_body_rows(html)) == PRINT_MIN_ROWS
        # Count the ROW, not the bare word: the stylesheet defines tr.filler, so
        # "filler" is in the response whether or not a filler row was emitted.
        assert html.count('<tr class="filler">') == 0


class TestLongRequisitionIsNeverTruncated:

    def test_more_lines_than_the_minimum_all_print(self, client, db_session,
                                                   admin_user, main_branch):
        """range() of a negative number is empty, so a long requisition simply
        prints every line. Pinned, because a cap here would silently drop ordered
        items from a document someone signs."""
        n = PRINT_MIN_ROWS + 5
        html = _print_with_lines(client, db_session, admin_user, main_branch, n, 'GRID-LONG')

        assert len(_body_rows(html)) == n
        assert html.count('<tr class="filler">') == 0
        assert f'ITEM-{n}' in html
