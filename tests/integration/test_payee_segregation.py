from datetime import date
from decimal import Decimal
from app import db
from app.accounts_payable.models import AccountsPayable
from app.employees.models import Employee
from app.vendors.models import Vendor


def _post_ap(payee_type, payee_id, vendor_id, name, num, branch_id, wht=Decimal('0.00')):
    ap = AccountsPayable(
        ap_number=num, ap_date=date(2026, 6, 15), due_date=date(2026, 7, 15),
        vendor_name=name, notes='n', status='posted', branch_id=branch_id,
        payee_type=payee_type, payee_id=payee_id, vendor_id=vendor_id,
        vendor_tin='001-002-003', subtotal=Decimal('1000.00'),
        vat_amount=Decimal('0.00'), total_before_wt=Decimal('1000.00'),
        withholding_tax_amount=wht, total_amount=Decimal('1000.00'),
        amount_paid=Decimal('0.00'), balance=Decimal('1000.00'),
    )
    db.session.add(ap); db.session.commit()
    return ap


def _setup(client, admin_user, branch, login_user):
    login_user(client, 'admin', 'admin123')
    with client.session_transaction() as sess:
        sess['selected_branch_id'] = branch.id
    v = Vendor(code='V001', name='Anthropic', is_active=True); db.session.add(v)
    e = Employee(employee_no='EMP-0001', first_name='Alvin', last_name='Cruz',
                 branch_id=branch.id)
    db.session.add(e); db.session.commit()
    return v, e


def test_employee_ap_absent_from_ap_aging(client, admin_user, main_branch, login_user):
    v, e = _setup(client, admin_user, main_branch, login_user)
    _post_ap('vendor', v.id, v.id, 'Anthropic', 'AP-SEG-V', main_branch.id)
    _post_ap('employee', e.id, None, 'Alvin Cruz', 'AP-SEG-E', main_branch.id)
    html = client.get('/reports/ap-aging?as_of=2026-12-31').get_data(as_text=True)
    assert 'Anthropic' in html
    assert 'Alvin Cruz' not in html          # employee payee segregated out


def test_employee_ap_absent_from_bir_purchases(client, admin_user, main_branch, login_user):
    v, e = _setup(client, admin_user, main_branch, login_user)
    _post_ap('vendor', v.id, v.id, 'Anthropic', 'AP-SEG-V2', main_branch.id)
    _post_ap('employee', e.id, None, 'Alvin Cruz', 'AP-SEG-E2', main_branch.id)
    html = client.get('/reports/bir/purchases?year=2026&month=6').get_data(as_text=True)
    assert 'Anthropic' in html
    assert 'Alvin Cruz' not in html


def _wht_line(ap, wt, amount, line_total):
    from app.accounts_payable.models import AccountsPayableItem
    li = AccountsPayableItem(ap_id=ap.id, line_number=1, description='svc',
                             amount=Decimal(str(line_total)), line_total=Decimal(str(line_total)),
                             wt_id=wt.id, wt_amount=Decimal(str(amount)))
    db.session.add(li); db.session.commit()


def test_employee_ap_absent_from_bir_alphalist(client, admin_user, main_branch, login_user):
    # The /reports/bir/alphalist ROUTE is still under-development (redirects), so
    # assert segregation on the service function that backs it directly.
    from app.reports.bir import get_alphalist_of_payees
    from app.withholding_tax.models import WithholdingTax
    v, e = _setup(client, admin_user, main_branch, login_user)
    wt = WithholdingTax(code='WC010', name='Professional', rate=Decimal('10.00'), is_active=True)
    db.session.add(wt); db.session.commit()

    v_ap = _post_ap('vendor', v.id, v.id, 'Anthropic', 'AP-SEG-V3', main_branch.id, wht=Decimal('20.00'))
    e_ap = _post_ap('employee', e.id, None, 'Alvin Cruz', 'AP-SEG-E3', main_branch.id, wht=Decimal('50.00'))
    _wht_line(v_ap, wt, 20.00, 200.00)
    _wht_line(e_ap, wt, 50.00, 500.00)

    rows = get_alphalist_of_payees(2026, 2, branch_id=main_branch.id)
    names = {r['payee_name'] for r in rows}
    assert 'Anthropic' in names
    assert 'Alvin Cruz' not in names          # employee payee segregated out
