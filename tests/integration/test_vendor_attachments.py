"""Vendor master records accept file attachments: BIR 2303, SEC reg, Business Permit.

Owner request: a supplier's certificates should live on the supplier, not in
someone's email. Almost entirely REUSE -- `document_attachments` is already
polymorphic on (document_type, document_id) with a `kind` slot per named
document, so this needed a registry entry and template wiring, and NO migration.

The two things a vendor does differently from the four documents already wired,
both covered below:

  * It is MASTER DATA with no branch. The attachments table carries no
    `branch_id` on the grounds that an attachment takes its parent's branch; a
    vendor has none, so its certificates are company-wide, which is the right
    answer for a BIR 2303 rather than a gap.
  * It has no lifecycle. `Vendor.status` is a derived property over `is_active`
    that exists only to give the upload gate something real to read, and both
    of its values are open -- going inactive is not an approval.

Deleting a vendor is the sharp edge: nothing cascades, because the link is a
plain Integer with no ORM foreign key.
"""
import io

import pytest

pytestmark = [pytest.mark.integration, pytest.mark.vendors, pytest.mark.attachments]


def _login(client, username='admin', password='admin123'):
    return client.post('/login', data={'username': username, 'password': password},
                       follow_redirects=True)


def _vendor(db_session, code='ATT-VEND', name='Attachment Test Supply'):
    from app.vendors.models import Vendor
    v = Vendor.query.filter_by(code=code).first()
    if v is None:
        v = Vendor(code=code, name=name)
        db_session.add(v); db_session.commit()
    return v


def _upload(client, vendor, kind='bir_2303', filename='2303.pdf', data=b'%PDF-1.4 fake'):
    return client.post(
        f'/attachments/vendors/{vendor.id}/upload',
        data={'kind': kind, 'attachments': (io.BytesIO(data), filename)},
        content_type='multipart/form-data', follow_redirects=True)


def _rows(vendor):
    from app.attachments.models import DocumentAttachment
    return (DocumentAttachment.query
            .filter_by(document_type='vendors', document_id=vendor.id)
            .order_by(DocumentAttachment.id).all())


class TestTheThreeSlotsAreOffered:

    def test_the_detail_page_names_all_three_certificates(
            self, client, db_session, admin_user, main_branch):
        vendor = _vendor(db_session)
        _login(client)
        body = client.get(f'/vendors/{vendor.id}').data.decode()
        assert 'BIR Form 2303' in body
        assert 'SEC Registration' in body
        assert 'Business Permit' in body

    def test_the_edit_page_offers_the_panel(
            self, client, db_session, admin_user, main_branch):
        vendor = _vendor(db_session)
        _login(client)
        body = client.get(f'/vendors/{vendor.id}/edit').data.decode()
        assert f'/attachments/vendors/{vendor.id}/upload' in body

    def test_the_create_page_offers_the_queue_and_can_carry_files(
            self, client, admin_user, main_branch):
        """The create form has no vendor id yet, so it queues files in the
        browser -- which needs the multipart enctype on the form itself."""
        _login(client)
        body = client.get('/vendors/create').data.decode()
        assert 'enctype="multipart/form-data"' in body
        assert 'id="createAttachments"' in body

    def test_the_create_page_still_names_no_2307_or_certificate_of_registration(
            self, client, admin_user, main_branch):
        """Guards the same two strings TestVendorNoBirNotes guards. The slot is
        labelled "BIR Form 2303", a different document from the 2307, and the
        create-mode queue deliberately renders no slot labels at all."""
        _login(client)
        body = client.get('/vendors/create').data
        assert b'Required on BIR Form 2307' not in body
        assert b'Certificate of Registration' not in body


class TestUploading:

    def test_a_certificate_uploads_against_its_named_slot(
            self, client, db_session, admin_user, main_branch):
        vendor = _vendor(db_session)
        _login(client)
        resp = _upload(client, vendor)
        assert resp.status_code == 200
        rows = _rows(vendor)
        assert len(rows) == 1
        assert rows[0].kind == 'bir_2303'
        assert rows[0].original_filename == '2303.pdf'

    def test_the_upload_is_audited_through_the_real_route(
            self, client, db_session, admin_user, main_branch):
        """Exercised over HTTP, not the service, so the route's own gate and the
        audit write are both in the picture."""
        from app.audit.models import AuditLog
        vendor = _vendor(db_session, code='ATT-AUD')
        _login(client)
        _upload(client, vendor, filename='audited.pdf')
        row = (AuditLog.query.filter_by(module='vendors_attachment')
               .order_by(AuditLog.id.desc()).first())
        assert row is not None, 'no audit row for the upload'
        assert 'audited.pdf' in (row.new_values or '')

    def test_all_three_slots_can_be_filled_independently(
            self, client, db_session, admin_user, main_branch):
        vendor = _vendor(db_session, code='ATT-THREE')
        _login(client)
        for kind, name in (('bir_2303', 'a.pdf'), ('sec_registration', 'b.pdf'),
                           ('business_permit', 'c.pdf')):
            _upload(client, vendor, kind=kind, filename=name)
        assert sorted(r.kind for r in _rows(vendor)) == \
            ['bir_2303', 'business_permit', 'sec_registration']

    def test_an_unknown_slot_name_lands_as_unlabelled_rather_than_being_refused(
            self, client, db_session, admin_user, main_branch):
        """The route normalises an unrecognised `kind` to None ("Other"), which
        is the existing contract for every document type."""
        vendor = _vendor(db_session, code='ATT-UNK')
        _login(client)
        _upload(client, vendor, kind='not_a_real_slot', filename='mystery.pdf')
        rows = _rows(vendor)
        assert len(rows) == 1 and rows[0].kind is None

    def test_an_inactive_vendor_still_accepts_uploads(
            self, client, db_session, admin_user, main_branch):
        """Vendor.status reads 'inactive', which the target declares open.
        Going inactive is not an approval and must freeze nothing."""
        vendor = _vendor(db_session, code='ATT-OFF')
        vendor.is_active = False
        db_session.commit()
        assert vendor.status == 'inactive'
        _login(client)
        _upload(client, vendor, filename='still-works.pdf')
        assert len(_rows(vendor)) == 1


class TestTheVendorStatusProperty:

    def test_it_follows_is_active_and_is_not_stored(self, db_session):
        from app.vendors.models import Vendor
        v = _vendor(db_session, code='ATT-PROP')
        assert v.status == 'active'
        v.is_active = False
        assert v.status == 'inactive', 'must be derived, not a cached column'
        assert 'status' not in Vendor.__table__.columns, \
            'a vendor has no lifecycle and must not gain a status column'


class TestDeletingTheVendorTakesItsFilesWithIt:
    """The sharp edge. `document_attachments.document_id` is a plain Integer with
    no ORM foreign key, so nothing cascades: without explicit cleanup the rows
    and their files outlive the vendor, and a later vendor reusing the id would
    inherit somebody else's certificates."""

    def test_the_rows_are_gone(self, client, db_session, admin_user, main_branch):
        vendor = _vendor(db_session, code='ATT-DEL')
        _login(client)
        _upload(client, vendor, filename='doomed.pdf')
        assert len(_rows(vendor)) == 1
        vendor_id = vendor.id

        resp = client.post(f'/vendors/{vendor_id}/delete', follow_redirects=True)
        assert resp.status_code == 200

        from app.vendors.models import Vendor
        from app.attachments.models import DocumentAttachment
        assert db_session.get(Vendor, vendor_id) is None, 'the vendor survived'
        assert DocumentAttachment.query.filter_by(
            document_type='vendors', document_id=vendor_id).count() == 0

    def test_the_file_is_gone_from_disk(self, client, db_session, admin_user,
                                        main_branch):
        import os
        from app.attachments.service import file_path
        vendor = _vendor(db_session, code='ATT-DELF')
        _login(client)
        _upload(client, vendor, filename='ondisk.pdf')
        path = file_path(_rows(vendor)[0])
        assert os.path.exists(path), 'precondition: the upload reached the disk'

        client.post(f'/vendors/{vendor.id}/delete', follow_redirects=True)
        assert not os.path.exists(path)

    def test_a_vendor_that_cannot_be_deleted_keeps_its_files(
            self, client, db_session, admin_user, main_branch):
        """The existing reference guard refuses the delete. The cleanup must not
        have run first -- otherwise a refused delete silently destroys files."""
        from datetime import date
        from app.accounts_payable.models import AccountsPayable
        vendor = _vendor(db_session, code='ATT-KEEP')
        _login(client)
        _upload(client, vendor, filename='kept.pdf')

        bill = AccountsPayable(branch_id=main_branch.id, ap_number='ATT-KEEP-1',
                               ap_date=date(2026, 9, 22), due_date=date(2026, 10, 22),
                               payee_type='vendor', payee_id=vendor.id,
                               vendor_id=vendor.id, vendor_name=vendor.name,
                               status='posted')
        db_session.add(bill); db_session.commit()

        resp = client.post(f'/vendors/{vendor.id}/delete', follow_redirects=True)
        assert b'Cannot delete vendor' in resp.data

        from app.vendors.models import Vendor
        assert db_session.get(Vendor, vendor.id) is not None
        assert len(_rows(vendor)) == 1, 'a refused delete destroyed the files'
