import domain
import records
import seed_data


def _ref(table, code):
    return (table, code)


def _code_of(table, linked):
    return linked[1]


def _seed():
    return domain.normalize({table: seed_data.load().get(table) or [] for table in records.ORDER})


def test_every_record_round_trips_through_its_row():
    plant = _seed()
    for table in records.ORDER:
        for item in plant[table]:
            row = records.to_row(table, item, _ref)
            back = records.to_item(table, row, _code_of)
            for child, _, _, key, _ in records.CHILDREN_OF.get(table, ()):
                back[key] = [records.child_item(child, line, _code_of) for line in records.child_rows(child, item, None, _ref)]
            want = {key: value for key, value in item.items() if key in back}
            assert back == want, (table, item["id"])


def test_moments_are_utc_and_bad_ones_are_blank():
    moment = records.parse_moment("2026-05-25T19:00:00Z")
    assert records.moment_text(moment) == "2026-05-25T19:00:00Z"
    assert records.parse_moment("25/05/2026") is None
    assert records.parse_moment("") is None


def test_numbers_read_like_the_setter_writes_them():
    assert records.number("5,5") == 5.5
    assert records.number("12") == 12
    assert records.number("") is None
    assert records.number("abc") is None
    assert records.number_text(30.0) == "30"


def test_recipe_settings_keep_text_and_numbers():
    item = {"id": "REC-1", "temps": {"nozzle": "210/195", "t1": "180"}, "settings": [{"label": "Hold pressure", "value": "450"}],
            "cooling": "8", "screwRpm": "", "px": "", "py": "", "printPieces": "", "printTotal": ""}
    row = records.to_row("recipes", item, _ref)
    assert {"label": "Nozzle", "value": "210/195"} in row["temps"]
    assert {"label": "T1", "value": 180} in row["temps"]
    back = records.to_item("recipes", row, _code_of)
    assert back["temps"]["nozzle"] == "210/195" and back["temps"]["t1"] == "180"
    assert back["cooling"] == "8"
    assert back["settings"] == [{"label": "Hold pressure", "value": "450"}]


def test_tables_only_link_to_tables_written_before_them():
    seen = set()
    for table, columns in records.TABLES:
        for column, _, kind in columns:
            if isinstance(kind, tuple) and column not in records.LATE.get(table, ()):
                assert kind[1] in seen, (table, column)
        seen.add(table)
