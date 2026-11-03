"""Tabulator lists. A row click opens the record."""

from anvil import *
from tabulator.Tabulator import Tabulator

from cyclops_app import Format, Layout, Nav


def _value(cell):
    try:
        return cell.getValue()
    except Exception:
        return None


def _id(kind):
    def formatter(cell, **params):
        return Format.id_tag(kind, _value(cell))
    return formatter


def _status(cell, **params):
    try:
        data = dict(cell.getRow().getData())
    except Exception:
        data = {}
    return Format.status(data.get("status"), data.get("tone"))


def _pills(kind):
    def formatter(cell, **params):
        return Format.pills(_value(cell) or [], kind)
    return formatter


def _text(cell, **params):
    value = _value(cell)
    if value is None or value == "":
        return '<span class="cy-empty">—</span>'
    return Layout.esc(value)


def _wrap(cell, **params):
    value = _value(cell)
    if value is None or value == "":
        return '<span class="cy-empty">—</span>'
    return '<span class="cy-wrap">%s</span>' % Layout.esc(value)


def _num(cell, **params):
    value = _value(cell)
    if value is None or value == "":
        return '<span class="cy-empty">—</span>'
    return Layout.esc(Format.trim(value))


def _mold_id(cell, **params):
    value = _value(cell)
    if not value:
        return '<span class="cy-empty">—</span>'
    return Format.id_tag("mold", value)


def _press_pill(cell, **params):
    value = _value(cell)
    if not value:
        return '<span class="cy-empty">—</span>'
    return '<span class="cy-pill cy-press">%s</span>' % Layout.esc(value)


def _col(title, field, **extra):
    column = {"title": title, "field": field, "header_filter": True}
    column.update(extra)
    return column


def _num_col(title, field, width=96):
    return {"title": title, "field": field, "width": width, "hoz_align": "right", "sorter": "number", "formatter": _num}


def _status_col():
    return {
        "title": "Status",
        "field": "status",
        "width": 140,
        "formatter": _status,
        "header_filter": "list",
        "header_filter_params": {"valuesLookup": True, "clearable": True, "sort": "asc"},
        "header_filter_func": "=",
    }


def columns_for(kind, hide=()):
    if kind == "product":
        columns = [
            _col("ID", "id", width=112, formatter=_id("product")),
            _col("Product", "name", min_width=220, formatter=_text),
            _status_col(),
            _col("Type", "type", width=130, formatter=_text),
            _col("ERP code", "erp", width=110, formatter=_text),
            {"title": "Mold", "field": "mold", "width": 120, "formatter": _mold_id},
            {"title": "Runs on", "field": "presses", "min_width": 150, "formatter": _pills("press")},
            {"title": "Approved on", "field": "approved", "min_width": 150, "formatter": _pills("press")},
            _num_col("Variants", "variants", 90),
            _num_col("Recipes", "recipes", 86),
            _num_col("Trial", "trial", 70),
            {"title": "Raw materials", "field": "materials", "min_width": 160, "formatter": _pills("material")},
            {"title": "Colors", "field": "colors", "min_width": 140, "formatter": _pills("color")},
            _num_col("Links", "links", 70),
        ]
    elif kind == "mold":
        columns = [
            _col("ID", "id", width=112, formatter=_id("mold")),
            _col("Mold", "name", min_width=220, formatter=_text),
            _status_col(),
            _col("Makes", "product", min_width=180, formatter=_text),
            {"title": "Runs on", "field": "presses", "min_width": 150, "formatter": _pills("press")},
            _num_col("Recipes", "recipes", 86),
            _num_col("Cavities", "cavities", 90),
            _num_col("Shot (g)", "shot", 90),
            _col("Location", "location", width=120, formatter=_text),
        ]
    elif kind == "press":
        columns = [
            _col("ID", "id", width=100, formatter=_id("press")),
            _col("Press", "name", width=160, formatter=_text),
            _status_col(),
            _col("EUROMAP", "euromap", width=120, formatter=_text),
            _col("Robot", "robot", width=160, formatter=_text),
            _num_col("Molds", "molds", 80),
            _num_col("Recipes", "recipes", 86),
            _col("On the board", "board", min_width=200, formatter=_text),
            _num_col("Changeover (min)", "changeover", 140),
        ]
    elif kind == "recipe":
        columns = [
            _col("ID", "id", width=112, formatter=_id("recipe")),
            _col("Product", "product", min_width=190, formatter=_text),
            {"title": "Press", "field": "press", "width": 150, "formatter": _press_pill},
            {"title": "Colors", "field": "colors", "min_width": 140, "formatter": _pills("color")},
            _num_col("Cycle (s)", "cycle"),
            _num_col("Pcs/h", "pph", 80),
            {"title": "Raw materials", "field": "materials", "min_width": 160, "formatter": _pills("material")},
            _col("Last lot", "lot", width=100, formatter=_text),
            _status_col(),
        ]
    elif kind == "summary":
        columns = [
            _col("ID", "id", width=112, formatter=_id("product")),
            _col("Product", "name", min_width=200, formatter=_text),
            {"title": "Mold", "field": "mold", "width": 120, "formatter": _mold_id},
            {"title": "Presses", "field": "presses", "min_width": 140, "formatter": _pills("press")},
            _num_col("Recipes", "recipes", 90),
            _num_col("Best cycle (s)", "cycle", 120),
            {"title": "Colors", "field": "colors", "min_width": 140, "formatter": _pills("color")},
            _status_col(),
        ]
    elif kind == "issue":
        columns = [
            _col("Stopped", "start", width=140, formatter=_text),
            _col("Recipe", "id", width=112, formatter=_id("recipe")),
            _col("Product", "product", min_width=170, formatter=_text),
            {"title": "Press", "field": "press", "width": 130, "formatter": _press_pill, "header_filter": True},
            _col("Cause", "cause", min_width=240, formatter=_wrap),
            _col("Worker", "worker", width=170, formatter=_text),
            _col("Fix", "fix", min_width=240, formatter=_wrap),
            _col("Restarted", "end", width=140, formatter=_text),
            _num_col("Hours", "hours", 80),
            _status_col(),
        ]
    elif kind == "material":
        columns = [
            _col("ID", "id", width=100, formatter=_id("material")),
            _col("Material", "text", min_width=180, formatter=_text),
            _status_col(),
            {"title": "Type", "field": "kind", "width": 110, "header_filter": "list", "header_filter_params": {"valuesLookup": True, "clearable": True}},
            _col("Supplier", "supplier", width=140, formatter=_text),
            _col("Family", "family", width=120, formatter=_text),
            _num_col("MFI", "mfi", 70),
            _col("Accounting", "account", width=130, formatter=_text),
            _num_col("Recipes", "recipes", 86),
            _num_col("Products", "products", 90),
        ]
    else:
        columns = [
            _col("ID", "id", width=100, formatter=_id("color")),
            _col("Color", "name", width=140, formatter=_text),
            _status_col(),
            _col("Label code", "code", width=120, formatter=_text),
            _col("Label", "label", min_width=220, formatter=_text),
            _col("Accounting", "account", width=130, formatter=_text),
            _num_col("Recipes", "recipes", 86),
            _num_col("Products", "products", 90),
        ]
    hidden = set(hide or [])
    return [column for column in columns if column.get("field") not in hidden]


def mount(rows, kind, columns, height="640px"):
    table = Tabulator()
    table.height = height
    table.options = {
        "pagination": True,
        "pagination_size": 25,
        "pagination_size_selector": [25, 50, 100, True],
        "pagination_counter": "rows",
        "layout": "fitDataFill",
        "index": "key" if kind == "issue" else "id",
        "placeholder": "No rows match.",
    }
    table.columns = columns
    table.data = rows or []
    target = "recipe" if kind == "issue" else kind

    def on_row(sender, **event_args):
        row = event_args.get("row")
        if row is None:
            return
        try:
            data = dict(row.getData())
        except Exception:
            return
        code = data.get("id")
        if code:
            Nav.go(target, code)

    table.set_event_handler("row_click", on_row)
    return Layout.flat(table)
