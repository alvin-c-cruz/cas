"""What a given user can actually reach, and why -- the admin viewer's resolver.

BUG-NO-ADMIN-PATH-TO-VERIFY-ANOTHER-USERS-ACCESS (owner option 2, 2026-08-28).
An admin could confirm a permission grant only in the DATABASE or in the admin's
own edit form, and neither shows what the app will actually do for that user. The
alternatives were both closed: logging in as them needs their password, and
resetting it to look changes a live user's credentials for a convenience.

THE VERDICT IS DELEGATED, NEVER REIMPLEMENTED. `can_access_module` decides;
this module only explains. A second copy of the rule drifts from the first, and a
viewer that confidently explains a rule the app stopped following is worse than
no viewer -- it turns "I cannot verify this" into "I verified it wrongly". The
`reason_code` is derived separately and
`tests/unit/test_effective_access.py::TestReasonsAndVerdictsAgree` fails the
moment an explanation and a verdict disagree.

ONE FACTOR IS DELIBERATELY OUTSIDE `can_access_module`: the branch prerequisite.
A user with no ACCESSIBLE branch is redirected to the branch picker by
create_app's `before_request` on EVERY request, before any module gate is
consulted -- so their grants are irrelevant and the module table alone would read
as a permissions problem. It is resolved once for the user, not per module,
because it is a property of the user and not of any module.
"""
from dataclasses import dataclass

from app.users.module_access import MODULE_REGISTRY, can_access_module, module_enabled
from app.users.utils import get_accessible_branches

#: reason_code -> the verdict that reason can ever justify. A row whose verdict
#: disagrees with its reason is a bug in the explanation, and is tested as one.
REASON_VERDICT = {
    'no_branch': False,
    'instance_off': False,
    'full_access': True,
    'granted': True,
    'not_grantable': False,
    'not_granted': False,
}

#: Written for an administrator reading the page, not for a developer. Each one
#: has to imply what to DO about it -- which control to reach for -- or the row
#: is just a red cross with extra words.
REASON_TEXT = {
    'no_branch': 'No branch assigned — blocked before the module gate',
    'instance_off': 'Module is off company-wide — this grant has no effect',
    'full_access': 'Full access by role',
    'granted': 'Granted to this user',
    'not_grantable': ('Instance-gated only — cannot be granted per user, so '
                      'Admin and Chief Accountant only'),
    'not_granted': 'Not granted to this user',
}

#: The instance_off wording above assumes a grant is present. When there is no
#: grant either, the module being off is still the honest first answer, but
#: "this grant has no effect" would name a grant that does not exist.
REASON_TEXT_OFF_UNGRANTED = 'Module is off company-wide'


@dataclass(frozen=True)
class AccessRow:
    """One module, for one user."""
    key: str
    label: str
    section: str
    area: str
    instance_enabled: bool
    grantable: bool
    granted: bool
    effective: bool
    reason_code: str
    reason: str


def is_grantable(entry):
    """Whether this module can be granted PER USER at all.

    Mirrors `all_permission_keys()`: an `optional` module not also flagged
    `per_user` is instance-gated only, never appears in the permission grid, and
    therefore resolves False forever for anyone below full access -- silently,
    even with the instance flag ON. Surfacing that is half the point of the page.
    """
    return (not entry.get('optional')) or bool(entry.get('per_user'))


def effective_access(user):
    """Resolve *user*'s reachable modules.

    Returns ``{'rows': [AccessRow], 'notices': {...}, 'summary': {...}}``.
    Read-only: touches no session, changes no credential, writes nothing.
    """
    branches = get_accessible_branches(user)
    no_branch = not branches
    permissions = user.get_book_permissions()
    full_access = bool(user.has_full_access)

    rows = []
    for entry in MODULE_REGISTRY:
        key = entry['key']
        enabled = module_enabled(key)
        grantable = is_grantable(entry)
        granted = bool(permissions.get(key, False))

        if no_branch:
            # Resolved before the module gate, exactly as the request would be.
            effective, code = False, 'no_branch'
        else:
            # THE DELEGATION. Everything below only explains this answer.
            effective = bool(can_access_module(user, key))
            if not enabled:
                code = 'instance_off'
            elif full_access:
                code = 'full_access'
            elif granted:
                code = 'granted'
            elif not grantable:
                code = 'not_grantable'
            else:
                code = 'not_granted'

        reason = REASON_TEXT[code]
        if code == 'instance_off' and not granted:
            reason = REASON_TEXT_OFF_UNGRANTED

        rows.append(AccessRow(
            key=key, label=entry.get('label', key),
            section=entry.get('section', ''),
            area=entry.get('area') or entry.get('section') or 'Other',
            instance_enabled=enabled, grantable=grantable, granted=granted,
            effective=effective, reason_code=code, reason=reason))

    return {
        'rows': rows,
        'notices': {
            'no_branch': no_branch,
            # A grant the instance gate overrules. The permission grid renders it
            # as held, so nothing else in the app contradicts it.
            'dead_grants': [r for r in rows if r.granted and not r.instance_enabled],
            # Switched on for the company, unreachable for this user's role, and
            # not fixable by granting anything. Reported only while the module is
            # ON: with it off, the instance gate is the honest first answer and
            # this notice would send an admin to the wrong control.
            'ungrantable_but_enabled': [
                r for r in rows
                if not r.grantable and r.instance_enabled and not full_access],
        },
        'summary': {
            'reachable': sum(1 for r in rows if r.effective),
            'total': len(rows),
            'branches': [b.name for b in branches],
            'role': user.role,
            'full_access': full_access,
        },
    }


def grouped_rows(rows):
    """Rows as ``[(area, [row, ...])]`` in registry order, for the template.

    Grouped the way the sidebar is, so an admin comparing the page against what
    the user describes seeing is reading the same shape.
    """
    order, groups = [], {}
    for row in rows:
        if row.area not in groups:
            groups[row.area] = []
            order.append(row.area)
        groups[row.area].append(row)
    return [(area, groups[area]) for area in order]
