import access
import audit
import domain
import exports
import notify


def test_observer_cannot_write_and_user_can():
    assert access.can_apply("observer", "add-run") is False
    assert access.can_apply("observer", "log-shift") is False
    assert access.can_apply("user", "add-run") is True
    assert access.can_apply("user", "edit-item") is True
    assert access.can_apply("administrator", "save-setting") is True
    assert access.can_apply("administrator", "save-access") is True
    assert access.can_apply("user", "save-access") is False
    assert access.can_apply("observer", "save-setting") is False


def test_screens_follow_the_role_not_the_label():
    assert access.can_open("observer", ["floor", "run"], "floor")
    assert not access.can_open("observer", ["floor"], "users")
    assert not access.can_open("user", ["item"], "history")
    assert access.can_open("administrator", [], "users")
    assert "notify" in access.visible_screens("observer", [])
    assert access.home_path("user", ["floor", "item"]) == "/floor"


def test_the_last_administrator_stays_active():
    profiles = [{"email": "a@plant.test", "role": "administrator", "active": True}]
    assert access.leaves_an_admin(profiles, "a@plant.test", "administrator", False) is False
    assert access.leaves_an_admin(profiles, "a@plant.test", "user", True) is False
    profiles.append({"email": "b@plant.test", "role": "administrator", "active": True})
    assert access.leaves_an_admin(profiles, "a@plant.test", "observer", False) is True


def test_audit_lines_expand_recipe_input_shares():
    before = {"recipes": {"REC-1": {"id": "REC-1", "inputs": [{"itemId": "ITM-A", "share": 0.97}]}}}
    after = {"recipes": {"REC-1": {"id": "REC-1", "inputs": [{"itemId": "ITM-A", "share": 0.95}, {"itemId": "ITM-B", "share": 0.05}]}}}
    rows = audit.rows(before, after, {"recipes": ["REC-1"]}, "ada@plant.test", "2026-11-13T08:00:00Z")
    labels = [line["label"] for line in rows[0]["lines"]]
    assert any("ITM-A" in label and "share" in label for label in labels)
    assert any("ITM-B" in label and "added" in label for label in labels)


def test_an_audit_row_records_who_changed_an_item():
    before = {"items": {"ITM-1": {"id": "ITM-1", "name": "Cup", "erpCode": "A"}}}
    after = {"items": {"ITM-1": {"id": "ITM-1", "name": "Cup", "erpCode": "B"}}}
    rows = audit.rows(before, after, {"items": ["ITM-1"]}, "ada@plant.test", "2026-11-13T08:00:00Z")
    assert len(rows) == 1
    assert rows[0]["email"] == "ada@plant.test"
    assert rows[0]["action"] == "update"
    assert rows[0]["record"] == "ITM-1"
    assert rows[0]["changes"]["erpCode"] == ["A", "B"]
    renamed = {"items": {"ITM-1": {"id": "ITM-1", "name": "Cup 2", "erpCode": "A"}}}
    change = audit.rows(before, renamed, {"items": ["ITM-1"]}, "ada@plant.test", "2026-11-13T08:00:00Z")[0]
    assert change["changes"]["name"] == ["Cup", "Cup 2"]
    assert "erpCode" not in change["changes"]
    assert audit.rows(before, before, {"items": ["ITM-1"]}, "ada@plant.test", "2026-11-13T08:00:00Z") == []


def test_a_breakdown_stoppage_notifies_only_who_opted_in():
    stop = {"id": "STP-1", "causeId": "CAU-1", "machineId": "Press 1", "description": "heater"}
    breakdown = {"id": "CAU-1", "name": "Heater", "planned": False, "changeover": False}
    maintenance = {"id": "CAU-2", "name": "Service", "planned": True, "changeover": False}
    change = {"id": "CAU-3", "name": "Mold", "planned": False, "changeover": True}
    prefs = [
        {"email": "a@plant.test", "maintenance": False, "breakdowns": True},
        {"email": "b@plant.test", "maintenance": True, "breakdowns": False},
    ]
    notes = notify.for_users(notify.kind_for(None, stop, breakdown), stop, breakdown, prefs, "2026-11-13T08:00:00Z")
    assert [note["email"] for note in notes] == ["a@plant.test"]
    assert notes[0]["kind"] == "breakdown"
    assert notes[0]["record"] == "STP-1"
    planned = dict(stop, causeId="CAU-2")
    assert [note["email"] for note in notify.for_users(notify.kind_for(None, planned, maintenance), planned, maintenance, prefs, "2026-11-13T08:00:00Z")] == ["b@plant.test"]
    assert notify.kind_for(None, dict(stop, causeId="CAU-3"), change) == ""
    assert notify.kind_for(stop, stop, breakdown) == ""


def test_a_variant_keeps_its_parent_and_its_own_sku():
    graph = domain.normalize({
        "units": [{"id": "UNT-01", "name": "pcs", "status": "active"}],
        "item_categories": [{"id": "CAT-01", "name": "Parts", "type": "SFG", "role": ""}],
        "variant_attributes": [{"id": "VAT-01", "name": "Pack size", "status": "active"}],
    })
    base = {"type": "SFG", "categoryId": "CAT-01", "uomId": "UNT-01"}
    parent = domain.dispatch(graph, "new-item", dict(base, name="Cup", erpCode="CUP"))["redirect"]["code"]
    child = domain.dispatch(graph, "new-item", dict(base, name="Cup 12-pack", erpCode="CUP-12", parentId=parent, **{"attr::VAT-01": "12"}))["redirect"]["code"]
    detail = domain.detail(graph, "item", child)
    assert detail["parentId"] == parent
    assert detail["erpCode"] == "CUP-12"
    assert detail["attributes"] == [{"id": "VAT-01", "name": "Pack size", "value": "12"}]
    assert domain.detail(graph, "item", parent)["parentId"] == ""
    assert domain.detail(graph, "item", parent)["variants"][0]["id"] == child
    error = domain.dispatch(graph, "edit-item", dict(base, contextKind="item", contextId=parent, name="Cup", erpCode="CUP", parentId=child))
    assert "loop" in error["error"]


def test_variant_attribute_names_are_seeded_only_when_the_list_is_empty():
    graph = domain.normalize({})
    assert [entry["name"] for entry in graph["variant_attributes"]] == []
    made = domain.ensure_variant_attributes(graph)
    assert [entry["name"] for entry in graph["variant_attributes"]] == ["Customer", "Pack size", "Color"]
    assert made
    assert domain.ensure_variant_attributes(graph) == []


def test_the_floor_separates_running_idle_and_stopped():
    graph = domain.normalize({
        "machines": [
            {"id": "MCH-01", "name": "One", "status": "active"},
            {"id": "MCH-02", "name": "Two", "status": "active"},
            {"id": "MCH-03", "name": "Three", "status": "active"},
            {"id": "MCH-04", "name": "Arm", "status": "active", "attachedToId": "MCH-01"},
        ],
        "items": [{"id": "ITM-1", "name": "Cup", "type": "SFG", "status": "active"}],
        "molds": [{"id": "MLD-1", "name": "Mold", "cavities": 2, "status": "in use"}],
        "recipes": [{"id": "REC-1", "itemId": "ITM-1", "machineId": "MCH-01", "moldId": "MLD-1", "status": "approved", "cycle": 10}],
        "production_runs": [{"id": "RUN-1", "recipeId": "REC-1", "orderId": "PO-1", "startedAt": "2026-11-13T06:00:00Z", "status": "running"}],
        "production_orders": [{"id": "PO-1", "itemId": "ITM-1", "quantity": 100, "dueDate": "2026-11-14", "status": "released", "erpOrderNo": "SO-1"}],
        "stoppage_causes": [{"id": "CAU-1", "name": "Heater", "planned": False, "changeover": False, "status": "active"}],
        "stoppages": [{"id": "STP-1", "machineId": "MCH-02", "startedAt": "2026-11-13T07:00:00Z", "causeId": "CAU-1"}],
        "shifts": [{"id": "SHF-01", "name": "Morning", "start": "06:00", "end": "14:00", "status": "active"}],
        "personnel": [{"id": "PER-1", "name": "Ada", "status": "active"}],
    })
    graph["production_runs"][0]["shiftId"] = "SHF-01"
    graph["production_runs"][0]["operatorId"] = "PER-1"
    board = domain.floor_view(graph, "2026-11-13T08:30:00Z", "2026-11-13")
    by_name = {card["name"]: card for card in board["machines"]}
    assert by_name["One"]["state"] == "Running"
    assert by_name["One"]["item"] == "Cup"
    assert by_name["One"]["elapsed"] == "2h 30m"
    assert by_name["One"]["pph"] == 720
    assert by_name["Two"]["state"] == "Stopped"
    assert by_name["Three"]["state"] == "Idle"
    assert "Arm" not in by_name
    assert board["dueSoon"][0]["id"] == "PO-1"
    assert board["dueSoon"][0]["erp"] == "SO-1"
    assert board["noGood"][0]["id"] == "RUN-1"
    assert board["counts"] == {"running": 1, "idle": 1, "stopped": 1}
    assert board.get("demo") is False


def test_the_floor_uses_demo_preview_when_everything_is_idle():
    graph = domain.normalize({
        "machines": [
            {"id": "MCH-01", "name": "One", "status": "active"},
            {"id": "MCH-02", "name": "Two", "status": "active"},
        ],
    })
    board = domain.floor_view(graph, "2026-11-13T08:30:00Z", "2026-11-13")
    assert board.get("demo") is True
    assert (board["counts"]["running"] or 0) > 0


def test_export_writes_the_sku_column():
    text = exports.csv_bytes("item", [{"id": "ITM-1", "name": "Cup", "erp": "CUP", "status": "Active"}]).decode("utf-8")
    assert "SKU" in text.splitlines()[0]
    assert "CUP" in text
    book = exports.xlsx_bytes("item", [{"id": "ITM-1", "name": "Cup", "erp": "CUP", "status": "Active"}])
    assert book[:2] == b"PK"
