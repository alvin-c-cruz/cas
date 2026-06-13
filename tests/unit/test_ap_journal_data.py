from datetime import date
from app.journals.ap_journal_data import resolve_period


def test_resolve_period_defaults_to_given_month():
    p = resolve_period({}, today=date(2026, 6, 13))
    assert p['mode'] == 'month'
    assert p['date_from'] == date(2026, 6, 1)
    assert p['date_to'] == date(2026, 6, 30)
    assert p['label'] == 'For the month of June 2026'


def test_resolve_period_explicit_month():
    p = resolve_period({'mode': 'month', 'year': '2026', 'month': '2'}, today=date(2026, 6, 13))
    assert p['date_from'] == date(2026, 2, 1)
    assert p['date_to'] == date(2026, 2, 28)  # 2026 not a leap year
    assert p['label'] == 'For the month of February 2026'


def test_resolve_period_custom_range():
    p = resolve_period(
        {'mode': 'custom', 'date_from': '2026-01-15', 'date_to': '2026-03-10'},
        today=date(2026, 6, 13),
    )
    assert p['mode'] == 'custom'
    assert p['date_from'] == date(2026, 1, 15)
    assert p['date_to'] == date(2026, 3, 10)
    assert p['label'] == 'From January 15, 2026 to March 10, 2026'  # no leading zero on day


def test_resolve_period_custom_with_bad_dates_falls_back_to_month():
    p = resolve_period({'mode': 'custom', 'date_from': 'bad', 'date_to': ''}, today=date(2026, 6, 13))
    assert p['mode'] == 'month'
    assert p['date_from'] == date(2026, 6, 1)


def test_resolve_period_custom_label_no_leading_zero():
    p = resolve_period(
        {'mode': 'custom', 'date_from': '2026-03-05', 'date_to': '2026-03-09'},
        today=date(2026, 6, 13),
    )
    assert p['label'] == 'From March 5, 2026 to March 9, 2026'


def test_resolve_period_custom_inverted_falls_back_to_month():
    p = resolve_period(
        {'mode': 'custom', 'date_from': '2026-06-30', 'date_to': '2026-01-01'},
        today=date(2026, 6, 13),
    )
    assert p['mode'] == 'month'
    assert p['date_from'] == date(2026, 6, 1)
