"""The refusal names the action the user actually attempted.

BUG-PR-APPROVE-GATE-MESSAGE-NAMES-THE-WRONG-ACTION (Low, owner-reported
2026-08-20, confirmed live on the PhilGen local copy as staff user `angilyn`).

`_approve_gate()` flashed one fixed string -- "Only an approver
(accountant/admin) can APPROVE Purchase Requisitions." -- for EIGHT different
actions. A staff user who pressed Convert, Reject, Cancel or Amend was told they
could not approve, which is not what they tried to do.

The guard itself was always correct and is unchanged; only the text was wrong.
The tracker entry counted five callers; there are eight -- the three amendment
review routes were added after it was written, and inherited the same string.
"""
import pytest

from datetime import date
from decimal import Decimal

from app import db
from app.purchase_requests.models import PurchaseRequest, PurchaseRequestItem

pytestmark = [pytest.mark.integration, pytest.mark.purchase_requests]


@pytest.fixture(autouse=True)
def pr_enabled(db_session):
    from app.settings import AppSettings
    from app.utils.cache_helpers import clear_module_config_cache
    for k in ('products', 'purchase_orders', 'purchase_requests'):
        AppSettings.set_setting('module_enabled:%s' % k, '1')
    db_session.commit(); clear_module_config_cache()
    yield
    clear_module_config_cache()


@pytest.fixture
def staff(db_session, main_branch):
    """A staff user with the module and the branch, so the request reaches the
    view's OWN role guard rather than being bounced by an outer gate
    (memory feedback-outer-gate-masks-inner-guard)."""
    from app.users.models import User
    u = User(username='gate_staff', email='gs@t.com', full_name='Gate Staff',
             role='staff', is_active=True)
    u.set_password('x')
    u.set_book_permissions({'purchase_requests': True, 'purchase_orders': True,
                            'products': True})
    u.branches.append(main_branch)
    db_session.add(u); db.session.commit()
    return u


@pytest.fixture
def pr(db_session, main_branch):
    p = PurchaseRequest(pr_number='GATE-1', request_date=date(2026, 8, 26),
                        branch_id=main_branch.id, status='approved')
    p.line_items.append(PurchaseRequestItem(
        line_number=1, description='Cement', quantity=Decimal('5')))
    db_session.add(p); db.session.commit()
    return p


def _login(client, user, branch):
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user.id); sess['_fresh'] = True
        sess['selected_branch_id'] = branch.id


def _text(client, method, url, **kw):
    resp = getattr(client, method)(url, follow_redirects=True, **kw)
    assert resp.status_code == 200
    return resp.get_data(as_text=True)


class TestEachActionNamesItself:
    """One test per action. The whole defect is that these were identical."""

    def test_convert_says_convert(self, client, staff, main_branch, pr):
        _login(client, staff, main_branch)
        body = _text(client, 'post', '/purchase-requests/%d/convert' % pr.id)
        assert 'convert' in body.lower()
        assert 'can approve Purchase Requisitions' not in body

    def test_reject_says_reject(self, client, staff, main_branch, pr):
        pr.status = 'submitted'; db.session.commit()
        _login(client, staff, main_branch)
        body = _text(client, 'post', '/purchase-requests/%d/reject' % pr.id,
                     data={'reject_reason': 'not needed after all'})
        assert 'reject' in body.lower()
        assert 'can approve Purchase Requisitions' not in body

    def test_cancel_says_cancel(self, client, staff, main_branch, pr):
        _login(client, staff, main_branch)
        body = _text(client, 'post', '/purchase-requests/%d/cancel' % pr.id,
                     data={'cancel_reason': 'project shelved indefinitely'})
        assert 'cancel' in body.lower()
        assert 'can approve Purchase Requisitions' not in body

    def test_amend_says_amend(self, client, staff, main_branch, pr):
        _login(client, staff, main_branch)
        body = _text(client, 'get', '/purchase-requests/%d/amend' % pr.id)
        assert 'amend' in body.lower()
        assert 'can approve Purchase Requisitions' not in body

    def test_approve_still_says_approve(self, client, staff, main_branch, pr):
        """CONTROL. The one caller whose original wording was already correct
        must keep it -- a fix that changes every message is not a fix."""
        pr.status = 'submitted'; db.session.commit()
        _login(client, staff, main_branch)
        body = _text(client, 'post', '/purchase-requests/%d/approve' % pr.id)
        assert 'approve' in body.lower()


class TestTheGuardStillGuards:
    """The text was the bug; the refusal was never in question. These pin that
    the fix did not soften anything -- a message-only change that accidentally
    let staff through would be far worse than the wording."""

    def test_staff_still_cannot_convert(self, client, staff, main_branch, pr):
        _login(client, staff, main_branch)
        client.post('/purchase-requests/%d/convert' % pr.id, follow_redirects=True)
        assert db.session.get(PurchaseRequest, pr.id).status == 'approved'

    def test_staff_still_cannot_cancel(self, client, staff, main_branch, pr):
        _login(client, staff, main_branch)
        client.post('/purchase-requests/%d/cancel' % pr.id,
                    data={'cancel_reason': 'project shelved indefinitely'},
                    follow_redirects=True)
        assert db.session.get(PurchaseRequest, pr.id).status == 'approved'

    def test_an_accountant_is_not_refused(self, client, accountant_user,
                                          main_branch, pr):
        """CONTROL on the gate's population: an approver passes it, so the
        refusals above are about ROLE and not about a broken route."""
        # The accountant_user fixture may already carry this branch -- appending
        # blindly trips the user_branches unique constraint.
        if main_branch not in accountant_user.branches:
            accountant_user.branches.append(main_branch)
            db.session.commit()
        _login(client, accountant_user, main_branch)
        body = _text(client, 'post', '/purchase-requests/%d/cancel' % pr.id,
                     data={'cancel_reason': 'project shelved indefinitely'})
        assert 'do not have permission' not in body.lower()
        assert db.session.get(PurchaseRequest, pr.id).status == 'cancelled'


class TestEveryCallerPassesAnAction:
    """Structural. Eight callers share this gate and the tracker entry knew of
    five -- the three amendment-review routes were added later and silently
    inherited the wrong string. A fix that only updates the callers someone
    remembers repeats exactly that, so the requirement is enforced rather than
    remembered.
    """

    def test_no_caller_uses_the_bare_default(self):
        import pathlib
        import re
        src = (pathlib.Path(__file__).resolve().parents[2]
               / 'app' / 'purchase_requests' / 'views.py').read_text(encoding='utf-8')
        bare = re.findall(r'_approve_gate\(\s*\)', src)
        # The definition line itself is `def _approve_gate(action=...)`, which
        # this pattern does not match; every remaining hit is a CALL.
        assert not bare, (
            '%d caller(s) of _approve_gate() pass no action and would flash the '
            'generic wording again' % len(bare))
