"""Check-serial integrity: a non-null check_number is unique per cash/bank account
among NON-voided CDVs (a voided serial is freed for reuse — user decision 2026-07-07).

The DB partial-unique index is the real guard (it wins the TOCTOU race). These tests
exercise it via conftest's create_all() (which builds the model's __table_args__ index).
"""
import pytest
from datetime import date

from sqlalchemy.exc import IntegrityError
from app.vendors.models import Vendor
from app.accounts.models import Account
from app.cash_disbursements.models import CashDisbursementVoucher

pytestmark = [pytest.mark.cash_disbursements, pytest.mark.integration]


def _acct(db_session, code):
    a = Account(code=code, name=f'Cash {code}', account_type='Asset',
                normal_balance='debit', is_active=True)
    db_session.add(a); db_session.commit()
    return a


def _vendor(db_session):
    v = Vendor(code='SERV1', name='Serial Vendor', is_active=True)
    db_session.add(v); db_session.commit()
    return v


def _cdv(db_session, acct, vendor, branch, number, check_number, method='check', status='posted'):
    c = CashDisbursementVoucher(
        branch_id=branch.id, cdv_number=number, cdv_date=date(2026, 7, 7),
        vendor_id=vendor.id, vendor_name=vendor.name, payment_method=method,
        check_number=check_number, cash_account_id=acct.id, status=status)
    db_session.add(c)
    return c


class TestSerialUniqueness:
    def test_dup_serial_same_account_rejected(self, db_session, main_branch):
        acct = _acct(db_session, '1010'); v = _vendor(db_session)
        _cdv(db_session, acct, v, main_branch, 'CD-1', 'CHK-1'); db_session.commit()
        _cdv(db_session, acct, v, main_branch, 'CD-2', 'CHK-1')
        with pytest.raises(IntegrityError):
            db_session.commit()
        db_session.rollback()

    def test_same_serial_different_account_ok(self, db_session, main_branch):
        a1 = _acct(db_session, '1010'); a2 = _acct(db_session, '1020'); v = _vendor(db_session)
        _cdv(db_session, a1, v, main_branch, 'CD-1', 'CHK-1'); db_session.commit()
        _cdv(db_session, a2, v, main_branch, 'CD-2', 'CHK-1'); db_session.commit()   # no raise

    def test_multiple_null_serials_allowed(self, db_session, main_branch):
        acct = _acct(db_session, '1010'); v = _vendor(db_session)
        _cdv(db_session, acct, v, main_branch, 'CD-1', None, method='cash')
        _cdv(db_session, acct, v, main_branch, 'CD-2', None, method='cash')
        db_session.commit()   # cash CDVs (null serial) don't collide

    def test_voided_serial_freed_for_reuse(self, db_session, main_branch):
        acct = _acct(db_session, '1010'); v = _vendor(db_session)
        c1 = _cdv(db_session, acct, v, main_branch, 'CD-1', 'CHK-1'); db_session.commit()
        c1.status = 'voided'; db_session.commit()
        _cdv(db_session, acct, v, main_branch, 'CD-2', 'CHK-1'); db_session.commit()   # freed -> ok


class TestAppGuard:
    def _new(self, main_branch, vendor, acct, number, check_number, method='check'):
        return CashDisbursementVoucher(
            branch_id=main_branch.id, cdv_number=number, cdv_date=date(2026, 7, 7),
            vendor_id=vendor.id, vendor_name=vendor.name, payment_method=method,
            check_number=check_number, cash_account_id=acct.id, status='draft')

    def test_duplicate_serial_detected_case_space(self, db_session, main_branch):
        from app.cash_disbursements.views import _check_serial_error
        acct = _acct(db_session, '1010'); v = _vendor(db_session)
        _cdv(db_session, acct, v, main_branch, 'CD-1', 'CHK-1'); db_session.commit()
        msg = _check_serial_error(self._new(main_branch, v, acct, 'CD-2', ' CHK-1 '))  # trimmed
        assert msg and 'CD-1' in msg

    def test_no_conflict_different_account(self, db_session, main_branch):
        from app.cash_disbursements.views import _check_serial_error
        a1 = _acct(db_session, '1010'); a2 = _acct(db_session, '1020'); v = _vendor(db_session)
        _cdv(db_session, a1, v, main_branch, 'CD-1', 'CHK-1'); db_session.commit()
        assert _check_serial_error(self._new(main_branch, v, a2, 'CD-2', 'CHK-1')) is None

    def test_voided_conflict_ignored(self, db_session, main_branch):
        from app.cash_disbursements.views import _check_serial_error
        acct = _acct(db_session, '1010'); v = _vendor(db_session)
        c1 = _cdv(db_session, acct, v, main_branch, 'CD-1', 'CHK-1'); c1.status = 'voided'; db_session.commit()
        assert _check_serial_error(self._new(main_branch, v, acct, 'CD-2', 'CHK-1')) is None

    def test_cash_method_and_blank_ignored(self, db_session, main_branch):
        from app.cash_disbursements.views import _check_serial_error
        acct = _acct(db_session, '1010'); v = _vendor(db_session)
        assert _check_serial_error(self._new(main_branch, v, acct, 'CD-2', None, method='cash')) is None
        assert _check_serial_error(self._new(main_branch, v, acct, 'CD-3', '   ')) is None
