"""What POST /bug-reports accepts (spec section 4, "Create, in order", steps 2-5)."""
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


def body(**over):
    b = {'message': '  It broke.  ', 'context': {'where': {'path': '/x'}},
         'images': [{'kind': 'page', 'data': b64(JPEG)}]}
    b.update(over)
    return b


def refusal(b):
    with pytest.raises(ReportRejected) as e:
        parse_report(b)
    return e.value.code, e.value.status


def test_limits_are_sanays():
    assert LIMITS == {'body_bytes': 2_000_000, 'message': 5000, 'context_bytes': 64_000,
                      'image_bytes': 400_000, 'images': 2, 'per_day': 10, 'keep_pictures_days': 90}


def test_sniff_mime_reads_the_first_bytes():
    assert sniff_mime(JPEG) == 'image/jpeg'
    assert sniff_mime(PNG) == 'image/png'
    assert sniff_mime(WEBP) == 'image/webp'
    assert sniff_mime(GIF) is None
    assert sniff_mime(b'') is None
    assert sniff_mime(b'RIFF\x00\x00\x00\x00WAVEfmt ') is None


def test_a_good_report_parses():
    message, context, images = parse_report(body())
    assert message == 'It broke.'
    assert context == {'where': {'path': '/x'}}
    assert images == [('page', 'image/jpeg', JPEG)]


def test_the_browsers_mime_claim_is_ignored():
    _, _, images = parse_report(body(images=[{'kind': 'own', 'mime': 'image/jpeg', 'data': b64(PNG)}]))
    assert images == [('own', 'image/png', PNG)]


def test_a_server_block_from_the_browser_is_dropped():
    _, context, _ = parse_report(body(context={'where': {}, 'server': {'user': {'id': 99}}}))
    assert context == {'where': {}}


def test_images_may_be_missing_or_null():
    assert parse_report(body(images=None))[2] == []
    b = body()
    del b['images']
    assert parse_report(b)[2] == []


def test_exactly_at_the_limits_is_accepted():
    pad = 'x' * (64_000 - len('{"pad": ""}'))
    biggest = b'\xff\xd8\xff' + b'\x00' * (400_000 - 3)
    message, context, images = parse_report(body(
        message='x' * 5000, context={'pad': pad},
        images=[{'kind': 'page', 'data': b64(biggest)}, {'kind': 'own', 'data': b64(WEBP)}]))
    assert len(message) == 5000
    assert images[0][2] == biggest and images[1][1] == 'image/webp'


@pytest.mark.parametrize('b, expected', [
    ('not a dict', ('bad_json', 400)),
    (None, ('bad_json', 400)),
    (body(message='   '), ('bad_message', 400)),
    (body(message='x' * 5001), ('bad_message', 400)),
    (body(message=7), ('bad_message', 400)),
    (body(context=None), ('bad_context', 400)),
    (body(context=['a']), ('bad_context', 400)),
    (body(context={'pad': 'x' * 64_001}), ('context_too_large', 413)),
    (body(images={'kind': 'page'}), ('bad_images', 400)),
    (body(images=[{'kind': 'page', 'data': b64(JPEG)}] * 3), ('bad_images', 400)),
    (body(images=['x']), ('bad_image', 400)),
    (body(images=[{'kind': 'screen', 'data': b64(JPEG)}]), ('bad_image', 400)),
    (body(images=[{'kind': 'page', 'data': 5}]), ('bad_image', 400)),
    (body(images=[{'kind': 'page', 'data': 'not base64!'}]), ('bad_image', 400)),
    (body(images=[{'kind': 'page', 'data': 'abc'}]), ('bad_image', 400)),
    (body(images=[{'kind': 'page', 'data': b64(JPEG) + '\n'}]), ('bad_image', 400)),
    (body(images=[{'kind': 'page', 'data': b64(GIF)}]), ('bad_image', 400)),
    (body(images=[{'kind': 'page', 'data': b64(b'\xff\xd8\xff' + b'\x00' * 400_000)}]),
     ('image_too_large', 413)),
])
def test_refusals(b, expected):
    assert refusal(b) == expected


def test_first_words_keeps_short_messages_whole_on_one_line():
    assert first_words('  The save\n button   did nothing ') == 'The save button did nothing'


def test_first_words_cuts_long_messages_at_a_word():
    message = 'When I click Save on the purchase order the page reloads and every line I typed is gone'
    assert first_words(message) == 'When I click Save on the purchase order the page reloads…'
    assert len(first_words(message)) <= 58
