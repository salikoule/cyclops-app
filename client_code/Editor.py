"""Inline editors. Field values go to cyclops_apply as strings."""

from anvil import *
import anvil.google.auth, anvil.google.drive
from anvil.google.drive import app_files

from cyclops_app import Data, Layout


def _text(value):
    if value is None:
        return ""
    return str(value)


def show(slot, title, fields, on_save, hint=""):
    slot.clear()
    widgets = {}
    boxes = []
    for field in fields:
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
        elif kind == "area":
            widget = TextArea(text=_text(field.get("value")), height=80)
        else:
            widget = TextBox(text=_text(field.get("value")), placeholder=field.get("placeholder") or "")
            if kind == "number":
                widget.type = "number"
        widgets[field["name"]] = widget
        boxes.append(Layout.field(field["label"], widget))
    card = Layout.section(title)
    Layout.body(card, Layout.grid("repeat(auto-fill, minmax(200px, 1fr))", *boxes))
    if hint:
        Layout.body(card, Layout.note(hint))

    def save(**event_args):
        payload = {}
        for name, widget in widgets.items():
            if isinstance(widget, DropDown):
                payload[name] = widget.selected_value or ""
            else:
                payload[name] = widget.text or ""
        on_save(payload)

    actions = FlowPanel(spacing="small", align="left")
    actions.add_component(Layout.button("Save", save, primary=True))
    actions.add_component(Layout.button("Cancel", lambda **event_args: slot.clear()))
    Layout.body(card, actions)
    slot.add_component(card, full_width_row=True)


def _blank(label):
    return {"value": "", "label": label}


def open_editor(screen, action):
    spec = _spec(screen, action)
    if spec is None:
        return False
    title, fields, hint = spec
    show(screen.slot, title, fields, lambda payload: screen.apply(action, payload), hint)
    return True


def _spec(screen, action):
    choices = Data.choices()
    data = screen.data or {}
    if action == "new-product":
        return ("New product", [
            {"name": "name", "label": "Name"},
            {"name": "type", "label": "Type", "type": "select", "options": choices.get("types") or [], "value": "part"},
            {"name": "erp", "label": "ERP code"},
        ], "")
    if action == "new-mold":
        return ("New mold", [
            {"name": "name", "label": "Mold name"},
            {"name": "product", "label": "Makes", "type": "select", "options": [_blank("Choose a product")] + (choices.get("products") or [])},
            {"name": "cavities", "label": "Cavities", "type": "number"},
            {"name": "shot", "label": "Shot weight (g)", "type": "number"},
        ], "")
    if action == "new-press":
        return ("New press", [
            {"name": "name", "label": "Name"},
            {"name": "euromap", "label": "EUROMAP class"},
            {"name": "changeover", "label": "Changeover (min)", "type": "number"},
        ], "")
    if action == "new-material":
        return ("New raw material", [
            {"name": "text", "label": "Grade"},
            {"name": "kind", "label": "Type", "type": "select", "options": choices.get("kinds") or [], "value": "resin"},
            {"name": "supplier", "label": "Supplier"},
            {"name": "family", "label": "Family"},
            {"name": "account", "label": "Accounting code"},
        ], "Only resin and regrind count as a base material. A setup with additives or colors alone is flagged Cannot produce.")
    if action == "new-color":
        return ("New color", [
            {"name": "name", "label": "Color"},
            {"name": "code", "label": "Label code"},
            {"name": "account", "label": "Accounting code"},
        ], "")
    if action == "edit-product":
        return ("Edit product", [
            {"name": "name", "label": "Name", "value": data.get("name")},
            {"name": "type", "label": "Type", "type": "select", "options": choices.get("types") or [], "value": data.get("type")},
            {"name": "lifecycle", "label": "Lifecycle", "type": "select", "options": choices.get("lifecycles") or [], "value": data.get("lifecycle")},
            {"name": "erpCode", "label": "ERP code", "value": data.get("erpCode"), "placeholder": "from the ERP"},
            {"name": "notes", "label": "Notes", "type": "area", "value": data.get("notes")},
        ], "The ERP code is what lets orders and stock meet this record. Status is otherwise computed from the setups.")
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
        return ("Edit press %s" % data.get("id"), [
            {"name": "lifecycle", "label": "Lifecycle", "type": "select", "options": choices.get("lifecycles") or [], "value": data.get("lifecycle")},
            {"name": "changeoverMin", "label": "Changeover (min)", "type": "number", "value": data.get("changeoverMin")},
            {"name": "mounted", "label": "On the board", "value": data.get("mounted"), "placeholder": "product name"},
            {"name": "location", "label": "Board note", "value": data.get("location")},
        ], "")
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
        ])
        hint = "Saving confirms this row: it leaves the trial block." if data.get("trial") else ""
        return ("Edit settings of %s" % data.get("id"), fields, hint)
    if action == "add-recipe":
        live = data.get("liveRecipes") or []
        return ("Add a recipe", [
            {"name": "press", "label": "Press", "type": "select", "options": choices.get("presses") or []},
            {"name": "from", "label": "Start from", "type": "select", "options": [_blank("Empty recipe")] + live},
            {"name": "color", "label": "Color (optional)", "type": "select", "options": [_blank("Keep / none")] + (choices.get("colors") or [])},
        ], "A new press for this product, or a new color on an existing press, is a new recipe.")
    if action == "add-material":
        live = [_blank("All live recipes")] + [{"value": item["value"], "label": item["label"]} for item in (data.get("liveRecipes") or [])]
        live[0] = {"value": "all", "label": "All %s live recipes" % len(data.get("liveRecipes") or [])}
        return ("Add a raw material", [
            {"name": "material", "label": "Raw material", "type": "select", "options": choices.get("materials") or []},
            {"name": "recipe", "label": "On", "type": "select", "options": live, "value": "all"},
        ], "")
    if action == "add-color":
        live = [{"value": "all", "label": "All %s live recipes" % len(data.get("liveRecipes") or [])}]
        live.extend(data.get("liveRecipes") or [])
        return ("Add a color", [
            {"name": "color", "label": "Color", "type": "select", "options": choices.get("colors") or []},
            {"name": "recipe", "label": "On", "type": "select", "options": live, "value": "all"},
        ], "Adding a color to one recipe makes a new color variant for that press.")
    if action == "add-link":
        return ("Link another part", [
            {"name": "relation", "label": "This product", "type": "select", "options": [
                {"value": "part", "label": "is the body; the other is its lid"},
                {"value": "lid", "label": "is the lid; it fits onto the other"},
            ], "value": "part"},
            {"name": "other", "label": "Other product", "type": "select", "options": choices.get("products") or []},
        ], "")
    if action == "add-slot-material":
        return ("Add raw material", [
            {"name": "material", "label": "Raw material", "type": "select", "options": choices.get("materials") or []},
            {"name": "lot", "label": "Lot"},
        ], "")
    if action == "add-slot-color":
        return ("Add color", [
            {"name": "color", "label": "Color", "type": "select", "options": choices.get("colors") or []},
            {"name": "lot", "label": "Lot"},
        ], "")
    return None
