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


def test_compare_header_reads_the_operator():
    assert listing._compare_parts(">= 2") == (">=", 2.0)
    assert listing._compare_parts("< 0,5") == ("<", 0.5)
    assert listing._compare_parts("8") == (">=", 8.0)


def test_number_condition_matches_the_shown_value():
    assert listing._condition_values("cf|equals|8") == ("equals", [8.0])
    assert listing._condition_values("cf|inRange|2|8,5") == ("inRange", [2.0, 8.5])
    assert listing._condition_values("8") == ("greaterThanOrEqual", [8.0])
    assert listing._stored_number_query("equals", [8.0]) == 8
    assert listing._number_holds(8.0, "equals", [8.0])
    assert not listing._number_holds(18.0, "equals", [8.0])
    assert listing._number_holds(8.0, "inRange", [2.0, 8.0])
    assert listing._number_holds(None, "blank", [])
    assert not listing._number_holds(None, "notEqual", [8.0])


def test_date_condition_is_a_calendar_day():
    assert listing._date_window("equals", ["2025-12-29"]) == ("within", D(2025, 12, 29), D(2025, 12, 30))
    assert listing._date_window("greaterThan", ["2025-12-29"]) == ("from", D(2025, 12, 30))
    assert listing._date_window("inRange", ["2025-12-31", "2025-12-01"]) == ("within", D(2025, 12, 1), D(2026, 1, 1))
    assert listing._date_window("blank", []) == ("blank",)
    assert listing.moment("started_at")("29 Dec 2025")["started_at"] is not None


def test_iso_date_range_from_picker():
    assert listing.period_ranges("2025-03-01..2025-03-31") == [(D(2025, 3, 1), D(2025, 4, 1))]
    assert listing.period_ranges("2025-03-15") == [(D(2025, 3, 15), D(2025, 3, 16))]


def test_plain_folds_accents_for_matching():
    assert listing._plain("Σταμάτησε") == "Σταματησε"


def test_calculated_number_sorts_with_blanks_last():
    rows = [{"code": "a"}, {"code": "b"}, {"code": "c"}]
    spec = {"sort": {"n": listing._Rank(lambda found: {"a": 2, "b": None, "c": 1})}, "order": ("code", True)}
    assert [row["code"] for row in listing._apply_ranks(spec, rows, [{"field": "n", "dir": "asc"}])] == ["c", "a", "b"]
    assert [row["code"] for row in listing._apply_ranks(spec, rows, [{"field": "n", "dir": "desc"}])] == ["a", "c", "b"]


def test_calculated_sort_does_not_become_a_query_column():
    spec = {"sort": {"hours": listing._Rank(lambda found: {}, ("started_at", "ended_at")), "good": "good_qty"}, "order": ("started_at", False)}
    assert listing._sort_columns(spec, [{"field": "hours", "dir": "desc"}]) == [("started_at", False), ("code", True)]
    assert listing._sort_columns(spec, [{"field": "good", "dir": "asc"}]) == [("good_qty", True), ("code", True)]


def test_number_and_percentage_columns_can_be_sorted():
    sortable = listing.capabilities()
    expected = {
        "item": ("recipes", "trial", "usedIn"),
        "mold": ("recipes", "cavities", "shot"),
        "machine": ("molds", "recipes", "changeover"),
        "recipe": ("cycle", "pph"),
        "order": ("quantity", "made", "progress", "runs"),
        "run": ("hours", "good", "scrapPct", "pph", "performance"),
        "stoppage": ("hours",),
        "lot": ("quantity", "used"),
        "changeover": ("hours",),
    }
    for kind, fields in expected.items():
        missing = [field for field in fields if field not in sortable[kind]["sort"]]
        assert not missing, "%s cannot sort %s" % (kind, missing)
