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


def test_an_earlier_year_stays_selected():
    graph = domain.normalize({
        "machines": [{"id": "M1", "name": "EKIN"}],
        "shifts": [{"id": "S1", "name": "Morning", "start": "06:00", "end": "14:00"}],
        "items": [{"id": "I1", "name": "Cup"}],
        "recipes": [{"id": "R1", "itemId": "I1", "machineId": "M1"}],
        "production_runs": [
            {"id": "RUN-A", "recipeId": "R1", "shiftId": "S1", "startedAt": "2025-05-18T03:00:00Z", "endedAt": "2025-05-18T11:00:00Z", "good": 800, "cycle": 12, "cavities": 2},
            {"id": "RUN-B", "recipeId": "R1", "shiftId": "S1", "startedAt": "2026-01-10T03:00:00Z", "endedAt": "2026-01-10T11:00:00Z", "good": 100, "cycle": 12, "cavities": 2},
        ],
    })
    earlier = performance.view(graph, "2025", years=[2026, 2025])
    assert earlier["year"] == 2025
    assert earlier["years"] == [2026, 2025]
    assert earlier["kpis"]["runs"] == 1
    assert earlier["kpis"]["good"] == 800
    latest = performance.view(graph, None, years=[2026, 2025])
    assert latest["year"] == 2026
    assert latest["kpis"]["runs"] == 1
    assert latest["kpis"]["good"] == 100


def test_filters_narrow_the_view(seed, year):
    machine = year["machines"][0]["value"]
    month = performance.view(seed, year["year"], 3)
    one = performance.view(seed, year["year"], 0, machine)
    assert month["kpis"]["runs"] < year["kpis"]["runs"]
    assert one["kpis"]["runs"] < year["kpis"]["runs"]
    label = next(entry["label"] for entry in year["machines"] if entry["value"] == machine)
    assert one["calendarMachines"] == [label]
    assert {cell[1] for cell in one["calendar"]} <= {0}


def _tiny(run):
    return domain.normalize({
        "machines": [{"id": "M1", "name": "EKIN"}],
        "shifts": [{"id": "S1", "name": "Morning", "start": "06:00", "end": "14:00"}],
        "items": [{"id": "I1", "name": "Cup"}],
        "recipes": [{"id": "R1", "itemId": "I1", "machineId": "M1"}],
        "production_runs": [run],
    })


def test_calendar_uses_actual_pieces_per_hour_when_speed_is_not_rated():
    graph = _tiny({
        "id": "RUN-1", "recipeId": "R1", "shiftId": "S1",
        "startedAt": "2025-05-18T03:00:00Z", "endedAt": "2025-05-18T11:00:00Z",
        "good": 800, "cycle": 12,
    })
    shown = performance.view(graph, 2025, 5)
    shares = [cell[2] for cell in shown["calendar"]]
    assert shares == [pytest.approx(33.3)]
    assert shown["kpis"]["ratedRuns"] == 0
    assert shown["calendarMachines"] == ["EKIN"]


def test_effective_cycle_needs_cavities_and_is_not_the_target():
    closed = {
        "id": "RUN-1", "recipeId": "R1", "shiftId": "S1",
        "startedAt": "2025-05-18T03:00:00Z", "endedAt": "2025-05-18T04:00:00Z",
        "good": 720,
    }
    graph = _tiny(dict(closed, cycle=20))
    without = domain.run_metrics(graph, graph["production_runs"][0])
    assert without["pph"] == 720
    assert without["effectiveCycle"] is None
    assert without["target"] is None
    graph = _tiny(dict(closed, cycle=20, cavities=2))
    with_cavities = domain.run_metrics(graph, graph["production_runs"][0])
    assert with_cavities["effectiveCycle"] == 10
    assert with_cavities["target"] == 360
    assert graph["production_runs"][0]["cycle"] == 20


def test_calendar_marks_days_without_a_rated_speed(year):
    shares = [cell[2] for cell in year["calendar"]]
    assert None in shares and all(share is None or 0 <= share <= 100 for share in shares)
    assert all(0 <= cell[0] <= 365 and cell[1] < len(year["calendarMachines"]) for cell in year["calendar"])
    assert all(number < len(year["calendarItems"]) for cell in year["calendar"] for number in cell[5])


def test_capacity_and_scrap_shares_are_percentages(year):
    assert all(0 <= row["pct"] <= 100 for row in year["capacity"])
    cumulative = [row["cumulative"] for row in year["scrapItems"]]
    assert cumulative == sorted(cumulative) and cumulative[-1] <= 100
