"""A bug report's status, Sanay's set (src/lib/report-status.ts). The open ones still need work; a
closed one stamps closed_at, and its pictures are deleted 90 days later."""

OPEN_STATUSES = ('new', 'seen', 'in_progress')
CLOSED_STATUSES = ('fixed', 'wont_fix', 'duplicate', 'cant_reproduce')
STATUSES = OPEN_STATUSES + CLOSED_STATUSES

STATUS_LABEL = {
    'new': 'New',
    'seen': 'Seen',
    'in_progress': 'In progress',
    'fixed': 'Fixed',
    'wont_fix': "Won't fix",
    'duplicate': 'Duplicate',
    'cant_reproduce': "Can't reproduce",
}


def is_status(value):
    return value in STATUSES


def is_closed(status):
    return status in CLOSED_STATUSES
