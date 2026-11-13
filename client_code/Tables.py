"""Tabulator lists. A row click opens the record."""

import anvil.server
from anvil import *
from tabulator.Tabulator import Tabulator

from craftify_library.CraftifyUtils import craftify_table as cf_table
from cyclops_app import Format, Layout, Nav

Tabulator.modules = set(Tabulator.modules) | {"Ajax"}


def _value(cell):
    try:
        return cell.getValue()
    except Exception:
        return None


def _data(cell):
    try:
        return dict(cell.getRow().getData())
    except Exception:
        return {}


def _empty():
    return '<span class="cy-empty">—</span>'


def _id(kind):
    def formatter(cell, **params):
        return Format.id_tag(kind, _value(cell))
    return formatter


def _status(cell, **params):
    data = _data(cell)
    return Format.status(data.get("status"), data.get("tone"))


def _pills(kind):
    def formatter(cell, **params):
        value = _value(cell)
        if isinstance(value, str):
            value = [value] if value else []
        return Format.pills(value or [], kind)
    return formatter


def _text(cell, **params):
    value = _value(cell)
    if value is None or value == "":
        return _empty()
    return Layout.esc(value)


def _clip(cell, **params):
    value = _value(cell)
    if value is None or value == "":
        return _empty()
    text = Layout.esc(value)
    return '<span class="cy-clip" title="%s">%s</span>' % (text, text)


_SHOWN = {}


def _shown(value, with_time):
    """The text a date cell shows, remembered so filtering a long list stays quick."""
    key = (value, with_time)
    if key not in _SHOWN:
        _SHOWN[key] = (Format.when(value, "") if with_time else Format.day(value, "")) if value else ""
    return _SHOWN[key]


def _when(cell, **params):
    value = _value(cell)
    shown = _shown(value, True)
    if not shown:
        return _clip(cell) if value else _empty()
    day, clock = shown.split(", ")
    return '<span class="cy-date">%s</span><span class="cy-time">%s</span>' % (Layout.esc(day), Layout.esc(clock))


def _day(cell, **params):
    shown = _shown(_value(cell), False)
    return '<span class="cy-date">%s</span>' % Layout.esc(shown) if shown else _empty()


def _matches_shown(with_time):
    def match(header, value, row, **params):
        return str(header or "").strip().lower() in _shown(value, with_time).lower()
    return match


def _when_col(title, field, width=150):
    return _col(title, field, width=width, formatter=_when, header_filter_func=_matches_shown(True))


def _day_col(title, field, width=120):
    return _col(title, field, width=width, formatter=_day, header_filter_func=_matches_shown(False))


def _suffix(unit):
    def formatter(cell, **params):
        value = _value(cell)
        if value is None or value == "":
            return _empty()
        return Layout.esc(Format.trim(value)) + unit
    return formatter


def _edit(cell, **params):
    return '<button type="button" class="cy-mini cy-row-edit">Edit</button>'


def _num(cell, **params):
    value = _value(cell)
    if value is None or value == "":
        return _empty()
    return Layout.esc(Format.trim(value))


def _machine_pill(cell, **params):
    value = _value(cell)
    if not value:
        return _empty()
    return '<span class="cy-pill cy-machine">%s</span>' % Layout.esc(value)


_NO_AUTOFILL = {"elementAttributes": {"autocomplete": "off", "name": "cy-filter"}}
_LOGS = ("stoppage", "run", "changeover")
_OPENS = {"summary": ("item", "id"), "changeover": ("run", "toRun")}


def _col(title, field, **extra):
    column = {"title": title, "field": field, "header_filter": True, "header_filter_params": dict(_NO_AUTOFILL)}
    column.update(extra)
    return column


def _num_col(title, field, width=96):
    return {"title": title, "field": field, "width": width, "hoz_align": "right", "sorter": "number", "formatter": _num}


def _list_col(title, field, width=130):
    return {"title": title, "field": field, "width": width, "header_filter": "list",
            "header_filter_params": dict(_NO_AUTOFILL, valuesLookup=True, clearable=True, sort="asc"), "header_filter_func": "="}


def _status_col(width=140):
    return dict(_list_col("Status", "status", width), formatter=_status)


def _machine_col(field="machine"):
    return {"title": "Machine", "field": field, "width": 130, "formatter": _machine_pill, "header_filter": True,
            "header_filter_params": dict(_NO_AUTOFILL)}


SETTING_COLUMNS = {
    "shift": lambda: [_col("Starts", "start", width=90, formatter=_text), _col("Ends", "end", width=90, formatter=_text)],
    "cause": lambda: [_list_col("Category", "category", 130), _list_col("Planned", "planned", 110), _list_col("Changeover", "changeover", 120)],
    "reason": lambda: [_list_col("Category", "category", 130)],
    "category": lambda: [_list_col("Item type", "typeLabel", 150), _list_col("Recipe role", "roleLabel", 140)],
    "machineType": lambda: [],
    "role": lambda: [_list_col("Runs machines", "runsMachines", 140)],
    "unit": lambda: [],
    "attribute": lambda: [],
    "person": lambda: [_list_col("Role", "roleLabel", 150), _col("Qualified on", "machines", min_width=220, formatter=_clip)],
}


def columns_for(kind, hide=()):
    if kind == "item":
        columns = [
            _col("ID", "id", width=112, formatter=_id("item")),
            _col("Item", "name", min_width=220, formatter=_text),
            _status_col(),
            _list_col("Type", "typeLabel", 130),
            _list_col("Category", "category", 130),
            _col("SKU", "erp", width=110, formatter=_text),
            _col("Product", "parent", min_width=160, formatter=_text),
            {"title": "Runs on", "field": "machines", "min_width": 150, "formatter": _pills("machine")},
            _num_col("Recipes", "recipes", 86),
            _num_col("Trial", "trial", 70),
            _num_col("Used in", "usedIn", 84),
            {"title": "Colors", "field": "colors", "min_width": 140, "formatter": _pills("colorant")},
        ]
    elif kind == "mold":
        columns = [
            _col("ID", "id", width=112, formatter=_id("mold")),
            _col("Mold", "name", min_width=220, formatter=_text),
            _status_col(),
            {"title": "Makes", "field": "items", "min_width": 180, "formatter": _pills("item")},
            {"title": "Runs on", "field": "machines", "min_width": 150, "formatter": _pills("machine")},
            _num_col("Recipes", "recipes", 86),
            _num_col("Cavities", "cavities", 90),
            _num_col("Shot (g)", "shot", 90),
            _col("Location", "location", width=120, formatter=_text),
        ]
    elif kind == "machine":
        columns = [
            _col("ID", "id", width=100, formatter=_id("machine")),
            _col("Machine", "name", width=170, formatter=_text),
            _status_col(),
            _list_col("Type", "type", 140),
            _col("Attached to", "attachedTo", width=130, formatter=_text),
            _col("EUROMAP", "euromap", width=120, formatter=_text),
            _num_col("Molds", "molds", 80),
            _num_col("Recipes", "recipes", 86),
            _col("Running now", "current", min_width=180, formatter=_text),
            _num_col("Changeover (min)", "changeover", 140),
        ]
    elif kind == "recipe":
        columns = [
            _col("ID", "id", width=112, formatter=_id("recipe")),
            _col("Item", "item", min_width=190, formatter=_text),
            _machine_col(),
            _col("Mold", "mold", width=110, formatter=_id("mold")),
            {"title": "Colors", "field": "colors", "min_width": 140, "formatter": _pills("colorant")},
            _num_col("Cycle (s)", "cycle"),
            _num_col("Pcs/h", "pph", 80),
            {"title": "Materials", "field": "materials", "min_width": 160, "formatter": _pills("base")},
            _list_col("Shares", "shares", 96),
            _status_col(),
        ]
    elif kind == "summary":
        columns = [
            _col("ID", "id", width=112, formatter=_id("item")),
            _col("Item", "name", min_width=200, formatter=_text),
            {"title": "Molds", "field": "molds", "min_width": 120, "formatter": _pills("mold")},
            {"title": "Machines", "field": "machines", "min_width": 140, "formatter": _pills("machine")},
            _num_col("Recipes", "recipes", 90),
            _num_col("Best cycle (s)", "cycle", 120),
            {"title": "Colors", "field": "colors", "min_width": 140, "formatter": _pills("colorant")},
            _status_col(),
        ]
    elif kind == "order":
        columns = [
            _col("ID", "id", width=110, formatter=_id("order")),
            _col("Item", "item", min_width=200, formatter=_text),
            _status_col(120),
            _num_col("Quantity", "quantity", 100),
            _num_col("Made", "made", 90),
            dict(_num_col("Done", "progress", 80), formatter=_suffix("%")),
            _day_col("Due", "due"),
            _col("ERP order", "erp", width=110, formatter=_text),
            _num_col("Runs", "runs", 70),
        ]
    elif kind == "run":
        columns = [
            _col("ID", "id", width=108, formatter=_id("run")),
            _when_col("Started", "start"),
            dict(_num_col("Hours", "hours", 82), formatter=_suffix(" h")),
            _machine_col(),
            _col("Item", "item", min_width=140, width_grow=3, formatter=_clip),
            _col("Order", "order", width=100, formatter=_text),
            _num_col("Good", "good", 86),
            dict(_num_col("Scrap", "scrapPct", 84), formatter=_suffix("%")),
            _num_col("Pcs/h", "pph", 80),
            dict(_num_col("Vs target", "performance", 100), formatter=_suffix("%")),
            _col("Operator", "operator", min_width=110, width_grow=1, formatter=_clip),
            _status_col(110),
        ]
    elif kind == "stoppage":
        columns = [
            _when_col("Stopped", "start"),
            _when_col("Restarted", "end"),
            dict(_num_col("Downtime", "hours", 104), formatter=_suffix(" h")),
            _machine_col(),
            _col("Item", "item", min_width=110, width_grow=1, formatter=_clip),
            _col("Cause", "cause", min_width=110, width_grow=1, formatter=_clip),
            _list_col("Category", "category", 110),
            _col("What was seen", "description", min_width=120, width_grow=3, formatter=_clip),
            _col("Fix", "fix", min_width=100, width_grow=2, formatter=_clip),
            _col("Reported by", "reportedBy", width=110, formatter=_clip),
            _status_col(118),
        ]
    elif kind == "changeover":
        columns = [
            _col("ID", "id", width=108, formatter=_text),
            _when_col("Started", "start"),
            dict(_num_col("Lost", "hours", 80), formatter=_suffix(" h")),
            _machine_col(),
            _col("From", "from", min_width=120, width_grow=2, formatter=_clip),
            _col("To", "to", min_width=120, width_grow=2, formatter=_clip),
            _list_col("Kind", "kind", 150),
            _list_col("Source", "source", 150),
            dict(_status_col(116), title="Confidence"),
            _col("How it was worked out", "basis", min_width=160, width_grow=4, formatter=_clip),
        ]
    elif kind in SETTING_COLUMNS:
        columns = [_col("ID", "id", width=100, formatter=_id("setting")), _col("Name", "name", min_width=220, formatter=_text)]
        columns += SETTING_COLUMNS[kind]()
        if kind != "machineType":
            columns.append(_status_col(120))
    else:
        columns = [
            _col("ID", "id", width=118, formatter=_id("lot")),
            _col("Lot", "number", width=120, formatter=_text),
            _col("Item", "item", min_width=200, formatter=_text),
            _list_col("Origin", "origin", 110),
            _num_col("Quantity", "quantity", 100),
            _col("Unit", "uom", width=70, formatter=_text, header_filter=False),
            _when_col("Received", "received"),
            _col("Run", "run", width=110, formatter=_text),
            _num_col("Used by", "used", 84),
            _status_col(120),
        ]
    hidden = set(hide or [])
    return [column for column in columns if column.get("field") not in hidden]


def _median_hours(cell, **params):
    value = _value(cell)
    if value is None or value == "":
        return _empty()
    return Layout.esc(Format.trim(value)) + " h"


def columns_perf_causes():
    return [
        _col("Cause", "cause", min_width=160, width_grow=2, formatter=_clip),
        _col("Group", "group", width=120, formatter=_text),
        _list_col("Kind", "kind", 110),
        _num_col("Stops", "count", 88),
        dict(_num_col("Hours", "hours", 88), formatter=_suffix(" h")),
        dict(_num_col("Share", "share", 88), formatter=_suffix("%")),
    ]


def columns_perf_changeover_kinds():
    return [
        _col("Kind", "label", min_width=160, width_grow=2, formatter=_text),
        _num_col("Changes", "count", 100),
        dict(_num_col("Lost", "hours", 88), formatter=_suffix(" h")),
        dict(_num_col("Median", "median", 100), formatter=_median_hours),
    ]


def columns_perf_changeover_machines():
    return [
        dict(_machine_col("machine"), min_width=140, width_grow=1),
        _num_col("Changes", "count", 100),
        dict(_num_col("Lost", "hours", 88), formatter=_suffix(" h")),
        dict(_num_col("Median", "median", 100), formatter=_median_hours),
    ]


def columns_perf_capacity():
    return [
        dict(_machine_col("machine"), min_width=140, width_grow=1),
        _num_col("Shifts run", "used", 110),
        dict(_num_col("Used", "pct", 88), formatter=_suffix("%")),
        _num_col("One-shift days", "oneShiftDays", 130),
        _num_col("Idle days", "idleDays", 100),
    ]


def report_height(count):
    if count <= 12:
        return None
    return "%dpx" % min(520, 40 * count + 48)


def mount_report(rows, columns, height=None, on_row=None, on_excel=None):
    """Read-only report table: sortable columns, no header filters, optional row action."""
    table = Tabulator()
    data = []
    for index, row in enumerate(rows or []):
        entry = dict(row)
        entry.setdefault("_row", "r%d" % index)
        data.append(entry)
    count = len(data)
    if height is None:
        height = report_height(count)
    use_page = count > 25
    table.options = {
        "pagination": use_page,
        "pagination_size": 25,
        "pagination_size_selector": [25, 50, 100] if use_page else False,
        "pagination_counter": "rows" if use_page else False,
        "layout": "fitColumns",
        "index": "_row",
        "placeholder": "No rows.",
    }
    if height:
        table.height = height
    table.columns = [{**column, "header_filter": False} for column in columns]
    table.data = data
    if on_row is not None:

        def on_row_click(sender, **event_args):
            row = event_args.get("row")
            if row is None:
                return
            try:
                on_row(dict(row.getData()))
            except Exception:
                pass

        table.set_event_handler("row_click", on_row_click)
    if on_excel is not None:
        cf_table.attach_excel_download(table, on_excel)
    return Layout.flat(table)


def mount(rows, kind, columns, height="640px", on_edit=None, edit_on_click=False, on_excel=None):
    """``on_edit(row_data)`` adds an Edit button to each row; the rest of the row still opens the record,
    unless ``edit_on_click`` (stoppages, which have no page of their own)."""
    table = Tabulator()
    if height:
        table.height = height
    table.options = {
        "pagination": True,
        "pagination_size": 25,
        "pagination_size_selector": [25, 50, 100, True],
        "pagination_counter": "rows",
        "layout": "fitColumns" if kind in _LOGS else "fitDataFill",
        "index": "id",
        "placeholder": "No rows match.",
    }
    cf_table.apply_table_theme(table)
    built = _with_edit(columns, on_edit)
    table.columns = cf_table.stamp_columns(built)
    table.data = rows or []
    _open_rows(table, kind, on_edit, edit_on_click)
    cf_table.attach_toolbar(table, remote=False)
    if on_excel is not None:
        cf_table.attach_excel_download(table, on_excel)
    return Layout.flat(table)


def _with_edit(columns, on_edit):
    if on_edit is None:
        return columns
    return list(columns) + [{"title": "", "field": "edit", "width": 62, "hoz_align": "center",
                             "header_sort": False, "formatter": _edit, "css_class": "cy-col-edit"}]


def _remote_column(column, fields):
    """A column as the server can page it: header filters and sorting only where the tables can answer them."""
    column = dict(column)
    field = column.get("field")
    for key in ("header_filter_func", "header_filter_params"):
        column.pop(key, None)
    column["header_sort"] = field in fields["sort"]
    if field in (fields.get("choices") or {}):
        column["header_filter"] = "list"
        column["header_filter_params"] = dict(_NO_AUTOFILL, values=fields["choices"][field], clearable=True)
    elif field in fields["filter"]:
        column["header_filter"] = "input"
        column["header_filter_params"] = dict(_NO_AUTOFILL)
        if field in cf_table.DATE_FIELDS or column.get("formatter") in (_when, _day):
            column["header_filter_placeholder"] = cf_table.DATE_FILTER_HINT
    else:
        column["header_filter"] = False
    return column


def _reply_value(response, key):
    try:
        return response[key]
    except Exception:
        return None


def mount_remote(kind, columns, fields, gap=None, on_reply=None, height="640px", on_edit=None, edit_on_click=False, on_excel=None):
    """A list read a page at a time from the ``/list/<kind>`` endpoint; ``on_reply(total, banner)`` sees each page."""
    table = Tabulator()
    if height:
        table.height = height

    def received(url, params, response):
        if on_reply is not None:
            banner = _reply_value(response, "banner")
            if banner:
                banner = {key: _reply_value(banner, key) for key in ("count", "title", "benefit")}
            on_reply(_reply_value(response, "last_row") or 0, banner)
        return response

    def failed(*error):
        Notification("The list could not be loaded. Sign in again if this keeps happening.", style="danger", timeout=5).show()

    table.options = {
        "pagination": True,
        "pagination_mode": "remote",
        "pagination_size": 25,
        "pagination_size_selector": [25, 50, 100],
        "pagination_counter": "rows",
        "sort_mode": "remote",
        "filter_mode": "remote",
        "ajaxURL": anvil.server.get_api_origin() + "/list/" + kind,
        "ajax_config": "POST",
        "ajax_content_type": "json",
        "ajax_params": {"gap": gap} if gap else {},
        "ajax_response": received,
        "header_filter_live_filter_delay": 500,
        "layout": "fitColumns" if kind in _LOGS else "fitDataFill",
        "index": "id",
        "placeholder": "No rows match.",
    }
    cf_table.apply_table_theme(table)
    built = _with_edit([_remote_column(column, fields) for column in columns], on_edit)
    table.columns = cf_table.stamp_columns(built, fields)
    _open_rows(table, kind, on_edit, edit_on_click)
    table.on("dataLoadError", failed)
    cf_table.attach_toolbar(table, remote=True)
    if on_excel is not None:
        cf_table.attach_excel_download(table, on_excel)
    return Layout.flat(table)


def _open_rows(table, kind, on_edit, edit_on_click):
    target, key = _OPENS.get(kind, (kind, "id"))

    def on_row(sender, **event_args):
        row = event_args.get("row")
        if row is None:
            return
        event = event_args.get("event")
        try:
            on_button = event is not None and event.target.closest(".cy-col-edit")
        except Exception:
            on_button = False
        if on_button or edit_on_click:
            if on_edit is not None:
                on_edit(dict(row.getData()))
            return
        try:
            data = dict(row.getData())
        except Exception:
            return
        if data.get(key) and target in Nav.SLUG:
            Nav.go(target, data[key])

    table.set_event_handler("row_click", on_row)
