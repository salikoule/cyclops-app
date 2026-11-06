"""The Performance page: where the staffed hours went, stoppages, changeovers, scrap, capacity, and data checks."""

import anvil.server
from anvil import *
from craftify_library.CustomComponents.ChartCard import ChartCard
from craftify_library.CustomComponents.EChart import EChart
from craftify_library.CustomComponents.KpiCard import KpiCard
from cyclops_app import Format, Layout, Nav

TABS = (
    ("time", "Time"), ("stoppages", "Stoppages"), ("changeovers", "Changeovers"), ("scrap", "Scrap"),
    ("capacity", "Capacity and fit"), ("data", "Data checks"),
)
COLORS = {"good": "#22c55e", "scrap": "#a855f7", "slow": "#f59e0b", "planned": "#3b82f6", "unplanned": "#ef4444", "idle": "#94a3b8"}
MONTHS = ("All months", "January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December")


def _n(value):
    if value is None:
        return "—"
    return "{:,}".format(int(round(value)))


def _pct(value):
    return "—" if value is None else "%s%%" % Format.trim(value)


def _chart(title, subtitle, options, height="320px"):
    for series in options.get("series") or []:
        if "label" in series:
            series["label"].update({"color": "#94a3b8", "textBorderWidth": 0, "fontSize": 11})
    axes = options.get("xAxis")
    if isinstance(axes, dict) and axes.get("type") == "value" and axes.get("name"):
        axes.update({"nameLocation": "middle", "nameGap": 24})
    card = ChartCard(title=title, subtitle=subtitle)
    card.mount(EChart(options=options, height=height))
    return Layout.flat(card)


class PerformancePage:
    def __init__(self, form, ctx):
        self.form = form
        self.query = Nav.query(ctx)
        self.tab = self.query.get("tab") or "time"
        self.data = None
        self.holder = None

    def render(self):
        try:
            data = anvil.server.call("cyclops_performance", self.query.get("year") or None, self.query.get("month") or 0, self.query.get("machine") or "")
        except Exception as error:
            Notification(str(error), style="danger", timeout=5).show()
            return
        self.data = data
        self.holder = Layout.flat(ColumnPanel())
        self.form.clear()
        self.form.add_component(Layout.stack(
            Layout.page_header("Performance", description=self._lead(), actions=self._filters()),
            Layout.interactive(self._tabs_markup(), self._on_tab),
            self.holder,
        ), full_width_row=True)
        self._show_tab()

    def _lead(self):
        data = self.data
        when = "%s %s" % (MONTHS[data["month"]], data.get("year")) if data.get("month") else str(data.get("year"))
        machine = next((entry["label"] for entry in data.get("machines") or [] if entry["value"] == data.get("machine")), "the plant")
        return "How %s used its staffed time in %s, worked out from each run's pieces and rated speed." % (machine, when)

    def _filters(self):
        data = self.data
        year = DropDown(items=[(str(value), value) for value in data.get("years") or [data.get("year")]], selected_value=data.get("year"))
        month = DropDown(items=[(label, number) for number, label in enumerate(MONTHS)], selected_value=data.get("month") or 0)
        machine = DropDown(items=[("Every machine", "")] + [(entry["label"], entry["value"]) for entry in data.get("machines") or []],
                           selected_value=data.get("machine") or "")

        def apply(**event_args):
            query = {"year": year.selected_value, "month": month.selected_value or "", "machine": machine.selected_value or "", "tab": self.tab}
            Nav.go("performance", query={key: value for key, value in query.items() if value not in ("", None, 0)})

        for box in (year, month, machine):
            box.set_event_handler("change", apply)
            box.role = "cy-filter"
        return (year, month, machine)

    def _tabs_markup(self):
        return '<nav class="cy-tabs">%s</nav>' % "".join(
            '<a class="cy-tab%s" href="javascript:void(0)" data-action="tab" data-item="%s">%s</a>' % (" is-active" if key == self.tab else "", key, Layout.esc(label))
            for key, label in TABS)

    def _on_tab(self, mode, node):
        key = Layout.attr(node, "data-item")
        if not key or key == self.tab:
            return
        self.tab = key
        for link in node.parentElement.querySelectorAll(".cy-tab"):
            link.classList.toggle("is-active", Layout.attr(link, "data-item") == key)
        self._show_tab()

    def _show_tab(self):
        build = getattr(self, "_tab_" + self.tab, self._tab_time)
        self.holder.clear()
        self.holder.add_component(Layout.stack(*[part for part in build() if part is not None]), full_width_row=True)

    # Time ---------------------------------------------------------------------------------

    def _kpis(self):
        kpis = self.data.get("kpis") or {}
        cards = (
            ("Good pieces", _n(kpis.get("good")), "%s runs logged" % _n(kpis.get("runs")), "check_circle", "#16a34a"),
            ("Productive time", _pct(kpis.get("oee")), "good-piece hours of %s staffed" % _n(kpis.get("staffedHours")), "speed", "#2563eb"),
            ("Hours lost", _n(kpis.get("lostHours")), "slow, stopped, idle and scrap", "hourglass_bottom", "#dc2626"),
            ("Capacity used", _pct(kpis.get("capacityPct")), "of every machine-shift", "event_available", "#0f766e"),
            ("Scrap", _pct(kpis.get("scrapPct")), "as recorded", "delete", "#7c3aed"),
            ("Changeovers", _n(kpis.get("changeovers")), "product changes on a machine", "swap_horiz", "#d97706"),
        )
        return Layout.grid("repeat(auto-fit, minmax(170px, 1fr))", *[
            KpiCard(title=title, value=value, subtitle=subtitle, icon=icon, icon_color=color) for title, value, subtitle, icon, color in cards])

    def _tab_time(self):
        data = self.data
        kpis = data.get("kpis") or {}
        parts = [self._kpis()]
        if kpis.get("runs") and not kpis.get("ratedRuns"):
            parts.append(Layout.note("None of these runs has a cycle time and cavities, so their hours cannot be worked out.", "warn"))
        elif kpis.get("ratedRuns") and kpis["ratedRuns"] < kpis.get("runs", 0):
            parts.append(Layout.note("%s of %s runs have a rated speed (cycle and cavities); the hours below come from those."
                                     % (_n(kpis["ratedRuns"]), _n(kpis["runs"]))))
        buckets = data.get("buckets") or []
        months = None if data.get("month") else self._months_chart()
        parts.append(Layout.grid("minmax(280px, 1fr) minmax(320px, 2fr)" if months else "1fr",
            _chart("Where the staffed hours went", "Each staffed shift split into hours.", {
                "tooltip": {"trigger": "item", "formatter": "{b}: {c} h ({d}%)"},
                "legend": {"bottom": 0, "left": "center"},
                "series": [{"type": "pie", "radius": ["45%", "72%"], "center": ["50%", "44%"], "label": {"show": False},
                            "data": [{"name": entry["label"], "value": entry["hours"], "itemStyle": {"color": COLORS[entry["key"]]}} for entry in buckets]}],
            }),
            *([months] if months else [])))
        parts.append(self._calendar())
        parts.append(self._machines_chart())
        return parts

    def _months_chart(self):
        months = self.data.get("byMonth") or {}
        series = [{"type": "bar", "stack": "h", "name": entry["label"], "data": entry["values"], "itemStyle": {"color": COLORS[entry["key"]]}}
                  for entry in months.get("series") or []]
        series.append({"type": "line", "name": "Productive time %", "yAxisIndex": 1, "data": months.get("oee") or [], "symbolSize": 6,
                       "itemStyle": {"color": "#06b6d4"}, "lineStyle": {"width": 2}})
        return _chart("Month by month", "Staffed hours by what they turned into; the line is the productive share.", {
            "tooltip": {"trigger": "axis"}, "legend": {"top": 0, "type": "scroll"},
            "grid": {"left": 52, "right": 48, "top": 64, "bottom": 28},
            "xAxis": {"type": "category", "data": months.get("labels") or []},
            "yAxis": [{"type": "value", "name": "Hours"}, {"type": "value", "name": "%", "max": 100, "splitLine": {"show": False}}],
            "series": series,
        })

    def _calendar(self):
        data = self.data
        cells = data.get("calendar") or []
        machines = data.get("calendarMachines") or []
        if not cells or not machines:
            return None
        days = sorted({cell[0] for cell in cells})
        first, last = data.get("calendarRange") or [days[0], days[-1]]
        every_day = _days_between(first, last)
        x_of = {day: index for index, day in enumerate(every_day)}
        y_of = {name: index for index, name in enumerate(machines)}
        points, unknown = [], []
        for day, machine, value, shifts, pieces, items in cells:
            if day not in x_of or machine not in y_of:
                continue
            share = "speed unknown" if value is None else "%s%% of the day productive" % Format.trim(value)
            point = {"value": [x_of[day], y_of[machine], value if value is not None else 0],
                     "name": "%s · %s<br>%s shift%s · %s pcs · %s<br>%s" % (
                         Format.day(day), machine, shifts, "" if shifts == 1 else "s", _n(pieces), share, Layout.esc(items))}
            (unknown if value is None else points).append(point)
        labels = [Format.day(day)[:6] for day in every_day]
        return _chart("Plant calendar", "Each square is a machine-day: the share of 24 hours spent making good pieces. "
                      "Blank means nobody ran it; grey means it ran but its runs have no rated speed.", {
            "tooltip": {"formatter": "{b}"},
            "grid": {"left": 104, "right": 16, "top": 8, "bottom": 70},
            "xAxis": {"type": "category", "data": labels, "splitArea": {"show": False}, "axisLabel": {"interval": max(0, len(labels) // 12 - 1)}},
            "yAxis": {"type": "category", "data": machines, "inverse": True},
            "visualMap": {"min": 0, "max": 100, "seriesIndex": 0, "orient": "horizontal", "left": "center", "bottom": 4, "itemHeight": 160,
                          "calculable": False, "text": ["100% productive", "0%"], "textStyle": {"color": "#94a3b8"},
                          "inRange": {"color": ["#fde2e2", "#fbbf24", "#22c55e", "#15803d"]}},
            "series": [
                {"type": "heatmap", "data": points, "itemStyle": {"borderColor": "rgba(0,0,0,0.04)", "borderWidth": 1}},
                {"type": "heatmap", "data": unknown, "itemStyle": {"color": "#64748b", "borderColor": "rgba(0,0,0,0.04)", "borderWidth": 1}},
            ],
        }, height="%dpx" % max(260, 26 * len(machines) + 100))

    def _machines_chart(self):
        rows = self.data.get("byMachine") or []
        if not rows:
            return None
        names = [row["machine"] for row in rows]
        series = [{"type": "bar", "stack": "h", "name": label, "data": [row.get(key) for row in rows], "itemStyle": {"color": COLORS[key]}}
                  for key, label in (("good", "Good pieces"), ("scrap", "Scrap"), ("slow", "Running slow"), ("planned", "Planned stops"),
                                     ("unplanned", "Breakdowns and other stops"), ("idle", "Idle, no reason given"))]
        return _chart("By machine", "Staffed hours per machine, lowest productive share first. Machines with no rated speed are left out.", {
            "tooltip": {"trigger": "axis", "axisPointer": {"type": "shadow"}}, "legend": {"top": 0, "type": "scroll"},
            "grid": {"left": 104, "right": 24, "top": 40, "bottom": 24},
            "xAxis": {"type": "value", "name": "Hours"}, "yAxis": {"type": "category", "data": names, "inverse": True},
            "series": series,
        }, height="%dpx" % max(260, 26 * len(names) + 80))

    # Stoppages ----------------------------------------------------------------------------

    def _tab_stoppages(self):
        rows = self.data.get("causes") or []
        if not rows:
            return [Layout.empty_state("No stoppages in this period.")]
        total = sum(row["hours"] for row in rows) or 1
        chart = _chart("Hours lost by cause", "Blue: planned stops. Red: breakdowns and other unplanned stops. Grey: no cause yet.", {
            "tooltip": {"trigger": "axis", "axisPointer": {"type": "shadow"}},
            "grid": {"left": 170, "right": 40, "top": 12, "bottom": 28},
            "xAxis": {"type": "value", "name": "Hours"}, "yAxis": {"type": "category", "data": [row["cause"] for row in rows], "inverse": True},
            "series": [{"type": "bar", "name": "Hours", "label": {"show": True, "position": "right"},
                        "data": [{"value": row["hours"], "itemStyle": {"color": "#94a3b8" if not row["group"] else ("#3b82f6" if row["planned"] else "#ef4444")}}
                                 for row in rows]}],
        }, height="%dpx" % max(220, 30 * len(rows) + 60))
        table = "".join("<tr><td>%s</td><td>%s</td><td>%s</td><td class='cy-num'>%s</td><td class='cy-num'>%s h</td><td class='cy-num'>%s%%</td></tr>" % (
            Layout.esc(row["cause"]), Layout.esc(row["group"] or "—"), "Planned" if row["planned"] else "Unplanned",
            row["count"], Format.trim(row["hours"]), Format.trim(round(100.0 * row["hours"] / total, 1))) for row in rows)
        card = Layout.section("Causes", "Stoppages taken from the log's notes carry an auto-classified cause; open one on the Stoppages page to correct it.")
        Layout.body(card, Layout.html("<table class='cy-table'><thead><tr><th>Cause</th><th>Group</th><th>Kind</th><th class='cy-num'>Stops</th>"
                                      "<th class='cy-num'>Hours</th><th class='cy-num'>Share</th></tr></thead><tbody>%s</tbody></table>" % table))
        return [chart, card]

    # Changeovers --------------------------------------------------------------------------

    def _tab_changeovers(self):
        data = self.data.get("changeovers") or {}
        kpis = self.data.get("kpis") or {}
        shifts = data.get("shifts") or []
        lead = Layout.grid("repeat(auto-fit, minmax(170px, 1fr))",
            KpiCard(title="Changeovers", value=_n(kpis.get("changeovers")), subtitle="product changes on a machine", icon="swap_horiz", icon_color="#d97706"),
            KpiCard(title="Planned stop hours", value=_n(data.get("plannedHours")), subtitle="mold changes and other planned stops", icon="build", icon_color="#3b82f6"))
        shift_chart = _chart("Speed by shift, on changeover days and other days",
                             "Median pieces made against the rated speed while running. A product change costs the shift it lands on.", {
            "tooltip": {"trigger": "axis"}, "legend": {"top": 0},
            "grid": {"left": 48, "right": 16, "top": 40, "bottom": 28},
            "xAxis": {"type": "category", "data": [row["shift"] for row in shifts]},
            "yAxis": {"type": "value", "name": "%"},
            "series": [
                {"type": "bar", "name": "Days with a product change", "data": [row["changeover"] for row in shifts], "itemStyle": {"color": "#f59e0b"},
                 "label": {"show": True, "position": "top", "formatter": "{c}%"}},
                {"type": "bar", "name": "Other days", "data": [row["normal"] for row in shifts], "itemStyle": {"color": "#22c55e"},
                 "label": {"show": True, "position": "top", "formatter": "{c}%"}},
            ],
        })
        lengths = data.get("lengths") or []
        length_chart = _chart("How long a product stays on a machine", "Days per campaign: short campaigns mean more changeovers.", {
            "tooltip": {"trigger": "axis"}, "grid": {"left": 48, "right": 16, "top": 16, "bottom": 28},
            "xAxis": {"type": "category", "data": [row["label"] for row in lengths]}, "yAxis": {"type": "value", "name": "Campaigns"},
            "series": [{"type": "bar", "data": [row["count"] for row in lengths], "itemStyle": {"color": "#6366f1"}, "label": {"show": True, "position": "top"}}],
        })
        months = data.get("byMonth") or {}
        month_chart = _chart("Changeovers per month", "", {
            "tooltip": {"trigger": "axis"}, "grid": {"left": 48, "right": 16, "top": 16, "bottom": 28},
            "xAxis": {"type": "category", "data": months.get("labels") or []}, "yAxis": {"type": "value"},
            "series": [{"type": "bar", "data": months.get("values") or [], "itemStyle": {"color": "#d97706"}}],
        }, height="260px")
        gaps = [row for row in shifts if row.get("changeover") is not None and row.get("normal") is not None]
        worst = max(gaps, key=lambda row: row["normal"] - row["changeover"]) if gaps else None
        takeaway = None
        if worst and worst["normal"] - worst["changeover"] >= 10:
            takeaway = Layout.html("<p class='cy-takeaway'>On days a product changes, the %s shift runs at <b>%s%%</b> of rated speed, against <b>%s%%</b> on other days.</p>"
                                   % (worst["shift"].lower(), worst["changeover"], worst["normal"]))
        return [lead, takeaway, shift_chart, Layout.grid("repeat(auto-fit, minmax(320px, 1fr))", length_chart, month_chart)]

    # Scrap --------------------------------------------------------------------------------

    def _tab_scrap(self):
        items = self.data.get("scrapItems") or []
        machines = self.data.get("scrapMachines") or []
        if not items:
            return [Layout.empty_state("No scrap recorded in this period.")]
        share = items[-1]["cumulative"]
        spread = "Scrap is spread across many items" if share < 50 else "A few items make most of the scrap"
        pareto = _chart("Scrap by item", "The %d items with the most recorded scrap make %s%% of it. %s." % (len(items), Format.trim(share), spread), {
            "tooltip": {"trigger": "axis", "axisPointer": {"type": "shadow"}},
            "grid": {"left": 260, "right": 120, "top": 12, "bottom": 36},
            "xAxis": {"type": "value", "name": "Scrap pieces"},
            "yAxis": {"type": "category", "inverse": True, "data": [Format.clip(row["item"], 38) for row in items], "axisLabel": {"width": 250, "overflow": "truncate"}},
            "series": [{"type": "bar", "name": "Scrap pieces", "itemStyle": {"color": "#a855f7"},
                        "label": {"show": True, "position": "right"},
                        "data": [{"value": row["scrap"], "label": {"formatter": "%s · %s%% of its pieces" % (_n(row["scrap"]), Format.trim(row["pct"]))}}
                                 for row in items]}],
        }, height="%dpx" % max(260, 26 * len(items) + 60))
        rate = _chart("Scrap rate by machine", "Recorded scrap as a share of pieces made.", {
            "tooltip": {"trigger": "axis", "axisPointer": {"type": "shadow"}},
            "grid": {"left": 104, "right": 48, "top": 12, "bottom": 28},
            "xAxis": {"type": "value", "name": "%"}, "yAxis": {"type": "category", "data": [row["machine"] for row in machines], "inverse": True},
            "series": [{"type": "bar", "data": [row["pct"] for row in machines], "itemStyle": {"color": "#a855f7"},
                        "label": {"show": True, "position": "right", "formatter": "{c}%"}}],
        }, height="%dpx" % max(220, 26 * len(machines) + 60))
        return [pareto, rate, Layout.note("Scrap was left blank on many days of the log, so these rates are likely lower than the real ones.", "warn")]

    # Capacity and fit ---------------------------------------------------------------------

    def _tab_capacity(self):
        rows = self.data.get("capacity") or []
        chart = _chart("Machine-shifts used", "Share of every possible shift (days × 3) that had a run. The rest is room for more orders.", {
            "tooltip": {"trigger": "axis", "axisPointer": {"type": "shadow"}},
            "grid": {"left": 104, "right": 48, "top": 12, "bottom": 28},
            "xAxis": {"type": "value", "max": 100, "name": "%"}, "yAxis": {"type": "category", "data": [row["machine"] for row in rows], "inverse": True},
            "series": [{"type": "bar", "data": [row["pct"] for row in rows], "itemStyle": {"color": "#0f766e"},
                        "label": {"show": True, "position": "right", "formatter": "{c}%"}}],
        }, height="%dpx" % max(220, 26 * len(rows) + 60))
        table = "".join("<tr><td>%s</td><td class='cy-num'>%s</td><td class='cy-num'>%s</td><td class='cy-num'>%s</td><td class='cy-num'>%s</td></tr>" % (
            Layout.esc(row["machine"]), _n(row["used"]), _pct(row["pct"]), _n(row["oneShiftDays"]), _n(row["idleDays"])) for row in rows)
        card = Layout.section("Shifts and idle days", "One-shift days ran a single shift; idle days had no run at all.")
        Layout.body(card, Layout.html("<table class='cy-table'><thead><tr><th>Machine</th><th class='cy-num'>Shifts run</th><th class='cy-num'>Used</th>"
                                      "<th class='cy-num'>One-shift days</th><th class='cy-num'>Idle days</th></tr></thead><tbody>%s</tbody></table>" % table))
        return [chart, card, self._fit()]

    def _fit(self):
        rows = self.data.get("fit") or []
        if not rows:
            return None
        body = []
        for row in rows:
            options = "".join("<div class='cy-fit-opt%s'><b>%s</b><span>%s pcs/h</span><small>rated %s · %s shifts</small></div>" % (
                " is-best" if index == 0 else "", Layout.esc(option["machine"]), _n(option["actual"]), _n(option["rated"]), option["shifts"])
                for index, option in enumerate(row["options"]))
            body.append("<tr><td><a href='javascript:void(0)' data-nav='%s'>%s</a></td><td class='cy-num'>+%s%%</td><td><div class='cy-fit'>%s</div></td></tr>" % (
                Layout.esc(Nav.path("item", row["id"])), Layout.esc(row["item"]), row["gain"], options))
        card = Layout.section("Same item, different machines",
                              "Items made on more than one machine, fastest first: actual pieces per hour while running. Part of a gap can be a different mold.")
        Layout.body(card, Layout.interactive("<table class='cy-table'><thead><tr><th>Item</th><th class='cy-num'>Fastest vs slowest</th>"
                                             "<th>Machines</th></tr></thead><tbody>%s</tbody></table>" % "".join(body), self._on_nav))
        return card

    def _on_nav(self, mode, node):
        if mode == "nav":
            Nav.open_path(Layout.attr(node, "data-nav"))

    # Data checks --------------------------------------------------------------------------

    def _tab_data(self):
        checks = self.data.get("checks") or []
        if not checks:
            return [Layout.note("The import found nothing to report.")]
        cards = []
        for check in checks:
            examples = "".join("<li>%s</li>" % Layout.esc(example) for example in check.get("examples") or [])
            cards.append("<div class='cy-check'><div class='cy-check-count'>%s</div><div><b>%s</b><p>%s</p>%s</div></div>" % (
                _n(check.get("count")), Layout.esc(check.get("label")), Layout.esc(check.get("detail")),
                "<ul>%s</ul>" % examples if examples else ""))
        card = Layout.section("What the import found", "From %s. Each line was fixed or left out on the way in; the counts are what the spreadsheet holds."
                              % (self.data.get("source") or "the import"))
        Layout.body(card, Layout.html("<div class='cy-checks'>%s</div>" % "".join(cards)))
        return [card]


def _days_between(first, last):
    import datetime

    start = datetime.date(int(first[0:4]), int(first[5:7]), int(first[8:10]))
    end = datetime.date(int(last[0:4]), int(last[5:7]), int(last[8:10]))
    days = []
    while start <= end:
        days.append(start.isoformat())
        start += datetime.timedelta(days=1)
    return days


def mount_performance(form, ctx):
    PerformancePage(form, ctx).render()
