import json
from datetime import date
from app import db
from app.accounts_payable.models import AccountsPayable
from app.employees.models import Employee
from app.accounts.models import Account


def _seed_accounts():
    for code, name, typ, bal in [
        ('20101', 'Accounts Payable - Trade', 'Liability', 'Credit'),
        ('20301', 'Withholding Tax Payable - Expanded', 'Liability', 'Credit'),
        ('10502', 'Input VAT - Domestic Goods', 'Asset', 'Debit'),
        ('69903', 'Test Expense', 'Expense', 'Debit'),
    ]:
        db.session.add(Account(code=code, name=name, account_type=typ,
                               normal_balance=bal, is_active=True))
    db.session.commit()
    from tests.conftest import assign_control_accounts
    assign_control_accounts(db.session)
    return Account.query.filter_by(code='69903').first()


def test_create_ap_with_employee_payee(client, db_session, admin_user, main_branch):
    exp = _seed_accounts()
    e = Employee(employee_no='EMP-0001', first_name='Alvin', last_name='Cruz',
                 branch_id=main_branch.id)
    db.session.add(e); db.session.commit()

    client.post('/login', data={'username': 'admin', 'password': 'admin123'},
                follow_redirects=True)
    with client.session_transaction() as sess:
        sess['selected_branch_id'] = main_branch.id

    resp = client.post('/accounts-payable/create', data={
        'ap_number': 'AP-2026-06-9001', 'ap_date': date.today().isoformat(),
        'due_date': date.today().isoformat(),
        'payee': f'employee:{e.id}', 'payment_terms': 'Net 30',
        'notes': 'Salary for June 2026',
        'line_items': json.dumps([{
            'description': 'Salary', 'amount': 1000.0, 'vat_category': None,
            'account_id': exp.id, 'wt_id': None, 'wt_rate': None,
        }]),
        'vat_override': '0', 'vat_override_value': '0',
        'wt_override': '0', 'wt_override_value': '0',
    }, follow_redirects=False)
    assert resp.status_code == 302, resp.data[:400]
    ap = AccountsPayable.query.filter_by(ap_number='AP-2026-06-9001').first()
    assert ap is not None
    assert ap.payee_type == 'employee' and ap.payee_id == e.id
    assert ap.vendor_id is None
    assert ap.vendor_name == 'Alvin Cruz'
