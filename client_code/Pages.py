"""Screens for the plant record. Routes call mount_*."""

import anvil.server
from anvil import *
from craftify_library.CraftifyUtils import dialogs
from craftify_library.CustomComponents.ChartCard import ChartCard
from craftify_library.CustomComponents.EChart import EChart
from craftify_library.CustomComponents.KpiCard import KpiCard
from craftify_library.CraftifyUtils.echarts_theme import apply_craftify_echarts_theme
from cyclops_app import Data, Editor, Format, Layout, Nav, Tables, Tree

LEADS = {
    "product": "One row per name. Presses and recipes count only live rows; trial rows are shown separately. Filter Status to see what is active, incomplete, or cannot be produced.",
    "mold": "One record per mold. Cavities and shot weight start empty. Enter cavities and pieces per hour appears on every recipe that uses the mold.",
    "press": "The injection machines, in the order of the Machines sheet. On the board is the current floor entry.",
    "recipe": "One row per setup: a mold on a press, with the color and material written on that row. Sheet rows 2–16 are the trial block.",
    "material": "Grades from the material sheet, including regrind and additives, plus texts written on recipes that were not in the catalog. A setup needs at least one resin or regrind.",
    "color": "Masterbatch codes, with the accounting code when the sheet has one.",
    "issue": "Every stop logged on a recipe, from the Issues sheet and the floor. Filter by press, worker, or cause; open a row for the recipe.",
}
TITLES = {
    "product": "Products",
    "mold": "Molds",
    "press": "Presses",
    "recipe": "Recipes",
    "material": "Raw materials",
    "color": "Colors",
    "issue": "Stoppages",
}
CONFIRM = {
    "remove-link": ("Unlink these parts?", "The lid and the body stop showing each other.", "Unlink", True),
    "remove-slot": ("Remove this feed?", "The material or color comes off this recipe. Its lot goes with it.", "Remove", True),
    "remove-issue": ("Delete this stoppage?", "The record of this stop and its fix is removed from the recipe.", "Delete", True),
    "delete-recipe": ("Delete this recipe?", "The setting sheet, its feeds, and its stoppages are removed. The product and the mold stay.", "Delete recipe", True),
    "clone-product": ("Clone this product?", "A copy is made with its mold and every recipe. Stoppages are not copied.", "Clone", False),
    "clone-recipe": ("Clone this recipe?", "A copy with the same settings and feeds is made on the same press.", "Clone", False),
}
DIRECT = ("remove-link", "remove-slot", "set-standard", "clone-product", "clone-recipe", "remove-issue", "delete-recipe")
KPI_ICON = {
    "product": ("inventory_2", "#1e3a5f"),
    "mold": ("view_in_ar", "#7c3aed"),
    "press": ("precision_manufacturing", "#0f766e"),
    "recipe": ("tune", "#2563eb"),
    "variant": ("palette", "#db2777"),
    "material": ("science", "#d97706"),
    "stoppage": ("build", "#dc2626"),
}
CREATE = {
    "product": ("New product", "new-product"),
    "mold": ("New mold", "new-mold"),
    "press": ("New press", "new-press"),
    "material": ("New material", "new-material"),
    "color": ("New color", "new-color"),
}


def _call(name, *args):
    try:
        return anvil.server.call(name, *args)
    except Exception as error:
        Notification(str(error), style="danger", timeout=5).show()
        return None


class Screen:
    def __init__(self, form, kind, code, ctx):
        self.form = form
        self.kind = kind
        self.code = code
        self.query = Nav.query(ctx)
        self.data = None
        self.slot = None

    def render(self):
        self.slot = ColumnPanel(spacing_above="none", spacing_below="none")
        if self.kind == "overview":
            self._overview()
        elif self.kind == "structure":
            self._structure()
        elif self.code:
            self._detail()
        else:
            self._list()

    def show(self, *children):
        self.form.clear()
        kept = [child for child in children if child is not None]
        self.form.add_component(Layout.stack(*kept), full_width_row=True)

    def act(self, action):
        def handler(**event_args):
            self.handle(action, {})
        return handler

    def on_html(self, mode, node):
        if mode == "nav":
            Nav.open_path(Layout.attr(node, "data-nav"))
            return
        self.handle(Layout.attr(node, "data-action"), {
            "who": Layout.attr(node, "data-who"),
            "gap": Layout.attr(node, "data-gap"),
            "route": Layout.attr(node, "data-route"),
            "lidId": Layout.attr(node, "data-lid"),
            "partId": Layout.attr(node, "data-part"),
            "index": Layout.attr(node, "data-index"),
            "slotKind": Layout.attr(node, "data-kind"),
        })

    def handle(self, action, dataset):
        if action == "open-gap":
            Nav.go(Nav.kind_for(dataset.get("route")), query={"gap": dataset.get("gap") or ""})
            return
        payload = {
            "lidId": dataset.get("lidId") or "",
            "partId": dataset.get("partId") or "",
            "index": dataset.get("index") or "",
            "slotKind": dataset.get("slotKind") or "",
        }
        if action in DIRECT:
            ask = CONFIRM.get(action)
            if ask and not dialogs.confirm(ask[1], title=ask[0], confirm_text=ask[2], danger=ask[3]):
                return
            problem = self.apply(action, payload)
            if problem:
                Notification(problem, style="warning", timeout=5).show()
            return
        if not Editor.open_editor(self, action, payload):
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
        if close is not None:
            close()
        Data.invalidate()
        shell = get_open_form()
        if hasattr(shell, "refresh_counts"):
            shell.refresh_counts()
        redirect = result.get("redirect") or {}
        if redirect.get("kind"):
            Nav.go(redirect["kind"], redirect.get("code"))
            return None
        self.render()
        return None

    def block(self, markup):
        return Layout.interactive(markup, self.on_html)

    def _overview(self):
        data = _call("cyclops_overview", self.query.get("who") or "all")
        if not data:
            self.show(Layout.empty_state("The overview could not be loaded."))
            return
        self.data = data
        counts = data.get("counts") or {}
        self.show(
            Layout.page_header(
                "Plant overview",
                description="What the floor board says is mounted on each press, and the gaps between this record and a planner's answer.",
            ),
            self._kpis(counts),
            self._chart(data.get("chart") or {}),
            self._board(data.get("presses") or []),
            self._stoppages(data.get("stoppages") or []),
            self._gaps(data),
        )

    def _stoppages(self, rows):
        if not rows:
            return None
        items = []
        for row in rows:
            hours = ("%s h" % Format.trim(row.get("hours"))) if row.get("hours") is not None else row.get("status")
            items.append(
                '<a class="cy-row cy-stop" href="javascript:void(0)" data-nav="%s"><div class="cy-when">%s</div><div class="cy-grow"><b>%s</b> <span class="cy-muted">on %s</span><div class="cy-sub">%s</div></div>%s</a>'
                % (
                    Layout.esc(Nav.path("recipe", row.get("id"))),
                    Layout.esc(row.get("start") or "—"),
                    Layout.esc(row.get("product")),
                    Layout.esc(row.get("press")),
                    Layout.esc(Format.clip(row.get("cause"), 140)),
                    Format.status(hours, row.get("tone")),
                )
            )
        card = Layout.section("Latest stoppages", "From the Issues sheet and the floor. Open a row for the recipe, the fix, and the worker.",
                              actions=(Layout.button("All stoppages", lambda **e: Nav.go("issue")),))
        Layout.body(card, self.block('<div class="cy-list">%s</div>' % "".join(items)))
        return card

    def _kpis(self, counts):
        cards = (
            ("Products", counts.get("products"), "%s with a recipe" % (counts.get("withRecipe") or 0), "product", "product", None),
            ("Molds", counts.get("molds"), "One per product name today", "mold", "mold", None),
            ("Presses", counts.get("presses"), "%s on the board" % (counts.get("onBoard") or 0), "press", "press", None),
            ("Recipes", counts.get("liveRecipes"), "+ %s trial" % (counts.get("trialRecipes") or 0), "recipe", "recipe", None),
            ("Color variants", counts.get("variants"), "Distinct colors on live recipes", "product", "variant", None),
            ("Materials", counts.get("materials"), "%s colors" % (counts.get("colors") or 0), "material", "material", None),
            ("Stoppages", counts.get("stoppages"), "%s h of downtime logged" % (Format.trim(counts.get("downtimeHours")) or "0"), "issue", "stoppage", None),
        )
        built = []
        for title, value, subtitle, kind, icon, gap in cards:
            name, color = KPI_ICON[icon]
            card = KpiCard(title=title, value=Format.trim(value) or "0", subtitle=subtitle, clickable=True, icon=name, icon_color=color)
            card.set_event_handler("click", lambda kind=kind, gap=gap, **e: Nav.go(kind, query={"gap": gap} if gap else None))
            built.append(card)
        return Layout.grid("repeat(auto-fit, minmax(170px, 1fr))", *built)

    def _chart(self, chart):
        card = ChartCard(title="Live recipes and downtime by press", subtitle="Bars: live recipes, trial rows left out. Line: hours of logged stoppages.")
        labels = chart.get("labels") or []
        values = chart.get("values") or []
        downtime = chart.get("downtime") or []
        options = apply_craftify_echarts_theme({
            "tooltip": {"trigger": "axis"},
            "legend": {"top": 0, "left": "center"},
            "grid": {"left": 44, "right": 52, "top": 48, "bottom": 64},
            "xAxis": {"type": "category", "data": labels, "axisLabel": {"rotate": 40, "interval": 0}},
            "yAxis": [
                {"type": "value", "minInterval": 1, "name": "Recipes"},
                {"type": "value", "name": "Hours", "splitLine": {"show": False}},
            ],
            "series": [
                {"type": "bar", "data": values, "name": "Recipes"},
                {"type": "line", "data": downtime, "name": "Downtime (h)", "yAxisIndex": 1, "smooth": False, "symbolSize": 7},
            ],
        })
        card.mount(EChart(options=options, height="280px"))
        return Layout.flat(card)

    def _board(self, presses):
        cards = []
        for press in presses:
            if press.get("mounted"):
                mounted = Layout.esc(press.get("mounted"))
            else:
                mounted = '<span class="cy-muted">Nothing on the board</span>'
            if press.get("hasRecipe"):
                cycle = "no cycle" if press.get("cycle") is None else ("%s s" % Format.trim(press.get("cycle")))
                rate = (" · %s pcs/h" % press.get("pph")) if press.get("pph") else " · pcs/h unknown"
                detail = cycle + rate
            elif press.get("mounted"):
                detail = "no recipe for this on this press"
            else:
                detail = ""
            location = (Layout.esc(press.get("location")) + " · ") if press.get("location") else ""
            change = ("changeover %s min" % Format.trim(press.get("changeover"))) if press.get("changeover") else "changeover unknown"
            idle = " cy-idle" if press.get("idle") else ""
            cards.append(
                '<a class="cy-presscard%s" href="javascript:void(0)" data-nav="%s"><div class="pn">%s<small>%s</small></div><div class="mounted">%s</div><div class="sub">%s%s</div><div class="sub">%s · %s</div></a>'
                % (
                    idle,
                    Layout.esc(Nav.path("press", press.get("id"))),
                    Layout.esc(press.get("name")),
                    Layout.esc(press.get("euromap") or ""),
                    mounted,
                    location,
                    Layout.esc(detail),
                    Layout.esc(Format.plural(press.get("moldCount") or 0, "mold")),
                    Layout.esc(change),
                )
            )
        card = Layout.section("Presses, as the board writes them", "Source: the current floor sheet. Pieces per hour appear once a mold has a cavity count.")
        Layout.body(card, self.block('<div class="cy-board">%s</div>' % "".join(cards)))
        return card

    def _gaps(self, data):
        current = data.get("who") or "all"
        buttons = []
        for who, label in (("all", "All"), ("engineer", "Engineer"), ("planner", "Planner"), ("manager", "Manager")):
            buttons.append(Layout.button(
                label,
                lambda who=who, **e: Nav.go("overview", query={} if who == "all" else {"who": who}),
                primary=who == current,
            ))
        bits = []
        for gap in data.get("gaps") or []:
            bits.append(
                '<a class="cy-gap" href="javascript:void(0)" data-action="open-gap" data-route="%s" data-gap="%s"><div class="n">%s</div><div class="t">%s</div><div class="b">%s</div><div class="cy-whos">%s</div></a>'
                % (
                    Layout.esc(gap.get("route")),
                    Layout.esc(gap.get("key")),
                    gap.get("count") or 0,
                    Layout.esc(gap.get("title")),
                    Layout.esc(gap.get("benefit")),
                    Format.who(gap.get("who")),
                )
            )
        card = Layout.section(
            "Data gaps and what closing them buys",
            "Counts are live: fill a field anywhere and the number drops.",
            actions=tuple(buttons),
        )
        body = ['<div class="cy-gaps">%s</div>' % "".join(bits)]
        done = data.get("done") or []
        if done:
            body.append('<p class="cy-muted cy-clean">Clean: %s.</p>' % Layout.esc(" · ".join(done)))
        if not bits:
            body.insert(0, '<p class="cy-muted">Nothing open for this role.</p>')
        Layout.body(card, self.block("".join(body)))
        return card

    def _structure(self):
        data = _call("cyclops_structure")
        if not data:
            self.show(Layout.empty_state("The structure page could not be loaded."))
            return
        self.data = data
        self.show(
            Layout.page_header(
                "How the records fit together",
                description="A product is one name. It is made by a mold. The mold is mounted on a press. One way of running that mold on that press — material, color, and settings — is a recipe. The row number is kept, so sheet row 345 is REC-0345. The colors on a product's recipes are its color variants.",
            ),
            self._roles(),
            self._glossary(data),
        )

    def _roles(self):
        cards = (
            ("Engineer / setter", "Opens the recipe for the job: mold, press, temperatures, injection profile, material and masterbatch with lots. Marks the standard recipe when several exist. Enters cavities and shot weight on the mold."),
            ("Planner", "Opens the product to see where it runs and at what cycle, and the press to see what it can run and what is mounted. Needs cavities, for pieces per hour, and changeover times."),
            ("Manager", "Uses the overview: the board, the counts, and the gap list with the benefit of closing each one. Owns ERP codes on products and accounting codes on materials."),
        )
        built = []
        for title, copy in cards:
            built.append(Layout.html('<div class="cy-card"><h3>%s</h3><p>%s</p></div>' % (Layout.esc(title), Layout.esc(copy))))
        card = Layout.section("Who uses what, every day")
        Layout.body(card, Layout.grid("repeat(auto-fit, minmax(240px, 1fr))", *built))
        return card

    def _glossary(self, data):
        entries = (
            ("product", "product", "PRD", "Product · Προϊόν", "%s names. Fields: name, type (part, lid, set), ERP code, notes. A product has one mold today; the model allows more." % data.get("products")),
            ("product", "color", "V", "Color variant · Χρωματική παραλλαγή", "Derived from the distinct color sets on a product's recipes. Shown on the product until the ERP codes for variants are known."),
            ("mold", "mold", "MLD", "Mold · Καλούπι", "%s molds. Cavities, shot weight, location, and status are the fields the workbook left empty." % data.get("molds")),
            ("press", "press", "PRS", "Press · Πρέσα", "%s machines with serial, robot, EUROMAP class, and the board entry. Changeover time is the field to add." % data.get("presses")),
            ("recipe", "recipe", "REC", "Recipe · Συνταγή", "%s recipes: mold + press + feed + settings. %s are live and %s are trial rows. One recipe in a color group can be marked standard." % (data.get("recipes"), data.get("liveRecipes"), data.get("trialRecipes"))),
            ("material", "material", "MAT", "Raw material · Color", "%s materials, including regrind and additives, and %s masterbatch codes. %s lid–body links are name matches so far." % (data.get("materials"), data.get("colors"), data.get("links"))),
        )
        bits = []
        for nav_kind, tag_kind, code, title, copy in entries:
            bits.append(
                '<a class="cy-card cy-gloss" href="javascript:void(0)" data-nav="%s"><div class="t">%s %s</div><p>%s</p></a>'
                % (Layout.esc(Nav.path(nav_kind)), Format.id_tag(tag_kind, code), Layout.esc(title), Layout.esc(copy))
            )
        card = Layout.section("Records")
        Layout.body(card, self.block('<div class="cy-glossary">%s</div>' % "".join(bits)))
        return card

    def _list(self):
        gap = self.query.get("gap") or None
        data = _call("cyclops_list", self.kind, gap)
        if not data or data.get("error"):
            self.show(Layout.empty_state((data or {}).get("error") or "The list could not be loaded."))
            return
        self.data = data
        create = CREATE.get(self.kind)
        actions = (Layout.button(create[0], self.act(create[1]), primary=True),) if create else ()
        banner = None
        info = data.get("banner")
        if info:
            banner = self.block(
                '<div class="cy-banner"><strong>%s</strong> %s. <span class="cy-muted">%s</span><a href="javascript:void(0)" data-nav="%s">Show all</a></div>'
                % (info.get("count") or 0, Layout.esc((info.get("title") or "").lower()), Layout.esc(info.get("benefit")), Layout.esc(Nav.path(self.kind)))
            )
        table_card = Layout.section(TITLES.get(self.kind) or "Records", "%s rows" % len(data.get("rows") or []), padded=False)
        Layout.body(table_card, Tables.mount(data.get("rows") or [], self.kind, Tables.columns_for(self.kind)))
        self.show(
            Layout.page_header(TITLES.get(self.kind) or "Records", description=LEADS.get(self.kind) or "", actions=actions),
            self.slot,
            banner,
            table_card,
        )

    def _detail(self):
        data = _call("cyclops_detail", self.kind, self.code)
        if not data:
            self.show(Layout.empty_state("The record could not be loaded."))
            return
        if data.get("missing"):
            self.show(
                Layout.page_header("Not found"),
                Layout.empty_state("There is no %s with id %s." % (Nav.LABEL.get(self.kind, "record"), self.code), "Back to the list", lambda **e: Nav.go(self.kind)),
            )
            return
        self.data = data
        if self.kind == "product":
            self._product(data)
        elif self.kind == "mold":
            self._mold(data)
        elif self.kind == "press":
            self._press(data)
        elif self.kind == "recipe":
            self._recipe(data)
        elif self.kind == "material":
            self._material(data)
        else:
            self._color(data)

    def _meta(self, data, extra=""):
        return self.block(
            '<div class="cy-meta">%s%s%s</div>'
            % (Format.id_tag(data.get("kind") or self.kind, data.get("id")), Format.status(data.get("status"), data.get("tone")), extra)
        )

    def _facts(self, items):
        cells = []
        for item in items:
            if not item:
                continue
            label, value, gap = item
            cells.append('<div class="cy-fact%s"><div class="k">%s</div><div class="v">%s</div></div>' % (" cy-gap" if gap else "", Layout.esc(label), value))
        return self.block('<div class="cy-facts">%s</div>' % "".join(cells))

    def _product(self, data):
        mold = data.get("mold") or {}
        mold_value = "none yet"
        if mold:
            cavities = ("%s cav." % mold.get("cavities")) if mold.get("cavities") else "cavities ?"
            mold_value = "%s <small>· %s</small>" % (Format.link("mold", mold.get("id"), mold.get("id")), Layout.esc(cavities))
        header_actions = (
            Layout.button("Edit", self.act("edit-product")),
            Layout.button("Add recipe", self.act("add-recipe"), primary=True),
            Layout.button("Clone", self.act("clone-product")),
        )
        self.show(
            Layout.page_header(data.get("name") or "", eyebrow=data.get("id") or "", description=data.get("typeLabel") or "", actions=header_actions),
            self._meta(data, Format.flag(data.get("typeLabel") or "")),
            self.slot,
            self._facts((
                ("ERP code", Format.text(data.get("erpCode"), "<small>none yet</small>"), not data.get("erpCode")),
                ("Sheet id", Format.text(data.get("legacyId")), False),
                ("Mold", mold_value if mold else "<small>none</small>", not mold),
            )),
            self._flow_section(data),
            self._runs(data),
            self._approved(data),
            self._missing(data),
            self._recipe_section("All recipes", "Including trial rows.", data.get("recipes") or [], hide=("product",)),
            self._issue_section("Stoppages on this product", data.get("issues") or [], hide=("product",)),
            self.block('<div class="cy-card cy-notes"><b>Notes.</b> %s</div>' % Layout.esc(data.get("notes"))) if data.get("notes") else None,
        )

    def _flow_section(self, data):
        card = Layout.section("Production flow", "The picture of mold, press, recipe, material, and color for this product.")
        Layout.body(card, Tree.FlowView(data.get("flow") or {}).component())
        return card

    def _runs(self, data):
        actions = (
            Layout.button("Add a color", self.act("add-color")),
            Layout.button("Add a material", self.act("add-material")),
            Layout.button("Link a part", self.act("add-link")),
        )
        runs = data.get("runs") or []
        groups = []
        for run in runs:
            head = [Format.pill("press", run.get("pressId"), run.get("pressName"))]
            if run.get("moldId"):
                head.append(Format.pill("mold", run.get("moldId"), run.get("moldId")))
            head.append('<span class="cy-cycle">%s</span>' % Layout.esc(run.get("cycleLabel") or ""))
            if run.get("onBoard"):
                head.append(Format.flag("mounted now", "ok"))
            note = Format.plural(run.get("colorWays") or 0, "color way")
            if run.get("needsStandard"):
                note += " · two settings for one color, mark one standard"
            head.append('<span class="cy-muted">%s</span>' % Layout.esc(note))
            ways = []
            for way in run.get("ways") or []:
                colors = "".join(Format.pill("color", item.get("id"), item.get("label")) for item in (way.get("colors") or [])) or '<span class="cy-pill cy-more">None written</span>'
                materials = "".join(Format.pill("material", item.get("id"), item.get("label")) for item in (way.get("materials") or [])) or '<span class="cy-pill cy-more">None written</span>'
                flags = ""
                if way.get("standard"):
                    flags += Format.flag("standard", "std")
                if not way.get("canProduce"):
                    flags += Format.flag("cannot produce")
                cycle = ""
                if way.get("showCycle"):
                    cycle = "<span>%s</span>" % ("cycle not written" if way.get("cycle") is None else Layout.esc("%s s" % Format.trim(way.get("cycle"))))
                ways.append(
                    '<article class="cy-way"><div class="cy-way-row"><span class="k">Color</span><div class="cy-pills">%s</div></div><div class="cy-way-row"><span class="k">Material</span><div class="cy-pills">%s</div></div><div class="cy-way-foot">%s%s<a href="javascript:void(0)" data-nav="%s">Settings</a></div></article>'
                    % (colors, materials, flags, cycle, Layout.esc(Nav.path("recipe", way.get("id"))))
                )
            groups.append('<div class="cy-run"><div class="cy-run-head">%s</div><div class="cy-ways">%s</div></div>' % ("".join(head), "".join(ways)))
        if groups:
            body = "".join(groups)
        elif data.get("trialCount"):
            body = '<p class="cy-muted">Only trial rows so far. Nothing confirmed for the machine.</p>'
        else:
            body = '<p class="cy-muted">No machine, no color, and no material recorded yet.</p>'
        links = data.get("links") or []
        if links:
            parts = ['<div class="cy-with"><span class="k">Goes with</span>']
            for item in links:
                parts.append(Format.pill("product", item.get("otherId"), item.get("otherName")))
                parts.append('<span class="cy-muted">%s</span>' % Layout.esc(item.get("text") or ""))
                parts.append('<button type="button" class="cy-mini" data-action="remove-link" data-lid="%s" data-part="%s">Unlink</button>' % (Layout.esc(item.get("lidId")), Layout.esc(item.get("partId"))))
            parts.append("</div>")
            goes = "".join(parts)
        else:
            goes = '<p class="cy-muted">Stands alone. Link a lid or a body if this part is sold with another.</p>'
        card = Layout.section("Colors on the machine", "Each card is one version you can mold.", actions=actions)
        Layout.body(card, self.block(body + goes))
        return card

    def _approved(self, data):
        rows = data.get("approvedPresses") or []
        pills = []
        for row in rows:
            if row.get("approved") and row.get("hasRecipe"):
                note, tone = "approved · has recipe", "ok"
            elif row.get("approved"):
                note, tone = "approved · no recipe yet", "warn"
            else:
                note, tone = "runs here · not on the sheet", "muted"
            pills.append(
                '<a class="cy-approval cy-tone-%s" href="javascript:void(0)" data-nav="%s"><b>%s</b><span>%s</span></a>'
                % (tone, Layout.esc(Nav.path("press", row.get("id"))), Layout.esc(row.get("name")), Layout.esc(note))
            )
        body = '<div class="cy-approvals">%s</div>' % "".join(pills) if pills else '<p class="cy-muted">No press is approved on the product sheet yet.</p>'
        card = Layout.section(
            "Presses this product may run on",
            "From the product sheet's press columns, next to where a recipe exists.",
            actions=(Layout.button("Change", self.act("set-approved")),),
        )
        Layout.body(card, self.block(body))
        return card

    def _issue_section(self, title, rows, hide=(), actions=()):
        if not rows and not actions:
            return None
        card = Layout.section(title, "%s logged · newest first. Open a row for the recipe." % len(rows), padded=False, actions=actions)
        if rows:
            Layout.body(card, Tables.mount(rows, "issue", Tables.columns_for("issue", hide), height="360px"))
        else:
            Layout.body(card, Layout.html('<p class="cy-muted cy-pad">No stoppages logged.</p>'))
        return card

    def _missing(self, data):
        bits = data.get("missingBits") or []
        if not bits:
            return None
        rows = []
        for item in bits:
            button = ""
            if item.get("action"):
                button = '<button type="button" class="cy-mini" data-action="%s">Add now</button>' % Layout.esc(item.get("action"))
            rows.append('<div class="cy-row"><div class="cy-grow"><b>%s</b><div class="cy-sub">%s</div></div>%s</div>' % (Layout.esc(item.get("what")), Layout.esc(item.get("why")), button))
        card = Layout.section("Missing for this product", "And what each field would unlock.")
        Layout.body(card, self.block('<div class="cy-list">%s</div>' % "".join(rows)))
        return card

    def _recipe_section(self, title, subtitle, rows, hide=()):
        card = Layout.section(title, subtitle, padded=False)
        Layout.body(card, Tables.mount(rows, "recipe", Tables.columns_for("recipe", hide), height="480px"))
        return card

    def _mold(self, data):
        self.show(
            Layout.page_header(data.get("name") or "", eyebrow=data.get("id") or "", actions=(Layout.button("Edit", self.act("edit-mold")),)),
            self._meta(data),
            self.slot,
            self._facts((
                ("Makes", Format.link("product", data.get("productId"), data.get("productName")), False),
                ("Cavities", Format.text(data.get("cavities"), "add → pcs/h"), not data.get("cavities")),
                ("Shot weight (g)", Format.text(data.get("shotWeight"), "add → g per piece"), not data.get("shotWeight")),
                ("Location", Format.text(data.get("location"), "add → where it is"), not data.get("location")),
            )),
            self._recipe_section("Recipes with this mold", "The product and the presses are on each row.", data.get("recipes") or []),
        )

    def _press(self, data):
        robot = data.get("robot") or "none"
        mounted = Format.text(data.get("mounted"), "<small>nothing</small>")
        if data.get("location"):
            mounted += " <small>· %s</small>" % Layout.esc(data.get("location"))
        self.show(
            Layout.page_header(data.get("name") or "", eyebrow=data.get("id") or "", description=data.get("alias") or "", actions=(Layout.button("Edit", self.act("edit-press")),)),
            self._meta(data),
            self.slot,
            self._facts((
                ("On the board", mounted, not data.get("mounted")),
                ("EUROMAP", Format.text(data.get("euromap")), False),
                ("Serial", Format.text(data.get("serial")), False),
                ("Robot", Format.text(robot) + ((" <small>· %s</small>" % Layout.esc(data.get("robotYear"))) if data.get("robotYear") else ""), False),
                ("Changeover (min)", Format.text(data.get("changeoverMin"), "add → sequencing"), not data.get("changeoverMin")),
            )),
            self._tabs((
                ("Products", "summary", data.get("products") or [], ("presses",)),
                ("Approved products", "summary", data.get("approved") or [], ("presses",)),
                ("Recipes", "recipe", data.get("recipes") or [], ("press",)),
                ("Stoppages", "issue", data.get("issues") or [], ("press",)),
            )),
        )

    def _recipe(self, data):
        actions = [Layout.button("Edit settings", self.act("edit-recipe"), primary=True)]
        if not data.get("standard") and not data.get("trial"):
            actions.append(Layout.button("Mark as standard", self.act("set-standard")))
        actions.append(Layout.button("Clone", self.act("clone-recipe")))
        actions.append(Layout.button("Delete", self.act("delete-recipe"), danger=True))
        siblings = data.get("siblings") or []
        sibling_html = " · ".join(Format.link("recipe", code, code) for code in siblings)
        pph = data.get("pph")
        pph_html = Format.text(pph) if pph else Format.text(data.get("pphHint"), "unknown")
        zones = []
        for zone in data.get("zones") or []:
            zones.append('<div class="cy-zone"><div class="k">%s</div><div class="v">%s</div></div>' % (Layout.esc(zone.get("label")), Format.text(zone.get("value"))))
        self.show(
            Layout.page_header(
                "%s on %s" % (data.get("productName") or "", data.get("pressName") or ""),
                eyebrow=data.get("id") or "",
                actions=tuple(actions),
            ),
            self._meta(data, Format.flag("trial row") if data.get("trial") else ""),
            self.slot,
            self._facts((
                ("Mold", Format.link("mold", data.get("moldId"), data.get("moldId")), False),
                ("Cycle", "%s <small>s</small>" % Format.text(data.get("cycle")), not data.get("cycle")),
                ("Cooling", "%s <small>s</small>" % Format.text(data.get("cooling")), False),
                ("Screw", "%s <small>rpm</small>" % Format.text(data.get("screwRpm")), False),
                ("Pieces / hour", pph_html, not pph),
                ("Last product lot", Format.text(data.get("productLot")), False),
                ("Sheet row", Format.text(data.get("legacyId")), False) if data.get("legacyId") else None,
                ("Same color", sibling_html, False) if siblings else None,
            )),
            self._zones(data, zones),
            self._feeds(data),
            self._settings(data),
            self._recipe_issues(data),
        )

    def _recipe_issues(self, data):
        rows = []
        for item in data.get("issues") or []:
            hours = ("%s h" % Format.trim(item.get("hours"))) if item.get("hours") is not None else item.get("status")
            who = (" · " + Layout.esc(item.get("worker"))) if item.get("worker") else ""
            rows.append(
                '<div class="cy-row cy-stop"><div class="cy-when">%s<small class="%s">%s</small></div><div class="cy-grow"><b>%s</b><div class="cy-sub">%s%s</div></div>%s'
                '<button type="button" class="cy-mini" data-action="edit-issue" data-index="%s">Edit</button>'
                '<button type="button" class="cy-mini cy-danger" data-action="remove-issue" data-index="%s">Delete</button></div>'
                % (
                    Layout.esc(item.get("start") or "—"),
                    "cy-bad-date" if item.get("tone") == "bad" else "",
                    Layout.esc(("→ " + item.get("end")) if item.get("end") else "still down"),
                    Layout.esc(item.get("cause")),
                    Layout.esc(item.get("fix") or "No fix written"),
                    who,
                    Format.status(hours, item.get("tone")),
                    item.get("index"),
                    item.get("index"),
                )
            )
        body = '<div class="cy-list">%s</div>' % "".join(rows) if rows else '<p class="cy-muted">No stoppages logged on this recipe.</p>'
        card = Layout.section("Stoppages", "Breakdowns while this recipe ran: what stopped, who reported it, what was done.",
                              actions=(Layout.button("Log a stoppage", self.act("add-issue")),))
        Layout.body(card, self.block(body))
        return card

    def _zones(self, data, zones):
        why = "Trial block: these temperatures step by 10 °C. Saving the settings confirms the row." if data.get("trial") else "Barrel temperatures in °C."
        card = Layout.section("Barrel temperatures", why)
        Layout.body(card, self.block('<div class="cy-temps">%s</div>' % "".join(zones)))
        return card

    def _feeds(self, data):
        def rows(items, kind):
            if not items:
                return '<div class="cy-row cy-empty">None written</div>'
            html = []
            for item in items:
                account = ("acc. " + item.get("account")) if item.get("account") else "no accounting code"
                html.append(
                    '<div class="cy-row">%s<div class="cy-grow">%s<div class="cy-sub">%s · lot %s</div></div><button type="button" class="cy-mini cy-danger" data-action="remove-slot" data-kind="%s" data-index="%s">Remove</button></div>'
                    % (
                        Format.id_tag(kind, item.get("id")),
                        Format.link(kind, item.get("id"), item.get("name")),
                        Layout.esc(account),
                        Layout.esc(item.get("lot") or "—"),
                        kind,
                        item.get("index"),
                    )
                )
            return "".join(html)

        left = Layout.section("Raw materials fed", actions=(Layout.button("Add", self.act("add-slot-material")),))
        Layout.body(left, self.block('<div class="cy-list">%s</div>' % rows(data.get("materialSlots") or [], "material")))
        right = Layout.section("Colors fed", actions=(Layout.button("Add", self.act("add-slot-color")),))
        Layout.body(right, self.block('<div class="cy-list">%s</div>' % rows(data.get("colorSlots") or [], "color")))
        return Layout.grid("repeat(auto-fit, minmax(280px, 1fr))", left, right)

    def _settings(self, data):
        settings = data.get("settings") or []
        if settings:
            setting_rows = "".join("<tr><td>%s</td><td>%s</td></tr>" % (Layout.esc(item.get("label")), Layout.esc(item.get("value"))) for item in settings)
        else:
            setting_rows = '<tr><td colspan="2" class="cy-muted">No injection row filled</td></tr>'
        if data.get("settingsNote"):
            setting_rows += '<tr><td>Note</td><td>%s</td></tr>' % Layout.esc(data.get("settingsNote"))
        written = (
            ("ΠΧ", data.get("px")),
            ("ΠΥ", data.get("py")),
            ("ΤΕΜ εκτύπωση", data.get("printPieces")),
            ("TOT εκτύπωσης", data.get("printTotal")),
            ("Κατάσταση", data.get("statusText")),
            ("Comment", data.get("comment")),
        )
        written_rows = "".join("<tr><td>%s</td><td>%s</td></tr>" % (Layout.esc(label), Format.text(value)) for label, value in written)
        left = Layout.html('<div class="cy-card"><h3>Injection settings</h3><table class="cy-kv">%s</table></div>' % setting_rows)
        right = Layout.html('<div class="cy-card cy-note"><h3>Written on the row, meaning to confirm</h3><table class="cy-kv">%s</table></div>' % written_rows)
        return Layout.grid("repeat(auto-fit, minmax(280px, 1fr))", left, right)

    def _material(self, data):
        link = ""
        if data.get("link"):
            link = '<a href="%s" target="_blank" rel="noopener">Open</a>' % Layout.esc(data.get("link"))
        facts = [
            ("Type", Format.text(data.get("kindLabel")), False),
            ("Supplier", Format.text(data.get("supplier")), False),
            ("Family", Format.text(data.get("family")), False),
            ("MFI", Format.text(data.get("mfi")), False),
            ("Accounting", Format.text(data.get("account"), "<small>missing</small>"), not data.get("account")),
        ]
        if link:
            facts.append(("Datasheet", link, False))
        if data.get("invoiceCode"):
            facts.append(("Invoice code", Format.text(data.get("invoiceCode")), False))
        lines = [("Description", data.get("description")), ("Notes", data.get("notes"))]
        text = "<br>".join("<b>%s.</b> %s" % (label, Layout.esc(value)) for label, value in lines if value)
        description = self.block('<div class="cy-card cy-notes">%s</div>' % text) if text else None
        self.show(
            Layout.page_header(data.get("name") or "", eyebrow=data.get("id") or "",
                               description="" if data.get("catalog") else "Written on recipes but not in the material sheet.",
                               actions=(Layout.button("Edit", self.act("edit-material"), primary=not data.get("account")),)),
            self._meta(data),
            self._facts(tuple(facts)),
            description,
            self._tabs((
                ("Products", "summary", data.get("products") or [], ()),
                ("Recipes", "recipe", data.get("recipes") or [], ()),
            )),
        )

    def _color(self, data):
        link = ('<a href="%s" target="_blank" rel="noopener">Open</a>' % Layout.esc(data.get("link"))) if data.get("link") else ""
        self.show(
            Layout.page_header(data.get("name") or "", eyebrow=data.get("id") or "",
                               description="" if data.get("catalog") else "Written on recipes but not in the colour sheet.",
                               actions=(Layout.button("Edit", self.act("edit-color"), primary=not data.get("account")),)),
            self._meta(data),
            self._facts((
                ("Label", Format.text(data.get("label")), False),
                ("Label code", Format.text(data.get("code")), False),
                ("Shade", Format.text(data.get("shade")), False) if data.get("shade") else None,
                ("Accounting", Format.text(data.get("account"), "<small>missing</small>"), not data.get("account")),
                ("Sample", link, False) if link else None,
            )),
            self.block('<div class="cy-card cy-notes"><b>Notes.</b> %s</div>' % Layout.esc(data.get("notes"))) if data.get("notes") else None,
            self._tabs((
                ("Products", "summary", data.get("products") or [], ()),
                ("Recipes", "recipe", data.get("recipes") or [], ()),
            )),
        )

    def _tabs(self, tabs):
        bar = FlowPanel(spacing="small", align="left")
        panels = []
        buttons = []
        tables = []
        for index, (label, kind, rows, hide) in enumerate(tabs):
            button = Layout.button(label, lambda index=index, **e: _select(index), primary=index == 0)
            buttons.append(button)
            bar.add_component(button)
            panel = ColumnPanel(spacing_above="none", spacing_below="none", visible=index == 0)
            table = Tables.mount(rows, "product" if kind == "summary" else kind, Tables.columns_for(kind, hide), height="480px")
            button.text = "%s · %s" % (label, len(rows))
            panel.add_component(table, full_width_row=True)
            panels.append(panel)
            tables.append(table)

        def _select(index):
            for position, panel in enumerate(panels):
                panel.visible = position == index
            for position, button in enumerate(buttons):
                button.role = "primary-color" if position == index else None
            try:
                tables[index].redraw(True)
            except Exception:
                pass

        holder = Layout.html('<div class="cy-tabbar" anvil-slot="default"></div>')
        holder.add_component(bar)
        card = Layout.section("Where it is used", padded=False)
        Layout.body(card, holder, *panels)
        return card


def mount_overview(form, ctx):
    Screen(form, "overview", None, ctx).render()


def mount_structure(form, ctx):
    Screen(form, "structure", None, ctx).render()


def mount_list(form, kind, ctx):
    Screen(form, kind, None, ctx).render()


def mount_detail(form, kind, ctx):
    Screen(form, kind, Nav.params(ctx).get("code"), ctx).render()
