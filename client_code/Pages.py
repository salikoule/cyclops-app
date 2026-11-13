"""Screens for the plant record. Routes call mount_*."""

import anvil.media
import anvil.server
import anvil.users
from anvil import *
from anvil.js import window
from craftify_library.CraftifyUtils import dialogs
from craftify_library.CustomComponents.ChartCard import ChartCard
from craftify_library.CustomComponents.EChart import EChart
from craftify_library.CustomComponents.KpiCard import KpiCard
from craftify_library.CraftifyUtils.echarts_theme import apply_craftify_echarts_theme
from cyclops_app import Data, Editor, Format, Layout, Nav, Tables, Tree

LEADS = {
    "item": "Every product, part, and material is an item: raw materials, packaging, semi-finished parts, finished and trading goods.",
    "mold": "One record per mold. Enter cavities and pieces per hour appears on every recipe that uses the mold.",
    "machine": "Presses, and the robots and dryers attached to them. Running now comes from the production log.",
    "recipe": "One row per setup: an item, a mold, a machine, the inputs and their shares, and the settings sheet. Sheet rows 2–16 are the trial block.",
    "order": "What has to be made. Each run is logged against an order; done counts the good pieces of its runs.",
    "run": "One row per job on a machine: pieces, scrap, consumed lots, and stoppages. Pieces per hour leaves out the stoppages logged on the run; target is what the recipe's cycle and cavities promise.",
    "stoppage": "Every stop, with its machine, the run it interrupted, and a cause from the list. Click a row to edit it.",
    "lot": "Received lots of materials and packaging, and lots produced by runs. Open a lot for its trace back to the supplier and forward to what it went into.",
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


def _call(name, *args):
    try:
        return anvil.server.call(name, *args)
    except Exception as error:
        Notification(str(error), style="danger", timeout=5).show()
        return None


_FIELDS = {}


def _list_fields():
    """What each list can filter and sort; fixed by the server code, so read once per session."""
    if not _FIELDS:
        _FIELDS.update(_call("cyclops_list_fields") or {})
    return _FIELDS


class Screen:
    def __init__(self, form, kind, code, ctx):
        self.form = form
        self.kind = kind
        self.code = code
        self.query = Nav.query(ctx)
        self.tab = self.query.get("tab") or ""
        self.data = None

    def render(self):
        if self.kind == "overview":
            self._overview()
        elif self.kind == "floor":
            self._floor()
        elif self.kind == "structure":
            self._structure()
        elif self.kind == "configure":
            self._configure_page()
        elif self.kind == "users":
            self._users()
        elif self.kind == "history":
            self._history_page()
        elif self.kind == "notify":
            self._notifications()
        elif self.kind == "account":
            self._account()
        elif self.code:
            self._detail()
        else:
            self._list()

    def show(self, *children):
        """Replace the page. A form with ``content`` keeps its other components, such as a refresh timer."""
        target = getattr(self.form, "content", None) or self.form
        target.clear()
        kept = [child for child in children if child is not None and child != ""]
        target.add_component(Layout.stack(*kept), full_width_row=True)

    def show_tabbed(self, top, tabs):
        """``top`` stays above the tab bar; ``tabs`` are (key, label, count or None, build), and only the open tab is built.
        The open tab is kept in the address (?tab=) so a refresh or a shared link opens it again."""
        tabs = [tab for tab in tabs if tab]
        if self.code and self.kind in ("item", "mold", "machine", "recipe", "order", "run", "stoppage", "lot"):
            tabs = list(tabs) + [("history", "Audit", None, lambda: [self._record_history()])]
        if not tabs:
            self.show(*top)
            return
        if self.tab not in [tab[0] for tab in tabs]:
            self.tab = tabs[0][0]
        holder = Layout.stack()

        def fill():
            holder.clear()
            build = next(tab[3] for tab in tabs if tab[0] == self.tab)
            parts = [part for part in build() if part is not None]
            if len(parts) == 1 and "card" in getattr(parts[0], "dom_nodes", {}):
                parts[0].dom_nodes["title"].style.display = "none"
            for part in parts:
                Layout.add(holder, part)

        def on_tab(mode, node):
            key = Layout.attr(node, "data-item")
            if not key or key == self.tab:
                return
            self.tab = key
            for link in node.parentElement.querySelectorAll(".cy-tab"):
                link.classList.toggle("is-active", Layout.attr(link, "data-item") == key)
            url = window.URL(window.location.href)
            url.searchParams.set("tab", key)
            window.history.replaceState(window.history.state, "", url.toString())
            fill()

        bar = '<nav class="cy-tabs">%s</nav>' % "".join(
            '<a class="cy-tab%s" href="javascript:void(0)" data-action="tab" data-item="%s">%s%s</a>'
            % (" is-active" if key == self.tab else "", key, Layout.esc(label), "" if count is None else " <span>%s</span>" % count)
            for key, label, count, _ in tabs)
        fill()
        self.show(*(list(top) + [Layout.interactive(bar, on_tab), holder]))

    def act(self, action, **extra):
        def handler(**event_args):
            self.handle(action, extra)
        return handler

    def on_html(self, mode, node):
        if mode == "nav":
            Nav.open_path(Layout.attr(node, "data-nav"))
            return
        self.handle(Layout.attr(node, "data-action"), {
            "gap": Layout.attr(node, "data-gap"),
            "route": Layout.attr(node, "data-route"),
            "index": Layout.attr(node, "data-index"),
            "item": Layout.attr(node, "data-item"),
        })

    def handle(self, action, dataset):
        if action not in ("open-gap", "tab", "") and not Data.can_write():
            Notification("You have read-only access.", style="warning", timeout=4).show()
            return
        if action in ("log-shift", "close-shift"):
            card = next((entry for entry in (self.data or {}).get("machines") or [] if entry.get("id") == dataset.get("item")), None)
            if card is None:
                return
            Editor.open_editor(self, "log-shift", {"row": card, "close": action == "close-shift"})
            return
        if action == "open-gap":
            Nav.go(dataset.get("route"), query={"gap": dataset.get("gap") or ""})
            return
        if action == "edit-input-row":
            entry = next((entry for entry in (self.data or {}).get("inputs") or [] if entry.get("id") == dataset.get("item")), None)
            if entry is not None:
                Editor.open_editor(self, "edit-input", {"row": entry})
            return
        if action in DIRECT:
            ask = CONFIRM.get(action)
            if ask and not dialogs.confirm(ask[1], title=ask[0], confirm_text=ask[2], danger=ask[3]):
                return
            problem = self.apply(action, {"index": dataset.get("index") or "", "item": dataset.get("item") or ""})
            if problem:
                Notification(problem, style="warning", timeout=5).show()
            return
        if not Editor.open_editor(self, action, dataset):
            Notification("That edit is not available on this record.", style="warning").show()

    def apply(self, action, payload, close=None):
        """Run an edit. Returns an error message, or None once the page shows the result."""
        body = {"contextKind": self.kind or "", "contextId": self.code or ""}
        body.update(payload or {})
        try:
            result = anvil.server.call("cyclops_apply", action, body)
        except Exception as error:
            return str(error) or "The change could not be saved."
        if not result:
            return "The change could not be saved."
        if result.get("error"):
            return result["error"]
        gaps = result.get("gaps") or []
        if gaps:
            Notification("Saved. Still open: %s." % "; ".join(gaps), style="warning", timeout=6).show()
        if close is not None:
            close()
        Data.invalidate()
        redirect = result.get("redirect") or {}
        if redirect.get("kind"):
            Nav.go(redirect["kind"], redirect.get("code"))
            return None
        self.render()
        return None

    def block(self, markup):
        return Layout.interactive(markup, self.on_html)

    # Overview ---------------------------------------------------------------------------------

    def _overview(self):
        data = _call("cyclops_overview", self.query.get("who") or "all")
        if not data:
            self.show(Layout.empty_state("The overview could not be loaded."))
            return
        self.data = data
        machines = data.get("machines") or []
        self.show_tabbed(
            (Layout.page_header("Plant overview", description="What runs on each machine now, from the production log, and the gaps between this record and a planner's answer."),
             self._kpis(data.get("counts") or {})),
            (("machines", "Machines", None, lambda: [self._board(machines)]),
             ("gaps", "Data gaps", len(data.get("gaps") or []), lambda: [self._gaps(data)]),
             ("stoppages", "Latest stoppages", None, lambda: [self._latest_stoppages(data.get("stoppages") or [])]),
             ("chart", "Recipes and downtime", None, lambda: [self._chart(data.get("chart") or {})])),
        )

    def _latest_stoppages(self, rows):
        if not rows:
            return None
        items = []
        for row in rows:
            hours = ("%s h" % Format.trim(row.get("hours"))) if row.get("hours") is not None else row.get("status")
            items.append(
                '<a class="cy-row cy-stop" href="javascript:void(0)" data-nav="%s"><div class="cy-when">%s</div><div class="cy-grow"><b>%s</b> <span class="cy-muted">%s</span><div class="cy-sub">%s</div></div>%s</a>'
                % (
                    Layout.esc(Nav.path("machine", row.get("machineId"))),
                    Layout.esc(Format.when(row.get("start"))),
                    Layout.esc(row.get("machine")),
                    Layout.esc(row.get("cause") or "no cause yet"),
                    Layout.esc(Format.clip(row.get("description"), 140)),
                    Format.status(hours, row.get("tone")),
                )
            )
        card = Layout.section("Latest stoppages", "Open a row for its machine.", actions=(Layout.button("All stoppages", lambda **e: Nav.go("stoppage")),))
        Layout.body(card, self.block('<div class="cy-list">%s</div>' % "".join(items)))
        return card

    def _kpis(self, counts):
        by_type = counts.get("byType") or {}
        cards = (
            ("Items", counts.get("items"), "%s parts · %s raw" % (by_type.get("SFG") or 0, by_type.get("RAW") or 0), "item"),
            ("Molds", counts.get("molds"), "", "mold"),
            ("Presses", counts.get("presses"), "%s machines in all" % (counts.get("machines") or 0), "machine"),
            ("Recipes", counts.get("liveRecipes"), "+ %s trial" % (counts.get("trialRecipes") or 0), "recipe"),
            ("Open orders", counts.get("openOrders"), "%s in all" % (counts.get("orders") or 0), "order"),
            ("Running now", counts.get("running"), "%s runs logged" % (counts.get("runs") or 0), "run"),
            ("Stoppages", counts.get("stoppages"), "%s h of downtime" % (Format.trim(counts.get("downtimeHours")) or "0"), "stoppage"),
            ("Lots", counts.get("lots"), "received and produced", "lot"),
        )
        built = []
        for title, value, subtitle, kind in cards:
            name, color = KPI_ICON[kind]
            card = KpiCard(title=title, value=Format.trim(value) or "0", subtitle=subtitle, clickable=True, icon=name, icon_color=color)
            card.set_event_handler("click", lambda kind=kind, **e: Nav.go(kind))
            built.append(card)
        return Layout.grid("repeat(auto-fit, minmax(170px, 1fr))", *built)

    def _chart(self, chart):
        card = ChartCard(title="Live recipes and downtime by machine", subtitle="Bars: live recipes, trial rows left out. Line: hours of logged stoppages.")
        options = apply_craftify_echarts_theme({
            "tooltip": {"trigger": "axis"},
            "legend": {"top": 0, "left": "center"},
            "grid": {"left": 44, "right": 52, "top": 48, "bottom": 64},
            "xAxis": {"type": "category", "data": chart.get("labels") or [], "axisLabel": {"rotate": 40, "interval": 0}},
            "yAxis": [
                {"type": "value", "minInterval": 1, "name": "Recipes"},
                {"type": "value", "name": "Hours", "splitLine": {"show": False}},
            ],
            "series": [
                {"type": "bar", "data": chart.get("values") or [], "name": "Recipes"},
                {"type": "line", "data": chart.get("downtime") or [], "name": "Downtime (h)", "yAxisIndex": 1, "smooth": False, "symbolSize": 7},
            ],
        })
        card.mount(EChart(options=options, height="280px"))
        return Layout.flat(card)

    def _board(self, machines):
        cards = []
        for machine in machines:
            if machine.get("running"):
                mounted = Layout.esc(machine.get("item"))
                detail = "%s · since %s" % (machine.get("run"), Format.when(machine.get("since")))
                if machine.get("pph"):
                    detail += " · %s pcs/h" % machine.get("pph")
            else:
                mounted = '<span class="cy-muted">No run open</span>'
                detail = ""
            if machine.get("stoppedSince"):
                detail = "stopped since %s" % Format.when(machine.get("stoppedSince"))
            change = ("changeover %s min" % Format.trim(machine.get("changeover"))) if machine.get("changeover") else "changeover unknown"
            cards.append(
                '<a class="cy-presscard%s" href="javascript:void(0)" data-nav="%s"><div class="pn">%s<small>%s</small></div><div class="mounted">%s</div><div class="sub">%s</div><div class="sub">%s · %s</div></a>'
                % (
                    "" if machine.get("running") else " cy-idle",
                    Layout.esc(Nav.path("machine", machine.get("id"))),
                    Layout.esc(machine.get("name")),
                    Layout.esc(machine.get("euromap") or ""),
                    mounted,
                    Layout.esc(detail),
                    Layout.esc(Format.plural(machine.get("recipes") or 0, "recipe")),
                    Layout.esc(change),
                )
            )
        card = Layout.section("Machines", "What is running comes from the open runs in the production log.")
        Layout.body(card, self.block('<div class="cy-board">%s</div>' % "".join(cards)))
        return card

    def _gaps(self, data):
        current = data.get("who") or "all"
        buttons = []
        for who, label in (("all", "All"), ("engineer", "Engineer"), ("planner", "Planner"), ("manager", "Manager")):
            buttons.append(Layout.button(label, lambda who=who, **e: Nav.go("overview", query=dict({"tab": "gaps"}, **({} if who == "all" else {"who": who}))), primary=who == current))
        bits = []
        for gap in data.get("gaps") or []:
            bits.append(
                '<a class="cy-gap" href="javascript:void(0)" data-action="open-gap" data-route="%s" data-gap="%s"><div class="n">%s</div><div class="t">%s</div><div class="b">%s</div><div class="cy-whos">%s</div></a>'
                % (Layout.esc(gap.get("kind")), Layout.esc(gap.get("key")), gap.get("count") or 0, Layout.esc(gap.get("title")),
                   Layout.esc(gap.get("benefit")), Format.who(gap.get("who")))
            )
        card = Layout.section("Data gaps and what closing them buys", "Counts are live: fill a field anywhere and the number drops.", actions=tuple(buttons))
        body = ['<div class="cy-gaps">%s</div>' % "".join(bits)]
        done = data.get("done") or []
        if done:
            body.append('<p class="cy-muted cy-clean">Clean: %s.</p>' % Layout.esc(" · ".join(done)))
        if not bits:
            body.insert(0, '<p class="cy-muted">Nothing open for this role.</p>')
        Layout.body(card, self.block("".join(body)))
        return card

    # Structure --------------------------------------------------------------------------------

    def _structure(self):
        data = _call("cyclops_structure")
        if not data:
            self.show(Layout.empty_state("The structure page could not be loaded."))
            return
        self.data = data
        self.show_tabbed(
            (Layout.page_header("How the records fit together", description=(
                "Every product and material is an item. A semi-finished item is made by a recipe: a mold on a machine, fed with input items in shares, "
                "with the machine's settings. A production order asks for a quantity of an item; each run of a recipe against it records pieces, "
                "scrap, stoppages, the lots it consumed, and the lots it produced.")),),
            (("records", "Records", None, lambda: [self._glossary(data)]),
             ("roles", "Who uses what", None, lambda: [self._roles()])),
        )

    def _roles(self):
        cards = (
            ("Engineer / setter", "Opens the recipe for the job: mold, machine, temperatures, injection profile, inputs and shares. Marks the standard recipe when several exist. Logs stoppages with their cause."),
            ("Planner", "Opens the item to see where it runs and at what cycle, and the machine for what it can run and what is running. Writes orders and logs runs against them."),
            ("Manager", "Uses the overview: the machines, the counts, and the gap list. Owns the ERP codes on items and materials, and traces lots."),
        )
        built = [Layout.html('<div class="cy-card"><h3>%s</h3><p>%s</p></div>' % (Layout.esc(title), Layout.esc(text))) for title, text in cards]
        card = Layout.section("Who uses what, every day")
        Layout.body(card, Layout.grid("repeat(auto-fit, minmax(240px, 1fr))", *built))
        return card

    def _glossary(self, data):
        by_type = data.get("byType") or {}
        entries = (
            ("item", "ITM", "Item · Είδος", "%s items: %s semi-finished, %s raw materials. Type RAW, PAK, SFG, FG, or TRD; a category with a role (base, colorant, additive)." % (data.get("items"), by_type.get("SFG"), by_type.get("RAW"))),
            ("mold", "MLD", "Mold · Καλούπι", "%s molds. Cavities and shot weight turn cycle times into pieces per hour and grams per piece." % data.get("molds")),
            ("machine", "MCH", "Machine · Μηχανή", "%s machines: presses, and robots attached to them." % data.get("machines")),
            ("recipe", "REC", "Recipe · Συνταγή", "%s recipes: %s live, %s trial. Sheet row 345 is REC-0345." % (data.get("recipes"), data.get("liveRecipes"), data.get("trialRecipes"))),
            ("order", "PO", "Production order · Εντολή παραγωγής", "%s orders, %s open." % (data.get("orders"), data.get("openOrders"))),
            ("run", "RUN", "Run · Παραγωγή", "%s runs. A run is a recipe on its machine for an order, on a shift, with an operator." % data.get("runs")),
            ("stoppage", "STP", "Stoppage · Στάση", "%s stoppages, %s h of downtime." % (data.get("stoppages"), Format.trim(data.get("downtimeHours")))),
            ("lot", "LOT", "Lot · Παρτίδα", "%s lots. Received lots are fed into runs; runs produce lots. Together they are the trace." % data.get("lots")),
        )
        bits = ['<a class="cy-card cy-gloss" href="javascript:void(0)" data-nav="%s"><div class="t">%s %s</div><p>%s</p></a>'
                % (Layout.esc(Nav.path(kind)), Format.id_tag(kind, code), Layout.esc(title), Layout.esc(text)) for kind, code, title, text in entries]
        card = Layout.section("Records")
        Layout.body(card, self.block('<div class="cy-glossary">%s</div>' % "".join(bits)))
        return card

    # Lists ------------------------------------------------------------------------------------

    def _list(self):
        gap = self.query.get("gap") or None
        fields = _list_fields().get(self.kind)
        if not fields:
            self.show(Layout.empty_state("The list could not be loaded."))
            return
        create = CREATE.get(self.kind)
        actions = []
        if create and Data.can_write():
            actions.append(Layout.button(create[0], self.act(create[1]), primary=True))
        if self.kind == "changeover":
            actions = [Layout.button("Derive again", self._derive_changeovers)] if Data.can_write() else []
        banner = Layout.stack()
        card = Layout.section(TITLES.get(self.kind) or "Records", LEADS.get(self.kind) or "", padded=False, actions=actions, lead=True)
        shown = {"banner": False}

        def on_reply(total, info):
            if info and not shown["banner"]:
                shown["banner"] = True
                Layout.add(banner, self.block(
                    '<div class="cy-banner"><strong>%s</strong> %s. <span class="cy-muted">%s</span><a href="javascript:void(0)" data-nav="%s">Show all</a></div>'
                    % (info.get("count") or 0, Layout.esc((info.get("title") or "")[:1].lower() + (info.get("title") or "")[1:]), Layout.esc(info.get("benefit")), Layout.esc(Nav.path(self.kind)))))

        editing = {"on_edit": self._edit_stoppage, "edit_on_click": True} if self.kind == "stoppage" else {}
        table = Tables.mount_remote(self.kind, Tables.columns_for(self.kind), fields, gap, on_reply, **editing)
        self._table = table
        footer_actions = LinearPanel(spacing_above="none", spacing_below="none")
        footer_actions.add_component(Layout.button("Download CSV", lambda **e: self._download("csv")))
        footer_actions.add_component(Layout.button("Download Excel", lambda **e: self._download("xlsx"), primary=True))
        Layout.body(card, banner, table)
        Layout.footer(card, Label(text="Exports respect the filters above."), footer_actions)
        self.show(card)

    def _download(self, fmt):
        filters = []
        table = getattr(self, "_table", None)
        if table is not None:
            try:
                filters = [{"field": item.get("field"), "value": item.get("value")}
                           for item in (table.get_header_filters() or []) if item.get("value")]
            except Exception:
                filters = []
        try:
            media = anvil.server.call("cyclops_export", self.kind, fmt, filters, self.query.get("gap") or "")
        except Exception as error:
            Notification(str(error) or "The export could not be built.", style="danger", timeout=5).show()
            return
        anvil.media.download(media)

    def _edit_stoppage(self, row):
        Editor.open_editor(self, "edit-stoppage", {"row": row})

    def _derive_changeovers(self, **event_args):
        if not dialogs.confirm("Every changeover not entered by hand is worked out again from the runs and stoppages as they are now.",
                               title="Derive the changeovers again?", confirm_text="Derive again"):
            return
        counted = _call("cyclops_derive_changeovers")
        if counted:
            Notification("%s changeovers, %s h lost." % (counted.get("found"), Format.trim(counted.get("hours lost"))), style="success", timeout=4).show()
            self.render()

    def _changeover_section(self, rows, hide=()):
        lost = sum(row.get("hours") or 0 for row in rows)
        return self._table_section("Changeovers", "%s changes · %s h of production lost · newest first. Click a row for the run that followed."
                                   % (len(rows), Format.trim(round(lost, 1))), rows, "changeover", hide, empty="No changeover found.")

    def _table_section(self, title, subtitle, rows, kind, hide=(), actions=(), height="420px", empty="Nothing yet."):
        card = Layout.section(title, subtitle, padded=not rows, actions=actions)
        if not rows:
            Layout.body(card, Layout.html('<p class="cy-muted">%s</p>' % Layout.esc(empty)))
            return card
        if kind == "stoppage":
            table = Tables.mount(rows, kind, Tables.columns_for(kind, hide), height=height if len(rows) > 8 else None,
                                 on_edit=self._edit_stoppage, edit_on_click=True)
        else:
            table = Tables.mount(rows, kind, Tables.columns_for(kind, hide), height=height if len(rows) > 8 else None)
        Layout.body(card, table)
        return card

    def _stoppage_section(self, rows, hide=(), actions=()):
        return self._table_section("Stoppages", "%s logged · newest first. Click a row to edit it." % len(rows), rows, "stoppage", hide,
                                   actions, empty="No stoppages logged.")

    def _run_section(self, rows, hide=(), actions=(), subtitle="Each job: pieces, scrap, and pieces per hour against the cycle and cavities."):
        return self._table_section("Production runs", subtitle, rows, "run", hide, actions, empty="No runs logged.")

    # Details ----------------------------------------------------------------------------------

    def _detail(self):
        data = _call("cyclops_detail", self.kind, self.code)
        if not data:
            self.show(Layout.empty_state("The record could not be loaded."))
            return
        if data.get("missing"):
            self.show(
                Layout.page_header("Not found"),
                Layout.empty_state("There is no %s with id %s." % (Nav.LABEL.get(self.kind, "record").lower(), self.code), "Back to the list", lambda **e: Nav.go(self.kind)),
            )
            return
        self.data = data
        getattr(self, "_" + self.kind)(data)

    def _meta(self, data, extra=""):
        return self.block('<div class="cy-meta">%s%s%s</div>' % (Format.id_tag(data.get("kind") or self.kind, data.get("id")),
                                                                Format.status(data.get("status"), data.get("tone")), extra))

    def _facts(self, entries):
        cells = []
        for entry in entries:
            if not entry:
                continue
            label, value, gap = entry
            cells.append('<div class="cy-fact%s"><div class="k">%s</div><div class="v">%s</div></div>' % (" cy-gap" if gap else "", Layout.esc(label), value))
        return self.block('<div class="cy-facts">%s</div>' % "".join(cells))

    def _notes(self, text):
        return self.block('<div class="cy-card cy-notes"><b>Notes.</b> %s</div>' % Layout.esc(text)) if text else None

    def _item(self, data):
        made = data.get("type") in ("SFG", "FG")
        actions = [Layout.button("Edit", self.act("edit-item"), primary=not made)]
        if data.get("type") == "SFG":
            actions += [Layout.button("Add recipe", self.act("add-recipe"), primary=True), Layout.button("New order", self.act("new-order"))]
        if made:
            actions.append(Layout.button("Clone", self.act("clone-item")))
        else:
            actions.append(Layout.button("Receive a lot", self.act("receive-lot")))
        facts = [
            ("Type", Layout.esc(data.get("typeLabel")), False),
            ("Category", Format.text(data.get("category")) + ((" <small>· %s</small>" % Layout.esc(data.get("role"))) if data.get("role") else ""), False),
            ("Unit", Format.text(data.get("uom")), False),
            ("SKU", Format.text(data.get("erpCode"), "<small>none yet</small>"), not data.get("erpCode") and made),
            ("Product", Format.link("item", data.get("parentId"), data.get("parentName")), False) if data.get("parentId") else None,
            ("Supplier", Format.text(data.get("supplier")), False) if data.get("supplier") else None,
        ]
        for entry in data.get("attributes") or []:
            if entry.get("value"):
                facts.append((entry.get("name") or "Attribute", Format.text(entry.get("value")), False))
        for entry in data.get("properties") or []:
            if entry.get("key") == "swatch" and entry.get("value"):
                facts.append((entry["label"], '<span class="cy-swatch" style="background:%s"></span> %s' % (Layout.esc(entry["value"]), Layout.esc(entry["value"].upper())), False))
            elif entry.get("value"):
                facts.append((entry["label"], Format.text(entry["value"]), False))
        if data.get("link"):
            facts.append(("Link", '<a href="%s" target="_blank" rel="noopener">Open</a>' % Layout.esc(data.get("link")), False))
        hint = "" if data.get("catalog", True) else "Written on recipes but not in the workbook's catalog sheet."
        top = (Layout.page_header(data.get("name") or "", eyebrow=data.get("id") or "", description=hint, actions=tuple(actions)),
               self._meta(data, Format.flag(data.get("typeLabel") or "")), self._facts(facts), self._notes(data.get("notes")))
        tabs = []
        if data.get("type") == "SFG":
            tabs += [
                ("flow", "Production flow", None, lambda: [self._flow_section(data)]),
                ("colors", "Colors on the machine", None, lambda: [self._machine_cards(data)]),
                ("machines", "Machines", None, lambda: [self._approved(data)]),
                ("recipes", "Recipes", len(data.get("recipes") or []), lambda: [self._table_section(
                    "All recipes", "Including trial rows.", data.get("recipes") or [], "recipe", ("item",), height="480px", empty="No recipe yet.")]),
            ]
        if made:
            tabs += [
                ("orders", "Orders", len(data.get("orders") or []), lambda: [self._table_section(
                    "Production orders", "", data.get("orders") or [], "order", ("item",), actions=(Layout.button("New order", self.act("new-order")),), empty="No orders.")]),
                ("production", "Production", len(data.get("production") or []), lambda: [self._run_section(data.get("production") or [], ("item",))]),
            ]
        if data.get("usedIn"):
            tabs += [
                ("used-in", "Used in recipes", len(data.get("usedIn") or []), lambda: [self._table_section(
                    "Recipes using it", "", data.get("usedIn") or [], "recipe", height="480px")]),
                ("made-into", "Items made from it", len(data.get("madeFrom") or []), lambda: [self._table_section(
                    "Items made from it", "", data.get("madeFrom") or [], "summary", height="480px")]),
            ]
        lot_actions = () if made else (Layout.button("Receive a lot", self.act("receive-lot")),)
        tabs.append(("lots", "Lots", len(data.get("lots") or []), lambda: [self._table_section(
            "Lots", "", data.get("lots") or [], "lot", ("item",), actions=lot_actions, empty="No lots recorded.")]))
        if data.get("parentId") or data.get("variants"):
            tabs.append(("variants", "Variants", len(data.get("variants") or []), lambda: [self._variants(data)]))
        if data.get("missingBits"):
            tabs.append(("missing", "Missing", len(data.get("missingBits")), lambda: [self._missing(data)]))
        self.show_tabbed(top, tabs)

    def _flow_section(self, data):
        card = Layout.section("Production flow", "Mold, machine, recipe, and inputs for this item.")
        Layout.body(card, Tree.FlowView(data.get("flow") or {}).component())
        return card

    def _machine_cards(self, data):
        actions = (Layout.button("Add an input", self.act("add-input")),)
        groups = []
        for group in data.get("machines") or []:
            head = [Format.pill("machine", group.get("machineId"), group.get("machineName"))]
            head += [Format.pill("mold", code, code) for code in group.get("molds") or []]
            head.append('<span class="cy-cycle">%s</span>' % Layout.esc(group.get("cycleLabel") or ""))
            if group.get("runningNow"):
                head.append(Format.flag("running now", "ok"))
            note = Format.plural(group.get("colorWays") or 0, "color way")
            if group.get("needsStandard"):
                note += " · two recipes for one color, mark one standard"
            head.append('<span class="cy-muted">%s</span>' % Layout.esc(note))
            ways = []
            for way in group.get("ways") or []:
                colors = "".join(Format.pill("item", entry.get("id"), entry.get("label")) for entry in way.get("colors") or []) or '<span class="cy-pill cy-more">Natural</span>'
                materials = "".join(Format.pill("item", entry.get("id"), entry.get("label")) for entry in way.get("materials") or []) or '<span class="cy-pill cy-more">None written</span>'
                flags = (Format.flag("standard", "std") if way.get("standard") else "") + ("" if way.get("canProduce") else Format.flag("cannot produce"))
                cycle = ""
                if way.get("showCycle"):
                    cycle = "<span>%s</span>" % ("cycle not written" if way.get("cycle") is None else Layout.esc("%s s" % Format.trim(way.get("cycle"))))
                ways.append(
                    '<article class="cy-way"><div class="cy-way-row"><span class="k">Color</span><div class="cy-pills">%s</div></div><div class="cy-way-row"><span class="k">Inputs</span><div class="cy-pills">%s</div></div><div class="cy-way-foot">%s%s<a href="javascript:void(0)" data-nav="%s">Settings</a></div></article>'
                    % (colors, materials, flags, cycle, Layout.esc(Nav.path("recipe", way.get("id"))))
                )
            groups.append('<div class="cy-mgroup"><div class="cy-mgroup-head">%s</div><div class="cy-ways">%s</div></div>' % ("".join(head), "".join(ways)))
        if groups:
            body = "".join(groups)
        elif data.get("trialCount"):
            body = '<p class="cy-muted">Only trial rows so far. Nothing confirmed for the machine.</p>'
        else:
            body = '<p class="cy-muted">No machine, no color, and no material recorded yet.</p>'
        card = Layout.section("Colors on the machine", "Each card is one version you can mold.", actions=actions)
        Layout.body(card, self.block(body))
        return card

    def _approved(self, data):
        pills = []
        for entry in data.get("approvedMachines") or []:
            if entry.get("approved") and entry.get("hasRecipe"):
                note, tone = "approved · has recipe", "ok"
            elif entry.get("approved"):
                note, tone = "approved · no recipe yet", "warn"
            else:
                note, tone = "runs here · not approved", "muted"
            pills.append('<a class="cy-approval cy-tone-%s" href="javascript:void(0)" data-nav="%s"><b>%s</b><span>%s</span></a>'
                         % (tone, Layout.esc(Nav.path("machine", entry.get("id"))), Layout.esc(entry.get("name")), Layout.esc(note)))
        body = '<div class="cy-approvals">%s</div>' % "".join(pills) if pills else '<p class="cy-muted">No machine is approved for this item yet.</p>'
        card = Layout.section("Machines this item may run on", "Approved machines, next to where a recipe exists.", actions=(Layout.button("Change", self.act("set-approved")),))
        Layout.body(card, self.block(body))
        return card

    def _missing(self, data):
        bits = data.get("missingBits") or []
        if not bits:
            return None
        rows = []
        for entry in bits:
            button = '<button type="button" class="cy-mini" data-action="%s">Add now</button>' % Layout.esc(entry["action"]) if entry.get("action") else ""
            rows.append('<div class="cy-row"><div class="cy-grow"><b>%s</b><div class="cy-sub">%s</div></div>%s</div>' % (Layout.esc(entry.get("what")), Layout.esc(entry.get("why")), button))
        card = Layout.section("Missing for this item", "And what each field would unlock.")
        Layout.body(card, self.block('<div class="cy-list">%s</div>' % "".join(rows)))
        return card

    def _mold(self, data):
        self.show_tabbed(
            (Layout.page_header(data.get("name") or "", eyebrow=data.get("id") or "", actions=(Layout.button("Edit", self.act("edit-mold")),)),
             self._meta(data),
             self._facts((
                 ("Cavities", Format.text(data.get("cavities"), "add → pcs/h"), not data.get("cavities")),
                 ("Shot weight (g)", Format.text(data.get("shotWeight"), "add → g per piece"), not data.get("shotWeight")),
                 ("Location", Format.text(data.get("location"), "add → where it is"), not data.get("location")),
             )),
             self._notes(data.get("notes"))),
            (("items", "Items", len(data.get("items") or []), lambda: [self._table_section(
                "Items made with this mold", "", data.get("items") or [], "summary", ("molds",), empty="No recipe uses this mold.")]),
             ("recipes", "Recipes", len(data.get("recipes") or []), lambda: [self._table_section(
                 "Recipes with this mold", "The item and the machine are on each row.", data.get("recipes") or [], "recipe", ("mold",))])),
        )

    def _machine(self, data):
        current = data.get("current")
        running = Format.text(None, "<small>nothing</small>")
        if current:
            running = "%s <small>· %s · since %s</small>" % (Format.link("run", current.get("id"), current.get("item")), Layout.esc(current.get("order")),
                                                           Layout.esc(Format.when(current.get("start"))))
        attached = " · ".join(Format.link("machine", entry.get("id"), entry.get("name")) for entry in data.get("attached") or [])
        self.show_tabbed(
            (Layout.page_header(data.get("name") or "", eyebrow=data.get("id") or "", description=data.get("alias") or "",
                                actions=(Layout.button("Edit", self.act("edit-machine")), Layout.button("Log a stoppage", self.act("add-stoppage")))),
            self._meta(data, Format.flag(data.get("type") or "")),
            self._facts((
                ("Running now", running, False),
                ("Attached to", Format.link("machine", data.get("attachedToId"), data.get("attachedTo")), False) if data.get("attachedToId") else None,
                ("Attached", attached, False) if attached else None,
                ("EUROMAP", Format.text(data.get("euromap")), False),
                ("Serial", Format.text(data.get("serial")), False),
                ("Year", Format.text(data.get("year")), False) if data.get("year") else None,
                ("Changeover (min)", Format.text(data.get("changeoverMin"), "add → sequencing"), not data.get("changeoverMin") and not data.get("attachedToId")),
                ("Location", Format.text(data.get("location")), False) if data.get("location") else None,
            )),
            self._notes(data.get("notes"))),
            (("items", "Items", len(data.get("items") or []), lambda: [self._table_section(
                "Items", "Items with a recipe on this machine.", data.get("items") or [], "summary", ("machines",), height="480px", empty="No item runs here yet.")]),
             ("approved", "Approved items", len(data.get("approved") or []), lambda: [self._table_section(
                 "Approved items", "Items a planner may book on this machine.", data.get("approved") or [], "item", ("machines",), height="480px", empty="No item approved here.")]),
             ("recipes", "Recipes", len(data.get("recipes") or []), lambda: [self._table_section(
                 "Recipes", "", data.get("recipes") or [], "recipe", ("machine",), height="480px", empty="No recipe on this machine.")]),
             ("production", "Production", len(data.get("production") or []), lambda: [self._run_section(data.get("production") or [], ("machine",))]),
             ("stoppages", "Stoppages", len(data.get("stoppages") or []), lambda: [self._stoppage_section(
                 data.get("stoppages") or [], ("machine",), (Layout.button("Log a stoppage", self.act("add-stoppage")),))]),
             ("changeovers", "Changeovers", len(data.get("changeovers") or []), lambda: [self._changeover_section(
                 data.get("changeovers") or [], ("machine",))])),
        )

    def _recipe(self, data):
        actions = [Layout.button("Edit settings", self.act("edit-recipe"), primary=True)]
        if not data.get("standard") and data.get("recipeStatus") == "approved":
            actions.append(Layout.button("Mark as standard", self.act("set-standard")))
        actions += [Layout.button("Log a run", self.act("add-run")), Layout.button("Clone", self.act("clone-recipe")),
                    Layout.button("Delete", self.act("delete-recipe"), danger=True)]
        siblings = " · ".join(Format.link("recipe", code, code) for code in data.get("siblings") or [])
        pph = data.get("pph")
        zones = "".join('<div class="cy-zone"><div class="k">%s</div><div class="v">%s</div></div>' % (Layout.esc(zone.get("label")), Format.text(zone.get("value")))
                        for zone in data.get("zones") or [])
        self.show_tabbed(
            (Layout.page_header("%s on %s" % (data.get("itemName") or "", data.get("machineName") or ""), eyebrow=data.get("id") or "", actions=tuple(actions)),
            self._meta(data, Format.flag("trial row") if data.get("recipeStatus") == "trial" else ""),
            self._facts((
                ("Item", Format.link("item", data.get("itemId"), data.get("itemName")), False),
                ("Machine", Format.link("machine", data.get("machineId"), data.get("machineName")), False),
                ("Mold", Format.link("mold", data.get("moldId"), data.get("moldId")), False),
                ("Cycle", "%s <small>s</small>" % Format.text(data.get("cycle")), not data.get("cycle")),
                ("Cooling", "%s <small>s</small>" % Format.text(data.get("cooling")), False),
                ("Screw", "%s <small>rpm</small>" % Format.text(data.get("screwRpm")), False),
                ("Pieces / hour", Format.text(pph) if pph else Format.text(data.get("pphHint"), "unknown"), not pph),
                ("Same color", siblings, False) if siblings else None,
            ))),
            (("sheet", "Setting sheet", None, lambda: [self._zones(data, zones), self._inputs(data), self._settings(data)]),
             ("production", "Production", len(data.get("production") or []), lambda: [self._run_section(
                 data.get("production") or [], ("machine", "item"), (Layout.button("Log a run", self.act("add-run")),))]),
             ("stoppages", "Stoppages", len(data.get("stoppages") or []), lambda: [self._stoppage_section(data.get("stoppages") or [], ("machine", "item"))])),
        )

    def _zones(self, data, zones):
        why = "Trial block: these temperatures step by 10 °C. Approve the recipe to make it live." if data.get("recipeStatus") == "trial" else "Barrel temperatures in °C."
        card = Layout.section("Barrel temperatures", why)
        Layout.body(card, self.block('<div class="cy-temps">%s</div>' % zones))
        return card

    def _inputs(self, data):
        rows = []
        for entry in data.get("inputs") or []:
            share = ("%s%%" % Format.trim(entry.get("share"))) if entry.get("share") is not None else "share ?"
            per_piece = (" · %s g per piece" % Format.trim(entry.get("perPiece"))) if entry.get("perPiece") is not None else ""
            account = ("ERP " + entry["erp"]) if entry.get("erp") else "no ERP code"
            rows.append(
                '<div class="cy-row"><span class="cy-flag cy-role-%s">%s</span><div class="cy-grow">%s<div class="cy-sub">%s · %s%s</div></div><b>%s</b>'
                '<button type="button" class="cy-mini" data-action="edit-input-row" data-item="%s">Share</button>'
                '<button type="button" class="cy-mini cy-danger" data-action="remove-input" data-item="%s">Remove</button></div>'
                % (Layout.esc(entry.get("role") or "none"), Layout.esc(entry.get("roleLabel") or "Other"), Format.link("item", entry.get("id"), entry.get("name")),
                   Layout.esc(entry.get("category")), Layout.esc(account), Layout.esc(per_piece), Layout.esc(share),
                   Layout.esc(entry.get("id")), Layout.esc(entry.get("id")))
            )
        total = data.get("shareTotal")
        subtitle = "Shares add up to %s%%." % Format.trim(total) if total is not None else "Shares of the shot are not written yet."
        body = '<div class="cy-list">%s</div>' % "".join(rows) if rows else '<p class="cy-muted">No input written. A recipe needs a base material.</p>'
        card = Layout.section("Inputs", subtitle, actions=(Layout.button("Add", self.act("add-input")),))
        Layout.body(card, self.block(body))
        return card

    def _settings(self, data):
        settings = data.get("settings") or []
        filled = sum(1 for entry in settings if entry.get("value"))
        rows = "".join("<tr><td>%s</td><td>%s</td></tr>" % (Layout.esc(entry.get("label")), Format.text(entry.get("value"), "<small>fill in</small>")) for entry in settings)
        if data.get("settingsNote"):
            rows += '<tr><td>Note</td><td>%s</td></tr>' % Layout.esc(data.get("settingsNote"))
        written = (("ΠΧ", data.get("px")), ("ΠΥ", data.get("py")), ("ΤΕΜ εκτύπωση", data.get("printPieces")),
                   ("TOT εκτύπωσης", data.get("printTotal")), ("Comment", data.get("comment")))
        written_rows = "".join("<tr><td>%s</td><td>%s</td></tr>" % (Layout.esc(label), Format.text(value)) for label, value in written)
        left = Layout.section("Injection settings", "%s of %s filled" % (filled, len(settings)), actions=(Layout.button("Edit", self.act("edit-injection"), primary=not filled),))
        Layout.body(left, self.block('<table class="cy-kv">%s</table>' % rows))
        right = Layout.html('<div class="cy-card cy-note"><h3>Written on the row, meaning to confirm</h3><table class="cy-kv">%s</table></div>' % written_rows)
        return Layout.grid("repeat(auto-fit, minmax(280px, 1fr))", left, right)

    def _order(self, data):
        progress = ("%s%%" % data.get("progress")) if data.get("progress") is not None else "—"
        self.show_tabbed(
            (Layout.page_header(data.get("item") or "", eyebrow=data.get("id") or "", description="Production order",
                               actions=(Layout.button("Log a run", self.act("add-run"), primary=True), Layout.button("Edit", self.act("edit-order")),
                                        Layout.button("Delete", self.act("delete-order"), danger=True))),
            self._meta(data),
            self._facts((
                ("Item", Format.link("item", data.get("itemId"), data.get("item")), False),
                ("Quantity", "%s <small>%s</small>" % (Format.text(Format.trim(data.get("quantity"))), Layout.esc(data.get("uom"))), False),
                ("Made", "%s <small>· %s</small>" % (Format.text(Format.trim(data.get("made"))), progress), False),
                ("Due", Layout.esc(Format.day(data.get("dueDate"))), False),
                ("ERP order", Format.text(data.get("erpOrderNo")), False),
            )),
            self._notes(data.get("notes"))),
            (("production", "Production", len(data.get("production") or []), lambda: [self._run_section(
                data.get("production") or [], ("order", "item"), (Layout.button("Log a run", self.act("add-run")),))]),
             ("lots", "Lots produced", len(data.get("lots") or []), lambda: [self._table_section(
                 "Lots produced", "", data.get("lots") or [], "lot", ("item",), empty="No lots yet.")])),
        )

    def _run(self, data):
        def metric(value, unit=""):
            return Format.text(None) if value is None else "%s%s" % (Layout.esc(Format.trim(value)), unit)

        self.show_tabbed(
            (Layout.page_header("%s on %s" % (data.get("item") or "", data.get("machine") or ""), eyebrow=data.get("id") or "",
                               actions=(Layout.button("Edit", self.act("edit-run"), primary=data.get("state") == "running"),
                                        Layout.button("Log a stoppage", self.act("add-stoppage")))),
            self._meta(data),
            self._facts((
                ("Order", Format.link("order", data.get("orderId"), data.get("orderId")), False),
                ("Recipe", Format.link("recipe", data.get("recipeId"), data.get("recipeId")), False),
                ("Machine", Format.link("machine", data.get("machineId"), data.get("machine")), False),
                ("Shift", Format.text(data.get("shift")), False),
                ("Operator", Format.text(data.get("operator")), False),
                ("Started", Layout.esc(Format.when(data.get("startedAt"))), False),
                ("Ended", Layout.esc(Format.when(data.get("endedAt"), "still running")), False),
                ("Good pieces", metric(data.get("good")), data.get("good") is None),
                ("Hours", metric(data.get("hours"), " h") + (" <small>· %s h down</small>" % Format.trim(data.get("downHours")) if data.get("downHours") else ""), False),
                ("Pieces / hour", metric(data.get("pph")) + (" <small>· target %s</small>" % data.get("target") if data.get("target") else ""), False),
                ("Vs target", metric(data.get("performance"), "%"), False),
                ("Scrap", metric(data.get("scrap")) + (" <small>· %s%%</small>" % Format.trim(data.get("scrapPct")) if data.get("scrapPct") is not None else ""), False),
            )),
            self._notes(data.get("notes"))),
            (("scrap", "Scrap", len(data.get("scrapLines") or []), lambda: [self._scrap_lines(data)]),
             ("consumed", "Lots consumed", len(data.get("inputLines") or []), lambda: [self._input_lines(data)]),
             ("produced", "Lots produced", len(data.get("outputLots") or []), lambda: [self._table_section(
                 "Lots produced", "The lots printed on the boxes of this run.", data.get("outputLots") or [], "lot", ("item", "run"),
                 actions=(Layout.button("Add", self.act("add-output-lot")),), empty="No output lot yet.")]),
             ("stoppages", "Stoppages", len(data.get("stoppages") or []), lambda: [self._stoppage_section(
                 data.get("stoppages") or [], ("machine", "item"), (Layout.button("Log a stoppage", self.act("add-stoppage")),))]),
             ("changeovers", "Changeovers", len(data.get("changeovers") or []), lambda: [self._changeover_section(
                 data.get("changeovers") or [], ("machine",))])),
        )

    def _line_list(self, rows, empty):
        return '<div class="cy-list">%s</div>' % "".join(rows) if rows else '<p class="cy-muted">%s</p>' % Layout.esc(empty)

    def _scrap_lines(self, data):
        rows = ['<div class="cy-row"><div class="cy-grow"><b>%s</b><div class="cy-sub">%s</div></div><b>%s</b>'
                '<button type="button" class="cy-mini cy-danger" data-action="remove-scrap" data-index="%s">Remove</button></div>'
                % (Layout.esc(entry.get("reason")), Layout.esc(entry.get("category")), Layout.esc(Format.trim(entry.get("quantity"))), entry.get("index"))
                for entry in data.get("scrapLines") or []]
        card = Layout.section("Scrap", "Pieces rejected, by reason.", actions=(Layout.button("Add", self.act("add-scrap")),))
        Layout.body(card, self.block(self._line_list(rows, "No scrap logged.")))
        return card

    def _input_lines(self, data):
        rows = ['<div class="cy-row"><div class="cy-grow">%s<div class="cy-sub">%s</div></div><b>%s %s</b>'
                '<button type="button" class="cy-mini cy-danger" data-action="remove-run-input" data-index="%s">Remove</button></div>'
                % (Format.link("lot", entry.get("lotId"), entry.get("lot")), Layout.esc(entry.get("item")), Layout.esc(Format.trim(entry.get("quantity"))),
                   Layout.esc(entry.get("uom")), entry.get("index"))
                for entry in data.get("inputLines") or []]
        card = Layout.section("Lots consumed", "The resin, masterbatch, and additive lots fed into this run.", actions=(Layout.button("Add", self.act("add-run-input")),))
        Layout.body(card, self.block(self._line_list(rows, "No lot recorded. Without it, this run cannot be traced to its materials.")))
        return card

    def _lot(self, data):
        facts = (
            ("Item", Format.link("item", data.get("itemId"), data.get("item")), False),
            ("Origin", Layout.esc(data.get("origin")), False),
            ("Produced by", Format.link("run", data.get("run"), data.get("run")), False) if data.get("run") else None,
            ("Received", Layout.esc(Format.when(data.get("receivedAt"))), False) if data.get("origin") == "Received" else None,
            ("Supplier batch", Format.text(data.get("supplierLot")), False) if data.get("supplierLot") else None,
            ("Quantity", "%s <small>%s</small>" % (Format.text(Format.trim(data.get("quantity"))), Layout.esc(data.get("uom"))), data.get("quantity") is None),
        )
        self.show_tabbed(
            (Layout.page_header("Lot %s" % (data.get("number") or ""), eyebrow=data.get("id") or "", description=data.get("item") or "",
                                actions=(Layout.button("Edit", self.act("edit-lot")),)),
             self._meta(data), self._facts(facts), self._notes(data.get("notes"))),
            (("back", "Trace back", None, lambda: [self._trace_back(data)]),
             ("forward", "Trace forward", len((data.get("forward") or {}).get("runs") or []), lambda: [self._trace_forward(data)])),
        )

    def _lot_label(self, lot):
        return "%s %s <span class=\"cy-muted\">%s</span>" % (Format.link("lot", lot.get("id"), lot.get("number")), Layout.esc(lot.get("item")),
                                                              Layout.esc(Format.status(lot.get("status"), lot.get("tone")) if lot.get("tone") != "ok" else ""))

    def _back_html(self, node):
        lot = node.get("lot") or {}
        run = node.get("run")
        used = (" <small>· %s %s used</small>" % (Layout.esc(Format.trim(node.get("quantity"))), Layout.esc(lot.get("uom")))) if node.get("quantity") is not None else ""
        html = "<li>%s%s" % (self._lot_label(lot), used)
        if run:
            html += ' <span class="cy-muted">made by</span> %s <small>%s · %s</small>' % (Format.link("run", run.get("id"), run.get("id")), Layout.esc(run.get("machine")),
                                                                                          Layout.esc(Format.when(run.get("start"))))
            if node.get("inputs"):
                html += "<ul>%s</ul>" % "".join(self._back_html(child) for child in node["inputs"])
            else:
                html += ' <span class="cy-flag">no consumed lot recorded</span>'
        elif lot.get("origin") == "Produced":
            html += ' <span class="cy-flag">no run recorded</span>'
        else:
            supplier = (" · batch %s" % lot.get("supplierLot")) if lot.get("supplierLot") else ""
            html += ' <span class="cy-muted">received %s%s</span>' % (Layout.esc(Format.when(lot.get("received"), "")), Layout.esc(supplier))
        return html + "</li>"

    def _forward_html(self, node):
        lot = node.get("lot") or {}
        html = "<li>%s" % self._lot_label(lot)
        runs = node.get("runs") or []
        if runs:
            html += "<ul>"
            for entry in runs:
                run = entry.get("run") or {}
                html += '<li><span class="cy-muted">into</span> %s <small>%s · %s · %s %s used</small>' % (
                    Format.link("run", run.get("id"), run.get("id")), Layout.esc(run.get("item")), Layout.esc(run.get("machine")),
                    Layout.esc(Format.trim(entry.get("quantity"))), Layout.esc(lot.get("uom")))
                if entry.get("outputs"):
                    html += "<ul>%s</ul>" % "".join(self._forward_html(child) for child in entry["outputs"])
                html += "</li>"
            html += "</ul>"
        return html + "</li>"

    def _trace_back(self, data):
        card = Layout.section("Trace back", "What this lot was made from, down to the supplier lots.")
        Layout.body(card, self.block('<ul class="cy-trace">%s</ul>' % self._back_html(data.get("back") or {})))
        return card

    def _trace_forward(self, data):
        forward = data.get("forward") or {}
        card = Layout.section("Trace forward", "What this lot went into: the runs that consumed it and the lots they made.")
        body = '<ul class="cy-trace">%s</ul>' % self._forward_html(forward) if forward.get("runs") else '<p class="cy-muted">No run has used this lot.</p>'
        Layout.body(card, self.block(body))
        return card

    # Configure --------------------------------------------------------------------------------

    def _configure_page(self):
        section = next((entry for entry in SETTING_SECTIONS if entry[2] == self.code), None)
        if section is None:
            Nav.go("configure", SETTING_SECTIONS[0][2])
            return
        data = _call("cyclops_detail", "settings", "")
        if not data:
            self.show(Layout.empty_state("The lists could not be loaded."))
            return
        self.data = data
        kind, key, slug, title, subtitle = section
        tabs = "".join('<a class="cy-tab%s" href="javascript:void(0)" data-nav="%s">%s <span>%s</span></a>' % (
            " is-active" if entry[2] == slug else "", Layout.esc(Nav.path("configure", entry[2])), Layout.esc(entry[3]), len(data.get(entry[1]) or []))
            for entry in SETTING_SECTIONS)
        rows = [self._setting_row(kind, entry) for entry in data.get(key) or []]
        card = Layout.section(title, subtitle, padded=False, actions=(Layout.button("Add", lambda **e: self._edit_setting(kind, "")),))
        Layout.body(card, Tables.mount(rows, kind, Tables.columns_for(kind), height="640px" if len(rows) > 12 else None,
                                       on_edit=lambda row: self._edit_setting(kind, row.get("id")), edit_on_click=True))
        self.show(
            Layout.page_header("Configure", description="The lists the records choose from. Retire a value instead of deleting it, so older records keep it."),
            self.block('<nav class="cy-tabs">%s</nav>' % tabs),
            card,
        )

    def _setting_row(self, kind, entry):
        retired = entry.get("status") == "retired"
        row = dict(entry, status="Retired" if retired else "Active", tone="muted" if retired else "ok")
        if kind == "cause":
            row["planned"] = "Yes" if entry.get("planned") else "No"
            row["changeover"] = "Yes" if entry.get("changeover") else "No"
        if kind == "role":
            row["runsMachines"] = "Yes" if entry.get("runsMachines") else "No"
        if kind == "category":
            row["roleLabel"] = entry.get("roleLabel") or "—"
        if kind == "person":
            row["roleLabel"] = entry.get("roleLabel") or "Not set"
            row["machines"] = ", ".join(entry.get("machines") or [])
        return row

    def _edit_setting(self, kind, code):
        key = next(section[1] for section in SETTING_SECTIONS if section[0] == kind)
        entry = next((entry for entry in (self.data or {}).get(key) or [] if entry.get("id") == code), {})
        Editor.open_editor(self, "save-setting", {"settingKind": kind, "row": entry})


    def _variants(self, data):
        rows = data.get("variants") or []
        card = self._table_section("Variants", "Items whose shared product is this one. Each keeps its own SKU.", rows, "item", empty="No variants. Set this item as the shared product on another item.")
        return card

    def _record_history(self):
        rows = _call("cyclops_history", self.kind, self.code) or []
        return self._audit_table("Audit log", "Who changed what on this record, with before and after values.", rows)

    def _audit_table(self, title, subtitle, rows):
        card = Layout.section(title, subtitle)
        if not rows:
            Layout.body(card, Layout.note("No changes recorded yet."))
            return card
        bits = [
            '<thead><tr><th>When</th><th>Who</th><th>Where</th><th>Change</th><th>Before</th><th>After</th></tr></thead><tbody>',
        ]
        for row in rows:
            lines = row.get("lines") or []
            if not lines:
                lines = [{"label": row.get("summary") or row.get("action"), "before": "—", "after": "—"}]
            for index, line in enumerate(lines):
                head = ""
                if index == 0:
                    head = '<td rowspan="%s">%s</td><td rowspan="%s">%s</td><td rowspan="%s">%s</td>' % (
                        len(lines), Layout.esc(Format.when(row.get("at"))),
                        len(lines), Layout.esc(row.get("email") or ""),
                        len(lines), Layout.esc(row.get("place") or row.get("record") or ""),
                    )
                bits.append(
                    "<tr>%s<td>%s</td><td>%s</td><td>%s</td></tr>"
                    % (head, Layout.esc(line.get("label") or ""), Layout.esc(line.get("before") or "—"), Layout.esc(line.get("after") or "—"))
                )
        bits.append("</tbody>")
        Layout.body(card, self.block('<div class="cy-audit-wrap"><table class="cy-table cy-audit">%s</table></div>' % "".join(bits)))
        return card

    def _floor(self):
        today = ""
        try:
            today = Format.now().date().isoformat()
        except Exception:
            today = ""
        data = _call("cyclops_floor", today)
        if not data:
            self.show(Layout.empty_state("The floor could not be loaded."))
            return
        self.data = data
        counts = data.get("counts") or {}
        kpis = data.get("kpis") or {}
        writable = Data.can_write() and not data.get("demo")
        cards = []
        for machine in data.get("machines") or []:
            state = machine.get("state") or "Idle"
            css = {"Running": "cy-running", "Stopped": "cy-stopped", "Idle": "cy-idle"}.get(state, "")
            title = machine.get("item") or '<span class="cy-muted">No run open</span>'
            progress = machine.get("progress")
            prog_bar = ""
            if progress is not None:
                prog_bar = (
                    '<div class="cy-prog"><div class="cy-prog-bar" style="width:%s%%"></div></div>'
                    '<div class="cy-sub">%s / %s pcs%s</div>'
                ) % (progress, Format.trim(machine.get("good")), Format.trim(machine.get("orderQty")),
                     (" · " + str(progress) + "%") if progress is not None else "")
            metrics = []
            if machine.get("mold"):
                metrics.append("Mold %s" % machine.get("mold"))
            if machine.get("cycleSec") is not None:
                metrics.append("%s s cycle" % Format.trim(machine.get("cycleSec")))
            if machine.get("pph"):
                metrics.append("%s pcs/h" % machine.get("pph"))
            if machine.get("barrelTemp"):
                metrics.append("%s °C" % machine.get("barrelTemp"))
            meta = []
            if machine.get("orderLabel") or machine.get("order"):
                meta.append("Order %s" % (machine.get("orderLabel") or machine.get("order")))
            if machine.get("recipe"):
                meta.append(machine.get("recipe"))
            if machine.get("operator"):
                meta.append(machine.get("operator"))
            if machine.get("shift"):
                meta.append(machine.get("shift"))
            if machine.get("elapsed"):
                meta.append(machine.get("elapsed"))
            stop = ""
            if machine.get("state") == "Stopped":
                stop = '<div class="cy-alert">Stopped%s%s</div>' % (
                    (" · " + Layout.esc(machine.get("cause"))) if machine.get("cause") else "",
                    (" · " + Layout.esc(machine.get("stoppedFor"))) if machine.get("stoppedFor") else "",
                )
            buttons = ""
            if writable:
                buttons = '<div class="cy-floor-actions"><button type="button" class="cy-mini" data-action="log-shift" data-item="%s">Log shift</button>' % Layout.esc(machine.get("id"))
                if machine.get("run"):
                    buttons += '<button type="button" class="cy-mini" data-action="close-shift" data-item="%s">Close shift</button>' % Layout.esc(machine.get("id"))
                buttons += "</div>"
            cards.append(
                '<article class="cy-presscard cy-floorcard %s"><div class="pn">%s %s</div>'
                '<div class="mounted">%s</div>%s<div class="cy-metrics">%s</div><div class="sub">%s</div>%s%s</article>'
                % (css, Layout.esc(machine.get("name")), Format.status(state, machine.get("tone")),
                   title, prog_bar, Layout.esc(" · ".join(metrics)), Layout.esc(" · ".join(meta)), stop, buttons)
            )
        kpi_bits = ""
        if kpis:
            kpi_bits = "".join(
                '<div class="cy-kpi"><span>%s</span><b>%s</b></div>' % (Layout.esc(label), Layout.esc(text))
                for index, (label, text) in enumerate((
                    ("Good today", kpis.get("goodToday")),
                    ("Downtime", kpis.get("downtime")),
                    ("Due this week", kpis.get("ordersDue")),
                    ("Utilization", ("%s%%" % kpis.get("utilization")) if kpis.get("utilization") is not None else "—"),
                ))
            )
        timeline = ""
        for event in data.get("timeline") or []:
            timeline += '<li class="cy-evt-%s"><span>%s</span> %s</li>' % (
                Layout.esc(event.get("tone") or "muted"), Layout.esc(event.get("at") or ""), Layout.esc(event.get("text") or ""))
        if timeline:
            timeline = '<div class="cy-card cy-timeline"><h3>Last on the floor</h3><ul>%s</ul></div>' % timeline
        demo_note = None
        if data.get("demo"):
            demo_note = Layout.html('<p class="cy-banner cy-demo">Preview data — no shift is open on the plant yet. Numbers and states are examples.</p>')
        strip = self._attention(data)
        board = Layout.section("Machines", "One card per press. Refreshes about every 20 seconds.")
        Layout.body(board, self.block('<div class="cy-board cy-floor-board">%s</div>' % "".join(cards or ['<p class="cy-muted">No machines.</p>'])))
        header = "%s running · %s idle · %s stopped" % (counts.get("running") or 0, counts.get("idle") or 0, counts.get("stopped") or 0)
        self.show(
            Layout.page_header("Live floor", description=header),
            demo_note,
            self.block('<div class="cy-floor-kpis">%s</div>' % kpi_bits) if kpi_bits else None,
            strip,
            self.block(timeline) if timeline else None,
            board,
        )

    def _attention(self, data):
        parts = []
        due = data.get("dueSoon") or []
        down = data.get("down") or []
        quiet = data.get("noGood") or []
        if due:
            items = "".join('<div class="cy-sub"><a href="javascript:void(0)" data-nav="%s">%s</a> · %s · due %s</div>'
                            % (Layout.esc(Nav.path("order", row.get("id"))), Layout.esc(row.get("id")), Layout.esc(row.get("item")), Layout.esc(row.get("due")))
                            for row in due)
            parts.append('<div class="cy-card"><h3>Orders due soon</h3>%s</div>' % items)
        if down:
            items = "".join('<div class="cy-sub"><a href="javascript:void(0)" data-nav="%s">%s</a>%s</div>'
                            % (Layout.esc(Nav.path("machine", row.get("id"))), Layout.esc(row.get("name")),
                               (" · " + Layout.esc(row.get("cause"))) if row.get("cause") else " · down")
                            for row in down)
            parts.append('<div class="cy-card"><h3>Machines down</h3>%s</div>' % items)
        if quiet:
            items = "".join('<div class="cy-sub"><a href="javascript:void(0)" data-nav="%s">%s</a> · %s · %s</div>'
                            % (Layout.esc(Nav.path("run", row.get("id"))), Layout.esc(row.get("machine")), Layout.esc(row.get("item")),
                               Layout.esc(row.get("elapsed") or "no good pieces yet"))
                            for row in quiet)
            parts.append('<div class="cy-card"><h3>No good pieces yet</h3>%s</div>' % items)
        if not parts:
            return None
        return self.block('<div class="cy-strip">%s</div>' % "".join(parts))

    def _users(self):
        data = _call("cyclops_users")
        if not data:
            self.show(Layout.empty_state("Users could not be loaded."))
            return
        self.data = data
        rows = []
        for user in data.get("users") or []:
            rows.append({
                "email": user.get("email"),
                "role": user.get("roleLabel") or user.get("role"),
                "status": "Active" if user.get("active") else "Deactivated",
                "tone": "ok" if user.get("active") else "muted",
                "screens": "All screens" if user.get("role") == "administrator" else (", ".join(user.get("screens") or []) or "Notifications and account"),
                "lastLogin": Format.when(user.get("lastLogin"), ""),
                "id": user.get("email"),
            })
        card = Layout.section("Users", "Activate an account, set its role, and choose the screens it sees. Administrator, User, and Observer are the three roles the app branches on.", padded=False)
        Layout.body(card, Tables.mount(rows, "user", [
            Tables._col("Email", "email", min_width=220, formatter=Tables._text),
            Tables._col("Role", "role", width=140, formatter=Tables._text),
            Tables._status_col(120),
            Tables._col("Screens", "screens", min_width=220, formatter=Tables._clip),
            Tables._col("Last sign-in", "lastLogin", width=160, formatter=Tables._text),
        ], height="640px" if len(rows) > 12 else None, on_edit=self._edit_user, edit_on_click=True))
        self.show(Layout.page_header("Users", description="The first signed-in account is an administrator. One active administrator always remains."), card)

    def _edit_user(self, row):
        user = next((entry for entry in (self.data or {}).get("users") or [] if entry.get("email") == row.get("email")), None)
        if user is not None:
            Editor.open_editor(self, "save-access", {"row": user})

    def _history_page(self):
        rows = _call("cyclops_history") or []
        self.show(Layout.page_header("Audit log", description="Who changed what, where, and when. Before and after values are stored for every save."),
                  self._audit_table("Latest changes", "Recipes, orders, runs, master data, and user access.", rows))

    def _notifications(self):
        rows = _call("cyclops_notifications") or []
        bits = []
        for row in rows:
            bits.append(
                '<div class="cy-row%s"><div class="cy-when">%s</div><div class="cy-grow"><b>%s</b><div class="cy-sub">%s</div></div></div>'
                % ("" if row.get("read") else " cy-unread", Layout.esc(Format.when(row.get("at"))), Layout.esc(row.get("title")), Layout.esc(row.get("body")))
            )
        card = Layout.section("Notifications", "Maintenance and breakdowns you asked to hear about.",
                              actions=(Layout.button("Mark all read", self._mark_read),))
        body = '<div class="cy-list">%s</div>' % "".join(bits) if bits else '<p class="cy-muted">Nothing yet. Turn alerts on from Account.</p>'
        Layout.body(card, self.block(body))
        self.show(Layout.page_header("Notifications"), card)

    def _mark_read(self, **event_args):
        _call("cyclops_mark_notifications")
        Data.invalidate_session()
        self.render()

    def _account(self):
        prefs = _call("cyclops_notification_prefs") or {}
        maintenance = CheckBox(text="Planned maintenance", checked=bool(prefs.get("maintenance")))
        breakdowns = CheckBox(text="Breakdowns", checked=bool(prefs.get("breakdowns")))

        def save_prefs(**event_args):
            saved = _call("cyclops_save_notification_prefs", bool(maintenance.checked), bool(breakdowns.checked))
            if saved is not None:
                Notification("Notification settings saved.", style="success", timeout=3).show()

        alerts = Layout.section("Notifications", "Stored in the app for the signed-in user. Email is sent as well when the Anvil email service can send.")
        Layout.body(alerts, maintenance, breakdowns, Layout.button("Save", save_prefs, primary=True))
        security = Layout.section("Password and two-factor authentication", "Open the account menu at the bottom of the sidebar, choose Account, then use Password and Two-factor authentication.")
        Layout.body(security, Layout.note("Notification preferences stay on this page. Everything about signing in lives in account settings."))
        self.show(Layout.page_header("Account", description=anvil.users.get_user()["email"] if anvil.users.get_user() else ""), alerts, security)


def mount_overview(form, ctx):
    Screen(form, "overview", None, ctx).render()


def mount_structure(form, ctx):
    Screen(form, "structure", None, ctx).render()


def mount_configure(form, ctx):
    Screen(form, "configure", Nav.params(ctx).get("code"), ctx).render()


def mount_list(form, kind, ctx):
    Screen(form, kind, None, ctx).render()


def mount_detail(form, kind, ctx):
    Screen(form, kind, Nav.params(ctx).get("code"), ctx).render()


def mount_floor(form, ctx):
    Screen(form, "floor", None, ctx).render()


def mount_users(form, ctx):
    Screen(form, "users", None, ctx).render()


def mount_history(form, ctx):
    Screen(form, "history", None, ctx).render()


def mount_notifications(form, ctx):
    Screen(form, "notify", None, ctx).render()


def mount_account(form, ctx):
    Screen(form, "account", None, ctx).render()


