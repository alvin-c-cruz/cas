"""BRANCH_LIST_ENDPOINTS must stay true, or a wrong-branch redirect goes nowhere useful.

The registry maps a blueprint to the list page a wrong-branch redirect lands on.
Nothing in normal use reads it until someone hits the wrong branch, so a typo or a
renamed route would sit undetected until a user ran into it -- and then silently
degrade to the dashboard, which is the one outcome the owner asked us to move away
from.

These tests make the table self-policing: every entry must resolve to a real
endpoint, and every blueprint that actually guards a branch must either have an
entry or pass one explicitly.
"""
import re
import glob
import io

import pytest

from app.utils.branch_scope import BRANCH_LIST_ENDPOINTS, FALLBACK_ENDPOINT

pytestmark = [pytest.mark.unit]


def _endpoints(app):
    return {rule.endpoint for rule in app.url_map.iter_rules()}


class TestEveryEntryResolves:

    def test_each_registry_endpoint_exists(self, app):
        missing = sorted(e for e in BRANCH_LIST_ENDPOINTS.values()
                         if e not in _endpoints(app))
        assert not missing, 'registry names endpoints that do not exist: %s' % missing

    def test_the_fallback_exists(self, app):
        assert FALLBACK_ENDPOINT in _endpoints(app)

    def test_each_key_is_a_real_blueprint(self, app):
        unknown = sorted(set(BRANCH_LIST_ENDPOINTS) - set(app.blueprints))
        assert not unknown, 'registry keys that are not blueprints: %s' % unknown

    def test_each_endpoint_belongs_to_its_own_blueprint(self):
        """A copy-paste that points sales_memos at the sales_orders list would
        still resolve, and would quietly send people to the wrong module."""
        wrong = {bp: ep for bp, ep in BRANCH_LIST_ENDPOINTS.items()
                 if not ep.startswith(bp + '.')}
        assert not wrong, 'entries pointing outside their own blueprint: %s' % wrong

    def test_each_target_takes_no_url_parameters(self, app):
        """The redirect calls url_for with no arguments, so a list route that
        needs an id would raise BuildError at the worst possible moment."""
        rules = {}
        for rule in app.url_map.iter_rules():
            rules.setdefault(rule.endpoint, []).append(rule)
        needy = []
        for endpoint in BRANCH_LIST_ENDPOINTS.values():
            if all(rule.arguments for rule in rules.get(endpoint, [])):
                needy.append(endpoint)
        assert not needy, 'list endpoints requiring url parameters: %s' % needy


class TestEveryGuardedBlueprintIsCovered:
    """The rot check. A module that starts guarding a branch, or one that is
    renamed, must not fall back to the dashboard unnoticed."""

    #: Blueprints that call require_same_branch with an EXPLICIT endpoint because
    #: they serve more than one list, so they need no registry entry.
    PASSES_ITS_OWN = {'purchase_memos', 'sales_memos'}

    def _modules_using_the_guard(self):
        found = set()
        for path in glob.glob('app/*/views.py'):
            src = io.open(path, encoding='utf-8').read()
            if 'require_same_branch(' in src:
                found.add(path.replace('\\', '/').split('/')[1])
        return found

    def test_every_module_that_guards_has_a_destination(self):
        using = self._modules_using_the_guard()
        assert using, 'no module calls require_same_branch -- did it get renamed?'
        uncovered = sorted(using - set(BRANCH_LIST_ENDPOINTS) - self.PASSES_ITS_OWN)
        assert not uncovered, (
            'these modules guard a branch but have no list destination, so a '
            'wrong-branch redirect silently falls back to the dashboard: %s'
            % uncovered)

    def test_no_bare_branch_404_remains_in_a_document_route(self):
        """The whole point of the change. One known exception is kept and named."""
        pattern = re.compile(
            r"if (\w+)\.branch_id != session\.get\('selected_branch_id'\):\s*\n\s*abort\(404\)")
        offenders = []
        for path in glob.glob('app/*/views.py'):
            src = io.open(path, encoding='utf-8').read()
            if pattern.search(src):
                offenders.append(path)
        assert not offenders, (
            'these still 404 on a branch mismatch instead of explaining it: %s'
            % offenders)
