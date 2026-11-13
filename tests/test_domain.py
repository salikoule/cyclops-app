import copy

import pytest

import domain
import records
import seed_data

ITEM, RECIPE = "ITM-00090", "REC-0222"


@pytest.fixture(scope="module")
def seed():
    return domain.normalize({table: seed_data.load().get(table) or [] for table in records.ORDER})


@pytest.fixture
def plant(seed):
    return copy.deepcopy(seed)


def act(plant, action, **payload):
    return domain.dispatch(plant, action, payload)


def _fed(plant):
    return [entry["itemId"] for entry in domain.reindex(plant)["recipes"][RECIPE]["inputs"]]


def _running(plant):
    order = act(plant, "new-order", contextKind="item", contextId=ITEM, quantity="5000")["redirect"]["code"]
    run = act(plant, "add-run", contextKind="order", contextId=order, recipe=RECIPE, shiftId="SHF-01", operatorId="PER-001",
              startedAt="2026-11-06T05:00:00Z")["redirect"]["code"]
    return order, run


def test_every_page_builds(plant):
    for kind, table in domain.KIND_TABLE.items():
        assert domain.list_view(plant, kind)["kind"] == kind
        if kind != "stoppage":
            for entry in plant[table][:25]:
                assert not domain.detail(plant, kind, entry["id"])["missing"]
    assert domain.overview(plant)["machines"]
    assert domain.choices(plant)["presses"]


def test_recipe_rules_follow_category_roles(plant):
    index = domain.reindex(plant)
    recipe = index["recipes"][RECIPE]
    assert domain.has_base(index, recipe)
    for entry in list(recipe["inputs"]):
        if domain.role_of(index, entry["itemId"]) == "base":
            recipe["inputs"].remove(entry)
    assert domain.recipe_status(plant, recipe) == "Cannot produce"


def test_gaps_name_the_open_data(plant):
    counted = {entry["key"]: entry["count"] for entry in domain.gaps(plant)}
    assert counted["no-cavities"] == len(plant["molds"])
    assert counted["stop-no-cause"] == sum(1 for entry in plant["stoppages"] if not entry.get("causeId"))
    assert counted["trial"] == 15


def test_a_run_needs_its_full_data(plant):
    order = act(plant, "new-order", contextKind="item", contextId=ITEM, quantity="5000")["redirect"]["code"]
    base = dict(contextKind="order", contextId=order, recipe=RECIPE, shiftId="SHF-01", operatorId="PER-001", startedAt="2026-11-06T05:00:00Z")
    assert "shift" in act(plant, "add-run", **dict(base, shiftId=""))["error"]
    assert "operator" in act(plant, "add-run", **dict(base, operatorId=""))["error"]
    assert "start" in act(plant, "add-run", **dict(base, startedAt=""))["error"]
    assert "good pieces" in act(plant, "add-run", **dict(base, endedAt="2026-11-06T13:00:00Z"))["error"]
    assert "before" in act(plant, "add-run", **dict(base, endedAt="2026-11-06T04:00:00Z", good="1"))["error"]
    assert "but the order is for" in act(plant, "add-run", **dict(base, recipe="REC-0002"))["error"]
    assert act(plant, "add-run", **base)["redirect"]["kind"] == "run"


def test_a_shift_log_saves_without_a_lot_or_cavities(plant):
    order, run = _running(plant)
    recipe = domain.reindex(plant)["recipes"][RECIPE]
    reason = plant["scrap_reasons"][0]["id"]
    result = act(plant, "log-shift", contextKind="floor", machine=recipe["machineId"], good="40",
                 scrapReason=reason, scrapQty="2", operatorId="PER-001")
    assert not result.get("error"), result
    assert "No consumed lot" in result["gaps"]
    assert "No cavity count" in result["gaps"]
    saved = domain.reindex(plant)["production_runs"][run]
    assert saved["good"] == 40 and saved["cavities"] is None and saved["inputs"] == []
    assert saved["scrap"] == [{"reasonId": reason, "quantity": 2}]
    assert saved.get("endedAt") in ("", None)


def test_a_stoppage_closes_only_with_a_cause(plant):
    _, run = _running(plant)
    result = act(plant, "add-stoppage", contextKind="run", contextId=run, startedAt="2026-11-06T07:00:00Z", endedAt="2026-11-06T08:00:00Z")
    assert "cause" in result["error"]
    assert not act(plant, "add-stoppage", contextKind="run", contextId=run, startedAt="2026-11-06T07:00:00Z", description="flash").get("error")
    closing = dict(contextKind="run", contextId=run, shiftId="SHF-01", operatorId="PER-001", startedAt="2026-11-06T05:00:00Z",
                   endedAt="2026-11-06T13:00:00Z", good="4000")
    assert "still open" in act(plant, "edit-run", **closing)["error"]


def test_run_metrics_leave_out_its_stoppages(plant):
    _, run = _running(plant)
    act(plant, "add-stoppage", contextKind="run", contextId=run, startedAt="2026-11-06T07:00:00Z", endedAt="2026-11-06T09:00:00Z", cause="CAU-01")
    act(plant, "add-scrap", contextKind="run", contextId=run, reason="SCR-01", quantity="60")
    act(plant, "edit-run", contextKind="run", contextId=run, shiftId="SHF-01", operatorId="PER-001", startedAt="2026-11-06T05:00:00Z",
        endedAt="2026-11-06T13:00:00Z", good="5940")
    page = domain.detail(plant, "run", run)
    assert (page["hours"], page["downHours"], page["pph"], page["scrapPct"]) == (8.0, 2.0, 1000, 1.0)


def test_lots_trace_back_and_forward(plant):
    _, run = _running(plant)
    received = act(plant, "receive-lot", item=_fed(plant)[0], number="R-1", receivedAt="2026-11-01T08:00:00Z", quantity="1000")["redirect"]["code"]
    assert "already exists" in act(plant, "receive-lot", item=_fed(plant)[0], number="R-1", receivedAt="2026-11-01T08:00:00Z", quantity="5")["error"]
    act(plant, "add-run-input", contextKind="run", contextId=run, lot=received, quantity="25")
    act(plant, "add-output-lot", contextKind="run", contextId=run, number="061126", quantity="4000")
    made = plant["lots"][-1]["id"]
    back = domain.detail(plant, "lot", made)["back"]
    assert back["run"]["id"] == run and back["inputs"][0]["lot"]["id"] == received
    forward = domain.detail(plant, "lot", received)["forward"]
    assert forward["runs"][0]["outputs"][0]["lot"]["id"] == made
    assert "Block it instead" in act(plant, "delete-lot", contextKind="lot", contextId=received)["error"]
    assert "used by later runs" not in (act(plant, "delete-run", contextKind="run", contextId=run).get("error") or "")


def test_history_blocks_deletes(plant):
    order, run = _running(plant)
    assert "Retire it" in act(plant, "delete-recipe", contextKind="recipe", contextId=RECIPE)["error"]
    assert "Cancel it" in act(plant, "delete-order", contextKind="order", contextId=order)["error"]


def test_a_standard_is_one_per_color_and_machine(plant):
    index = domain.reindex(plant)
    recipe = index["recipes"][RECIPE]
    twin = act(plant, "clone-recipe", contextKind="recipe", contextId=RECIPE)["redirect"]["code"]
    act(plant, "edit-recipe", contextKind="recipe", contextId=twin, status="approved")
    act(plant, "set-standard", contextKind="recipe", contextId=RECIPE)
    act(plant, "set-standard", contextKind="recipe", contextId=twin)
    index = domain.reindex(plant)
    assert index["recipes"][twin]["standard"] and not index["recipes"][RECIPE]["standard"]
    assert recipe["machineId"] == index["recipes"][twin]["machineId"]


def test_settings_reject_duplicates_without_adding(plant):
    before = len(plant["stoppage_causes"])
    assert act(plant, "save-setting", settingKind="cause", name="Mold change", category="Method")["error"]
    assert len(plant["stoppage_causes"]) == before
    assert "HH:MM" in act(plant, "save-setting", settingKind="shift", name="Late", start="25:00", end="06:00")["error"]


def test_only_roles_that_run_machines_hold_machines_and_run_them(plant):
    roles = {entry["name"]: entry["id"] for entry in plant["person_roles"]}
    act(plant, "save-setting", settingKind="role", name="Line lead", runsMachines="yes")
    lead = next(entry["id"] for entry in plant["person_roles"] if entry["name"] == "Line lead")
    act(plant, "save-setting", settingKind="person", code="PER-002", name=plant["personnel"][1]["name"], roleId=roles["Supervisor"], machines="MCH-01,MCH-02")
    act(plant, "save-setting", settingKind="person", code="PER-003", name=plant["personnel"][2]["name"], roleId=lead, machines="MCH-01,MCH-02")
    people = {entry["id"]: entry for entry in plant["personnel"]}
    assert people["PER-002"]["machineIds"] == [] and people["PER-003"]["machineIds"] == ["MCH-01", "MCH-02"]
    choices = domain.choices(plant)
    assert "PER-002" not in [entry["value"] for entry in choices["operators"]]
    assert "PER-002" in [entry["value"] for entry in choices["people"]]
    order = act(plant, "new-order", contextKind="item", contextId=ITEM, quantity="5000")["redirect"]["code"]
    refused = act(plant, "add-run", contextKind="order", contextId=order, recipe=RECIPE, shiftId="SHF-01", operatorId="PER-002",
                  startedAt="2026-11-06T05:00:00Z")
    assert "does not run machines" in refused["error"]


def test_fold_reads_greek_lookalikes_as_latin():
    assert domain.fold("Α100") == domain.fold("a100")
    assert domain.search({"items": [{"id": "ITM-1", "name": "ΚΑΛΥΚΑΣ Α100"}]}, "a100")
