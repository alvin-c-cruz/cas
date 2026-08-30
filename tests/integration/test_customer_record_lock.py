"""Staff may maintain customer data; an approver may FREEZE a record against them.

Owner directive 2026-08-30. Two changes that only make sense together:

1. Staff can edit a customer. They could already CREATE one through the quick-add
   on a document form, but not fix a typo in it a minute later -- and the sibling
   module, vendors, has allowed staff to edit all along. Customers were the
   outlier, not the rule.

2. An approver can LOCK a record. Widening (1) on its own removes a control and
   puts nothing back; the lock is what puts it back, per record rather than per
   role.

The rule, in one line: **a lock removes STAFF's write access and never restricts
accountant and above.** An approver can always correct a locked record -- freezing
it must not make a mistake uncorrectable -- and the same three roles that may edit
through a lock may also lift it.

Scope is the WHOLE customer: the record's own fields AND its delivery sites. A
lock that froze the name while staff kept adding drop-off addresses would not be a
lock. Delete is unchanged at accountant+, and is covered only in the sense that it
was never staff's to begin with.

Customers only for now. Vendors, products and the rest inherit this shape later,
which is why the three columns are worth getting right here.
"""
import pytest

from app import db
from app.customers.models import Customer, CustomerDeliverySite

pytestmark = [pytest.mark.integration, pytest.mark.customers]


def _login(client, user, branch):
    if branch not in user.branches.all():
        user.branches.append(branch)
    db.session.commit()
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user.id)
        sess['_fresh'] = True
        sess['selected_branch_id'] = branch.id


@pytest.fixture
def customer(db_session):
    c = Customer(code='C-LOCK', name='HILAS MARKETING CORPORATION',
                 payment_terms='Net 90', is_active=True)
    db.session.add(c)
    db.session.commit()
    return c


def _edit_post(client, customer, **over):
    data = {'code': customer.code, 'name': customer.name,
            'payment_terms': 'Net 30', 'is_active': '1'}
    data.update(over)
    return client.post('/customers/%d/edit' % customer.id, data=data,
                       follow_redirects=True)


class TestStaffMayMaintainCustomers:

    def test_staff_can_open_the_edit_form(self, client, db_session, staff_user,
                                          main_branch, customer):
        """THE WIDENING. Staff could already create a customer through quick-add;
        being unable to correct it was the inconsistency."""
        _login(client, staff_user, main_branch)

        resp = client.get('/customers/%d/edit' % customer.id)

        assert resp.status_code == 200, 'staff was bounced off the customer edit form'
        assert b'C-LOCK' in resp.data, 'the form did not render the customer'

    def test_staff_can_save_a_change(self, client, db_session, staff_user,
                                     main_branch, customer):
        """Reaching the form is not the same as being allowed to save from it --
        the route re-checks on POST, and only this proves the write lands."""
        _login(client, staff_user, main_branch)

        _edit_post(client, customer, name='HILAS MARKETING CORP.')

        assert db.session.get(Customer, customer.id).name == 'HILAS MARKETING CORP.', \
            'the staff save did not persist'

    def test_staff_can_add_a_delivery_site(self, client, db_session, staff_user,
                                           main_branch, customer):
        """Delivery sites are customer data and follow the same rule (owner,
        2026-08-30: "include new delivery site to staffs")."""
        _login(client, staff_user, main_branch)

        client.post('/customers/%d/delivery-sites/create' % customer.id,
                    data={'name': 'TAGUIG COLD STORE'}, follow_redirects=True)

        sites = CustomerDeliverySite.query.filter_by(customer_id=customer.id).all()
        assert [s.name for s in sites] == ['TAGUIG COLD STORE'], \
            'staff could not add a delivery site to an unlocked customer'


class TestALockedRecordRefusesStaff:

    def test_a_new_customer_is_unlocked(self, db_session, customer):
        """CONTROL, and the migration's contract: nothing is frozen by default, so
        no existing customer becomes uneditable the moment this ships."""
        assert customer.is_locked is False
        assert customer.locked_by_id is None
        assert customer.locked_at is None

    def test_staff_cannot_open_the_edit_form_when_locked(
            self, client, db_session, staff_user, admin_user, main_branch, customer):
        customer.lock(admin_user)
        db.session.commit()
        _login(client, staff_user, main_branch)

        resp = client.get('/customers/%d/edit' % customer.id, follow_redirects=True)

        assert b'C-LOCK' not in resp.data or b'locked' in resp.data.lower(), \
            'staff was served the edit form for a locked customer'

    def test_staff_cannot_SAVE_a_locked_customer(
            self, client, db_session, staff_user, admin_user, main_branch, customer):
        """THE ONE THAT MATTERS. Hiding the form is cosmetic; the POST is the door.
        A guard that only hid the button would pass the test above and still let a
        crafted POST through."""
        customer.lock(admin_user)
        db.session.commit()
        _login(client, staff_user, main_branch)

        _edit_post(client, customer, name='TAMPERED BY STAFF')

        assert db.session.get(Customer, customer.id).name == 'HILAS MARKETING CORPORATION', \
            'a locked customer was modified by staff through a direct POST'

    def test_staff_cannot_add_a_delivery_site_when_locked(
            self, client, db_session, staff_user, admin_user, main_branch, customer):
        """A lock that froze the name while staff kept adding addresses under it
        would not be a lock."""
        customer.lock(admin_user)
        db.session.commit()
        _login(client, staff_user, main_branch)

        client.post('/customers/%d/delivery-sites/create' % customer.id,
                    data={'name': 'SNUCK IN'}, follow_redirects=True)

        assert CustomerDeliverySite.query.filter_by(customer_id=customer.id).count() == 0, \
            'a delivery site was added to a locked customer by staff'


class TestApproversAreNeverRestricted:

    @pytest.mark.parametrize('role', ['accountant', 'admin'])
    def test_an_approver_can_still_edit_a_locked_customer(
            self, client, db_session, request, admin_user, main_branch, customer, role):
        """A lock must not make a record uncorrectable -- otherwise a typo frozen
        by mistake needs a DBA. Accountant, chief accountant and admin all keep
        write access through the lock (owner, 2026-08-30)."""
        actor = admin_user if role == 'admin' else request.getfixturevalue('accountant_user')
        customer.lock(admin_user)
        db.session.commit()
        _login(client, actor, main_branch)

        _edit_post(client, customer, name='CORRECTED BY %s' % role.upper())

        assert db.session.get(Customer, customer.id).name == 'CORRECTED BY %s' % role.upper(), \
            '%s could not correct a locked customer' % role

    def test_an_approver_can_lock_and_unlock(
            self, client, db_session, accountant_user, main_branch, customer):
        _login(client, accountant_user, main_branch)

        client.post('/customers/%d/lock' % customer.id, follow_redirects=True)
        locked = db.session.get(Customer, customer.id)
        assert locked.is_locked is True, 'the lock action did not take'
        assert locked.locked_by_id == accountant_user.id, 'the lock did not record WHO'
        assert locked.locked_at is not None, 'the lock did not record WHEN'

        client.post('/customers/%d/unlock' % customer.id, follow_redirects=True)
        after = db.session.get(Customer, customer.id)
        assert after.is_locked is False, 'the unlock action did not take'
        assert after.locked_by_id is None and after.locked_at is None, \
            'unlocking left stale lock provenance behind'

    def test_staff_cannot_lock_or_unlock(
            self, client, db_session, staff_user, main_branch, customer):
        """CONTROL. If staff could lift the lock, the lock would protect nothing."""
        _login(client, staff_user, main_branch)

        client.post('/customers/%d/lock' % customer.id, follow_redirects=True)

        assert db.session.get(Customer, customer.id).is_locked is False, \
            'staff locked a customer record'


class TestTheControlsMatchTheRules:
    """The Edit button is currently rendered unconditionally (list.html:92,
    detail.html:20), so staff saw a control the route then refused -- the
    delete_approved_email shape. Widening access does not remove that problem, it
    moves it: a LOCKED record would dangle the same dead button at staff.
    """

    def test_a_locked_record_offers_staff_no_edit_link(
            self, client, db_session, staff_user, admin_user, main_branch, customer):
        customer.lock(admin_user)
        db.session.commit()
        _login(client, staff_user, main_branch)

        body = client.get('/customers').data.decode()

        assert '/customers/%d/edit' % customer.id not in body, \
            'the list offered staff an Edit link the route will refuse'

    def test_an_unlocked_record_DOES_offer_staff_the_edit_link(
            self, client, db_session, staff_user, main_branch, customer):
        """CONTROL, and the one that stops the fix being "hide it from everyone".
        An absence-only assertion passes just as well when the button is gone for
        good."""
        _login(client, staff_user, main_branch)

        body = client.get('/customers').data.decode()

        assert '/customers/%d/edit' % customer.id in body, \
            'staff lost the Edit link on a customer they are allowed to edit'

    def test_the_list_says_a_record_is_locked(
            self, client, db_session, accountant_user, admin_user, main_branch, customer):
        """Someone has to be able to SEE the freeze without opening the record."""
        customer.lock(admin_user)
        db.session.commit()
        _login(client, accountant_user, main_branch)

        assert b'Locked' in client.get('/customers').data, \
            'a locked customer is indistinguishable from an unlocked one'


class TestTheLockIsAudited:

    def test_locking_writes_an_audit_row(
            self, client, db_session, accountant_user, main_branch, customer):
        """"Who froze this, and when" is the question the columns exist to answer;
        the audit log is where it gets asked."""
        from app.audit.models import AuditLog
        _login(client, accountant_user, main_branch)

        client.post('/customers/%d/lock' % customer.id, follow_redirects=True)

        rows = [r for r in AuditLog.query.filter_by(module='customer').all()
                if 'C-LOCK' in (r.record_identifier or '')]
        assert rows, 'locking a customer left no audit trail'

        # The row existing is not the assertion. `is_locked` has to be inside the
        # snapshot, or both sides of the diff are identical and the entry records
        # "nothing changed" about the only thing that did.
        entry = rows[-1]
        assert 'is_locked' in (entry.new_values or ''), \
            'the audit snapshot omits is_locked, so the lock is invisible in the log'
        assert '"is_locked": true' in (entry.new_values or '').lower().replace("'", '"'), \
            'the audit row does not record the customer as locked'
        assert '"is_locked": false' in (entry.old_values or '').lower().replace("'", '"'), \
            'the audit row does not record what the lock changed FROM'
