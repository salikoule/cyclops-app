import copy

import domain
import records
import seed_data

KINDS = ("products", "molds", "presses", "materials", "colors", "recipes", "links", "workers")


def _ref(table, code):
    return code


def _round_trip(plant):
    """Every record through its row writer and back, with links standing in as codes."""
    mold_product = {item["id"]: item["productId"] for item in plant["molds"]}
    names = {item["id"]: item["name"] for item in plant["products"]}
    back = {
        "workers": [records.worker_row(name)["name"] for name in plant["workers"]],
        "materials": [records.material_item(records.material_row(item, _ref)) for item in plant["materials"]],
        "colors": [records.color_item(records.color_row(item, _ref)) for item in plant["colors"]],
        "products": [],
        "molds": [],
        "presses": [],
        "recipes": [],
        "links": [],
    }
    for item in plant["products"]:
        row = dict(records.product_row(item, _ref), **records.product_lid_row(item, _ref))
        back["products"].append(records.product_item(row, row["approved_presses"], row["lid"]))
    for item in plant["molds"]:
        row = records.mold_row(item, _ref)
        back["molds"].append(records.mold_item(row, row["product"]))
    for item in plant["presses"]:
        row = dict(records.press_row(item, _ref), **records.press_board_row(item, _ref))
        back["presses"].append(records.press_item(row, row["mounted_product"], names))
    for item in plant["recipes"]:
        row = records.recipe_row(item, _ref)
        recipe = records.recipe_item(row, row["mold"], mold_product.get(row["mold"]), row["press"])
        recipe["materialSlots"] = [records.material_slot_item(slot, slot["material"]) for slot in records.material_slot_rows(item, row["code"], _ref)]
        recipe["colorSlots"] = [records.color_slot_item(slot, slot["color"]) for slot in records.color_slot_rows(item, row["code"], _ref)]
        recipe["issues"] = [records.stoppage_item(log, log["worker"]) for log in records.stoppage_rows(item, row["code"], _ref)]
        recipe["runs"] = [records.run_item(log, log["operator"]) for log in records.run_rows(item, row["code"], _ref)]
        back["recipes"].append(recipe)
    return back


def _comparable(plant):
    plain = {kind: copy.deepcopy(plant.get(kind) or []) for kind in KINDS}
    for product in plain["products"]:
        product.pop("moldId", None)
    plain["workers"] = sorted(plain["workers"])
    return plain


def test_every_workbook_value_survives_the_tables():
    seed = seed_data.load()
    plant = domain.normalize({kind: seed.get(kind) or [] for kind in KINDS})
    expected = _comparable(plant)
    actual = _comparable(domain.normalize(_round_trip(plant)))
    for kind in KINDS:
        assert len(actual[kind]) == len(expected[kind]), kind
        for want, got in zip(expected[kind], actual[kind]):
            assert got == want, (kind, want.get("id") if isinstance(want, dict) else want)


def test_numbers_are_stored_as_numbers_and_odd_text_is_kept():
    item = {"id": "REC-1", "temps": {"t1": "210/195", "t2": "245", "t5": "-"}, "cycle": "48.19", "cooling": "5,5",
            "printPieces": "10+22", "settings": [{"label": "Hold time (s)", "value": "6"}]}
    row = records.recipe_row(item, _ref)
    assert row["temp_2"] == 245 and row["cycle_s"] == 48.19
    assert row["temp_1"] is None and row["temp_5"] is None and row["print_pieces"] is None
    assert row["cooling_s"] == 5.5
    assert row["as_written"] == {"temp_1": "210/195", "temp_5": "-", "cooling_s": "5,5", "print_pieces": "10+22"}


def test_injection_settings_are_one_ordered_list_on_the_recipe():
    item = {"id": "REC-1", "settings": [{"label": "Hold time (s)", "value": "6"}, {"label": "Hold pressure", "value": "60/55"},
                                        {"label": "Nozzle stroke (Arburg)", "value": "12.5"}, {"label": "Hold speed", "value": ""}]}
    row = records.recipe_row(item, _ref)
    assert row["injection"] == [{"label": "Hold time (s)", "value": 6}, {"label": "Hold pressure", "value": "60/55"},
                                {"label": "Nozzle stroke (Arburg)", "value": 12.5}]
    assert records.recipe_item(row, None, None, None)["settings"] == [
        {"label": "Hold time (s)", "value": "6"}, {"label": "Hold pressure", "value": "60/55"},
        {"label": "Nozzle stroke (Arburg)", "value": "12.5"}]
    assert records.recipe_row({"id": "REC-2"}, _ref)["injection"] is None


def test_recipe_settings_drop_the_copies_of_recipe_fields():
    plant = domain.normalize({"recipes": [{"id": "REC-1", "cycle": "30", "settings": [
        {"label": "Cycle time (s)", "value": "30"}, {"label": "Hold pressure", "value": "25"}]}]})
    assert plant["recipes"][0]["settings"] == [{"label": "Hold pressure", "value": "25"}]


def test_lids_are_a_link_on_the_part():
    plant = domain.normalize({"products": [{"id": "PRD-0001", "name": "CAVE"}, {"id": "PRD-0002", "name": "ΚΑΠΑΚΙ CAVE"}],
                              "links": [{"lidId": "PRD-0002", "partId": "PRD-0001", "basis": "exact"}]})
    part = plant["products"][0]
    assert (part["lidId"], part["lidBasis"]) == ("PRD-0002", "exact")
    assert plant["links"] == [{"lidId": "PRD-0002", "partId": "PRD-0001", "basis": "exact"}]
    assert records.product_lid_row(part, _ref) == {"lid": "PRD-0002"}
    assert records.product_row(plant["products"][1], _ref)["lid_basis"] == ""


def test_read_columns_match_the_row_writers():
    press = records.press_row({"id": "PRS-01"}, _ref)
    product = records.product_row({"id": "PRD-0001"}, _ref)
    assert set(records.PRESS_COLUMNS) == set(press)
    assert set(records.PRODUCT_COLUMNS) == set(product)


def test_a_board_entry_survives_when_its_product_is_not_loaded():
    plant = domain.normalize({"presses": [{"id": "PRS-01", "board": {"mountedId": "PRD-0009", "mounted": "CAVE"}}]})
    assert plant["presses"][0]["board"]["mountedId"] == "PRD-0009"


def test_new_codes_count_codes_that_are_not_loaded():
    graph = {"products": [{"id": "PRD-0002"}], "codes": {"products": ["PRD-0001", "PRD-0446"]}}
    assert domain.new_code(graph, "products", "PRD", 4) == "PRD-0447"


def test_board_links_the_mounted_product():
    plant = domain.normalize({"products": [{"id": "PRD-0001", "name": "CAVE 11 lt"}],
                              "presses": [{"id": "PRS-01", "board": {"mounted": "cave 11 LT"}}]})
    board = plant["presses"][0]["board"]
    assert board["mountedId"] == "PRD-0001" and board["mounted"] == "CAVE 11 lt"
