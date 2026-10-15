"""Shared pieces for the bug report tests."""
import base64

JPEG = b'\xff\xd8\xff\xe0' + b'\x00' * 60
PNG = b'\x89PNG\r\n\x1a\n' + b'\x00' * 60
GIF = b'GIF89a' + b'\x00' * 60


def b64(data):
    return base64.b64encode(data).decode('ascii')


def payload(message='The save button did nothing.', images=None, **extra):
    """A body as bug-report.js sends it."""
    body = {
        'message': message,
        'context': {
            'where': {'path': '/accounts-payable/12/edit?tab=lines', 'title': 'APV'},
            'before': {'taps': [], 'pages': [], 'errors': [], 'requests': [], 'sizes': []},
            'device': {'userAgent': 'pytest'},
        },
        'images': images if images is not None else [
            {'kind': 'page', 'mime': 'image/jpeg', 'data': b64(JPEG)}],
    }
    body.update(extra)
    return body


def login(client, user, password, branch=None):
    if branch is not None:
        with client.session_transaction() as sess:
            sess['selected_branch_id'] = branch.id
    client.post('/login', data={'username': user.username, 'password': password},
                follow_redirects=True)


def post_report(client, body, headers=None):
    return client.post('/bug-reports', json=body, headers=headers or {})
