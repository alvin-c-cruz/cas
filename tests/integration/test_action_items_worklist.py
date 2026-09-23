"""Action Items is a worklist: grouped by the action, and only what you can act on.

Owner, 2026-09-23: "Our user angilyn is not being guided accordingly with the
current setup of Action Items. I myself is also confused."

WHAT WAS WRONG
--------------
One card titled "Drafts", subtitled "N unfinished documents", holding three
unrelated things behind a single "Continue" button:

  * the reader's own drafts,
  * SUBMITTED documents missing a required file (the service picks submitted
    deliberately, and says so) -- so a row could read "Submitted" under a heading
    that said "Drafts", asking you to attach a file via a button saying Continue,
  * goods another branch had sent, which are not the reader's documents at all.

And for an accountant or admin the drafts were the WHOLE BRANCH's, so the owner's
page was mostly other people's half-typed work.

THE RULE (owner's decision)
---------------------------
Every row is something this reader can act on right now. Group by the action
needed, each group with its own verb. Anything they cannot act on is gone --
including other people's drafts, which is supervision rather than a next action.

Two consequences pinned below because they are easy to "simplify" back out:
  * drafts are own-only for EVERY role now, not just staff;
  * a submitted document missing a file appears in BOTH the attach and approve
    groups. My first attempt de-duplicated it into the approval group alone, and
    the owner caught that the upload requirement then vanished entirely for
    anyone able to approve -- approval rows say only "Review and approve." and
    name no files. Two actions, two verbs, two rows.
"""
from datetime import date
from decimal import Decimal

import pytest

pytestmark = [pytest.mark.integration, pytest.mark.purchase_orders]


@pytest.fixture(autouse=True)
def modules_on(db_session):
    from app.settings import AppSettings
    from app.utils.cache_helpers import clear_module_config_cache
    for k in ('products', 'purchase_orders', 'purchase_requests', 'receiving_reports'):
        AppSettings.set_setting(f'module_enabled:{k}', '1')
    db_session.commit(); clear_module_config_cache()
    yield
    clear_module_config_cache()


@pytest.fixture
def vendor(db_session):
    from app.vendors.models import Vendor
    v = Vendor.query.filter_by(code='WL-V').first()
    if v is None:
        v = Vendor(code='WL-V', name='Worklist Vendor')
        db_session.add(v); db_session.commit()
    return v


@pytest.fixture
def colleague(db_session, main_branch):
    from app.users.models import User
    u = User.query.filter_by(username='worklistmate').first()
    if u is None:
        u = User(username='worklistmate', email='mate@test.example',
                 full_name='Work Listmate', role='staff', is_active=True)
        u.set_password('mate12345')
        db_session.add(u); db_session.commit()
    u.branches = [main_branch]
    u.set_book_permissions({'purchase_orders': True, 'products': True,
                            'purchase_requests': True})
    db_session.commit()
    return u


def _po(db_session, branch, vendor, number, status='draft', creator=None):
    from app.purchase_orders.models import PurchaseOrder, PurchaseOrderItem
    po = PurchaseOrder(branch_id=branch.id, po_number=number,
                       order_date=date(2026, 9, 23), vendor_id=vendor.id,
                       vendor_name=vendor.name, status=status,
                       vat_treatment='inclusive',
                       created_by_id=(creator.id if creator else None))
    po.line_items.append(PurchaseOrderItem(line_number=1, description='Cement',
                                           quantity=Decimal('1'),
                                           unit_price=Decimal('100')))
    db_session.add(po); db_session.commit()
    return po


def _groups(user, branch):
    from app.dashboard.action_items_service import gather_action_groups
    return gather_action_groups(user, branch.id)


def _by_key(user, branch):
    return {g['key']: g for g in _groups(user, branch)}


class TestOnlyWhatYouCanActOn:

    def test_a_colleagues_draft_is_not_on_your_worklist(
            self, db_session, admin_user, colleague, main_branch, vendor):
        """The change the owner actually asked for. Admin used to get the whole
        branch's drafts, which was most of the noise on their page."""
        _po(db_session, main_branch, vendor, 'WL-MINE', creator=admin_user)
        _po(db_session, main_branch, vendor, 'WL-THEIRS', creator=colleague)

        ids = [i['id'] for i in _by_key(admin_user, main_branch)['draft']['items']]

        assert 'WL-MINE' in ids
        assert 'WL-THEIRS' not in ids

    def test_it_is_own_only_for_staff_too_which_was_already_true(
            self, db_session, colleague, admin_user, main_branch, vendor):
        _po(db_session, main_branch, vendor, 'WL-S-MINE', creator=colleague)
        _po(db_session, main_branch, vendor, 'WL-S-OTHER', creator=admin_user)

        ids = [i['id'] for i in _by_key(colleague, main_branch)['draft']['items']]

        assert ids == ['WL-S-MINE']

    def test_a_viewer_gets_nothing(self, db_session, main_branch, vendor):
        from app.users.models import User
        v = User(username='wl_viewer', email='v@test.example', full_name='V',
                 role='viewer', is_active=True)
        v.set_password('viewer123')
        db_session.add(v); db_session.commit()
        _po(db_session, main_branch, vendor, 'WL-VIEW', creator=v)

        assert _groups(v, main_branch) == []


class TestGroupedByAction:

    def test_each_group_carries_its_own_verb(
            self, db_session, admin_user, main_branch, vendor):
        _po(db_session, main_branch, vendor, 'WL-VERB', creator=admin_user)

        draft = _by_key(admin_user, main_branch)['draft']

        assert draft['verb'] == 'Continue'
        assert draft['title'] == 'Your unfinished drafts'

    def test_an_empty_group_is_dropped_rather_than_rendered_empty(
            self, db_session, admin_user, main_branch, vendor):
        _po(db_session, main_branch, vendor, 'WL-ONLY', creator=admin_user)

        keys = [g['key'] for g in _groups(admin_user, main_branch)]

        assert keys == ['draft'], 'only the group with something in it should survive'

    def test_files_come_before_approvals_which_come_before_your_own_drafts(
            self, db_session, admin_user, colleague, main_branch, vendor):
        """Owner, 2026-09-23: files above approval.

        The same document usually appears in both, and attaching is the
        prerequisite -- reading top-down should put the file in place before the
        approve button is offered. Approvals then outrank your own drafts because
        somebody else is blocked behind them and nobody is blocked behind yours.
        """
        _po(db_session, main_branch, vendor, 'WL-ORD-DRAFT', creator=admin_user)
        _po(db_session, main_branch, vendor, 'WL-ORD-SUB', status='submitted',
            creator=colleague)

        keys = [g['key'] for g in _groups(admin_user, main_branch)]

        assert keys.index('attach') < keys.index('approve') < keys.index('draft')

    def test_ordering_does_not_block_approving_an_incomplete_document(
            self, db_session, admin_user, colleague, main_branch, vendor):
        """Order only. This system deliberately permits approving with files
        missing, so the document must still be offered for approval."""
        _po(db_session, main_branch, vendor, 'WL-STILL-APPROVABLE', status='submitted',
            creator=colleague)

        groups = _by_key(admin_user, main_branch)

        assert 'WL-STILL-APPROVABLE' in [i['id'] for i in groups['approve']['items']]
        assert groups['approve']['verb'] == 'Review'

    def test_oldest_first_so_the_stalest_row_is_not_buried(
            self, db_session, admin_user, main_branch, vendor):
        """Drafts used to come out newest-first, putting the forgotten one last."""
        _po(db_session, main_branch, vendor, 'WL-OLD', creator=admin_user)
        _po(db_session, main_branch, vendor, 'WL-NEW', creator=admin_user)

        ids = [i['id'] for i in _by_key(admin_user, main_branch)['draft']['items']]

        assert ids == ['WL-OLD', 'WL-NEW']


class TestASubmittedDocumentMissingAFileShowsBothNeeds:
    """Owner decision 2026-09-23, correcting my first attempt.

    I de-duplicated these, keeping only the approval row, on the reasoning that an
    approver fixes both in one visit. That was wrong in a way the owner spotted
    from the outside: gather_document_approval_items describes EVERY row as
    "Review and approve." and names no files, so the upload requirement vanished
    from the page entirely for anyone who can approve -- worse than the old page,
    which at least showed it as a badly-labelled separate row.

    Two actions, two verbs, two rows. The badge therefore counts actions rather
    than documents.
    """

    def test_an_approver_sees_it_in_BOTH_groups(
            self, db_session, admin_user, colleague, main_branch, vendor):
        _po(db_session, main_branch, vendor, 'WL-DUP', status='submitted',
            creator=colleague)

        groups = _by_key(admin_user, main_branch)

        assert 'WL-DUP' in [i['id'] for i in groups['approve']['items']]
        assert 'WL-DUP' in [i['id'] for i in groups['attach']['items']],             'the upload requirement must not vanish for someone able to approve'

    def test_the_two_rows_ask_for_different_things(
            self, db_session, admin_user, colleague, main_branch, vendor):
        """The point of splitting them. Same document, different verbs."""
        _po(db_session, main_branch, vendor, 'WL-VERBS', status='submitted',
            creator=colleague)

        groups = _by_key(admin_user, main_branch)

        assert groups['approve']['verb'] == 'Review'
        assert groups['attach']['verb'] == 'Attach'

    def test_the_attach_row_names_the_missing_files_where_the_approval_row_does_not(
            self, db_session, admin_user, colleague, main_branch, vendor):
        """Precisely why one row was not enough."""
        _po(db_session, main_branch, vendor, 'WL-NAMES', status='submitted',
            creator=colleague)

        groups = _by_key(admin_user, main_branch)
        attach = next(i for i in groups['attach']['items'] if i['id'] == 'WL-NAMES')
        approve = next(i for i in groups['approve']['items'] if i['id'] == 'WL-NAMES')

        assert 'Signed PO' in attach['desc']
        assert 'Signed PO' not in approve['desc']

    def test_a_non_approver_still_sees_their_own_in_attach(
            self, db_session, colleague, main_branch, vendor):
        """Staff cannot approve, so nobody else is going to chase the file."""
        _po(db_session, main_branch, vendor, 'WL-ATT', status='submitted',
            creator=colleague)

        groups = _by_key(colleague, main_branch)

        assert 'approve' not in groups, 'staff must not get an approval group'
        assert 'WL-ATT' in [i['id'] for i in groups['attach']['items']]

    def test_the_attach_row_says_what_to_attach(
            self, db_session, colleague, main_branch, vendor):
        _po(db_session, main_branch, vendor, 'WL-ATT2', status='submitted',
            creator=colleague)

        row = next(i for i in _by_key(colleague, main_branch)['attach']['items']
                   if i['id'] == 'WL-ATT2')

        assert 'Signed PO' in row['desc']


class TestTheBadgeCannotDisagreeWithThePage:
    """The old count re-derived its own numbers and carried three comments
    apologising for the ways it could drift. It is now summed from the same
    groups, so a disagreement is unrepresentable rather than merely tested for."""

    @pytest.mark.parametrize('who', ['admin', 'staff'])
    def test_badge_equals_the_number_of_rows(
            self, db_session, admin_user, colleague, main_branch, vendor, who):
        from app.dashboard.action_items_service import count_action_items
        user = admin_user if who == 'admin' else colleague
        _po(db_session, main_branch, vendor, 'WL-B1-%s' % who, creator=user)
        _po(db_session, main_branch, vendor, 'WL-B2-%s' % who, status='submitted',
            creator=colleague)

        rows = sum(len(g['items']) for g in _groups(user, main_branch))

        assert count_action_items(user, main_branch.id) == rows

    def test_badge_is_zero_when_there_is_nothing(
            self, db_session, admin_user, main_branch):
        from app.dashboard.action_items_service import count_action_items
        assert _groups(admin_user, main_branch) == []
        assert count_action_items(admin_user, main_branch.id) == 0


class TestTheRenderedPage:

    def _login(self, client, user, branch):
        with client.session_transaction() as sess:
            sess['_user_id'] = str(user.id)
            sess['_fresh'] = True
            sess['selected_branch_id'] = branch.id
        import flask
        flask.g.pop('_login_user', None)

    def test_the_heading_no_longer_calls_everything_a_draft(
            self, client, db_session, colleague, main_branch, vendor):
        """The specific defect: a submitted document under a "Drafts" heading."""
        _po(db_session, main_branch, vendor, 'WL-PAGE', status='submitted',
            creator=colleague)
        self._login(client, colleague, main_branch)

        body = client.get('/action-items').data.decode()

        assert 'Missing a required file' in body
        assert 'WL-PAGE' in body
        assert '>Drafts<' not in body

    def test_the_button_says_what_the_row_needs(
            self, client, db_session, colleague, main_branch, vendor):
        _po(db_session, main_branch, vendor, 'WL-PAGE2', status='submitted',
            creator=colleague)
        self._login(client, colleague, main_branch)

        body = client.get('/action-items').data.decode()

        assert '>Attach</a>' in body

    def test_an_empty_worklist_reads_as_good_news(
            self, client, db_session, admin_user, main_branch):
        self._login(client, admin_user, main_branch)

        body = client.get('/action-items').data.decode()

        assert 'Nothing needs you right now' in body
