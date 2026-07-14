import pytest
from app import db
from app.opening_balances.approval_models import OpeningBalanceChangeRequest


@pytest.mark.unit
class TestOpeningBalanceChangeRequestModel:
    def test_roundtrip_change_data_and_defaults(self, db_session):
        data = {'cutover_date': '2026-01-01',
                'lines': [{'account_id': 1, 'debit': '100.00', 'credit': '0'}]}
        req = OpeningBalanceChangeRequest(
            branch_id=1, requested_by='alice')
        req.set_change_data(data)
        db.session.add(req)
        db.session.commit()

        fetched = db.session.get(OpeningBalanceChangeRequest, req.id)
        assert fetched.status == 'pending'
        assert fetched.get_change_data() == data
        assert fetched.to_dict()['requested_by'] == 'alice'
