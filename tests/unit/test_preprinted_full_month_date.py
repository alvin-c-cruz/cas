"""Every pre-printed layout offers a MONTH-FIRST full date: "September 01, 2026".

Owner request 2026-09-01, raised against /accounts-payable/1/print: "INCLUDE FULL
COMPLETE MONTH NAME IN THE DROP DOWN".

Measured before implementing, and the request needs restating: a full month name was
ALREADY available everywhere as `long` = "%d %B %Y" -> "01 September 2026". What no
module except delivery_receipts offered is the MONTH-FIRST form, "%B %d, %Y" ->
"September 01, 2026", which is how Philippine business documents normally read and how
the client's own legacy system printed (delivery_receipts added it as `full` precisely
to match legacy's hardcoded long_date()).

So this is not a new format so much as the delivery_receipts precedent applied to the
other nine declarations. `full` is reused verbatim -- key AND strftime pattern -- rather
than inventing a second spelling of the same thing.

The declarations are split two ways (memory project-preprinted-forms): purchase_orders,
purchase_requests and receiving_reports read DATE_FORMATS from app/common/preprinted_base;
the other nine files each carry their own copy. This test enumerates BOTH families from
the filesystem rather than listing modules by hand, so a tenth clone added later fails
here instead of silently shipping without the option.
"""
import importlib
import pathlib

import pytest

pytestmark = [pytest.mark.unit]

FULL_KEY = 'full'
FULL_FMT = '%B %d, %Y'

APP = pathlib.Path(__file__).resolve().parents[2] / 'app'


def _layout_modules():
    """Every module that DECLARES its own DATE_FORMATS, discovered on disk.

    Hand-listing them is what lets a clone slip through: this suite must fail when
    someone adds a tenth copy, not when someone remembers to update a list.
    """
    out = []
    for p in sorted(APP.glob('*/preprinted_layout.py')) + sorted(APP.glob('*/check_layout.py')):
        if 'DATE_FORMATS = {' in p.read_text(encoding='utf-8'):
            out.append('app.%s.%s' % (p.parent.name, p.stem))
    base = APP / 'common' / 'preprinted_base.py'
    if 'DATE_FORMATS = {' in base.read_text(encoding='utf-8'):
        out.append('app.common.preprinted_base')
    return out


def test_the_discovery_finds_the_expected_shape():
    """CONTROL. Without this, a glob that matched NOTHING would make every test below
    pass vacuously -- the zero-result probe that looks identical to success."""
    mods = _layout_modules()
    assert len(mods) >= 10, f'expected the 9 clones + the shared base, found {mods}'
    assert 'app.common.preprinted_base' in mods, 'the shared base was not discovered'
    assert 'app.accounts_payable.preprinted_layout' in mods, 'AP -- the reported page -- missing'


@pytest.mark.parametrize('modname', _layout_modules())
def test_every_layout_offers_the_month_first_full_date(modname):
    m = importlib.import_module(modname)
    assert FULL_KEY in m.DATE_FORMATS, \
        f'{modname}.DATE_FORMATS has no {FULL_KEY!r}: {sorted(m.DATE_FORMATS)}'
    assert m.DATE_FORMATS[FULL_KEY] == FULL_FMT, \
        f'{modname} spells {FULL_KEY!r} as {m.DATE_FORMATS[FULL_KEY]!r}, not {FULL_FMT!r}'


@pytest.mark.parametrize('modname', _layout_modules())
def test_the_new_key_is_actually_selectable(modname):
    """A format in DATE_FORMATS that is not in ALLOWED_DATE_FORMATS is dead: the
    sanitiser drops it and falls back to the default, so the dropdown would offer an
    option that silently does nothing. ALLOWED is derived from DATE_FORMATS in every
    file today -- this pins that it stays derived."""
    m = importlib.import_module(modname)
    assert FULL_KEY in m.ALLOWED_DATE_FORMATS, \
        f'{modname}: {FULL_KEY!r} is offered but not allowed by the sanitiser'


@pytest.mark.parametrize('modname', _layout_modules())
def test_long_is_left_alone(modname):
    """CONTROL: `long` already produced a full month name and some client layouts are
    saved with it. Redefining it would silently change what those instances print."""
    m = importlib.import_module(modname)
    assert m.DATE_FORMATS['long'] == '%d %B %Y'


def test_the_two_full_month_options_are_actually_different():
    """Guard the guard: if `full` were ever set equal to `long`, every assertion above
    would still pass while the dropdown gained a duplicate."""
    import datetime
    d = datetime.date(2026, 9, 1)
    assert d.strftime('%d %B %Y') == '01 September 2026'
    assert d.strftime(FULL_FMT) == 'September 01, 2026'
