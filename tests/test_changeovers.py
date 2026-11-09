import datetime

import pytest

import changeovers
import domain
import performance
import records
import seed_data

SHIFTS = [{"id": "SHF-01", "name": "Morning", "start": "06:00", "end": "14:00", "status": "active"},
          {"id": "SHF-02", "name": "Afternoon", "start": "14:00", "end": "22:00", "status": "active"},
          {"id": "SHF-03", "name": "Night", "start": "22:00", "end": "06:00", "status": "active"}]
FIRST = datetime.date(2025, 3, 3)


def at(day, hour):
    zone = performance._zone()
    moment = datetime.datetime(day.year, day.month, day.day, tzinfo=zone) + datetime.timedelta(hours=hour)
    return records.moment_text(moment.astimezone(datetime.timezone.utc))


def plant(runs, stoppages=(), molds=("MLD-0001", "MLD-0002", "MLD-0003")):
    """One machine at 100 pieces an hour, items A, B and C on their own molds."""
    graph = {
        "shifts": SHIFTS, "machines": [{"id": "MCH-01", "name": "Press 1"}],
        "stoppage_causes": [{"id": "CAU-01", "name": "Tool change", "category": "Method", "planned": True, "changeover": True},
                            {"id": "CAU-02", "name": "Breakdown", "category": "Machine", "planned": False, "changeover": False}],
        "items": [{"id": code, "name": code} for code in ("A", "B", "C")],
        "recipes": [{"id": "R" + item, "itemId": item, "machineId": "MCH-01", "moldId": mold, "inputs": []} for item, mold in zip("ABC", molds)],
        "production_runs": [], "stoppages": list(stoppages),
    }
    for number, (day, shift, item, good) in enumerate(runs, start=1):
        start = {"SHF-01": 6, "SHF-02": 14, "SHF-03": 22}[shift]
        graph["production_runs"].append({"id": "RUN-%05d" % number, "recipeId": "R" + item, "shiftId": shift, "startedAt": at(day, start),
                                         "endedAt": at(day, start + 8), "good": good, "cavities": 1, "cycle": 36, "scrap": []})
    return domain.normalize(graph)


def days(start, count, item, good=800, shift="SHF-01"):
    return [(FIRST + datetime.timedelta(days=start + offset), shift, item, good) for offset in range(count)]


def test_short_first_shift_is_the_changeover():
    graph = plant(days(0, 7, "A") + days(7, 1, "B", 400) + days(8, 7, "B"))
    [change] = changeovers.derive(graph)
    assert (change["fromItemId"], change["toItemId"], change["kind"], change["source"]) == ("A", "B", "mold", "derived")
    assert change["lostHours"] == pytest.approx(4.0)
    assert change["startedAt"] == at(FIRST + datetime.timedelta(days=7), 6)
    assert change["endedAt"] == at(FIRST + datetime.timedelta(days=7), 10)
    assert change["confidence"] == "medium"


def test_change_between_jobs_costs_nothing_when_the_first_shift_is_normal():
    graph = plant(days(0, 7, "A") + days(8, 7, "B"))
    [change] = changeovers.derive(graph)
    assert change["lostHours"] == 0
    assert change["startedAt"] == at(FIRST + datetime.timedelta(days=6), 14)
    assert change["endedAt"] == at(FIRST + datetime.timedelta(days=8), 6)


def test_two_items_in_one_shift_share_it():
    shared = FIRST + datetime.timedelta(days=7)
    graph = plant(days(0, 7, "A") + [(shared, "SHF-01", "A", 300), (shared, "SHF-01", "B", 200)] + days(8, 7, "B"))
    [change] = changeovers.derive(graph)
    assert change["lostHours"] == pytest.approx(3.0)
    assert (change["startedAt"], change["endedAt"]) == (at(shared, 9), at(shared, 12))
    graph["changeovers"] = [change]
    view = performance.view(graph, 2025)
    hours = {entry["key"]: entry["hours"] for entry in view["buckets"]}
    assert hours["changeover"] == pytest.approx(3.0)
    assert hours["good"] == pytest.approx(14 * 8 + 5.0)
    assert sum(hours.values()) == pytest.approx(15 * 8)


def test_a_family_mold_is_not_a_changeover():
    both = [(day, shift, item, good) for day, shift, _, good in days(7, 5, "A", 400) for item in "BC"]
    graph = plant(days(0, 7, "A") + both, molds=("MLD-0001", "MLD-0002", "MLD-0002"))
    found = changeovers.derive(graph)
    assert [(change["fromItemId"], change["toItemId"]) for change in found] == [("A", "B")]


def test_a_logged_stop_gives_the_times_and_leaves_planned_stops():
    day = FIRST + datetime.timedelta(days=7)
    stop = {"id": "STP-00001", "machineId": "MCH-01", "runId": "", "startedAt": at(day, 6), "endedAt": at(day, 8.5), "causeId": "CAU-01"}
    graph = plant(days(0, 7, "A") + days(7, 1, "B", 550) + days(8, 7, "B"), [stop])
    [change] = changeovers.derive(graph)
    assert (change["source"], change["stoppageId"], change["confidence"]) == ("stop", "STP-00001", "high")
    assert change["lostHours"] == pytest.approx(2.5)
    graph["changeovers"] = [change]
    hours = {entry["key"]: entry["hours"] for entry in performance.view(graph, 2025)["buckets"]}
    assert hours["changeover"] == pytest.approx(2.5) and hours["planned"] == 0


def test_hand_entered_changeovers_are_kept_and_codes_stay_unique():
    graph = plant(days(0, 7, "A") + days(7, 7, "B") + days(14, 7, "C"))
    entered = {"id": "CHG-00007", "machineId": "MCH-01", "fromRunId": "RUN-00007", "toRunId": "RUN-00008", "source": "entered"}
    graph["changeovers"] = [entered]
    found = changeovers.derive(graph)
    assert [(change["fromItemId"], change["toItemId"]) for change in found] == [("B", "C")]
    assert found[0]["id"] == "CHG-00008"


@pytest.fixture(scope="module")
def seed():
    return domain.normalize({table: seed_data.load().get(table) or [] for table in records.ORDER})


def test_seed_changeovers_point_at_their_machine_runs(seed):
    index = domain.reindex(seed)
    assert seed["changeovers"]
    for change in seed["changeovers"]:
        before, after = index["production_runs"][change["fromRunId"]], index["production_runs"][change["toRunId"]]
        assert domain.machine_of_run(index, before) == domain.machine_of_run(index, after) == change["machineId"]
        assert domain.item_of_run(index, before) == change["fromItemId"] != change["toItemId"] == domain.item_of_run(index, after)
        assert change["startedAt"] <= change["endedAt"] and change["lostHours"] >= 0
        assert change["kind"] in dict(domain.CHANGEOVER_KINDS) and change["source"] in ("stop", "derived")


def test_seed_derivation_is_repeatable(seed):
    again = changeovers.derive(seed)
    assert [(change["id"], change["fromRunId"], change["toRunId"], change["lostHours"]) for change in again] == \
           [(change["id"], change["fromRunId"], change["toRunId"], change["lostHours"]) for change in seed["changeovers"]]
