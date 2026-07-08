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


# NOTE: BIR Summary List of Purchases + supplier Alphalist segregation is intentionally
# NOT covered here — that BIR section is still under development (the alphalist route
# redirects to /under-development). The payee_type=='vendor' filter should be added to
# those queries + tested when the BIR section is actually built. See backlog #92 / the
# employee-master plan Phase 4 note.
