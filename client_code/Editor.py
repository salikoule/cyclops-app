"""Record editors in a side drawer. Field values go to cyclops_apply as strings."""

from datetime import datetime

from anvil import *
import anvil.tables as tables
import anvil.tables.query as q
from anvil.tables import app_tables
import anvil.js
from craftify_library.CraftifyUtils import dialogs, drawer
from craftify_library.CustomComponents.TimePicker import TimePicker

from cyclops_app import Data, Layout

WIDE = ("area", "checks", "datetime")
LOGS = ("issue", "run")
_REMOVE = {"issue": ("remove-issue", "Delete this stoppage?", "The record of this stop and its fix is removed from the recipe."),
           "run": ("remove-run", "Delete this run?", "The pieces, scrap, and settings logged for this run are removed.")}


def _text(value):
    if value is None:
        return ""
    return str(value)


def _as_date(value):
    try:
        return datetime.strptime(str(value or "")[:10], "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return None


class _Moment:
    """A day picker and a time box side by side. Picking a day needs no Apply, and the time stays optional."""

    def __init__(self, date_text, time_text):
        self.day = DatePicker(format="%d %b %Y", date=_as_date(date_text), pick_time=False, placeholder="Not set")
        self.clock = TimePicker(time=str(time_text or "").strip().replace(".", ":"), placeholder="HH:MM")
        self.panel = Layout.grid("minmax(0, 1fr) 120px", self.day, self.clock)

    def parts(self):
        return (self.day.date.isoformat() if self.day.date else ""), (self.clock.time or "")

    def set_event_handler(self, name, handler):
        self.day.set_event_handler(name, handler)
        self.clock.set_event_handler(name, handler)


class _Checks:
    def __init__(self, options, selected):
        chosen = set(selected or [])
        self.boxes = []
        self.panel = Layout.flat(FlowPanel(spacing="small", align="left"))
        for option in options:
            box = CheckBox(text=option.get("label") or "", checked=option.get("value") in chosen)
            box.tag.value = option.get("value")
            self.boxes.append(box)
            self.panel.add_component(Layout.flat(box))

    def value(self):
        return ",".join(box.tag.value for box in self.boxes if box.checked)


def _widget(field):
    kind = field.get("type") or "text"
    if kind == "select":
        options = field.get("options") or []
        widget = DropDown(items=[(opt.get("label") or "", opt.get("value")) for opt in options])
        allowed = [opt.get("value") for opt in options]
        wanted = field.get("value")
        if wanted in allowed:
            widget.selected_value = wanted
        elif allowed:
            widget.selected_value = allowed[0]
        return widget, widget
    if kind == "checks":
        checks = _Checks(field.get("options") or [], field.get("value"))
        return checks, checks.panel
    if kind == "area":
        widget = TextArea(text=_text(field.get("value")), height=field.get("height") or 88)
        return widget, widget
    if kind == "date":
        widget = DatePicker(format="%d %b %Y", date=_as_date(field.get("value")), pick_time=False)
        return widget, widget
    if kind == "datetime":
        moment = _Moment(field.get("date"), field.get("time"))
        return moment, moment.panel
    widget = TextBox(text=_text(field.get("value")), placeholder=field.get("placeholder") or "")
    if kind == "number":
        widget.type = "number"
    return widget, widget


def _read(widget):
    if isinstance(widget, _Checks):
        return widget.value()
    if isinstance(widget, DropDown):
        return widget.selected_value or ""
    if isinstance(widget, DatePicker):
        picked = widget.date
        return picked.isoformat() if picked else ""
    if isinstance(widget, (TextBox, TextArea)):
        return widget.text or ""
    return _text(widget)


def _order(first, then, box, field):
    """Show a reversed pair (``then`` before ``first``) in red."""
    hint = box.dom_nodes["hint"]
    usual = field.get("hint") or ""
    root = hint.parentElement

    def check(**event_args):
        (start_day, start_time), (end_day, end_time) = first.parts(), then.parts()
        reversed_pair = bool(start_day and end_day and (
            end_day < start_day or (end_day == start_day and start_time and end_time and end_time < start_time)))
        hint.textContent = field.get("after_error") if reversed_pair else usual
        if reversed_pair:
            root.classList.add("is-bad")
        else:
            root.classList.remove("is-bad")

    first.set_event_handler("change", check)
    then.set_event_handler("change", check)
    check()


def _follow(parent, child, groups, empty):
    """Refill ``child`` with ``groups[parent value]`` whenever the parent dropdown changes."""
    def refill(**event_args):
        options = groups.get(parent.selected_value) or []
        child.items = [(opt.get("label") or "", opt.get("value")) for opt in options] or [(empty, "")]
        child.selected_value = options[0].get("value") if options else ""

    parent.set_event_handler("change", refill)
    refill()


_OPEN = {"drawer": None}


def show(title, fields, on_save, hint="", eyebrow="", save_text="Save", width=520, on_delete=None):
    """Open a drawer with ``fields``. ``on_save(payload, close)`` and ``on_delete(close)`` return an error string or None."""
    if _OPEN["drawer"] is not None and _OPEN["drawer"].is_open:
        if not _OPEN["drawer"].close(force=False):
            return _OPEN["drawer"]
    widgets = {}
    moments = {}
    rows = []
    short = []

    def flush():
        if short:
            rows.append(Layout.grid("repeat(auto-fill, minmax(200px, 1fr))", *short))
            del short[:]

    for field in fields:
        if field.get("type") == "hidden":
            widgets[field["name"]] = _text(field.get("value"))
            continue
        widget, view = _widget(field)
        widgets[field["name"]] = widget
        box = Layout.field(field["label"], view, hint=field.get("hint") or "")
        if field.get("type") == "datetime":
            moments[field["name"]] = (field, box)
        if (field.get("type") or "text") in WIDE or field.get("wide"):
            flush()
            rows.append(box)
        else:
            short.append(box)
    flush()
    for field in fields:
        if field.get("follows") in widgets:
            _follow(widgets[field["follows"]], widgets[field["name"]], field.get("groups") or {}, field.get("empty") or "")
    error = Layout.html('<p class="bc-note bc-note-warn cy-form-error" anvil-name="msg"></p>')
    content = Layout.stack(error, *rows)
    for name, (field, box) in moments.items():
        if field.get("after") in widgets:
            _order(widgets[field["after"]], widgets[name], box, field)

    def values():
        out = {}
        for name, widget in widgets.items():
            if name not in moments:
                out[name] = _read(widget)
                continue
            day_key, time_key = moments[name][0]["keys"]
            out[day_key], out[time_key] = widget.parts()
        return out

    initial = values()
    holder = {"drawer": None}
    save_button = Layout.button(save_text, primary=True)
    cancel_button = Layout.button("Cancel")

    def close(force=True):
        if holder["drawer"] is not None:
            holder["drawer"].close(force=force)

    def save(**event_args):
        error.dom_nodes["msg"].textContent = ""
        error.dom_nodes["msg"].classList.remove("is-on")
        save_button.enabled = False
        try:
            problem = on_save(values(), close)
        finally:
            save_button.enabled = True
        if problem:
            error.dom_nodes["msg"].textContent = problem
            error.dom_nodes["msg"].classList.add("is-on")

    save_button.set_event_handler("click", save)
    cancel_button.set_event_handler("click", lambda **e: close(force=False))
    footer = (cancel_button, save_button)
    if on_delete is not None:
        def delete(**event_args):
            problem = on_delete(close)
            if problem:
                error.dom_nodes["msg"].textContent = problem
                error.dom_nodes["msg"].classList.add("is-on")

        footer = (Layout.button("Delete", delete, danger=True),) + footer
    holder["drawer"] = drawer.open(
        content,
        host=get_open_form(),
        title=title,
        subtitle=hint,
        eyebrow=eyebrow,
        footer=footer,
        width=width,
        confirm_close=drawer.discard_check(lambda: values() != initial),
    )
    _OPEN["drawer"] = holder["drawer"]
    return holder["drawer"]


def _blank(label):
    return {"value": "", "label": label}


def open_editor(screen, action, extra=None):
    extra = extra or {}
    spec = _spec(screen, action, extra)
    if spec is None:
        return False
    title, fields, hint = spec[:3]
    save_text = spec[3] if len(spec) > 3 else "Save"
    eyebrow = (screen.data or {}).get("id") or ""
    on_save = lambda payload, close: screen.apply(action, payload, close)
    on_delete = None
    row = extra.get("row") or {}
    if screen.kind in LOGS or row or action in ("add-issue", "add-run"):
        eyebrow = row.get("id") or eyebrow

        def on_save(payload, close):
            recipe = row.get("id") or payload.get("recipe") or (screen.code if screen.kind == "recipe" else "")
            if not recipe:
                return "Choose the recipe that was running."
            return screen.apply(action, dict(payload, contextKind="recipe", contextId=recipe), close)

    if row and action[5:] in _REMOVE:
        remove, question, detail = _REMOVE[action[5:]]

        def on_delete(close):
            if not dialogs.confirm(detail, title=question, confirm_text="Delete", danger=True):
                return None
            return screen.apply(remove, {"contextKind": "recipe", "contextId": row.get("id"), "index": row.get("index")}, close)

    show(title, fields, on_save, hint, eyebrow=eyebrow, save_text=save_text, on_delete=on_delete)
    return True


def _worker_options(workers, current):
    options = sorted(workers or [], key=lambda opt: (opt.get("label") or opt.get("value") or "").lower())
    if current and current not in [opt.get("value") for opt in options]:
        options.append({"label": current, "value": current})
    return [{"label": "Not recorded", "value": ""}] + options


def _now_rounded():
    now = datetime.now()
    return now.strftime("%Y-%m-%d"), "%02d:%02d" % (now.hour, now.minute - now.minute % 5)


def _shift_at(time_text):
    try:
        hour = int(str(time_text or "")[:2])
    except ValueError:
        return ""
    return "morning" if 6 <= hour < 14 else ("afternoon" if 14 <= hour < 22 else "night")


def _job_fields(choices):
    return [
        {"name": "press", "label": "Press", "type": "select", "options": [_blank("Choose a press")] + (choices.get("presses") or [])},
        {"name": "recipe", "label": "Recipe that was running", "type": "select", "options": [], "follows": "press", "wide": True,
         "groups": choices.get("recipesByPress") or {}, "empty": "Choose a press first"},
    ]


def _run_fields(run, choices):
    start_date, start_time = run.get("startDate"), run.get("startTime")
    if not run:
        start_date, start_time = _now_rounded()
    return [
        {"name": "start", "label": "Started", "type": "datetime", "keys": ("startDate", "startTime"), "date": start_date, "time": start_time},
        {"name": "end", "label": "Ended", "type": "datetime", "keys": ("endDate", "endTime"), "date": run.get("endDate"), "time": run.get("endTime"),
         "after": "start", "after_error": "The end is before the start.", "hint": "Leave empty while the job is still running."},
        {"name": "shift", "label": "Shift", "type": "select", "options": [_blank("Not recorded")] + (choices.get("shifts") or []),
         "value": run.get("shift") if run else _shift_at(start_time)},
        {"name": "operator", "label": "Operator", "type": "select", "options": _worker_options(choices.get("workers") or [], run.get("operator")), "value": run.get("operator") or ""},
        {"name": "good", "label": "Good pieces", "type": "number", "value": run.get("good")},
        {"name": "scrap", "label": "Scrap pieces", "type": "number", "value": run.get("scrap")},
        {"name": "scrapReason", "label": "Scrap reason", "value": run.get("scrapReason"), "placeholder": "short shots, flash, streaks…"},
        {"name": "cycle", "label": "Actual cycle (s)", "type": "number", "value": run.get("cycle"), "placeholder": "from the press display"},
        {"name": "cavities", "label": "Cavities running", "type": "number", "value": run.get("cavities"), "placeholder": "blocked ones excluded"},
        {"name": "lot", "label": "Product lot", "value": run.get("lot"), "placeholder": "printed on the boxes, e.g. 060526"},
        {"name": "order", "label": "Order / ERP no.", "value": run.get("order")},
        {"name": "notes", "label": "Notes", "type": "area", "value": run.get("notes"), "height": 64},
    ]


def _issue_fields(issue, workers):
    now = datetime.now()
    start_date, start_time = issue.get("startDate"), issue.get("startTime")
    if not issue:
        start_date, start_time = now.strftime("%Y-%m-%d"), "%02d:%02d" % (now.hour, now.minute - now.minute % 5)
    return [
        {"name": "start", "label": "Stopped at", "type": "datetime", "keys": ("startDate", "startTime"), "date": start_date, "time": start_time},
        {"name": "end", "label": "Restarted at", "type": "datetime", "keys": ("endDate", "endTime"), "date": issue.get("endDate"), "time": issue.get("endTime"),
         "after": "start", "after_error": "The restart is before the stop.", "hint": "Leave empty while the press is still down."},
        {"name": "worker", "label": "Reported by", "type": "select", "options": _worker_options(workers, issue.get("worker")), "value": issue.get("worker") or ""},
        {"name": "cause", "label": "What stopped it", "type": "area", "value": issue.get("cause")},
        {"name": "fix", "label": "What was done", "type": "area", "value": issue.get("fix")},
    ]


def _spec(screen, action, extra):
    choices = Data.choices()
    data = screen.data or {}
    if action == "new-product":
        return ("New product", [
            {"name": "name", "label": "Name"},
            {"name": "type", "label": "Type", "type": "select", "options": choices.get("types") or [], "value": "part"},
            {"name": "erp", "label": "ERP code"},
        ], "", "Create product")
    if action == "new-mold":
        return ("New mold", [
            {"name": "name", "label": "Mold name"},
            {"name": "product", "label": "Makes", "type": "select", "options": [_blank("Choose a product")] + (choices.get("products") or [])},
            {"name": "cavities", "label": "Cavities", "type": "number"},
            {"name": "shot", "label": "Shot weight (g)", "type": "number"},
        ], "", "Create mold")
    if action == "new-press":
        return ("New press", [
            {"name": "name", "label": "Name"},
            {"name": "euromap", "label": "EUROMAP class"},
            {"name": "changeover", "label": "Changeover (min)", "type": "number"},
        ], "", "Create press")
    if action == "new-material":
        return ("New raw material", [
            {"name": "text", "label": "Grade"},
            {"name": "kind", "label": "Type", "type": "select", "options": choices.get("kinds") or [], "value": "resin"},
            {"name": "supplier", "label": "Supplier"},
            {"name": "family", "label": "Family"},
            {"name": "account", "label": "Accounting code"},
        ], "Only resin and regrind count as a base material. A setup with additives or colors alone is flagged Cannot produce.", "Create material")
    if action == "new-color":
        return ("New color", [
            {"name": "name", "label": "Color"},
            {"name": "code", "label": "Label code"},
            {"name": "account", "label": "Accounting code"},
        ], "", "Create color")
    if action == "edit-product":
        return ("Edit product", [
            {"name": "name", "label": "Name", "value": data.get("name")},
            {"name": "type", "label": "Type", "type": "select", "options": choices.get("types") or [], "value": data.get("type")},
            {"name": "lifecycle", "label": "Lifecycle", "type": "select", "options": choices.get("lifecycles") or [], "value": data.get("lifecycle")},
            {"name": "erpCode", "label": "ERP code", "value": data.get("erpCode"), "placeholder": "from the ERP"},
            {"name": "notes", "label": "Notes", "type": "area", "value": data.get("notes")},
        ], "The ERP code is what lets orders and stock meet this record. Status is otherwise computed from the setups.")
    if action == "set-approved":
        return ("Approved presses", [
            {"name": "presses", "label": "This product may run on", "type": "checks", "options": choices.get("presses") or [], "value": data.get("approvedPressIds") or []},
        ], "The product sheet's press columns. A press that is approved but has no recipe shows up as a gap for the planner.")
    if action == "edit-mold":
        mold = data if screen.kind == "mold" else (data.get("mold") or None)
        if not mold:
            Notification("This product has no mold yet. Add a recipe and one will be created.", style="warning", timeout=4).show()
            return None
        return ("Edit mold %s" % mold.get("id"), [
            {"name": "cavities", "label": "Cavities", "type": "number", "value": mold.get("cavities")},
            {"name": "shotWeight", "label": "Shot weight (g)", "type": "number", "value": mold.get("shotWeight")},
            {"name": "location", "label": "Location", "value": mold.get("location")},
            {"name": "status", "label": "Status", "type": "select", "options": choices.get("moldStatuses") or [], "value": mold.get("moldStatus") or mold.get("status") or "in use"},
        ], "Cavities turn every cycle time of this mold into pieces per hour. Shot weight turns a run into kilograms of resin.")
    if action == "edit-press":
        return ("Edit press %s" % data.get("name"), [
            {"name": "lifecycle", "label": "Lifecycle", "type": "select", "options": choices.get("lifecycles") or [], "value": data.get("lifecycle")},
            {"name": "changeoverMin", "label": "Changeover (min)", "type": "number", "value": data.get("changeoverMin")},
            {"name": "mounted", "label": "On the board", "value": data.get("mounted"), "placeholder": "product name"},
            {"name": "location", "label": "Board note", "value": data.get("location")},
            {"name": "euromap", "label": "EUROMAP class", "value": data.get("euromap")},
            {"name": "serial", "label": "Serial", "value": data.get("serial")},
            {"name": "robot", "label": "Robot", "value": data.get("robot")},
            {"name": "robotSerial", "label": "Robot serial", "value": data.get("robotSerial")},
            {"name": "robotYear", "label": "Robot year", "value": data.get("robotYear")},
        ], "Changeover minutes let the planner sequence mold and color changes.")
    if action == "edit-recipe":
        temps = data.get("temps") or {}
        fields = [{"name": "temp_" + key, "label": label + " °C", "value": temps.get(key)} for key, label in (
            ("nozzle", "Nozzle"), ("t6", "T6"), ("t5", "T5"), ("t4", "T4"), ("t3", "T3"), ("t2", "T2"), ("t1", "T1"),
        )]
        fields.extend([
            {"name": "cycle", "label": "Cycle (s)", "value": data.get("cycle")},
            {"name": "cooling", "label": "Cooling (s)", "value": data.get("cooling")},
            {"name": "screwRpm", "label": "Screw (rpm)", "value": data.get("screwRpm")},
            {"name": "productLot", "label": "Product lot", "value": data.get("productLot")},
            {"name": "settingsNote", "label": "Note on the settings", "type": "area", "value": data.get("settingsNote"), "height": 64},
            {"name": "comment", "label": "Comment", "type": "area", "value": data.get("comment"), "height": 64},
        ])
        hint = "Saving confirms this row: it leaves the trial block." if data.get("trial") else "Barrel zones in °C, nozzle first."
        return ("Edit settings", fields, hint)
    if action == "edit-injection":
        fields = [{"name": "setting::" + item.get("label"), "label": item.get("label"), "value": item.get("value")}
                  for item in data.get("settings") or []]
        return ("Injection settings", fields,
                "As set on the machine's injection page. Leave a box empty when the press does not use that step.")
    if action == "add-recipe":
        live = data.get("liveRecipes") or []
        return ("Add a recipe", [
            {"name": "press", "label": "Press", "type": "select", "options": choices.get("presses") or []},
            {"name": "from", "label": "Start from", "type": "select", "options": [_blank("Empty recipe")] + live},
            {"name": "color", "label": "Color (optional)", "type": "select", "options": [_blank("Keep / none")] + (choices.get("colors") or [])},
        ], "A new press for this product, or a new color on an existing press, is a new recipe.", "Create recipe")
    if action == "add-material":
        live = [{"value": "all", "label": "All %s live recipes" % len(data.get("liveRecipes") or [])}]
        live.extend({"value": item["value"], "label": item["label"]} for item in (data.get("liveRecipes") or []))
        return ("Add a raw material", [
            {"name": "material", "label": "Raw material", "type": "select", "options": choices.get("materials") or []},
            {"name": "recipe", "label": "On", "type": "select", "options": live, "value": "all"},
        ], "", "Add material")
    if action == "add-color":
        live = [{"value": "all", "label": "All %s live recipes" % len(data.get("liveRecipes") or [])}]
        live.extend(data.get("liveRecipes") or [])
        return ("Add a color", [
            {"name": "color", "label": "Color", "type": "select", "options": choices.get("colors") or []},
            {"name": "recipe", "label": "On", "type": "select", "options": live, "value": "all"},
        ], "Adding a color to one recipe makes a new color variant for that press.", "Add color")
    if action == "add-link":
        return ("Link another part", [
            {"name": "relation", "label": "This product", "type": "select", "options": [
                {"value": "part", "label": "is the body; the other is its lid"},
                {"value": "lid", "label": "is the lid; it fits onto the other"},
            ], "value": "part"},
            {"name": "other", "label": "Other product", "type": "select", "options": choices.get("products") or []},
        ], "", "Link")
    if action == "add-slot-material":
        return ("Add raw material", [
            {"name": "material", "label": "Raw material", "type": "select", "options": choices.get("materials") or []},
            {"name": "lot", "label": "Lot"},
        ], "", "Add")
    if action == "add-slot-color":
        return ("Add color", [
            {"name": "color", "label": "Color", "type": "select", "options": choices.get("colors") or []},
            {"name": "lot", "label": "Lot"},
        ], "", "Add")
    if action == "add-issue":
        fields = _issue_fields({}, choices.get("workers") or [])
        if screen.kind == "issue":
            fields = _job_fields(choices) + fields
        elif screen.kind == "product":
            live = data.get("liveRecipes") or []
            fields = [{"name": "recipe", "label": "Recipe that was running", "type": "select",
                       "options": ([_blank("Choose the recipe")] if len(live) > 1 else []) + live}] + fields
        return ("Log a stoppage", fields, "Leave the restart empty while the press is still down.", "Log stoppage")
    if action == "add-run":
        fields = _run_fields({}, choices)
        if screen.kind == "run":
            fields = _job_fields(choices) + fields
        return ("Log a run", fields,
                "Cycle and cavities as they really ran. Empty cycle or cavities fall back to the recipe and the mold.", "Log run")
    if action == "edit-run":
        row = extra.get("row") or {}
        fields = [{"name": "index", "type": "hidden", "value": row.get("index")}] + _run_fields(row, choices)
        hint = "%s on %s" % (row.get("product") or "", row.get("press") or "")
        if row.get("sample"):
            hint += ". This is a sample run: saving it makes it a real one."
        return ("Edit run", fields, hint)
    if action == "edit-issue" and extra.get("row"):
        row = extra.get("row") or {}
        fields = [{"name": "index", "type": "hidden", "value": row.get("index")}] + _issue_fields(row, choices.get("workers") or [])
        return ("Edit stoppage", fields, "%s on %s" % (row.get("product") or "", row.get("press") or ""))
    if action == "edit-issue":
        issues = data.get("rawIssues") or []
        try:
            issue = issues[int(extra.get("index"))]
        except (TypeError, ValueError, IndexError):
            Notification("That stoppage is no longer on the recipe.", style="warning").show()
            return None
        fields = [{"name": "index", "type": "hidden", "value": issue.get("index")}] + _issue_fields(issue, choices.get("workers") or [])
        return ("Edit stoppage", fields, "")
    if action == "edit-material":
        return ("Edit raw material", [
            {"name": "text", "label": "Grade", "value": data.get("name")},
            {"name": "kind", "label": "Type", "type": "select", "options": choices.get("kinds") or [], "value": data.get("kind")},
            {"name": "supplier", "label": "Supplier", "value": data.get("supplier")},
            {"name": "family", "label": "Family", "value": data.get("family")},
            {"name": "mfi", "label": "MFI", "value": data.get("mfi")},
            {"name": "account", "label": "Accounting code", "value": data.get("account")},
            {"name": "invoiceCode", "label": "Invoice code", "value": data.get("invoiceCode")},
            {"name": "link", "label": "Datasheet link", "value": data.get("rawLink"), "placeholder": "https://"},
            {"name": "description", "label": "Description", "type": "area", "value": data.get("description"), "height": 64},
            {"name": "notes", "label": "Notes", "type": "area", "value": data.get("notes"), "height": 64},
        ], "Saving adds the grade to the catalog. Resin and regrind count as base material.")
    if action == "edit-color":
        return ("Edit color", [
            {"name": "name", "label": "Color", "value": data.get("colorName")},
            {"name": "code", "label": "Label code", "value": data.get("code")},
            {"name": "account", "label": "Accounting code", "value": data.get("account")},
            {"name": "shade", "label": "Shade / supplier ref.", "value": data.get("shade")},
            {"name": "label", "label": "Label text", "type": "area", "value": data.get("label"), "height": 56},
            {"name": "link", "label": "Sample link", "value": data.get("link"), "placeholder": "https://"},
            {"name": "notes", "label": "Notes", "type": "area", "value": data.get("notes"), "height": 56},
        ], "Saving adds the code to the catalog.")
    return None
