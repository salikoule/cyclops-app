import json
from pathlib import Path

import domain

SEED = Path(__file__).resolve().parents[1] / "server_code" / "seed.json"


def plant():
    graph = {
        "products": [
            {"id": "PRD-0001", "name": "CAVE 11 lt", "erpCode": ""},
            {"id": "PRD-0002", "name": "ΚΑΠΑΚΙ CAVE 11 lt", "erpCode": "ERP-1"},
        ],
        "molds": [{"id": "MLD-0001", "name": "CAVE 11 lt", "productId": "PRD-0001"}],
        "presses": [{
            "id": "PRS-01",
            "name": "NOVA 130T",
            "board": {"mounted": "CAVE 11 lt", "location": "A1", "note": ""},
        }],
        "materials": [
            {"id": "MAT-001", "text": "J590K", "family": "RANDOM", "account": "910000307", "catalog": True},
            {"id": "MAT-002", "text": "ροή", "family": "", "account": "", "catalog": True},
            {"id": "MAT-003", "text": "Unused grade", "family": "RANDOM", "account": "1", "catalog": True},
        ],
        "colors": [{"id": "COL-001", "code": "10692", "name": "ΜΠΕΖ", "account": "920000032", "catalog": True}],
        "recipes": [
            {
                "id": "REC-0002",
                "legacyId": 2,
                "productId": "PRD-0001",
                "moldId": "MLD-0001",
                "pressId": "PRS-01",
                "temps": {"t6": "170", "t5": "174"},
                "cycle": "",
                "trial": True,
                "materialSlots": [{"slot": 1, "materialId": "MAT-001", "lot": ""}],
                "colorSlots": [{"slot": 1, "colorId": "COL-001", "lot": ""}],
            },
            {
                "id": "REC-0020",
                "legacyId": 20,
                "productId": "PRD-0001",
                "moldId": "MLD-0001",
                "pressId": "PRS-01",
                "temps": {"nozzle": "200", "t6": "200", "t5": "200", "t4": "210"},
                "cycle": "30",
                "trial": False,
                "materialSlots": [{"slot": 1, "materialId": "MAT-002", "lot": ""}],
                "colorSlots": [{"slot": 1, "colorId": "COL-001", "lot": ""}],
            },
            {
                "id": "REC-0021",
                "legacyId": 21,
                "productId": "PRD-0001",
                "moldId": "MLD-0001",
                "pressId": "PRS-01",
                "temps": {"nozzle": "200", "t6": "200", "t5": "200", "t4": "210"},
                "cycle": "28",
                "trial": False,
                "materialSlots": [{"slot": 1, "materialId": "MAT-001", "lot": "L1"}],
                "colorSlots": [{"slot": 1, "colorId": "COL-001", "lot": ""}],
            },
        ],
        "links": [{"lidId": "PRD-0002", "partId": "PRD-0001", "basis": "exact"}],
    }
    domain.normalize(graph)
    domain.reindex(graph)
    return graph


def test_defaults_and_kinds():
    graph = plant()
    lid = graph["_ix"]["product"]["PRD-0002"]
    assert lid["type"] == "lid"
    assert lid["lifecycle"] == "active"
    assert graph["_ix"]["material"]["MAT-001"]["kind"] == "resin"
    assert graph["_ix"]["material"]["MAT-002"]["kind"] == "additive"


def test_statuses_and_pieces_per_hour():
    graph = plant()
    index = graph["_ix"]
    assert domain.setup_status(graph, index["recipe"]["REC-0002"]) == "Trial row"
    assert domain.setup_status(graph, index["recipe"]["REC-0020"]) == "Cannot produce"
    assert domain.setup_status(graph, index["recipe"]["REC-0021"]) == "Active"
    assert domain.product_status(graph, index["product"]["PRD-0001"]) == "Incomplete"
    assert domain.product_status(graph, index["product"]["PRD-0002"]) == "Name only"
    assert domain.mold_status(graph, index["mold"]["MLD-0001"]) == "Incomplete"
    assert domain.press_status(graph, index["press"]["PRS-01"]) == "Mounted"
    assert domain.pieces_per_hour(index, index["recipe"]["REC-0021"]) is None
    index["mold"]["MLD-0001"]["cavities"] = 2
    assert domain.pieces_per_hour(index, index["recipe"]["REC-0021"]) == 257
    assert domain.pieces_per_hour(index, index["recipe"]["REC-0020"]) == 240


def test_gaps_and_variants():
    graph = plant()
    by_key = {item["key"]: item for item in domain.gaps(graph)}
    assert "PRD-0001" in by_key["no-erp"]["ids"]
    assert "PRD-0002" not in by_key["no-erp"]["ids"]
    assert "MLD-0001" in by_key["no-cavities"]["ids"]
    assert "REC-0020" in by_key["no-base"]["ids"]
    assert "REC-0002" in by_key["trial"]["ids"]
    assert "REC-0020" in by_key["dup-standard"]["ids"]
    assert "REC-0021" in by_key["dup-standard"]["ids"]
    assert "MAT-003" in by_key["mat-unused"]["ids"]
    assert "PRS-01" in by_key["no-changeover"]["ids"]
    variants = domain.variants_of(graph, graph["_ix"]["product"]["PRD-0001"])
    assert len(variants) == 1
    assert variants[0]["label"] == "ΜΠΕΖ"
    filtered = domain.list_view(graph, "recipe", "no-base")
    assert [row["id"] for row in filtered["rows"]] == ["REC-0020"]
    assert filtered["banner"]["count"] == 1


def test_edits_do_not_alias_clones_and_confirm_trials():
    graph = plant()
    created = domain.dispatch(graph, "new-product", {"name": "Bucket", "type": "part", "erp": "B-1"})
    assert created["redirect"]["code"] == "PRD-0003"
    assert graph["_ix"]["product"]["PRD-0003"]["erpCode"] == "B-1"

    cloned = domain.dispatch(graph, "clone-recipe", {"contextId": "REC-0021"})
    clone_id = cloned["redirect"]["code"]
    clone = graph["_ix"]["recipe"][clone_id]
    clone["materialSlots"][0]["lot"] = "CHANGED"
    assert graph["_ix"]["recipe"]["REC-0021"]["materialSlots"][0]["lot"] == "L1"

    confirmed = domain.dispatch(graph, "edit-recipe", {
        "contextId": "REC-0002",
        "temp_nozzle": "180",
        "temp_t6": "180",
        "temp_t5": "180",
        "temp_t4": "190",
        "temp_t3": "",
        "temp_t2": "",
        "temp_t1": "",
        "cycle": "22",
        "cooling": "",
        "screwRpm": "",
        "productLot": "LOT",
    })
    assert confirmed.get("error") is None
    recipe = graph["_ix"]["recipe"]["REC-0002"]
    assert recipe["trial"] is False
    assert recipe["cycle"] == "22"
    assert domain.setup_status(graph, recipe) == "Active"

    marked = domain.dispatch(graph, "set-standard", {"contextId": "REC-0021"})
    assert marked.get("error") is None
    assert graph["_ix"]["recipe"]["REC-0021"]["standard"] is True
    assert domain.setup_status(graph, graph["_ix"]["recipe"]["REC-0021"]) == "Standard"
    same = [item for item in domain.gaps(graph) if item["key"] == "dup-standard"][0]
    assert "REC-0021" not in same["ids"]
    assert "REC-0020" not in same["ids"]

    rejected = domain.dispatch(graph, "add-link", {"contextId": "PRD-0001", "other": "PRD-0001", "relation": "lid"})
    assert rejected["error"]


def test_seed_file_loads_the_workbook_clone():
    raw = json.loads(SEED.read_text(encoding="utf-8"))
    graph = {
        "products": raw["products"],
        "molds": raw["molds"],
        "presses": raw["presses"],
        "materials": raw["materials"],
        "colors": raw["colors"],
        "recipes": raw["recipes"],
        "links": raw["links"],
    }
    domain.normalize(graph)
    domain.reindex(graph)
    counted = domain.counts(graph)
    assert counted["products"] == 446
    assert counted["molds"] == 319
    assert counted["presses"] == 17
    assert counted["recipes"] == 501
    assert counted["materials"] == 66
    assert counted["colors"] == 75
    assert counted["links"] == 18
    assert len(domain.gaps(graph)) == 14
    overview = domain.overview(graph, "engineer")
    assert overview["presses"]
    assert all(item["count"] > 0 for item in overview["gaps"])
    detail = domain.detail(graph, "product", "PRD-0001")
    assert detail["name"] == "CAVE 11 lt"
    assert detail["missing"] is False
    assert domain.search(graph, "nova")
