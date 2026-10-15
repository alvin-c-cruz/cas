"""Bug reports: validation, storage and clean-up. Ported from Sanay's src/server/reports.ts and
reports-http.ts (C:/envs/sanay); what changed for CAS is in the spec,
app-docs/superpowers/specs/2026-10-15-bug-reports-design.md beside the checkout."""
import base64
import binascii
import json
import re

LIMITS = {
    'body_bytes': 2_000_000,
    'message': 5000,
    'context_bytes': 64_000,
    'image_bytes': 400_000,
    'images': 2,
    'per_day': 10,
    'keep_pictures_days': 90,
}
_BASE64 = re.compile(r'[A-Za-z0-9+/]+={0,2}')


class ReportRejected(Exception):
    """A report the server refuses: `code` is the JSON error, `status` the HTTP status."""

    def __init__(self, code, status=400):
        super().__init__(code)
        self.code = code
        self.status = status


def sniff_mime(data):
    """JPEG, PNG or WebP, recognised by their first bytes; anything else is None."""
    if data[:3] == b'\xff\xd8\xff':
        return 'image/jpeg'
    if data[:8] == b'\x89PNG\r\n\x1a\n':
        return 'image/png'
    if len(data) >= 12 and data[:4] == b'RIFF' and data[8:12] == b'WEBP':
        return 'image/webp'
    return None


def first_words(message):
    """The message on one line, cut at a word after 57 characters, for a notification."""
    line = ' '.join(message.split())
    return line if len(line) <= 60 else re.sub(r'\s+\S*$', '', line[:57]) + '…'


def parse_report(body):
    """Check a decoded JSON body. Returns (message, context, images), images being
    (kind, mime, bytes) with the mime sniffed from the bytes. The browser's own 'server' key is
    dropped: only the server writes it. Raises ReportRejected."""
    if not isinstance(body, dict):
        raise ReportRejected('bad_json')

    message = body.get('message')
    message = message.strip() if isinstance(message, str) else ''
    if not message or len(message) > LIMITS['message']:
        raise ReportRejected('bad_message')

    context = body.get('context')
    if not isinstance(context, dict):
        raise ReportRejected('bad_context')
    context = dict(context)
    context.pop('server', None)
    if len(json.dumps(context, ensure_ascii=False).encode('utf-8')) > LIMITS['context_bytes']:
        raise ReportRejected('context_too_large', 413)

    raw = body.get('images')
    if raw is None:
        raw = []
    if not isinstance(raw, list) or len(raw) > LIMITS['images']:
        raise ReportRejected('bad_images')
    images = []
    for im in raw:
        if not isinstance(im, dict) or im.get('kind') not in ('page', 'own'):
            raise ReportRejected('bad_image')
        data = im.get('data')
        if not isinstance(data, str) or not _BASE64.fullmatch(data):
            raise ReportRejected('bad_image')
        try:
            decoded = base64.b64decode(data, validate=True)
        except (binascii.Error, ValueError):
            raise ReportRejected('bad_image')
        if len(decoded) > LIMITS['image_bytes']:
            raise ReportRejected('image_too_large', 413)
        mime = sniff_mime(decoded)
        if mime is None:
            raise ReportRejected('bad_image')
        images.append((im['kind'], mime, decoded))
    return message, context, images
