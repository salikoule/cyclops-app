"""Labels, confirmations, and the list-field cache shared by the record screens."""

from cyclops_app.ui.query import call as _call


LEADS = {
    "item": "Every product, part, and material is an item: raw materials, packaging, semi-finished parts, finished and trading goods.",
    "mold": "One record per mold. Enter cavities and pieces per hour appears on every recipe that uses the mold.",
    "machine": "Presses, and the robots and dryers attached to them. Running now comes from the production log.",
    "recipe": "One row per setup: an item, a mold, a machine, the inputs and their shares, and the settings sheet. Sheet rows 2–16 are the trial block.",
    "order": "What has to be made. Each run is logged against an order; done counts the good pieces of its runs.",
    "run": "One row per job on a machine: pieces, scrap, consumed lots, and stoppages. Pieces per hour leaves out the stoppages logged on the run; target is what the recipe's cycle and cavities promise.",
    "stoppage": "Every stop, with its machine, the run it interrupted, and a cause from the list. Click a row to edit it.",
    "lot": "Received lots of materials and packaging, and lots produced by runs. Trace forward lists the runs that used a lot. Trace back, on a lot a run produced, lists the lots that run consumed.",
    "changeover": "Every time a machine went from one item to another. When no stop was logged, the time is derived from the output the shifts around "
                  "the change did not make; the last column says how. Click a row for the run that followed.",
}
TITLES = {
    "item": "Items",
    "mold": "Molds",
    "machine": "Machines",
    "recipe": "Recipes",
    "order": "Production orders",
    "run": "Production log",
    "stoppage": "Stoppages",
    "changeover": "Changeovers",
    "lot": "Lots",
}
CONFIRM = {
    "remove-input": ("Remove this input?", "The material comes off this recipe.", "Remove", True),
    "remove-scrap": ("Remove this scrap line?", "", "Remove", True),
    "remove-run-input": ("Remove this consumed lot?", "The run no longer says it used this lot.", "Remove", True),
    "delete-recipe": ("Delete this recipe?", "The setting sheet and its inputs are removed. The item and the mold stay.", "Delete recipe", True),
    "delete-order": ("Delete this order?", "Only an order without runs can be deleted.", "Delete", True),
    "clone-item": ("Clone this item?", "A copy is made with every recipe, as new rows. Runs and lots are not copied.", "Clone", False),
    "clone-recipe": ("Clone this recipe?", "A copy with the same settings and inputs is made on the same machine.", "Clone", False),
}
DIRECT = ("remove-input", "remove-scrap", "remove-run-input", "set-standard", "clone-item", "clone-recipe", "delete-recipe", "delete-order")
KPI_ICON = {
    "item": ("inventory_2", "#1e3a5f"),
    "mold": ("view_in_ar", "#7c3aed"),
    "machine": ("precision_manufacturing", "#0f766e"),
    "recipe": ("tune", "#2563eb"),
    "order": ("assignment", "#db2777"),
    "run": ("play_circle", "#16a34a"),
    "stoppage": ("build", "#dc2626"),
    "lot": ("qr_code_2", "#d97706"),
}
CREATE = {
    "item": ("New item", "new-item"),
    "mold": ("New mold", "new-mold"),
    "machine": ("New machine", "new-machine"),
    "order": ("New order", "new-order"),
    "run": ("Log a run", "add-run"),
    "stoppage": ("Log a stoppage", "add-stoppage"),
    "lot": ("Receive a lot", "receive-lot"),
}
SETTING_SECTIONS = (
    ("shift", "shifts", "shifts", "Shifts", "Each run is logged on a shift."),
    ("cause", "causes", "causes", "Stoppage causes", "Each cause sits in one of the six fishbone groups (Man, Machine, Method, Material, Measurement, Environment). Planned stops are kept apart from breakdowns. A changeover cause marks the stop as a change from one item to the next, so it gives that change its times."),
    ("reason", "reasons", "scrap-reasons", "Scrap reasons", "Each scrap line on a run has a reason."),
    ("category", "categories", "categories", "Item categories", "The role of a raw-material category decides what a recipe needs: a base input, and colorants for its color."),
    ("machineType", "machineTypes", "machine-types", "Machine types", "Presses, robots, and the other equipment kinds a machine can be."),
    ("person", "personnel", "personnel", "Personnel", "Everyone who runs machines or reports stoppages. Only roles that run machines have machine qualifications."),
    ("role", "roles", "roles", "Roles", "The jobs people hold. A role that runs machines can be named on a run and holds machine qualifications."),
    ("unit", "units", "units", "Units", "How items are counted and weighed."),
    ("attribute", "variantAttributes", "attributes", "Variant attributes",
     "Names the plant uses to tell variants of one product apart, such as customer, pack size, or color. The value is stored on the item. The SKU is that item's ERP code."),
)


_FIELDS = {}


def _list_fields():
    """What each list can filter and sort; fixed by the server code, so read once per session."""
    if not _FIELDS:
        _FIELDS.update(_call("cyclops_list_fields") or {})
    return _FIELDS
