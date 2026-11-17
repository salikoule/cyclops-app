"""Record editors in a side drawer. Field values go to cyclops_apply as strings; moments as ISO UTC."""

from datetime import datetime

from anvil import *
from craftify_library.CraftifyUtils import dialogs, drawer

from cyclops_app.session import Data
from cyclops_app.ui import Format, Layout

WIDE = ("area", "tags")


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
    """One date-and-time picker in local time; the value is an ISO UTC moment."""

    def __init__(self, moment, default_now=False):
        shown = Format.local(moment)
        if shown is None and default_now:
            shown = Format.now()
            shown = shown.replace(minute=shown.minute - shown.minute % 5)
        self.picker = DatePicker(format="%d %b %Y, %H:%M", date=shown, pick_time=True, placeholder="Not set")
        self.panel = self.picker

    def value(self):
        picked = self.picker.date
        if not picked:
            return ""
        return Format.utc(picked.date(), "%02d:%02d" % (picked.hour, picked.minute))

    def set_event_handler(self, name, handler):
        self.picker.set_event_handler(name, handler)


class _Tags:
    """The chosen values as removable tags, and a dropdown of the ones not chosen yet."""

    def __init__(self, options, selected, placeholder):
        self.options = [(option.get("value"), option.get("label") or option.get("value")) for option in options]
        allowed = set(value for value, _ in self.options)
        self.chosen = set(value for value in selected or [] if value in allowed)
        self.placeholder = placeholder
        self.panel = Layout.flat(HtmlTemplate(html='<div class="cy-tags"><div class="cy-tag-list" anvil-name="list"></div><div anvil-slot="pick"></div></div>'))
        self.pick = Layout.flat(DropDown())
        self.pick.set_event_handler("change", self._add)
        self.panel.add_component(self.pick, slot="pick")
        self.panel.dom_nodes["list"].addEventListener("click", self._remove)
        self._draw()

    def _draw(self):
        tags = ['<button type="button" class="cy-tag" data-value="%s">%s<span aria-label="Remove">×</span></button>' % (Layout.esc(value), Layout.esc(label))
                for value, label in self.options if value in self.chosen]
        self.panel.dom_nodes["list"].innerHTML = "".join(tags) or '<span class="cy-muted">None yet</span>'
        rest = [(label, value) for value, label in self.options if value not in self.chosen]
        self.pick.items = [(self.placeholder if rest else "All added", "")] + rest
        self.pick.selected_value = ""
        self.pick.enabled = bool(rest)

    def _add(self, **event_args):
        if self.pick.selected_value:
            self.chosen.add(self.pick.selected_value)
            self._draw()

    def _remove(self, event):
        node = Layout.closest(getattr(event, "target", None), "[data-value]")
        if node is not None:
            self.chosen.discard(Layout.attr(node, "data-value"))
            self._draw()

    def value(self):
        return ",".join(value for value, _ in self.options if value in self.chosen)


class _Swatch:
    """A color picker that can also be left unset."""

    def __init__(self, value):
        self.hex = value or ""
        self.panel = Layout.flat(HtmlTemplate(html='<div class="cy-swatch-field"><input type="color" anvil-name="pick">'
                                                    '<span anvil-name="code"></span><a href="javascript:void(0)" anvil-name="clear">Clear</a></div>'))
        self.panel.dom_nodes["pick"].addEventListener("input", self._picked)
        self.panel.dom_nodes["clear"].addEventListener("click", self._clear)
        self._draw()

    def _draw(self):
        nodes = self.panel.dom_nodes
        nodes["pick"].value = self.hex or "#ffffff"
        nodes["code"].textContent = self.hex.upper() if self.hex else "Not set"
        nodes["clear"].style.display = "" if self.hex else "none"

    def _picked(self, event):
        self.hex = self.panel.dom_nodes["pick"].value
        self._draw()

    def _clear(self, event):
        self.hex = ""
        self._draw()

    def value(self):
        return self.hex


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
    if kind == "swatch":
        swatch = _Swatch(field.get("value"))
        return swatch, swatch.panel
    if kind == "tags":
        tags = _Tags(field.get("options") or [], field.get("value"), field.get("placeholder") or "Add…")
        return tags, tags.panel
    if kind == "area":
        widget = TextArea(text=_text(field.get("value")), height=field.get("height") or 88)
        return widget, widget
    if kind == "date":
        widget = DatePicker(format="%d %b %Y", date=_as_date(field.get("value")), pick_time=False)
        return widget, widget
    if kind == "datetime":
        moment = _Moment(field.get("value"), field.get("now"))
        return moment, moment.panel
    widget = TextBox(text=_text(field.get("value")), placeholder=field.get("placeholder") or "")
    if kind == "number":
        widget.type = "number"
    return widget, widget


def _read(widget):
    if isinstance(widget, (_Tags, _Moment, _Swatch)):
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
        start, end = first.value(), then.value()
        reversed_pair = bool(start.endswith("Z") and end.endswith("Z") and end < start)
        hint.textContent = field.get("after_error") if reversed_pair else usual
        if reversed_pair:
            root.classList.add("is-bad")
        else:
            root.classList.remove("is-bad")

    first.set_event_handler("change", check)
    then.set_event_handler("change", check)
    check()


def _follow(parent, child, groups, empty, keep):
    """Refill ``child`` with ``groups[parent value]`` whenever the parent dropdown changes; ``keep`` stays selected while it is offered."""
    def refill(**event_args):
        options = groups.get(parent.selected_value) or []
        child.items = [(opt.get("label") or "", opt.get("value")) for opt in options] or [(empty, "")]
        values = [opt.get("value") for opt in options]
        child.selected_value = keep["value"] if keep["value"] in values else (values[0] if values else "")
        keep["value"] = None

    parent.set_event_handler("change", refill)
    refill()


def _show_for(control, box, values):
    """Show ``box`` only while the ``control`` dropdown holds one of ``values``."""
    def sync(**event_args):
        box.visible = control.selected_value in values

    control.add_event_handler("change", sync)
    sync()


_OPEN = {"drawer": None}


def show(title, fields, on_save, hint="", eyebrow="", save_text="Save", width=520, on_delete=None):
    """Open a drawer with ``fields``. ``on_save(payload, close)`` and ``on_delete(close)`` return an error string or None."""
    if _OPEN["drawer"] is not None and _OPEN["drawer"].is_open:
        if not _OPEN["drawer"].close(force=False):
            return _OPEN["drawer"]
    widgets = {}
    boxes = {}
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
        boxes[field["name"]] = box
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
            _follow(widgets[field["follows"]], widgets[field["name"]], field.get("groups") or {}, field.get("empty") or "",
                    {"value": field.get("value")})
    for field in fields:
        rule = field.get("shown_for")
        if rule and rule[0] in widgets and field["name"] in boxes:
            _show_for(widgets[rule[0]], boxes[field["name"]], rule[1])
    error = Layout.html('<p class="bc-note bc-note-warn cy-form-error" anvil-name="msg"></p>')
    content = Layout.stack(error, *rows)
    for name, (field, box) in moments.items():
        if field.get("after") in widgets:
            _order(widgets[field["after"]], widgets[name], box, field)

    def values():
        return {name: _read(widget) for name, widget in widgets.items()}

    initial = values()
    holder = {"drawer": None}
    save_button = Layout.button(save_text, primary=True)
    cancel_button = Layout.button("Cancel")

    def close(force=True):
        if holder["drawer"] is not None:
            holder["drawer"].close(force=force)

    def report(problem):
        error.dom_nodes["msg"].textContent = problem or ""
        if problem:
            error.dom_nodes["msg"].classList.add("is-on")
        else:
            error.dom_nodes["msg"].classList.remove("is-on")

    def save(**event_args):
        report("")
        save_button.enabled = False
        try:
            problem = on_save(values(), close)
        finally:
            save_button.enabled = True
        report(problem)

    save_button.set_event_handler("click", save)
    cancel_button.set_event_handler("click", lambda **e: close(force=False))
    footer = (cancel_button, save_button)
    if on_delete is not None:
        footer = (Layout.button("Delete", lambda **e: report(on_delete(close)), danger=True),) + footer
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


def open_editor(screen, action, extra=None):
    extra = extra or {}
    spec = _spec(screen, action, extra)
    if spec is None:
        return False
    title, fields, hint = spec[:3]
    save_text = spec[3] if len(spec) > 3 else "Save"
    removal = spec[4] if len(spec) > 4 else None
    eyebrow = (extra.get("row") or {}).get("id") or (screen.data or {}).get("id") or ""
    on_delete = None
    if removal:
        remove, question, detail, payload = removal

        def on_delete(close):
            if not dialogs.confirm(detail, title=question, confirm_text="Delete", danger=True):
                return None
            return screen.apply(remove, payload, close)

    show(title, fields, lambda payload, close: screen.apply(action, payload, close), hint, eyebrow=eyebrow,
         save_text=save_text, on_delete=on_delete)
    return True


def _unit_named(choices, name):
    return next((opt["value"] for opt in choices.get("uoms") or [] if opt.get("label") == name), "")


def _blank(label):
    return {"value": "", "label": label}


def _sorted(options):
    return sorted(options or [], key=lambda opt: (opt.get("label") or "").lower())


def _moment(name, label, value="", now=False, after=None, after_error="", hint=""):
    return {"name": name, "label": label, "type": "datetime", "value": value, "now": now, "after": after,
            "after_error": after_error, "hint": hint}


def _shift_now(choices):
    now = datetime.now().strftime("%H:%M")
    for shift in choices.get("shifts") or []:
        start, end = shift.get("start") or "", shift.get("end") or ""
        if (start <= now < end) if start < end else (now >= start or now < end):
            return shift["value"]
    return ""


def _run_fields(run, choices, order_field=None, recipes=None):
    fields = []
    if order_field is not None:
        fields.append(order_field)
    if recipes is not None:
        fields.append(recipes)
    fields.extend([
        _moment("startedAt", "Started", run.get("startedAt"), now=not run),
        _moment("endedAt", "Ended", run.get("endedAt"), after="startedAt", after_error="The end is before the start.",
                hint="Leave empty while the job is still running. Closing it needs the good pieces."),
        {"name": "shiftId", "label": "Shift", "type": "select", "options": [_blank("Choose the shift")] + (choices.get("shifts") or []),
         "value": run.get("shiftId") if run else _shift_now(choices)},
        {"name": "operatorId", "label": "Operator", "type": "select", "options": [_blank("Choose the operator")] + _sorted(choices.get("operators")),
         "value": run.get("operatorId") or ""},
        {"name": "good", "label": "Good pieces", "type": "number", "value": run.get("good")},
        {"name": "cycle", "label": "Actual cycle (s)", "type": "number", "value": run.get("cycle"), "placeholder": "from the press display"},
        {"name": "cavities", "label": "Cavities running", "type": "number", "value": run.get("cavities"), "placeholder": "blocked ones excluded"},
        {"name": "notes", "label": "Notes", "type": "area", "value": run.get("notes"), "height": 64},
    ])
    return fields


def _stoppage_fields(stop, choices, machine=None, run=None):
    fields = []
    if machine is not None:
        fields.append(machine)
    if run is not None:
        fields.append(run)
    fields.extend([
        _moment("startedAt", "Stopped at", stop.get("startedAt"), now=not stop),
        _moment("endedAt", "Restarted at", stop.get("endedAt"), after="startedAt", after_error="The restart is before the stop.",
                hint="Leave empty while the machine is still down. Closing it needs the cause."),
        {"name": "cause", "label": "Cause", "type": "select", "options": [_blank("Not known yet")] + (choices.get("causes") or []),
         "value": stop.get("causeId") or "", "wide": True},
        {"name": "reportedBy", "label": "Reported by", "type": "select", "options": [_blank("Not recorded")] + _sorted(choices.get("people")),
         "value": stop.get("reportedById") or ""},
        {"name": "description", "label": "What was seen", "type": "area", "value": stop.get("description")},
        {"name": "fix", "label": "What was done", "type": "area", "value": stop.get("fix")},
    ])
    return fields


def _runs_by_machine(choices):
    return {code: [_blank("No run (machine idle)")] + runs for code, runs in (choices.get("runsByMachine") or {}).items()}


def _machine_run_fields(choices, stop):
    machine = {"name": "machine", "label": "Machine", "type": "select", "options": [_blank("Choose the machine")] + (choices.get("machines") or []),
               "value": stop.get("machineId") or ""}
    run = {"name": "run", "label": "During run", "type": "select", "options": [], "follows": "machine", "wide": True,
           "groups": _runs_by_machine(choices), "empty": "No run logged on this machine", "value": stop.get("runId") or ""}
    return machine, run


def _item_fields(data, choices, item_type):
    properties = data.get("properties") or []
    fields = [
        {"name": "name", "label": "Name", "value": data.get("name"), "wide": True},
        {"name": "type", "label": "Type", "type": "select", "options": choices.get("types") or [], "value": item_type},
        {"name": "categoryId", "label": "Category", "type": "select", "options": [], "follows": "type",
         "groups": choices.get("categoriesByType") or {}, "empty": "Add a category for this type in Configure", "value": data.get("categoryId")},
        {"name": "uomId", "label": "Unit", "type": "select", "options": choices.get("uoms") or [], "value": data.get("uomId") or _unit_named(choices, "kg" if item_type == "RAW" else "pcs")},
        {"name": "erpCode", "label": "SKU", "value": data.get("erpCode"), "placeholder": "ERP code",
         "hint": "The ERP code is the SKU. The ERP keeps prices and accounts."},
        {"name": "parentId", "label": "Shared product", "type": "select", "wide": True,
         "options": [_blank("Not a variant")] + [opt for opt in (choices.get("products") or []) if opt.get("value") != data.get("id")],
         "value": data.get("parentId") or "",
         "hint": "Set this when the item is a variant of another item. A product without variants stays a normal item."},
        {"name": "supplier", "label": "Supplier", "value": data.get("supplier")},
    ]
    known = {entry.get("id"): entry.get("value") or "" for entry in data.get("attributes") or []}
    for attr in choices.get("variantAttributes") or []:
        fields.append({"name": "attr::" + attr.get("value"), "label": attr.get("label") or "Attribute", "value": known.get(attr.get("value"), ""),
                       "hint": "Leave empty when this item does not use the attribute."})
    if data.get("id"):
        fields.append({"name": "status", "label": "Status", "type": "select", "options": choices.get("statuses") or [], "value": data.get("itemStatus")})
    for entry in properties:
        fields.append({"name": "prop::" + entry["key"], "label": entry["label"], "value": entry.get("value"),
                       "type": "swatch" if entry["key"] == "swatch" else "text",
                       "hint": "For the screen only. The real match is the standard or the supplier's reference." if entry["key"] == "swatch" else ""})
    if data.get("id"):
        fields.append({"name": "notes", "label": "Notes", "type": "area", "value": data.get("notes"), "height": 64})
    return fields


def _machine_fields(data, choices):
    others = [opt for opt in choices.get("machines") or [] if opt.get("value") != data.get("id")]
    return [
        {"name": "name", "label": "Name", "value": data.get("name")},
        {"name": "typeId", "label": "Type", "type": "select", "options": choices.get("machineTypes") or [], "value": data.get("typeId")},
        {"name": "attachedToId", "label": "Attached to", "type": "select", "options": [_blank("Stands alone")] + others, "value": data.get("attachedToId") or ""},
        {"name": "alias", "label": "Alias", "value": data.get("alias")},
        {"name": "euromap", "label": "EUROMAP class", "value": data.get("euromap")},
        {"name": "serial", "label": "Serial", "value": data.get("serial")},
        {"name": "year", "label": "Year", "value": data.get("year")},
        {"name": "floor", "label": "Floor number", "type": "number", "value": data.get("floor")},
        {"name": "changeoverMin", "label": "Changeover (min)", "type": "number", "value": data.get("changeoverMin")},
        {"name": "location", "label": "Location", "value": data.get("location")},
        {"name": "status", "label": "Status", "type": "select", "options": choices.get("statuses") or [], "value": data.get("machineStatus") or "active"},
        {"name": "notes", "label": "Notes", "type": "area", "value": data.get("notes"), "height": 64},
    ]


def _mold_fields(mold, choices):
    return [
        {"name": "name", "label": "Name", "value": mold.get("name"), "wide": True},
        {"name": "cavities", "label": "Cavities", "type": "number", "value": mold.get("cavities")},
        {"name": "shotWeight", "label": "Shot weight (g)", "type": "number", "value": mold.get("shotWeight")},
        {"name": "location", "label": "Location", "value": mold.get("location")},
        {"name": "status", "label": "Status", "type": "select", "options": choices.get("moldStatuses") or [], "value": mold.get("moldStatus") or "in use"},
        {"name": "notes", "label": "Notes", "type": "area", "value": mold.get("notes"), "height": 64},
    ]


def _order_fields(order, choices):
    return [
        {"name": "item", "label": "Item to make", "type": "select", "options": [_blank("Choose the item")] + (choices.get("made") or []),
         "value": order.get("itemId") or "", "wide": True},
        {"name": "quantity", "label": "Quantity", "type": "number", "value": order.get("quantity")},
        {"name": "dueDate", "label": "Due", "type": "date", "value": order.get("dueDate")},
        {"name": "erpOrderNo", "label": "ERP order no.", "value": order.get("erpOrderNo")},
        {"name": "status", "label": "Status", "type": "select", "options": choices.get("orderStatuses") or [], "value": order.get("orderStatus") or "planned"},
        {"name": "notes", "label": "Notes", "type": "area", "value": order.get("notes"), "height": 64},
    ]


def _setting_spec(kind, entry, choices):
    entry = entry or {}
    fields = [{"name": "settingKind", "type": "hidden", "value": kind}, {"name": "code", "type": "hidden", "value": entry.get("id") or ""},
              {"name": "name", "label": "Name", "value": entry.get("name"), "wide": True}]
    if kind == "shift":
        fields += [{"name": "start", "label": "Starts", "value": entry.get("start"), "placeholder": "06:00"},
                   {"name": "end", "label": "Ends", "value": entry.get("end"), "placeholder": "14:00"}]
    if kind in ("cause", "reason"):
        fields.append({"name": "category", "label": "Category", "type": "select", "options": choices.get("fishbone") or [], "hint": "The six fishbone groups: Man, Machine, Method, Material, Measurement, Environment.",
                       "value": entry.get("category") or "Machine"})
    if kind == "cause":
        fields.append({"name": "planned", "label": "Planned stop", "type": "select", "value": "yes" if entry.get("planned") else "no",
                       "options": [{"value": "no", "label": "No, a breakdown or a fault"}, {"value": "yes", "label": "Yes (mold change, maintenance)"}]})
        fields.append({"name": "changeover", "label": "Changeover", "type": "select", "value": "yes" if entry.get("changeover") else "no",
                       "hint": "A stop with this cause between two items gives that changeover its times.",
                       "options": [{"value": "no", "label": "No"}, {"value": "yes", "label": "Yes, the machine is changed to another item"}]})
    if kind == "category":
        fields += [{"name": "type", "label": "Item type", "type": "select", "options": choices.get("types") or [], "value": entry.get("type") or "RAW"},
                   {"name": "role", "label": "Role in a recipe", "type": "select", "options": choices.get("roles") or [], "value": entry.get("role") or "",
                    "hint": "Raw materials only. A recipe needs at least one base input; colorants make its color."}]
    if kind == "person":
        fields += [{"name": "roleId", "label": "Role", "type": "select", "value": entry.get("roleId") or "",
                    "options": [_blank("Not set yet")] + (choices.get("personRoles") or []),
                    "hint": "Roles that run machines can be named on a run. Roles are edited on the Roles tab."},
                   {"name": "machines", "label": "Qualified on", "type": "tags", "options": choices.get("presses") or [],
                    "value": entry.get("machineIds") or [], "placeholder": "Add a machine…",
                    "shown_for": ("roleId", choices.get("productionRoles") or [])}]
    if kind == "role":
        fields.append({"name": "runsMachines", "label": "Runs machines", "type": "select", "value": "yes" if entry.get("runsMachines") else "no",
                       "options": [{"value": "no", "label": "No"}, {"value": "yes", "label": "Yes: can be named on a run, holds machine qualifications"}]})
    if "status" in entry or kind in ("shift", "cause", "reason", "person", "role", "unit", "attribute"):
        fields.append({"name": "status", "label": "Status", "type": "select", "options": choices.get("statuses") or [], "value": entry.get("status") or "active"})
    titles = {"shift": "shift", "cause": "stoppage cause", "reason": "scrap reason", "category": "item category",
              "machineType": "machine type", "person": "person", "role": "role", "unit": "unit", "attribute": "variant attribute"}
    title = ("Edit %s" if entry.get("id") else "New %s") % titles.get(kind, "setting")
    return (title, fields, "Retire a value instead of deleting it, so the records that use it keep it.")


def _with_current(options, value, label):
    options = list(options or [])
    if value and value not in [opt.get("value") for opt in options]:
        options = [{"value": value, "label": label or value}] + options
    return options


def _shift_spec(card, choices, closing):
    """Order and recipe come from the open run. Shift and start stay as logged; the clock fills them only when that run has none."""
    card = card or {}
    order_value, recipe_value = card.get("order") or "", card.get("recipe") or ""
    fields = [
        {"name": "machine", "type": "hidden", "value": card.get("id") or ""},
        {"name": "close", "type": "hidden", "value": "yes" if closing else ""},
    ]
    if order_value:
        fields.append({"name": "order", "label": "Order", "type": "select", "wide": True,
                       "options": _with_current(choices.get("openOrders"), order_value, card.get("orderLabel") or order_value),
                       "value": order_value})
        recipes = (choices.get("recipesByOrder") or {}).get(order_value) or []
        fields.append({"name": "recipe", "label": "Recipe", "type": "select", "wide": True,
                       "options": _with_current(recipes, recipe_value, recipe_value), "value": recipe_value})
    else:
        fields.append({"name": "order", "label": "Order", "type": "select", "wide": True,
                       "options": [_blank("Choose the order")] + (choices.get("openOrders") or [])})
        fields.append({"name": "recipe", "label": "Recipe", "type": "select", "options": [], "follows": "order", "wide": True,
                       "groups": choices.get("recipesByOrder") or {}, "empty": "Choose an order with a live recipe"})
    fields.extend([
        {"name": "shiftId", "label": "Shift", "type": "select", "options": [_blank("Choose the shift")] + (choices.get("shifts") or []),
         "value": card.get("shiftId") or _shift_now(choices)},
        _moment("startedAt", "Started", card.get("startedAt"), now=not card.get("startedAt")),
        {"name": "operatorId", "label": "Who was on it", "type": "select",
         "options": [_blank("Choose the operator")] + _sorted(choices.get("operators")), "value": card.get("operatorId") or ""},
        {"name": "good", "label": "Good pieces", "type": "number", "value": card.get("good")},
        {"name": "scrapReason", "label": "Scrap reason", "type": "select", "options": [_blank("No scrap")] + (choices.get("reasons") or []), "wide": True},
        {"name": "scrapQty", "label": "Scrap", "type": "number"},
    ])
    if closing:
        fields.append(_moment("endedAt", "Ended", now=True))
    title = "Close the shift" if closing else "Log the shift"
    hint = "Saving does not need a consumed lot or a cavity count. Anything still missing is listed after the save, and can be filled in on the run."
    return (title, fields, hint, "Close shift" if closing else "Save shift")


def _spec(screen, action, extra):
    choices = Data.choices()
    data = screen.data or {}
    row = extra.get("row") or {}
    if action == "new-item":
        return ("New item", _item_fields({}, choices, extra.get("type") or "SFG"), "Every product, part, and material is an item. The type and category decide where it is used.", "Create item")
    if action == "edit-item":
        return ("Edit item", _item_fields(data, choices, data.get("type")), "The SKU is this item's ERP code. A parent links a variant to the shared product.")
    if action == "set-approved":
        return ("Approved machines", [
            {"name": "machines", "label": "This item may run on", "type": "tags", "options": choices.get("presses") or [], "value": data.get("approvedMachineIds") or [],
             "placeholder": "Add a machine…"},
        ], "A machine that is approved but has no recipe shows up as a gap for the planner.")
    if action == "new-mold":
        return ("New mold", _mold_fields({}, choices), "", "Create mold")
    if action == "edit-mold":
        return ("Edit mold %s" % data.get("id"), _mold_fields(data, choices),
                "Cavities turn every cycle time of this mold into pieces per hour. Shot weight turns a run into kilograms of resin.")
    if action == "new-machine":
        return ("New machine", _machine_fields({}, choices), "A robot or a dryer is a machine too, attached to its press.", "Create machine")
    if action == "edit-machine":
        return ("Edit machine", _machine_fields(data, choices), "Changeover minutes let the planner sequence mold and color changes.")
    if action == "add-recipe":
        molds = [opt for opt in choices.get("molds") or [] if opt.get("value") in (data.get("molds") or [])]
        others = [opt for opt in choices.get("molds") or [] if opt.get("value") not in (data.get("molds") or [])]
        return ("Add a recipe", [
            {"name": "machine", "label": "Machine", "type": "select", "options": choices.get("presses") or []},
            {"name": "mold", "label": "Mold", "type": "select", "options": molds + [_blank("New mold for this item")] + others},
            {"name": "from", "label": "Start from", "type": "select", "options": [_blank("Empty recipe")] + (data.get("liveRecipes") or []), "wide": True},
            {"name": "color", "label": "Colorant (optional)", "type": "select", "options": [_blank("Keep / none")] + (choices.get("colorants") or []), "wide": True},
        ], "A new machine for this item, or a new color on a machine, is a new recipe.", "Create recipe")
    if action == "edit-recipe":
        temps = data.get("temps") or {}
        fields = [{"name": "temp_" + zone["key"], "label": zone["label"] + " °C", "value": temps.get(zone["key"])} for zone in data.get("zones") or []]
        fields.extend([
            {"name": "cycle", "label": "Cycle (s)", "value": data.get("cycle")},
            {"name": "cooling", "label": "Cooling (s)", "value": data.get("cooling")},
            {"name": "screwRpm", "label": "Screw (rpm)", "value": data.get("screwRpm")},
            {"name": "status", "label": "Status", "type": "select", "options": choices.get("recipeStatuses") or [], "value": data.get("recipeStatus")},
            {"name": "px", "label": "ΠΧ", "value": data.get("px")},
            {"name": "py", "label": "ΠΥ", "value": data.get("py")},
            {"name": "printPieces", "label": "ΤΕΜ εκτύπωση", "value": data.get("printPieces")},
            {"name": "printTotal", "label": "TOT εκτύπωσης", "value": data.get("printTotal")},
            {"name": "settingsNote", "label": "Note on the settings", "type": "area", "value": data.get("settingsNote"), "height": 64},
            {"name": "comment", "label": "Comment", "type": "area", "value": data.get("comment"), "height": 64},
        ])
        return ("Edit settings", fields, "Barrel zones in °C, nozzle first. Approve a trial recipe to make it live.")
    if action == "edit-injection":
        fields = [{"name": "setting::" + entry.get("label"), "label": entry.get("label"), "value": entry.get("value")} for entry in data.get("settings") or []]
        return ("Injection settings", fields, "As set on the machine's injection page. Leave a box empty when the press does not use that step.")
    if action == "add-input":
        fields = [{"name": "item", "label": "Raw material", "type": "select", "options": choices.get("raw") or [], "wide": True},
                  {"name": "share", "label": "Share of the shot (%)", "type": "number", "placeholder": "e.g. 97"}]
        if screen.kind == "item":
            live = data.get("liveRecipes") or []
            fields.append({"name": "recipe", "label": "On", "type": "select", "wide": True,
                           "options": [{"value": "all", "label": "All %s live recipes" % len(live)}] + live, "value": "all"})
        return ("Add an input", fields, "Shares are the percentage of the shot weight. With them the kilograms per order are a calculation.", "Add")
    if action == "edit-input":
        return ("Share of %s" % row.get("name"), [
            {"name": "item", "type": "hidden", "value": row.get("id")},
            {"name": "share", "label": "Share of the shot (%)", "type": "number", "value": row.get("share")},
        ], "Leave empty when not known.", "Save",
            ("remove-input", "Remove this input?", "The material comes off this recipe.", {"item": row.get("id")}))
    if action == "new-order":
        order = {"itemId": data.get("id")} if screen.kind == "item" else {}
        return ("New production order", _order_fields(order, choices), "Until the ERP sends orders, write them here.", "Create order")
    if action == "edit-order":
        return ("Edit order", _order_fields(data, choices), "")
    if action == "add-run":
        if screen.kind == "order":
            recipes = {"name": "recipe", "label": "Recipe", "type": "select", "options": data.get("recipes") or [], "wide": True}
            return ("Log a run", _run_fields({}, choices, recipes=recipes), "One run is one job on one machine, start to end.", "Log run")
        order = {"name": "order", "label": "Production order", "type": "select", "options": [_blank("Choose the order")] + (choices.get("openOrders") or []), "wide": True}
        if screen.kind == "recipe":
            return ("Log a run", _run_fields({}, choices, order_field=order), "The order has to be for this recipe's item.", "Log run")
        recipes = {"name": "recipe", "label": "Recipe", "type": "select", "options": [], "follows": "order", "wide": True,
                   "groups": choices.get("recipesByOrder") or {}, "empty": "Choose an order with a live recipe"}
        return ("Log a run", _run_fields({}, choices, order_field=order, recipes=recipes), "One run is one job on one machine, start to end.", "Log run")
    if action == "log-shift":
        return _shift_spec(row, choices, extra.get("close"))
    if action == "save-access":
        return ("Access", [
            {"name": "email", "type": "hidden", "value": row.get("email")},
            {"name": "role", "label": "Role", "type": "select", "options": choices.get("accessRoles") or [], "value": row.get("role") or "observer"},
            {"name": "active", "label": "Account", "type": "select", "value": "yes" if row.get("active") else "no",
             "options": [{"value": "yes", "label": "Active"}, {"value": "no", "label": "Deactivated"}]},
            {"name": "screens", "label": "Screens", "type": "tags", "options": choices.get("accessScreens") or [],
             "value": row.get("screens") or [], "placeholder": "Add a screen…", "wide": True,
             "hint": "Administrators see every screen. For the other roles, these are the pages in the sidebar."},
        ], row.get("email") or "", "Save")
    if action == "edit-run":
        return ("Edit run", _run_fields(data, choices), "%s on %s" % (data.get("item") or "", data.get("machine") or ""), "Save",
                ("delete-run", "Delete this run?", "Its scrap, consumed lots, and output lots are removed. Its stoppages stay on the machine.", {}))
    if action == "add-scrap":
        return ("Add scrap", [
            {"name": "reason", "label": "Reason", "type": "select", "options": choices.get("reasons") or [], "wide": True},
            {"name": "quantity", "label": "Pieces", "type": "number"},
        ], "", "Add")
    if action == "add-run-input":
        lots = data.get("candidateLots") or []
        if not lots:
            Notification("No lot of this recipe's materials is recorded. Receive the lot first.", style="warning", timeout=5).show()
            return None
        return ("Add a consumed lot", [
            {"name": "lot", "label": "Lot", "type": "select", "options": lots, "wide": True},
            {"name": "quantity", "label": "Quantity used", "type": "number", "placeholder": "kg"},
        ], "The resin, masterbatch, and additive lots fed into this run. This is what traces a complaint back to its supplier.", "Add")
    if action == "add-output-lot":
        return ("Add an output lot", [
            {"name": "number", "label": "Lot printed on the boxes", "placeholder": "e.g. 061126"},
            {"name": "quantity", "label": "Pieces", "type": "number"},
            {"name": "notes", "label": "Notes", "type": "area", "height": 56},
        ], "", "Add lot")
    if action == "receive-lot":
        return ("Receive a lot", [
            {"name": "item", "label": "Material or packaging", "type": "select", "options": [_blank("Choose the item")] + _sorted(choices.get("received")),
             "value": data.get("id") if screen.kind == "item" else "", "wide": True},
            {"name": "number", "label": "Lot number", "placeholder": "on the bag or box"},
            {"name": "supplierLot", "label": "Supplier batch", "placeholder": "if different"},
            _moment("receivedAt", "Received", now=True),
            {"name": "quantity", "label": "Quantity", "type": "number"},
            {"name": "status", "label": "Status", "type": "select", "options": choices.get("lotStatuses") or [], "value": "released"},
            {"name": "notes", "label": "Notes", "type": "area", "height": 56},
        ], "Every bag or box that comes in gets a lot, so a run can say what it consumed.", "Receive")
    if action == "edit-lot":
        fields = [
            {"name": "number", "label": "Lot number", "value": data.get("number")},
            {"name": "supplierLot", "label": "Supplier batch", "value": data.get("supplierLot")},
            {"name": "quantity", "label": "Quantity", "type": "number", "value": data.get("quantity")},
            {"name": "status", "label": "Status", "type": "select", "options": choices.get("lotStatuses") or [], "value": data.get("lotStatus")},
        ]
        if data.get("origin") == "Received":
            fields.append(_moment("receivedAt", "Received", data.get("receivedAt")))
        fields.append({"name": "notes", "label": "Notes", "type": "area", "value": data.get("notes"), "height": 56})
        return ("Edit lot", fields, "Block a lot to stop it being fed; it stays on the runs that used it.", "Save",
                ("delete-lot", "Delete this lot?", "Only a lot no run has used can be deleted.", {}))
    if action == "add-stoppage":
        if screen.kind == "run":
            return ("Log a stoppage", _stoppage_fields({}, choices), "On this run.", "Log stoppage")
        if screen.kind == "machine":
            run = {"name": "run", "label": "During run", "type": "select", "wide": True,
                   "options": [_blank("No run (machine idle)")] + ((choices.get("runsByMachine") or {}).get(data.get("id")) or [])}
            return ("Log a stoppage", _stoppage_fields({}, choices, run=run), "", "Log stoppage")
        machine, run = _machine_run_fields(choices, {})
        return ("Log a stoppage", _stoppage_fields({}, choices, machine, run), "", "Log stoppage")
    if action == "edit-stoppage":
        machine, run = _machine_run_fields(choices, row)
        fields = [{"name": "stoppage", "type": "hidden", "value": row.get("id")}] + _stoppage_fields(row, choices, machine, run)
        return ("Edit stoppage", fields, "", "Save",
                ("delete-stoppage", "Delete this stoppage?", "The record of this stop and its fix is removed.", {"stoppage": row.get("id")}))
    if action == "save-setting":
        return _setting_spec(extra.get("settingKind"), row, choices)
    return None
