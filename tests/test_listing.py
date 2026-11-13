import datetime

import pytest

import listing

D = datetime.date


@pytest.mark.parametrize("typed, days", [
    ("2025", (D(2025, 1, 1), D(2026, 1, 1))),
    ("Mar 2025", (D(2025, 3, 1), D(2025, 4, 1))),
    ("december 2025", (D(2025, 12, 1), D(2026, 1, 1))),
    ("15 Mar 2025", (D(2025, 3, 15), D(2025, 3, 16))),
    ("15/3/2025", (D(2025, 3, 15), D(2025, 3, 16))),
    ("2025-03", (D(2025, 3, 1), D(2025, 4, 1))),
])
def test_typed_dates_cover_their_days(typed, days):
    assert listing.period_of(typed) == days


@pytest.mark.parametrize("typed", ["yesterday", "31/2/2025"])
def test_unreadable_dates_match_nothing(typed):
    with pytest.raises(listing._NoMatch):
        listing.period_of(typed)


def test_month_without_year_covers_recent_years():
    today = datetime.date.today()
    ranges = listing.period_ranges("Dec")
    assert (today.year, today.year - 1) == (ranges[0][0].year, ranges[1][0].year)
    assert ranges[0][0].month == 12 and ranges[1][0].month == 12


def test_clock_time_is_not_treated_as_a_day():
    assert listing.period_of("Dec 2025 06:00") == (D(2025, 12, 1), D(2026, 1, 1))
    assert listing.period_of("29 Dec 2025 06:00") == (D(2025, 12, 29), D(2025, 12, 30))


def test_filter_hint_uses_only_the_first_date():
    assert listing.period_of("15 Mar 2025, Mar 2025, 2025") == (D(2025, 3, 15), D(2025, 3, 16))


def test_iso_date_range_from_picker():
    assert listing.period_ranges("2025-03-01..2025-03-31") == [(D(2025, 3, 1), D(2025, 4, 1))]
    assert listing.period_ranges("2025-03-15") == [(D(2025, 3, 15), D(2025, 3, 16))]


def test_plain_folds_accents_for_matching():
    assert listing._plain("Σταμάτησε") == "Σταματησε"
