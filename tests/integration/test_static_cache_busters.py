"""Every link to a shared stylesheet must carry the SAME ?v= cache-buster.

CAS busts static caches with a manual `?v=N` query string, not a content hash, so
a stylesheet edit only reaches users through links that were bumped. Before this
test, `transactions.css` was linked 11 times at three different versions -- `?v=2`,
`?v=1`, and **no buster at all** on the sales_orders / sales_invoices / quotations
FORM templates, which are exactly where a fix to that file has to land. A link
with no `?v=` caches indefinitely.

That is a silent failure: the CSS is correct, the tests pass, and the user still
sees the old rendering. This pins the invariant instead of relying on remembering
to grep.
"""
import os
import re

import pytest

pytestmark = [pytest.mark.integration]

APP_ROOT = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))), 'app')

#: Stylesheets shared by more than one blueprint, where a version skew silently
#: hides an edit from some pages. Add to this list when a new shared sheet appears.
SHARED_SHEETS = ('transactions.css',)


def _links(sheet):
    """(template path, version-or-None) for every <link> to `sheet`."""
    pat = re.compile(
        r"url_for\(\s*'static',\s*filename='" + re.escape(sheet) + r"'\s*\)\s*\}\}(\?v=(\d+))?")
    found = []
    for dirpath, _dirs, files in os.walk(APP_ROOT):
        for fn in files:
            if not fn.endswith('.html'):
                continue
            path = os.path.join(dirpath, fn)
            with open(path, encoding='utf-8') as fh:
                text = fh.read()
            for m in pat.finditer(text):
                found.append((os.path.relpath(path, APP_ROOT).replace('\\', '/'),
                              m.group(2)))
    return found


@pytest.mark.parametrize('sheet', SHARED_SHEETS)
def test_every_link_has_a_cache_buster(sheet):
    missing = [p for p, v in _links(sheet) if v is None]
    assert not missing, (
        '%s is linked without a ?v= cache-buster in: %s -- those pages will serve '
        'a stale copy indefinitely after the file is edited' % (sheet, missing))


@pytest.mark.parametrize('sheet', SHARED_SHEETS)
def test_all_links_agree_on_the_version(sheet):
    links = _links(sheet)
    assert links, 'expected %s to be linked somewhere' % sheet
    versions = {v for _p, v in links}
    assert len(versions) == 1, (
        '%s is linked at mixed versions %s -- pages on the older version keep '
        'serving the old file. Bump every link together. Sites: %s'
        % (sheet, sorted(versions), links))
