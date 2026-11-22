"""What POST /bug-reports accepts (spec section 4, "Create, in order", steps 2-5), with the picture rules of SHOT-1
(owner, 22 Nov 2026): pictures only when the server's switch is on, JPEG only, at most 200 KB each, one of the page and
one of the user's own. A picture that breaks a rule is left out; the report's text is still kept."""
import base64

import pytest

from app.bug_reports.service import LIMITS, ReportRejected, first_words, parse_report, sniff_mime

pytestmark = [pytest.mark.unit, pytest.mark.bug_reports]

JPEG = b'\xff\xd8\xff\xe0' + b'\x00' * 60
PNG = b'\x89PNG\r\n\x1a\n' + b'\x00' * 60
WEBP = b'RIFF\x00\x00\x00\x00WEBPVP8 ' + b'\x00' * 60
GIF = b'GIF89a' + b'\x00' * 60


def b64(data):
    return base64.b64encode(data).decode('ascii')


def page(data=JPEG):
    return {'kind': 'page', 'mime': 'image/jpeg', 'data': b64(data)}


def own(data=JPEG):
    return {'kind': 'own', 'mime': 'image/jpeg', 'data': b64(data)}


def body(**over):
    b = {'message': '  It broke.  ', 'context': {'where': {'path': '/x'}}, 'images': [page()]}
    b.update(over)
    return b


def refusal(b):
    with pytest.raises(ReportRejected) as e:
        parse_report(b, pictures=True)
    return e.value.code, e.value.status


def test_the_limits():
    assert LIMITS == {'body_bytes': 2_000_000, 'message': 5000, 'context_bytes': 64_000,
                      'image_bytes': 200_000, 'images': 2, 'per_day': 10, 'keep_pictures_days': 30}


def test_sniff_mime_reads_the_first_bytes():
    assert sniff_mime(JPEG) == 'image/jpeg'
    assert sniff_mime(PNG) == 'image/png'
    assert sniff_mime(WEBP) == 'image/webp'
    assert sniff_mime(GIF) is None
    assert sniff_mime(b'') is None
    assert sniff_mime(b'RIFF\x00\x00\x00\x00WAVEfmt ') is None


def test_a_good_report_parses_with_its_picture_when_the_switch_is_on():
    message, context, images, left_out = parse_report(body(), pictures=True)
    assert message == 'It broke.'
    assert context == {'where': {'path': '/x'}}
    assert images == [('page', 'image/jpeg', JPEG)]
    assert left_out == 0


def test_with_the_switch_off_every_picture_is_ignored_without_a_word():
    for images in ([page()], [page(), own()], [page(PNG)], {'kind': 'page'}, 'rubbish', None):
        message, context, kept, left_out = parse_report(body(images=images), pictures=False)
        assert (message, kept, left_out) == ('It broke.', [], 0)


def test_the_switch_is_off_unless_the_caller_says_so():
    assert parse_report(body())[2:] == ([], 0)


def test_a_server_block_from_the_browser_is_dropped():
    _, context, _, _ = parse_report(body(context={'where': {}, 'server': {'user': {'id': 99}}}), pictures=True)
    assert context == {'where': {}}


def test_images_may_be_missing_or_null():
    assert parse_report(body(images=None), pictures=True)[2:] == ([], 0)
    b = body()
    del b['images']
    assert parse_report(b, pictures=True)[2:] == ([], 0)


def test_the_page_picture_and_one_own_screenshot_are_both_kept():
    _, _, images, left_out = parse_report(body(images=[page(), own()]), pictures=True)
    assert [kind for kind, _, _ in images] == ['page', 'own']
    assert left_out == 0


def test_exactly_at_the_limits_is_accepted():
    pad = 'x' * (64_000 - len('{"pad": ""}'))
    biggest = b'\xff\xd8\xff' + b'\x00' * (200_000 - 3)
    message, context, images, left_out = parse_report(body(
        message='x' * 5000, context={'pad': pad}, images=[page(biggest), own()]), pictures=True)
    assert len(message) == 5000
    assert images[0][2] == biggest and images[1][0] == 'own'
    assert left_out == 0


@pytest.mark.parametrize('images, kept, left_out', [
    ([page(b'\xff\xd8\xff' + b'\x00' * 200_000)], [], 1),                 # one byte over 200 KB
    ([page(PNG)], [], 1),                                                 # not a JPEG, whatever its label says
    ([own(WEBP)], [], 1),
    ([page(GIF)], [], 1),
    ([page(), page()], ['page'], 1),                                      # one picture of the page
    ([own(), own()], ['own'], 1),                                         # one own screenshot
    ([page(), own(), own()], ['page', 'own'], 1),
    ([own(PNG), own()], ['own'], 1),                                      # a bad one does not use up the place
    ({'kind': 'page'}, [], 1),                                            # not a list at all
    (['x'], [], 1),
    ([{'kind': 'screen', 'data': b64(JPEG)}], [], 1),
    ([{'kind': 'page', 'data': 5}], [], 1),
    ([{'kind': 'page', 'data': 'not base64!'}], [], 1),
    ([{'kind': 'page', 'data': 'abc'}], [], 1),
    ([{'kind': 'page', 'data': b64(JPEG) + '\n'}], [], 1),
])
def test_a_picture_that_breaks_a_rule_is_left_out_and_the_text_is_kept(images, kept, left_out):
    message, _, got, n = parse_report(body(images=images), pictures=True)
    assert message == 'It broke.'
    assert [kind for kind, _, _ in got] == kept
    assert all(mime == 'image/jpeg' for _, mime, _ in got)
    assert n == left_out


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
def test_the_text_is_still_refused_as_before(b, expected):
    assert refusal(b) == expected


def test_first_words_keeps_short_messages_whole_on_one_line():
    assert first_words('  The save\n button   did nothing ') == 'The save button did nothing'


def test_first_words_cuts_long_messages_at_a_word():
    message = 'When I click Save on the purchase order the page reloads and every line I typed is gone'
    assert first_words(message) == 'When I click Save on the purchase order the page reloads…'
    assert len(first_words(message)) <= 58
