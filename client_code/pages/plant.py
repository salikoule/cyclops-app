"""Overview, the live floor, and the structure page."""

from .common import KPI_ICON
from craftify_library.CraftifyUtils.echarts_theme import apply_craftify_echarts_theme
from craftify_library.CustomComponents.ChartCard import ChartCard
from craftify_library.CustomComponents.EChart import EChart
from craftify_library.CustomComponents.KpiCard import KpiCard
from cyclops_app.session import Data
from cyclops_app.ui import Format
from cyclops_app.ui import Layout
from cyclops_app.ui import Nav
from cyclops_app.ui.query import call as _call


class Plant:
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
        return Layout.kpi_row(*built)

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
