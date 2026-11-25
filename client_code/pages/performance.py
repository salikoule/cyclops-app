"""The Performance page: where the staffed hours went, stoppages, changeovers, scrap, capacity, and data checks."""

from anvil import *
from craftify_library.CustomComponents.ChartCard import ChartCard
from craftify_library.CustomComponents.EChart import EChart
from craftify_library.CustomComponents.KpiCard import KpiCard

from cyclops_app.ui import Format, Layout, Nav, Tables
from cyclops_app.ui.query import call
from cyclops_app.ui.tabs import tab_bar

TABS = (
    ("time", "Time"), ("stoppages", "Stoppages"), ("changeovers", "Changeovers"), ("scrap", "Scrap"),
    ("capacity", "Capacity and fit"), ("data", "Data checks"),
)
COLORS = {"good": "#22c55e", "scrap": "#a855f7", "slow": "#f59e0b", "changeover": "#14b8a6", "planned": "#3b82f6", "unplanned": "#ef4444",
          "idle": "#94a3b8"}
MONTHS = ("All months", "January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December")


def _filter_query(year, month, machine, tab):
    """The address-bar filters. Year, month and machine stay strings so the dropdown can show the year the page is actually on."""
    query = {}
    if year not in (None, ""):
        query["year"] = str(year)
    try:
        month_number = int(month or 0)
    except (TypeError, ValueError):
        month_number = 0
    if month_number:
        query["month"] = str(month_number)
    if machine not in (None, ""):
        query["machine"] = str(machine)
    if tab and tab != "time":
        query["tab"] = tab
    return query


def _cause_table_rows(rows):
    total = sum(row["hours"] for row in rows) or 1
    return [{
        "cause": row["cause"],
        "group": row["group"] or "—",
        "kind": "Planned" if row["planned"] else "Unplanned",
        "count": row["count"],
        "hours": row["hours"],
        "share": round(100.0 * row["hours"] / total, 1),
    } for row in rows]


def _hours_unit(value, *rest):
    """Tooltip unit for the By machine chart. Every series on that chart is hours."""
    if value is None or value == "":
        return "—"
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    text = "{:,.1f}".format(number)
    if text.endswith(".0"):
        text = "{:,.0f}".format(number)
    return text + " h"


def _open_machine(data, tab=None):
    code = data.get("id")
    if not code:
        return
    Nav.go("machine", code, query={"tab": tab} if tab else None)


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
        self._applying = False

    def render(self):
        data = call("cyclops_performance", self.query.get("year") or None, self.query.get("month") or 0, self.query.get("machine") or "")
        if data is None:
            return
        self.data = data
        self.holder = Layout.flat(ColumnPanel())
        self.form.clear()
        self.form.add_component(Layout.stack(
            Layout.page_header("Performance", description=self._lead(), actions=self._filters()),
            tab_bar([(key, label, None) for key, label in TABS], self.tab, self._select_tab),
            self.holder,
        ), full_width_row=True)
        self._show_tab()

    def _select_tab(self, key):
        self.tab = key
        self._show_tab()

    def _lead(self):
        data = self.data
        when = "%s %s" % (MONTHS[data["month"]], data.get("year")) if data.get("month") else str(data.get("year"))
        machine = next((entry["label"] for entry in data.get("machines") or [] if entry["value"] == data.get("machine")), "the plant")
        return "How %s used its staffed time in %s, worked out from each run's pieces and its speed." % (machine, when)

    def _filters(self):
        data = self.data
        years = [str(value) for value in data.get("years") or []]
        current = str(data.get("year") or "")
        if current and current not in years:
            years.insert(0, current)
        year = DropDown(items=years, selected_value=current or None)
        month = DropDown(items=[(label, str(number)) for number, label in enumerate(MONTHS)], selected_value=str(data.get("month") or 0))
        machine = DropDown(items=[("Every machine", "")] + [(entry["label"], entry["value"]) for entry in data.get("machines") or []],
                           selected_value=data.get("machine") or "")

        def apply(**event_args):
            if self._applying:
                return
            chosen = _filter_query(year.selected_value, month.selected_value, machine.selected_value, self.tab)
            current_query = _filter_query(self.query.get("year"), self.query.get("month"), self.query.get("machine"), self.tab)
            if chosen == current_query:
                return
            # The page form is cached, so changing the address does not rebuild it. Draw the chosen year here.
            self._applying = True
            try:
                self.query = chosen
                self.render()
                Nav.go("performance", query=dict(self.query))
            finally:
                self._applying = False

        for box in (year, month, machine):
            box.set_event_handler("change", apply)
            box.role = "cy-filter"
        return (year, month, machine)

    def _show_tab(self):
        build = getattr(self, "_tab_" + self.tab, self._tab_time)
        self.holder.clear()
        self.holder.add_component(Layout.stack(*[part for part in build() if part is not None]), full_width_row=True)

    # Time ---------------------------------------------------------------------------------

    def _kpis(self):
        kpis = self.data.get("kpis") or {}
        cards = (
            ("Good pieces", Format.grouped(kpis.get("good")), "%s runs logged" % Format.grouped(kpis.get("runs")), "check_circle", "#16a34a"),
            ("Productive time", Format.percent(kpis.get("oee")), "good-piece hours of %s staffed" % Format.grouped(kpis.get("staffedHours")), "speed", "#2563eb"),
            ("Hours lost", Format.grouped(kpis.get("lostHours")), "slow, stopped, idle and scrap", "hourglass_bottom", "#dc2626"),
            ("Capacity used", Format.percent(kpis.get("capacityPct")), "of every machine-shift", "event_available", "#0f766e"),
            ("Scrap", Format.percent(kpis.get("scrapPct")), "as recorded", "delete", "#7c3aed"),
            ("Changeovers", Format.grouped(kpis.get("changeovers")), "%s h of production lost" % Format.grouped(kpis.get("changeoverHours")), "swap_horiz", "#0d9488"),
        )
        return Layout.kpi_row(*[
            KpiCard(title=title, value=value, subtitle=subtitle, icon=icon, icon_color=color) for title, value, subtitle, icon, color in cards])

    def _tab_time(self):
        data = self.data
        kpis = data.get("kpis") or {}
        parts = [self._kpis()]
        if kpis.get("runs") and not kpis.get("ratedRuns"):
            parts.append(Layout.note("None of these runs has a cycle and a cavity count. Their hours are the time the pieces actually took. A day stays grey only when the pieces or the hours are missing.", "warn"))
        elif kpis.get("ratedRuns") and kpis["ratedRuns"] < kpis.get("runs", 0):
            parts.append(Layout.note("%s of %s runs have a rated speed (cycle and cavities). The others are counted at the pieces per hour they actually ran."
                                     % (Format.grouped(kpis["ratedRuns"]), Format.grouped(kpis["runs"]))))
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
        first, last = data["calendarRange"]
        every_day = _days_between(first, last)
        names = data.get("calendarItems") or []
        points, unknown = [], []
        for day, row, value, shifts, pieces, items in cells:
            share = "speed unknown" if value is None else "%s%% of the day productive" % Format.trim(value)
            made = Format.clip(", ".join(names[number] for number in items), 60)
            point = {"value": [day, row, value if value is not None else 0],
                     "name": "%s · %s<br>%s shift%s · %s pcs · %s<br>%s" % (
                         Format.day(every_day[day]), machines[row], shifts, "" if shifts == 1 else "s", Format.grouped(pieces), share, Layout.esc(made))}
            (unknown if value is None else points).append(point)
        labels = [Format.day(day)[:6] for day in every_day]
        return _chart("Plant calendar", "Each square is a machine-day: the share of 24 hours spent making good pieces. "
                      "Blank means nobody ran it; grey means it ran but the pieces or the hours are missing.", {
            "tooltip": {"formatter": lambda params, *rest: params["name"]},
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
                  for key, label in (("good", "Good-piece hours"), ("scrap", "Scrap hours"), ("slow", "Running slow"), ("changeover", "Changeovers"),
                                     ("planned", "Planned stops"), ("unplanned", "Breakdowns and other stops"), ("idle", "Idle, no reason given"))]
        return _chart("By machine", "Staffed hours per machine, lowest productive share first. A machine with no cycle and cavities is counted at the speed it actually ran. Every figure is hours.", {
            "tooltip": {"trigger": "axis", "axisPointer": {"type": "shadow"}, "valueFormatter": _hours_unit}, "legend": {"top": 0, "type": "scroll"},
            "grid": {"left": 104, "right": 24, "top": 40, "bottom": 24},
            "xAxis": {"type": "value", "name": "Hours"}, "yAxis": {"type": "category", "data": names, "inverse": True},
            "series": series,
        }, height="%dpx" % max(260, 26 * len(names) + 80))

    # Stoppages ----------------------------------------------------------------------------

    def _tab_stoppages(self):
        rows = self.data.get("causes") or []
        if not rows:
            return [Layout.empty_state("No stoppages in this period.")]
        chart = _chart("Hours lost by cause", "Blue: planned stops. Red: breakdowns and other unplanned stops. Grey: no cause yet.", {
            "tooltip": {"trigger": "axis", "axisPointer": {"type": "shadow"}},
            "grid": {"left": 170, "right": 40, "top": 12, "bottom": 28},
            "xAxis": {"type": "value", "name": "Hours"}, "yAxis": {"type": "category", "data": [row["cause"] for row in rows], "inverse": True},
            "series": [{"type": "bar", "name": "Hours", "label": {"show": True, "position": "right"},
                        "data": [{"value": row["hours"], "itemStyle": {"color": "#94a3b8" if not row["group"] else ("#3b82f6" if row["planned"] else "#ef4444")}}
                                 for row in rows]}],
        }, height="%dpx" % max(220, 30 * len(rows) + 60))
        card = Layout.section("Causes", "Stoppages taken from the log's notes carry an auto-classified cause; open one on the Stoppages page to correct it.")
        Layout.body(card, Tables.mount_report(_cause_table_rows(rows), Tables.columns_perf_causes()))
        return [chart, card]

    # Changeovers --------------------------------------------------------------------------

    def _tab_changeovers(self):
        data = self.data.get("changeovers") or {}
        if not data.get("count"):
            return [Layout.empty_state("No changeover in this period.")]
        sources = {row["key"]: row["count"] for row in data.get("sources") or []}
        lead = Layout.grid("repeat(auto-fit, minmax(170px, 1fr))",
            KpiCard(title="Changeovers", value=Format.grouped(data.get("count")), subtitle="%s cost production time" % Format.grouped(data.get("withLoss")),
                    icon="swap_horiz", icon_color="#0d9488"),
            KpiCard(title="Production lost", value="%s h" % Format.grouped(data.get("hours")), subtitle="median %s h a change" % Format.trim(data.get("median")),
                    icon="hourglass_bottom", icon_color="#dc2626"),
            KpiCard(title="Times from a logged stop", value=Format.grouped(sources.get("stop")), subtitle="%s derived from output" % Format.grouped(sources.get("derived")),
                    icon="fact_check", icon_color="#2563eb"),
            KpiCard(title="Mold not recorded", value=Format.grouped(data.get("unknownMold")), subtitle="kind of change unknown", icon="help", icon_color="#d97706"))
        parts = [lead, self._changeover_takeaway(data), self._changeover_notes(data)]
        parts.append(Layout.grid("repeat(auto-fit, minmax(320px, 1fr))", self._kinds_card(data), self._when_chart(data)))
        parts.append(self._speed_chart(data))
        parts.append(self._change_machines(data))
        parts.append(Layout.grid("repeat(auto-fit, minmax(320px, 1fr))", self._change_months(data), self._lengths_chart(data)))
        return parts

    def _changeover_takeaway(self, data):
        rows = [row for row in data.get("shifts") or [] if row.get("changeover") is not None and row.get("normal") is not None and row.get("count")]
        if not rows:
            return None
        busiest = max(data.get("byShift") or [{"shift": "", "count": 0}], key=lambda row: row["count"])
        row = next((entry for entry in rows if entry["shift"] == busiest["shift"]), rows[0])
        share = round(100.0 * busiest["count"] / data["withLoss"]) if data.get("withLoss") else 0
        if row["changeover"] >= row["normal"] - 5:
            speed = "With the changeover time taken out, the rest of that shift runs at <b>%s%%</b> of rated speed, against <b>%s%%</b> on other shifts: " \
                    "the loss is the change itself, not slow running after it." % (row["changeover"], row["normal"])
        else:
            speed = "Even with the changeover time taken out, the rest of that shift runs at <b>%s%%</b> of rated speed, against <b>%s%%</b> on " \
                    "other shifts: start-up after a change is slow too." % (row["changeover"], row["normal"])
        return Layout.html("<p class='cy-takeaway'><b>%s%%</b> of the changeovers that cost time start in the %s shift. %s</p>"
                           % (share, busiest["shift"].lower(), speed))

    def _changeover_notes(self, data):
        low = data.get("lowConfidence") or 0
        unknown = data.get("unknownMold") or 0
        lines = ["Most changeovers are not written in the log. Their times are worked out from the output the shifts around each change did not make, "
                 "against what each recipe usually makes in an hour; a logged mold-change stop is used where there is one."]
        if low:
            lines.append("%s rest on a speed known from few shifts and are marked low confidence." % Format.grouped(low))
        unknown_text = (" %s changeovers are between recipes with no mold written, so a mold change cannot be told from a color change. "
                        "<a href='javascript:void(0)' data-nav='gap'>Add the mold on those recipes.</a>" % Format.grouped(unknown)) if unknown else ""
        markup = "<p class='bc-note bc-note-muted'>%s%s <a href='javascript:void(0)' data-nav='list'>Open every changeover with how its time was " \
                 "worked out.</a></p>" % (Layout.esc(" ".join(lines)), unknown_text)
        return Layout.interactive(markup, self._on_change_nav)

    def _on_change_nav(self, mode, node):
        where = Layout.attr(node, "data-nav")
        if where == "gap":
            Nav.go("recipe", query={"gap": "no-mold"})
        elif where == "list":
            Nav.go("changeover")

    def _kinds_card(self, data):
        rows = data.get("kinds") or []
        card = Layout.section("By kind of change", "A mold change is told from a color or material change by the mold and inputs on the two recipes.")
        Layout.body(card, Tables.mount_report(rows, Tables.columns_perf_changeover_kinds()))
        return card

    def _when_chart(self, data):
        rows = data.get("byShift") or []
        return _chart("Which shift the time is lost in", "Changeovers that cost production time, by the shift they started in.", {
            "tooltip": {"trigger": "axis"}, "grid": {"left": 48, "right": 16, "top": 16, "bottom": 28},
            "xAxis": {"type": "category", "data": [row["shift"] for row in rows]}, "yAxis": {"type": "value", "name": "Changes"},
            "series": [{"type": "bar", "data": [row["count"] for row in rows], "itemStyle": {"color": "#14b8a6"}, "label": {"show": True, "position": "top"}}],
        }, height="260px")

    def _speed_chart(self, data):
        shifts = data.get("shifts") or []
        return _chart("Speed by shift, with the changeover time taken out",
                      "Median pieces made against the rated speed while running. Amber: shifts with a changeover; green: the others.", {
            "tooltip": {"trigger": "axis"}, "legend": {"top": 0},
            "grid": {"left": 48, "right": 16, "top": 40, "bottom": 28},
            "xAxis": {"type": "category", "data": [row["shift"] for row in shifts]},
            "yAxis": {"type": "value", "name": "%"},
            "series": [
                {"type": "bar", "name": "Shifts with a changeover", "data": [row["changeover"] for row in shifts], "itemStyle": {"color": "#f59e0b"},
                 "label": {"show": True, "position": "top", "formatter": "{c}%"}},
                {"type": "bar", "name": "Other shifts", "data": [row["normal"] for row in shifts], "itemStyle": {"color": "#22c55e"},
                 "label": {"show": True, "position": "top", "formatter": "{c}%"}},
            ],
        }, height="280px")

    def _change_machines(self, data):
        rows = data.get("byMachine") or []
        if not rows:
            return None
        card = Layout.section("By machine", "Most production lost first. Click a row to open that machine's changeovers.")
        Layout.body(card, Tables.mount_report(rows, Tables.columns_perf_changeover_machines(),
                                              on_row=lambda row: _open_machine(row, "changeovers")))
        return card

    def _change_months(self, data):
        months = data.get("byMonth") or {}
        return _chart("Month by month", "Bars: changeovers. Line: hours of production lost.", {
            "tooltip": {"trigger": "axis"}, "legend": {"top": 0},
            "grid": {"left": 48, "right": 48, "top": 40, "bottom": 28},
            "xAxis": {"type": "category", "data": months.get("labels") or []},
            "yAxis": [{"type": "value", "name": "Changes"}, {"type": "value", "name": "Hours", "splitLine": {"show": False}}],
            "series": [{"type": "bar", "name": "Changeovers", "data": months.get("values") or [], "itemStyle": {"color": "#14b8a6"}},
                       {"type": "line", "name": "Hours lost", "yAxisIndex": 1, "data": months.get("hours") or [], "itemStyle": {"color": "#dc2626"}}],
        }, height="280px")

    def _lengths_chart(self, data):
        lengths = data.get("lengths") or []
        return _chart("How long an item stays on a machine", "Days per campaign: short campaigns mean more changeovers.", {
            "tooltip": {"trigger": "axis"}, "grid": {"left": 48, "right": 16, "top": 16, "bottom": 28},
            "xAxis": {"type": "category", "data": [row["label"] for row in lengths]}, "yAxis": {"type": "value", "name": "Campaigns"},
            "series": [{"type": "bar", "data": [row["count"] for row in lengths], "itemStyle": {"color": "#6366f1"}, "label": {"show": True, "position": "top"}}],
        }, height="280px")

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
                        "data": [{"value": row["scrap"], "label": {"formatter": "%s · %s%% of its pieces" % (Format.grouped(row["scrap"]), Format.trim(row["pct"]))}}
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
        card = Layout.section("Shifts and idle days", "One-shift days ran a single shift; idle days had no run at all. Click a row to open the machine.")
        Layout.body(card, Tables.mount_report(rows, Tables.columns_perf_capacity(), on_row=_open_machine))
        return [chart, card, self._fit()]

    def _fit(self):
        rows = self.data.get("fit") or []
        if not rows:
            return None
        body = []
        for row in rows:
            options = "".join("<div class='cy-fit-opt%s'><b>%s</b><span>%s pcs/h</span><small>rated %s · %s shifts</small></div>" % (
                " is-best" if index == 0 else "", Layout.esc(option["machine"]), Format.grouped(option["actual"]), Format.grouped(option["rated"]), option["shifts"])
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
                Format.grouped(check.get("count")), Layout.esc(check.get("label")), Layout.esc(check.get("detail")),
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
