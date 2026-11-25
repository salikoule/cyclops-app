"""List and detail screens for the plant record."""

import anvil.media
import anvil.server
from .common import _list_fields, CREATE, LEADS, TITLES
from anvil import *
from craftify_library.CraftifyUtils import dialogs
from cyclops_app.session import Data
from cyclops_app.ui import Editor
from cyclops_app.ui import Format
from cyclops_app.ui import Layout
from cyclops_app.ui import Nav
from cyclops_app.ui import Tables
from cyclops_app.ui import Tree
from cyclops_app.ui.query import call as _call


_ROW_ACTIONS = {
    "order": ("edit-order", "delete-order", "Delete this order?", "Only an order without runs can be deleted."),
    "run": ("edit-run", "delete-run", "Delete this run?",
            "Its scrap, consumed lots, and output lots are removed. Its stoppages stay on the machine."),
    "stoppage": ("edit-stoppage", "delete-stoppage", "Delete this stoppage?", "The record of this stop and its fix is removed."),
}


class Record:
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
        menu = self._row_menu(self.kind) if self.kind in _ROW_ACTIONS and Data.can_write() else None
        table = Tables.mount_remote(self.kind, Tables.columns_for(self.kind), fields, gap, on_reply,
                                    on_excel=self._download_excel, on_menu=menu, **editing)
        self._table = table
        Layout.body(card, banner, table)
        self.show(card)

    def _download_excel(self):
        filters = []
        table = getattr(self, "_table", None)
        if table is not None:
            try:
                filters = [{"field": item.get("field"), "value": item.get("value")}
                           for item in (table.get_header_filters() or []) if item.get("value")]
            except Exception:
                filters = []
        try:
            media = anvil.server.call("cyclops_export", self.kind, "xlsx", filters, self.query.get("gap") or "")
        except Exception as error:
            Notification(str(error) or "The export could not be built.", style="danger", timeout=5).show()
            return
        anvil.media.download(media)

    def _row_menu(self, kind):
        def handler(action, row):
            self._row_action(kind, action, row)
        return handler

    def _row_action(self, kind, action, row):
        spec = _ROW_ACTIONS.get(kind)
        code = (row or {}).get("id")
        if spec is None or not code:
            return
        edit_action, delete_action, question, detail = spec
        if action == "delete":
            if not dialogs.confirm(detail, title=question, confirm_text="Delete", danger=True):
                return
            payload = {"contextKind": kind, "contextId": code}
            if kind == "stoppage":
                payload["stoppage"] = code
            problem = self.apply(delete_action, payload)
            if problem:
                Notification(problem, style="warning", timeout=5).show()
            return
        if kind == "stoppage":
            Editor.open_editor(self, edit_action, {"row": row, "contextKind": kind, "contextId": code})
            return
        loaded = _call("cyclops_detail", kind, code)
        if not loaded or loaded.get("missing"):
            Notification("The record could not be loaded.", style="warning", timeout=4).show()
            return
        Editor.open_editor(self, edit_action, {"record": loaded, "contextKind": kind, "contextId": code})

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
        return self._table_section("Changeovers", "%s changes · %s of production lost · newest first. Click a row for the run that followed."
                                   % (len(rows), Format.duration(lost) or "0 min"), rows, "changeover", hide, empty="No changeover found.")

    def _table_section(self, title, subtitle, rows, kind, hide=(), actions=(), height="420px", empty="Nothing yet."):
        card = Layout.section(title, subtitle, padded=not rows, actions=actions)
        if not rows:
            Layout.body(card, Layout.html('<p class="cy-muted">%s</p>' % Layout.esc(empty)))
            return card
        menu = self._row_menu(kind) if kind in _ROW_ACTIONS and Data.can_write() else None
        editing = {"on_edit": self._edit_stoppage, "edit_on_click": True} if kind == "stoppage" else {}
        table = Tables.mount(rows, kind, Tables.columns_for(kind, hide), height=height if len(rows) > 8 else None,
                             on_menu=menu, **editing)
        Layout.body(card, table)
        return card

    def _stoppage_section(self, rows, hide=(), actions=()):
        return self._table_section("Stoppages", "%s logged · newest first. Click a row to edit it." % len(rows), rows, "stoppage", hide,
                                   actions, empty="No stoppages logged.")

    def _run_section(self, rows, hide=(), actions=(), subtitle="Each job: pieces, scrap, and pieces per hour against the cycle and cavities."):
        return self._table_section("Production runs", subtitle, rows, "run", hide, actions, empty="No runs logged.")

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
                ("Hours", (Layout.esc(Format.duration(data.get("hours"))) or "—") + (" <small>· %s down</small>" % Layout.esc(Format.duration(data.get("downHours"))) if data.get("downHours") else ""), False),
                ("Pieces / hour", metric(data.get("pph")) + (" <small>· target %s</small>" % data.get("target") if data.get("target") else ""), False),
                ("Press cycle", metric(data.get("cycle"), " s"), data.get("cycle") is None),
                ("Effective cycle", metric(data.get("effectiveCycle"), " s") if data.get("effectiveCycle") is not None
                 else ("needs the cavity count" if data.get("endedAt") and data.get("pph") else "—"), data.get("effectiveCycle") is None),
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
        consumed = self._consumed_rows(data)
        used = self._used_rows(data)
        tabs = []
        if data.get("run") or data.get("origin") == "Produced":
            empty = "No run recorded for this lot." if not data.get("run") else "No consumed lot recorded."
            tabs.append(("back", "Trace back", len(consumed), lambda rows=consumed, blank=empty: [self._trace_table(
                "Trace back", "The lots this run consumed. Open a row to follow that lot further back.",
                rows, "lot", Tables.columns_trace_back(), blank)]))
        tabs.append(("forward", "Trace forward", len(used), lambda rows=used: [self._trace_table(
            "Trace forward", "The runs that used this lot. Open a row for what that run made.",
            rows, "run", Tables.columns_trace_forward(), "No run has used this lot.")]))
        self.show_tabbed(
            (Layout.page_header("Lot %s" % (data.get("number") or ""), eyebrow=data.get("id") or "", description=data.get("item") or "",
                                actions=(Layout.button("Edit", self.act("edit-lot")),)),
             self._meta(data), self._facts(facts), self._notes(data.get("notes"))),
            tabs,
        )

    def _consumed_rows(self, data):
        rows = []
        for child in (data.get("back") or {}).get("inputs") or []:
            lot = child.get("lot") or {}
            run = child.get("run") or {}
            rows.append({
                "id": lot.get("id") or "", "number": lot.get("number") or "", "item": lot.get("item") or "",
                "itemId": lot.get("itemId") or "", "quantity": child.get("quantity"), "uom": lot.get("uom") or "",
                "origin": lot.get("origin") or "", "received": lot.get("received") or "", "run": run.get("id") or "",
            })
        return rows

    def _used_rows(self, data):
        forward = data.get("forward") or {}
        unit = (forward.get("lot") or {}).get("uom") or ""
        rows = []
        for entry in forward.get("runs") or []:
            run = entry.get("run") or {}
            made = [number for number in [((child.get("lot") or {}).get("number") or "") for child in entry.get("outputs") or []] if number]
            rows.append({
                "id": run.get("id") or "", "start": run.get("start") or "", "machine": run.get("machine") or "",
                "item": run.get("item") or "", "itemId": run.get("itemId") or "", "quantity": entry.get("quantity"),
                "uom": unit, "made": ", ".join(made),
            })
        return rows

    def _trace_table(self, title, subtitle, rows, kind, columns, empty):
        card = Layout.section(title, subtitle, padded=not rows)
        if not rows:
            Layout.body(card, Layout.html('<p class="cy-muted">%s</p>' % Layout.esc(empty)))
            return card
        Layout.body(card, Tables.mount(rows, kind, columns, height="420px" if len(rows) > 8 else None))
        return card
