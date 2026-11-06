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


def test_plain_folds_accents_for_matching():
    assert listing._plain("Σταμάτησε") == "Σταματησε"
