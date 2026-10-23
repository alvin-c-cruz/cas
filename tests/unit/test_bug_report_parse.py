"""What POST /bug-reports accepts (spec section 4, "Create, in order", steps 2-5). Reports are text
only since 23 Oct 2026 (owner: no files are uploaded to the server)."""
import pytest

from app.bug_reports.service import LIMITS, ReportRejected, first_words, parse_report

pytestmark = [pytest.mark.unit, pytest.mark.bug_reports]

PARSED = ('It broke.', {'where': {'path': '/x'}})


def body(**over):
    b = {'message': '  It broke.  ', 'context': {'where': {'path': '/x'}}}
    b.update(over)
    return b


def refusal(b):
    with pytest.raises(ReportRejected) as e:
        parse_report(b)
    return e.value.code, e.value.status


def test_limits():
    assert LIMITS == {'body_bytes': 2_000_000, 'message': 5000, 'context_bytes': 64_000, 'per_day': 10,
                      'keep_pictures_days': 90}


def test_a_good_report_parses():
    assert parse_report(body()) == PARSED


@pytest.mark.parametrize('images', [
    [{'kind': 'page', 'mime': 'image/jpeg', 'data': '/9j/4AAQ'}],
    [{'kind': 'page', 'data': 'not base64!'}] * 3,
    {'kind': 'page'},
    'x',
    None,
])
def test_pictures_from_a_page_still_running_the_old_script_are_ignored(images):
    """A page opened before the change still sends pictures, good or bad: the report is kept, the
    pictures are not read."""
    assert parse_report(body(images=images)) == PARSED


def test_a_server_block_from_the_browser_is_dropped():
    _, context = parse_report(body(context={'where': {}, 'server': {'user': {'id': 99}}}))
    assert context == {'where': {}}


def test_exactly_at_the_limits_is_accepted():
    pad = 'x' * (64_000 - len('{"pad": ""}'))
    message, context = parse_report(body(message='x' * 5000, context={'pad': pad}))
    assert len(message) == 5000
    assert context == {'pad': pad}


@pytest.mark.parametrize('b, expected', [
    ('not a dict', ('bad_json', 400)),
    (None, ('bad_json', 400)),
    (body(message='   '), ('bad_message', 400)),
    (body(message='x' * 5001), ('bad_message', 400)),
    (body(message=7), ('bad_message', 400)),
    (body(context=None), ('bad_context', 400)),
    (body(context=['a']), ('bad_context', 400)),
    (body(context={'pad': 'x' * 64_001}), ('context_too_large', 413)),
])
def test_refusals(b, expected):
    assert refusal(b) == expected


def test_first_words_keeps_short_messages_whole_on_one_line():
    assert first_words('  The save\n button   did nothing ') == 'The save button did nothing'


def test_first_words_cuts_long_messages_at_a_word():
    message = 'When I click Save on the purchase order the page reloads and every line I typed is gone'
    assert first_words(message) == 'When I click Save on the purchase order the page reloads…'
    assert len(first_words(message)) <= 58
