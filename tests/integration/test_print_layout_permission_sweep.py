"""Who may save a pre-printed layout, across ALL ELEVEN documents at once.

Owner decision 2026-08-26: layout editing widens from has_full_access (admin or
Chief Accountant) to each module's EDIT-level role set, so staff and accountants
can reposition fields on the overlay.

ONE table, eleven routes. The gate was copy-pasted identically into eleven
modules, which is exactly how ten of them get updated and one is missed -- so
this is parametrized over the route list rather than written eleven times, and a
module added to the family without its permission decision fails the count check
below.

These routes take a JSON body and the session branch; none of them looks up a
document. That is what makes an eleven-way sweep cheap enough to be worth having.

PAYROLL IS DELIBERATELY DIFFERENT and is not an oversight -- see
TestPayrollKeepsItsStricterDoor.
"""
import pytest

from app import db

pytestmark = [pytest.mark.integration]

#: (url, module_keys_that_must_be_enabled)
LAYOUT_ROUTES = [
    ('/purchase-requests/print-layout', ('products', 'purchase_orders', 'purchase_requests')),
    ('/purchase-orders/print-layout', ('products', 'purchase_orders')),
    ('/receiving-reports/print-layout', ('products', 'purchase_orders', 'receiving_reports')),
    ('/accounts-payable/print-layout', ()),
    ('/cash-disbursements/print-layout', ()),
    ('/cash-receipts/print-layout', ()),
    ('/delivery-receipts/print-layout', ('delivery_receipts',)),
    ('/sales-invoices/print-layout', ()),
    ('/sales-orders/print-layout', ('sales_orders',)),
    ('/journal-entries/print-layout', ()),
]

#: Payroll's layout route is in the family but has its own stricter door.
PAYROLL_ROUTE = '/payroll/payslip-print-layout'

ALL_ELEVEN = [r for r, _ in LAYOUT_ROUTES] + [PAYROLL_ROUTE]


@pytest.fixture(autouse=True)
def modules_on(db_session):
    from app.settings import AppSettings
    from app.utils.cache_helpers import clear_module_config_cache
    for k in ('products', 'purchase_orders', 'purchase_requests', 'receiving_reports',
              'delivery_receipts', 'sales_orders', 'payroll', 'employees'):
        AppSettings.set_setting('module_enabled:%s' % k, '1')
    db_session.commit(); clear_module_config_cache()
    yield
    clear_module_config_cache()


def _user(db_session, role, branch, books=True):
    from app.users.models import User
    u = User(username='sweep_%s' % role, email='%s@sweep.test' % role,
             full_name=role.title(), role=role, is_active=True)
    u.set_password('x')
    # Non-full-access roles are BRANCH-SCOPED: without an assignment the
    # before_request branch gate 302s to the picker and every status assertion
    # below would be measuring that redirect instead of the permission.
    u.branches.append(branch)
    if books:
        # Staff and viewers are default-deny per module; without the books the
        # route 404s at the module gate and every assertion below would be
        # measuring the gate rather than the permission under test.
        u.set_book_permissions({k: True for k in (
            'purchase_requests', 'purchase_orders', 'receiving_reports',
            'accounts_payable', 'payments', 'collections', 'accounts_receivable',
            'journal_entries', 'delivery_receipts', 'sales_orders', 'payroll',
            'customers', 'vendors', 'products', 'units_of_measure')})
    db_session.add(u); db.session.commit()
    return u


def _login(client, user, branch):
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user.id); sess['_fresh'] = True
        sess['selected_branch_id'] = branch.id


def _post(client, url):
    return client.post(url, json={}, headers={'Content-Type': 'application/json'})


class TestStaffAndAccountantMayNowSave:
    """THE change. Neither role could save a layout before 2026-08-26."""

    @pytest.mark.parametrize('url,_mods', LAYOUT_ROUTES)
    def test_staff_is_not_forbidden(self, client, db_session, main_branch, url, _mods):
        _login(client, _user(db_session, 'staff', main_branch), main_branch)
        assert _post(client, url).status_code == 200, url

    @pytest.mark.parametrize('url,_mods', LAYOUT_ROUTES)
    def test_accountant_is_not_forbidden(self, client, db_session, main_branch, url, _mods):
        _login(client, _user(db_session, 'accountant', main_branch), main_branch)
        assert _post(client, url).status_code == 200, url


class TestViewerIsStillRefused:
    """THE control. A permission test with no negative case proves nothing --
    'not 403' would pass just as well against a route that forbids nobody."""

    @pytest.mark.parametrize('url,_mods', LAYOUT_ROUTES)
    def test_viewer_gets_403(self, client, db_session, main_branch, url, _mods):
        _login(client, _user(db_session, 'viewer', main_branch), main_branch)
        assert _post(client, url).status_code == 403, url

    @pytest.mark.parametrize('url,_mods', LAYOUT_ROUTES)
    def test_admin_still_allowed(self, client, db_session, main_branch, url, _mods):
        """Control on the direction: the widening only ever ADDS."""
        _login(client, _user(db_session, 'admin', main_branch), main_branch)
        assert _post(client, url).status_code == 200, url


class TestPayrollKeepsItsStricterDoor:
    """Payroll is in the family of eleven but is NOT swept to staff, on purpose.

    Its layout route carries @accountant_or_admin_required on TOP of the body
    check, and that decorator is shared by five payroll routes (posting and
    cancelling runs) -- loosening it would loosen those too. More decisive: the
    payslip VIEW route is itself @accountant_or_admin_required, so a staff user
    cannot open a payslip at all. Granting staff the ability to change what
    prints on every payslip in the branch, while they may never see one, would
    be a gap rather than a consistency.

    What the sweep DOES fix here is a real contradiction: the decorator said
    accountant-or-admin while the body said full-access-only, so an accountant
    passed the door and was then 403'd by the body. That is now consistent.
    """

    def test_accountant_may_save_a_payslip_layout(self, client, db_session, main_branch):
        """The contradiction this sweep resolves."""
        _login(client, _user(db_session, 'accountant', main_branch), main_branch)
        assert _post(client, PAYROLL_ROUTE).status_code != 403

    def test_staff_still_cannot(self, client, db_session, main_branch):
        """Not 403 -- the decorator FLASHES AND REDIRECTS rather than aborting,
        so the assertion is 'did not succeed', not a specific status."""
        _login(client, _user(db_session, 'staff', main_branch), main_branch)
        resp = _post(client, PAYROLL_ROUTE)
        assert resp.status_code != 200, 'staff must not save a payslip layout'

    def test_viewer_still_cannot(self, client, db_session, main_branch):
        _login(client, _user(db_session, 'viewer', main_branch), main_branch)
        assert _post(client, PAYROLL_ROUTE).status_code != 200


class TestTheFamilyIsComplete:
    """Guard on the sweep itself.

    The bug this whole exercise is about is a rule copy-pasted into N places and
    updated in N-1 of them. A test that lists ten routes cannot notice an
    eleventh, so the list is checked against the app's REAL url map.
    """

    def test_every_layout_route_in_the_app_is_covered(self, app):
        registered = sorted(
            str(r.rule) for r in app.url_map.iter_rules()
            if 'print-layout' in str(r.rule))
        missing = set(registered) - set(ALL_ELEVEN)
        assert not missing, (
            'These layout-save routes exist in the app but are not in this '
            "sweep's table, so nothing checks who may call them: %s"
            % sorted(missing))

    def test_the_url_map_still_has_eleven(self, app):
        """Cross-check the other way -- a route REMOVED from the app would leave
        a stale entry here silently passing against a 404."""
        registered = [str(r.rule) for r in app.url_map.iter_rules()
                      if 'print-layout' in str(r.rule)]
        assert len(set(registered)) == 11, sorted(set(registered))


class TestNoRouteStillUsesTheOldRule:
    """Structural backstop. The route tests above are the real check; this names
    the mistake directly so a half-done sweep is obvious in the failure text."""

    def test_no_save_layout_body_checks_has_full_access(self):
        import pathlib
        import re
        root = pathlib.Path(__file__).resolve().parents[2] / 'app'
        offenders = []
        for path in root.rglob('views.py'):
            src = path.read_text(encoding='utf-8')
            for m in re.finditer(r'def (save_\w*print_layout|save_\w+_print_layout)\('
                                 r'[^\n]*\)[^\n]*:\n(.*?)(?=\n@|\ndef |\Z)',
                                 src, re.DOTALL):
                # The GATE EXPRESSION, not any mention of the name. Matching
                # free text flagged payroll for a docstring that EXPLAINS why
                # its outer decorator is stricter -- a false positive that would
                # have pushed the next reader to delete a correct comment to get
                # a green test.
                if re.search(r'if not current_user\.has_full_access\s*:',
                             m.group(2)):
                    offenders.append('%s::%s' % (path.name, m.group(1)))
        assert not offenders, (
            'These layout-save routes still gate on has_full_access instead of '
            'can_edit_print_layout: %s' % offenders)


class TestTheCheckLayoutIsOutOfScope:
    """The CDV CHECK layout is a twelfth designer and stays narrow.

    It shares the `can_edit_layout` flag NAME with the eleven document overlays,
    which is how a name-matching sweep picks it up by accident -- this one did,
    on its first run, and would have shown staff a designer whose save route
    still 403s (the "delete_approved_email shape" this codebase warns about,
    inverted).

    It is genuinely different: keyed on the bank ACCOUNT rather than the branch,
    and it positions figures on a negotiable instrument. The 2026-08-26 owner
    decision named the eleven pre-printed DOCUMENTS; cheque stationery was not
    among them, and widening it is a separate decision nobody has taken.
    """

    def test_staff_cannot_save_a_check_layout(self, client, db_session, main_branch):
        _login(client, _user(db_session, 'staff', main_branch), main_branch)
        assert _post(client, '/cash-disbursements/check-layout').status_code == 403

    def test_accountant_cannot_save_a_check_layout(self, client, db_session, main_branch):
        _login(client, _user(db_session, 'accountant', main_branch), main_branch)
        assert _post(client, '/cash-disbursements/check-layout').status_code == 403

    def test_admin_still_can(self, client, db_session, main_branch):
        """Control -- narrow, not broken."""
        _login(client, _user(db_session, 'admin', main_branch), main_branch)
        assert _post(client, '/cash-disbursements/check-layout').status_code == 200


class TestTheRenderFlagWasSweptToo:
    """The route is only half of each pair.

    Every one of the eleven print pages also computes a render-time
    `can_edit_layout`, which decides whether the designer UI is drawn at all.
    Sweeping the routes but not the flags would leave staff able to SAVE a
    layout they are never shown the controls for -- the same route/template
    mismatch as the delete_approved_email case, in the opposite direction.

    The route tests above cannot see this: they POST directly and never render a
    page.
    """

    def test_no_render_flag_still_uses_the_old_rule(self):
        """Structural, and honest about it: this greps, it does not render.

        The behavioural anchor is test_staff_sees_the_designer_on_a_po below --
        one page actually loaded as staff. Rendering all eleven would need
        eleven documents' worth of fixtures for a one-line flag each.
        """
        import pathlib
        import re
        root = pathlib.Path(__file__).resolve().parents[2] / 'app'
        offenders = []
        for path in sorted(root.rglob('views.py')):
            for i, line in enumerate(path.read_text(encoding='utf-8').splitlines(), 1):
                if re.search(r'can_edit_layout\s*=\s*\(?current_user\.has_full_access', line):
                    offenders.append('%s:%d' % (path.relative_to(root).as_posix(), i))
        # The CDV CHECK layout keeps has_full_access on purpose -- cheque
        # stationery, keyed on the bank account, outside the eleven documents.
        # Named explicitly so it reads as a decision rather than a miss.
        expected = ['cash_disbursements/views.py']
        unexpected = [o for o in offenders
                      if not any(o.startswith(e) for e in expected)]
        assert not unexpected, (
            'These render-time layout flags still use has_full_access: %s'
            % unexpected)
        assert offenders, (
            'the CDV check-layout flag should still be here -- if it is gone, '
            'either it was swept by mistake or this guard has stopped matching')

    def test_staff_sees_the_designer_on_a_po_print_page(self, client, db_session,
                                                        main_branch):
        """THE behavioural anchor. Staff loads a real pre-printed print page and
        the designer is actually drawn -- `data-can-edit="true"` is what the
        template keys the whole editing UI on."""
        from datetime import date
        from decimal import Decimal
        from app.settings import AppSettings
        from app.purchase_orders.models import PurchaseOrder, PurchaseOrderItem

        AppSettings.set_setting('po_print_form', 'preprinted')
        AppSettings.set_setting('po_print_access', 'draft_and_approved')
        po = PurchaseOrder(po_number='FLAG-PO-1', order_date=date(2026, 8, 26),
                           status='draft', branch_id=main_branch.id, notes='',
                           vat_treatment='inclusive', vendor_name='ACME')
        po.line_items.append(PurchaseOrderItem(
            line_number=1, description='widget', quantity=Decimal('1'),
            unit_price=Decimal('10'), amount=Decimal('10')))
        db.session.add(po); db.session.commit()

        _login(client, _user(db_session, 'staff', main_branch), main_branch)
        resp = client.get('/purchase-orders/%d/print' % po.id)
        assert resp.status_code == 200
        assert b'data-can-edit="true"' in resp.data

    def test_a_viewer_does_not_see_the_designer(self, client, db_session, main_branch):
        """CONTROL. An absence assertion needs its positive twin above, or a
        page that renders nothing at all would pass it."""
        from datetime import date
        from decimal import Decimal
        from app.settings import AppSettings
        from app.purchase_orders.models import PurchaseOrder, PurchaseOrderItem

        AppSettings.set_setting('po_print_form', 'preprinted')
        AppSettings.set_setting('po_print_access', 'draft_and_approved')
        po = PurchaseOrder(po_number='FLAG-PO-2', order_date=date(2026, 8, 26),
                           status='draft', branch_id=main_branch.id, notes='',
                           vat_treatment='inclusive', vendor_name='ACME')
        po.line_items.append(PurchaseOrderItem(
            line_number=1, description='widget', quantity=Decimal('1'),
            unit_price=Decimal('10'), amount=Decimal('10')))
        db.session.add(po); db.session.commit()

        _login(client, _user(db_session, 'viewer', main_branch), main_branch)
        resp = client.get('/purchase-orders/%d/print' % po.id)
        assert resp.status_code == 200
        assert b'data-can-edit="false"' in resp.data


class TestTheSalesInvoiceBranchMatchSurvived:
    """sales_invoices computes can_edit_layout as a COMPOUND expression.

        can_edit_layout = (current_user.can_edit_print_layout
                           and invoice.branch_id == session.get('selected_branch_id'))

    Only the FIRST conjunct moved in the 2026-08-26 sweep. The second is a
    separate, load-bearing rule: print_invoice follows branch ACCESS (a
    full-access user may open an off-branch invoice's print page), while
    save_print_layout is branchless and writes under session['selected_branch_id'].
    Without the branch match, opening an off-branch invoice would offer a designer
    whose save lands on the WRONG branch's layout key.

    Added because a mutation dropping that conjunct left the whole suite green --
    it was preserved correctly and pinned by nothing.
    """

    def _invoice(self, db_session, branch_id, number):
        from datetime import date
        from decimal import Decimal
        from app.customers.models import Customer
        from app.sales_invoices.models import SalesInvoice
        c = Customer(code='LC%s' % number, name='Cust %s' % number, is_active=True)
        db_session.add(c); db.session.commit()
        inv = SalesInvoice(
            branch_id=branch_id, invoice_number=number,
            invoice_date=date(2026, 8, 26), due_date=date(2026, 9, 26),
            customer_id=c.id, customer_name=c.name, notes='', status='draft',
            amount_paid=Decimal('0.00'), balance=Decimal('100.00'),
            total_amount=Decimal('100.00'), subtotal=Decimal('100.00'),
            vat_amount=Decimal('0.00'), withholding_tax_amount=Decimal('0.00'))
        db_session.add(inv); db.session.commit()
        return inv

    def _print(self, client, db_session, inv, selected_branch):
        from app.settings import AppSettings
        AppSettings.set_setting('sv_print_form', 'preprinted')
        AppSettings.set_setting('sv_print_access', 'draft_and_posted')
        db.session.commit()
        _login(client, _user(db_session, 'admin', selected_branch), selected_branch)
        return client.get('/sales-invoices/%d/print' % inv.id)

    def test_an_on_branch_invoice_is_editable(self, client, db_session, main_branch):
        """POSITIVE CONTROL. Without it the off-branch assertion below would pass
        just as well against a page that never offers the designer at all."""
        inv = self._invoice(db_session, main_branch.id, 'LAY-ON')
        resp = self._print(client, db_session, inv, main_branch)
        assert resp.status_code == 200
        assert b'data-can-edit="true"' in resp.data

    def test_an_off_branch_invoice_is_not_editable(self, client, db_session,
                                                   main_branch, branch_manila):
        """The conjunct M4 dropped. Admin passes can_edit_print_layout, opens an
        invoice belonging to another branch, and must NOT get the designer."""
        inv = self._invoice(db_session, branch_manila.id, 'LAY-OFF')
        resp = self._print(client, db_session, inv, main_branch)
        assert resp.status_code == 200, 'the print page must still RENDER off-branch'
        assert b'data-can-edit="false"' in resp.data
