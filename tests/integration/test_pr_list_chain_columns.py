"""The requisition list names the whole buy-side chain: PO, RR, AP and CD.

Owner request 2026-09-06. Fulfilment is a question about which DOCUMENTS exist
downstream, not about the requisition's own approval state, so it is answered by
columns rather than by chips crowded into the Status cell. The short-lived
"Ordered" chip (2026-09-06, same day) was dropped when these columns replaced it.

Each column is resolved ONCE per page in list_pr() -- four queries for the whole
table, never one per row.

Chain: PR line -> PO line (source_pr_item_id) -> RR line (purchase_order_item_id)
-> AP (ReceivingReport.accounts_payable_id) -> CD (CDVApLine.ap_id).
"""
from datetime import date
from decimal import Decimal
import pytest

pytestmark = [pytest.mark.integration, pytest.mark.purchase_requests]


@pytest.fixture(autouse=True)
def modules_enabled(db_session):
    from app.settings import AppSettings
    from app.utils.cache_helpers import clear_module_config_cache
    for k in ('products', 'purchase_orders', 'purchase_requests', 'receiving_reports'):
        AppSettings.set_setting(f'module_enabled:{k}', '1')
    db_session.commit(); clear_module_config_cache()
    yield
    clear_module_config_cache()


def _login(client, user, branch):
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user.id); sess['_fresh'] = True
        sess['selected_branch_id'] = branch.id


def _chain(db_session, branch, upto='po', number='CHN-1', rr_status='approved'):
    """Build the chain as far as *upto*: 'po' | 'rr' | 'ap'. Returns the PR."""
    from app.purchase_requests.models import PurchaseRequest, PurchaseRequestItem
    from app.purchase_orders.models import PurchaseOrder, PurchaseOrderItem
    from app.receiving_reports.models import ReceivingReport, ReceivingReportItem
    from app.accounts_payable.models import AccountsPayable
    from app.vendors.models import Vendor

    vendor = Vendor.query.filter_by(code='CHN-VEND').first()
    if vendor is None:
        vendor = Vendor(code='CHN-VEND', name='Chain Test Vendor')
        db_session.add(vendor); db_session.commit()

    pr = PurchaseRequest(branch_id=branch.id, pr_number=number,
                         request_date=date(2026, 9, 6), status='approved',
                         reason='Site needs cement')
    pr_item = PurchaseRequestItem(line_number=1, description='Cement',
                                  quantity=Decimal('10'), uom_text='bag')
    pr.line_items.append(pr_item)
    db_session.add(pr); db_session.commit()

    po = PurchaseOrder(branch_id=branch.id, po_number=f'PO{number}',
                       order_date=date(2026, 9, 6), status='approved',
                       vendor_id=vendor.id, vendor_name=vendor.name)
    po_item = PurchaseOrderItem(line_number=1, description='Cement',
                                quantity=Decimal('10'),
                                source_pr_item_id=pr_item.id)
    po.line_items.append(po_item)
    db_session.add(po); db_session.commit()
    if upto == 'po':
        return pr

    rr = ReceivingReport(branch_id=branch.id, rr_number=f'RR{number}',
                         receipt_date=date(2026, 9, 6), status=rr_status,
                         vendor_id=vendor.id, vendor_name=vendor.name)
    rr.line_items.append(ReceivingReportItem(
        line_number=1, purchase_order_item_id=po_item.id,
        received_quantity=Decimal('10')))
    db_session.add(rr); db_session.commit()
    if upto == 'rr':
        return pr

    ap = AccountsPayable(branch_id=branch.id, ap_number=f'AP{number}',
                         ap_date=date(2026, 9, 6), due_date=date(2026, 10, 6),
                         payee_type='vendor', payee_id=vendor.id,
                         vendor_id=vendor.id, vendor_name=vendor.name,
                         status='posted')
    db_session.add(ap); db_session.commit()
    rr.accounts_payable_id = ap.id
    db_session.commit()
    return pr


class TestTheColumnsExist:

    def test_the_header_names_all_four_documents(self, client, accountant_user,
                                                 main_branch, db_session):
        _login(client, accountant_user, main_branch)
        _chain(db_session, main_branch, upto='po', number='CHN-HDR')
        body = client.get('/purchase-requests').data.decode()
        for header in ('PO #', 'RR #', 'AP #', 'CD #'):
            assert f'<th>{header}</th>' in body, header


class TestTheLinksResolve:

    def test_the_po_number_is_listed(self, client, accountant_user, main_branch,
                                     db_session):
        _login(client, accountant_user, main_branch)
        _chain(db_session, main_branch, upto='po', number='CHN-PO')
        assert 'POCHN-PO' in client.get('/purchase-requests').data.decode()

    def test_the_rr_number_is_listed(self, client, accountant_user, main_branch,
                                     db_session):
        _login(client, accountant_user, main_branch)
        _chain(db_session, main_branch, upto='rr', number='CHN-RR')
        assert 'RRCHN-RR' in client.get('/purchase-requests').data.decode()

    def test_the_ap_number_is_listed(self, client, accountant_user, main_branch,
                                     db_session):
        _login(client, accountant_user, main_branch)
        _chain(db_session, main_branch, upto='ap', number='CHN-AP')
        assert 'APCHN-AP' in client.get('/purchase-requests').data.decode()


class TestOnlyCommittedReceiptsAreNamed:

    @pytest.mark.parametrize('rr_status', ['draft', 'submitted', 'cancelled'])
    def test_an_uncommitted_receipt_is_not_listed(self, client, accountant_user,
                                                  main_branch, db_session, rr_status):
        """Naming it would tell the reader goods had arrived on the strength of
        an unapproved document."""
        _login(client, accountant_user, main_branch)
        _chain(db_session, main_branch, upto='rr', number=f'CHN-{rr_status}',
               rr_status=rr_status)
        assert f'RRCHN-{rr_status}' not in client.get('/purchase-requests').data.decode()


class TestTheOldChipIsGone:

    def test_no_ordered_chip_is_drawn(self, client, accountant_user, main_branch,
                                      db_session):
        """Dropped when the columns landed -- the chip and the PO # column said
        the same thing twice."""
        _login(client, accountant_user, main_branch)
        _chain(db_session, main_branch, upto='po', number='CHN-NOCHIP')
        body = client.get('/purchase-requests').data.decode()
        assert 'pr-ordered-chip' not in body


class TestTheStatusWording:

    def test_a_converted_pr_reads_ordered(self, client, accountant_user,
                                          main_branch, db_session):
        """The STORED status stays `converted`; only the label changes."""
        from app.purchase_requests.models import PurchaseRequest
        _login(client, accountant_user, main_branch)
        pr = _chain(db_session, main_branch, upto='po', number='CHN-WORD')
        pr.status = 'converted'
        db_session.commit()
        body = client.get('/purchase-requests').data.decode()
        assert '>Ordered<' in body
        assert '>Converted<' not in body
        assert db_session.get(PurchaseRequest, pr.id).status == 'converted'
