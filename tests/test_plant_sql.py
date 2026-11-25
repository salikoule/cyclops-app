"""The plant schema: loaded rows, list pages, and ordinary writes."""

import pytest

import listing
import sql


def test_a_run_keeps_its_moment_and_its_recipe():
    row = sql.one(
        """
        SELECT r.started_at, rec.code AS recipe
        FROM plant.production_runs r
        JOIN plant.recipes rec ON rec.id = r.recipe_id
        WHERE r.started_at IS NOT NULL
        LIMIT 1
        """
    )
    assert row["recipe"]
    assert row["started_at"].tzinfo is not None


def test_a_recipe_keeps_its_settings_and_its_item():
    row = sql.one(
        """
        SELECT r.temps, i.code AS item
        FROM plant.recipes r
        JOIN plant.items i ON i.id = r.item_id
        WHERE r.temps IS NOT NULL
        LIMIT 1
        """
    )
    assert row["item"]
    assert row["temps"][0]["label"]


@pytest.mark.parametrize("kind", ["item", "recipe", "run", "mold"])
def test_list_page_reads_sql(kind):
    page = listing.page(kind, 1, 5)
    assert page["last_row"] > 0
    assert len(page["data"]) == 5


def test_a_name_filter_is_a_query():
    page = listing.page("machine", 1, 25, filters=[{"field": "name", "value": "e"}])
    assert "error" not in page
    assert page["last_row"] > 0


def test_a_page_is_a_slice_of_the_same_order():
    """The LIMIT page matches the old full read, including a status word and a calculated sort."""
    spec = listing.LISTS["item"]
    loaded = listing._found(spec, None, None, None)
    page = listing.page("item", 1, 5)
    assert page["last_row"] == len(loaded)
    assert [row["id"] for row in page["data"]] == [row["code"] for row in loaded[:5]]
    second = listing.page("item", 2, 5)
    assert [row["id"] for row in second["data"]] == [row["code"] for row in loaded[5:10]]

    active = [{"field": "status", "value": "Active"}]
    loaded_active = listing._found(spec, active, None, None)
    filtered = listing.page("item", 1, 5, filters=active)
    assert filtered["last_row"] == len(loaded_active)
    assert [row["id"] for row in filtered["data"]] == [row["code"] for row in loaded_active[:5]]
    assert all(row["status"] == "Active" for row in filtered["data"])

    runs = listing.LISTS["run"]
    by_rate = [{"field": "pph", "dir": "desc"}]
    loaded_runs = listing._found(runs, None, None, by_rate)
    rated = listing.page("run", 1, 5, sorters=by_rate)
    assert rated["last_row"] == len(loaded_runs)
    assert [row["id"] for row in rated["data"]] == [row["code"] for row in loaded_runs[:5]]


def test_an_hours_filter_is_the_number_the_cell_shows():
    import domain
    import records

    def shown(start, end):
        hours = domain.span_hours(records.moment_text(start), records.moment_text(end))
        if not hours:
            return None
        return round(hours, 1)

    rows = sql.query("SELECT started_at, ended_at FROM plant.production_runs")
    longer = sum(1 for row in rows if (shown(row["started_at"], row["ended_at"]) or 0) > 8)
    page = listing.page("run", 1, 25, filters=[{"field": "hours", "value": "cf|greaterThan|8"}])
    assert page["last_row"] == longer
    assert page["last_row"] > 0
    assert all(row["hours"] > 8 for row in page["data"])

    stops = sql.query("SELECT started_at, ended_at FROM plant.stoppages")
    blanks = sum(1 for row in stops if shown(row["started_at"], row["ended_at"]) is None)
    page = listing.page("stoppage", 1, 25, filters=[{"field": "hours", "value": "cf|blank"}])
    assert page["last_row"] == blanks


def test_search_and_downtime_stay_on_the_same_numbers():
    import domain
    import records
    import store

    assert store.search("a") == []
    hits = store.search("ca")
    assert hits
    assert len(hits) <= 16
    assert all(hit["kind"] in ("item", "mold", "machine", "recipe", "order", "run", "lot") for hit in hits)

    stops = sql.query("SELECT started_at, ended_at FROM plant.stoppages")
    expected = round(sum(
        domain.span_hours(records.moment_text(row["started_at"]), records.moment_text(row["ended_at"])) or 0
        for row in stops
    ), 1)
    assert store.downtime_hours() == expected


def test_writes_can_commit_and_a_failed_transaction_rolls_back():
    before = sql.count("units")
    try:
        with sql.transaction():
            sql.execute(
                "INSERT INTO plant.units (code, name, status) VALUES (%s, %s, %s)",
                ("__probe__", "probe", "active"),
            )
            raise RuntimeError("rollback")
    except RuntimeError:
        pass
    assert sql.count("units") == before

    made = sql.insert("units", {"code": "__probe__", "name": "probe", "status": "active"})
    try:
        sql.update("units", made.get_id(), {"code": "__probe__", "name": "probe-2", "status": "active"})
        again = sql.read("units", "t.code = %s", ("__probe__",))[0]
        assert again["name"] == "probe-2"
        sql.delete("units", made.get_id())
        assert sql.read("units", "t.code = %s", ("__probe__",)) == []
    finally:
        sql.delete_where("units", "code = %s", ("__probe__",))
    assert sql.count("units") == before
