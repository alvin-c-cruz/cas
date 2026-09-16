import pytest
pytestmark = [pytest.mark.accounts_payable, pytest.mark.unit]

def test_model_defaults_and_pending(db_session):
    from app.accounts_payable.amendment_models import AccountsPayableAmendmentRequest as R
    r = R(ap_id=1, branch_id=1, requested_by_id=1, reason='need signed copy', kind='signed_ap',
          staged_original_filename='s.pdf', staged_stored_filename='abc.pdf',
          staged_mime_type='application/pdf', staged_file_size=10)
    from app import db
    db.session.add(r); db.session.commit()
    assert r.status == R.STATUS_PENDING
    assert r.is_pending is True
    assert R.MIN_REASON_LEN == 10
