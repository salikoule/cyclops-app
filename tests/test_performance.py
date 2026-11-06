import collections

import pytest

import domain
import performance
import records
import seed_data


@pytest.fixture(scope="module")
def seed():
    return domain.normalize({table: seed_data.load().get(table) or [] for table in records.ORDER})


@pytest.fixture(scope="module")
def year(seed):
    return performance.view(seed)


def test_seed_codes_are_unique(seed):
    for table in records.ORDER:
        counted = collections.Counter(entry["id"] for entry in seed.get(table) or [])
        assert not [code for code, times in counted.items() if times > 1], table


def test_hours_add_up_to_staffed_time(year):
    kpis = year["kpis"]
    buckets = sum(entry["hours"] for entry in year["buckets"])
    assert kpis["staffedHours"] == pytest.approx(buckets, abs=1)
    assert kpis["lostHours"] == pytest.approx(buckets - year["buckets"][0]["hours"], abs=1)
    assert 0 < kpis["oee"] <= 100


def test_filters_narrow_the_view(seed, year):
    machine = year["machines"][0]["value"]
    month = performance.view(seed, year["year"], 3)
    one = performance.view(seed, year["year"], 0, machine)
    assert month["kpis"]["runs"] < year["kpis"]["runs"]
    assert one["kpis"]["runs"] < year["kpis"]["runs"]
    label = next(entry["label"] for entry in year["machines"] if entry["value"] == machine)
    assert one["calendarMachines"] == [label]
    assert {cell[1] for cell in one["calendar"]} <= {0}


def test_calendar_marks_days_without_a_rated_speed(year):
    shares = [cell[2] for cell in year["calendar"]]
    assert None in shares and all(share is None or 0 <= share <= 100 for share in shares)
    assert all(0 <= cell[0] <= 365 and cell[1] < len(year["calendarMachines"]) for cell in year["calendar"])
    assert all(number < len(year["calendarItems"]) for cell in year["calendar"] for number in cell[5])


def test_capacity_and_scrap_shares_are_percentages(year):
    assert all(0 <= row["pct"] <= 100 for row in year["capacity"])
    cumulative = [row["cumulative"] for row in year["scrapItems"]]
    assert cumulative == sorted(cumulative) and cumulative[-1] <= 100
