"""How the plant used its time: the production log and stoppages turned into hours and losses.

Every staffed shift is split into hours: good pieces and scrap at the rated speed (the run's
cavities and cycle), running slower than that, stopped (planned or not, by the cause's flag),
and idle with no reason given. Pages filter by year, month and machine.
"""

import datetime
import statistics

import domain
import records

PLANT_ZONE = "Europe/Athens"
MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
BUCKETS = (
    ("good", "Good pieces"), ("scrap", "Scrap"), ("slow", "Running slow"),
    ("planned", "Planned stops"), ("unplanned", "Breakdowns and other stops"), ("idle", "Idle, no reason given"),
)
RUN_LENGTHS = (("1 day", 1, 1), ("2–3 days", 2, 3), ("4–7 days", 4, 7), ("1–2 weeks", 8, 14), ("Over 2 weeks", 15, 10000))


def _zone():
    try:
        from zoneinfo import ZoneInfo
        return ZoneInfo(PLANT_ZONE)
    except Exception:
        return datetime.timezone(datetime.timedelta(hours=2))


def _shift_hours(shift):
    try:
        start = [int(part) for part in (shift.get("start") or "").split(":")[:2]]
        end = [int(part) for part in (shift.get("end") or "").split(":")[:2]]
    except ValueError:
        return 8.0
    hours = (end[0] + end[1] / 60.0) - (start[0] + start[1] / 60.0)
    return hours + 24 if hours <= 0 else hours


def _rate(run):
    """Rated pieces per hour: cavities × 3600 / cycle seconds."""
    cavities, cycle = domain.num(run.get("cavities")), domain.num(run.get("cycle"))
    if not cavities or not cycle:
        return None
    return cavities * 3600.0 / cycle


def _overlap(begin, finish, start, end):
    low, high = max(begin, start), min(finish, end)
    return max(0.0, (high - low).total_seconds() / 3600.0)


def _parallel(entries):
    """Run id -> how many runs share its machine-shift at the same time (a family mold makes two items at once)."""
    slots = {}
    for entry in entries:
        slots.setdefault((entry["machine"], entry["day"], entry["shift"]), []).append(entry)
    together = {}
    for group in slots.values():
        if len(group) < 2:
            continue
        for entry in group:
            together[entry["run"]["id"]] = sum(1 for other in group if _overlap(entry["begin"], entry["finish"], other["begin"], other["finish"]) > 0)
    return together


def _blank():
    return {key: 0.0 for key, _ in BUCKETS}


def _add(target, source):
    for key in target:
        target[key] += source.get(key, 0.0)


def _round(buckets):
    return {key: round(value, 1) for key, value in buckets.items()}


def local_day(moment):
    """The plant day a run starting at ``moment`` belongs to: a night shift after midnight counts for the day before."""
    shown = moment.astimezone(_zone())
    return shown.date() - datetime.timedelta(days=1) if shown.hour < 6 else shown.date()


def period(year, month=0):
    """The UTC moments to read runs and stoppages between for ``year`` (and ``month``), a day wider each side for night shifts."""
    month = int(month or 0)
    start = datetime.date(int(year), month or 1, 1)
    end = datetime.date(int(year) + (month == 12), month % 12 + 1, 1) if month else datetime.date(int(year) + 1, 1, 1)
    zone = _zone()
    edges = [datetime.datetime(day.year, day.month, day.day, tzinfo=zone).astimezone(datetime.timezone.utc) for day in (start, end)]
    return edges[0] - datetime.timedelta(days=1), edges[1] + datetime.timedelta(days=1)


def view(graph, year=None, month=0, machine="", years=None, through=None):
    """``through`` is the plant's last run day; without it the last run read counts."""
    index = domain.reindex(graph)
    zone = _zone()
    machines = [entry for entry in graph["machines"] if not entry.get("attachedToId")]
    causes = index["stoppage_causes"]
    shifts = {entry["id"]: entry for entry in graph["shifts"]}
    shift_order = [entry["id"] for entry in graph["shifts"]]

    def local(moment):
        parsed = records.parse_moment(moment)
        return parsed.astimezone(zone) if parsed else None

    runs = []
    for run in graph["production_runs"]:
        begin, finish = records.parse_moment(run.get("startedAt")), records.parse_moment(run.get("endedAt"))
        if begin is None or finish is None or finish <= begin:
            continue
        recipe = index["recipes"].get(run.get("recipeId")) or {}
        shift = shifts.get(run.get("shiftId")) or {}
        start_local = begin.astimezone(zone)
        day = start_local.date()
        if shift and start_local.hour < 6 and (shift.get("start") or "") > (shift.get("end") or ""):
            day = day - datetime.timedelta(days=1)
        runs.append({"run": run, "begin": begin, "finish": finish, "day": day, "machine": recipe.get("machineId") or "",
                     "item": recipe.get("itemId") or "", "shift": run.get("shiftId") or "", "shiftHours": _shift_hours(shift)})
    years = years or sorted({entry["day"].year for entry in runs}, reverse=True)
    year = int(year) if year else (years[0] if years else datetime.date.today().year)
    month = int(month or 0)

    def wanted_day(day):
        return day.year == year and (not month or day.month == month)

    chosen = [entry for entry in runs if wanted_day(entry["day"]) and (not machine or entry["machine"] == machine)]
    every_machine_runs = [entry for entry in runs if wanted_day(entry["day"])]
    stops = []
    for stop in graph["stoppages"]:
        begin, finish = records.parse_moment(stop.get("startedAt")), records.parse_moment(stop.get("endedAt"))
        if begin is None or finish is None or finish <= begin:
            continue
        day = begin.astimezone(zone).date()
        if not wanted_day(day) or (machine and stop.get("machineId") != machine):
            continue
        cause = causes.get(stop.get("causeId")) or {}
        stops.append({"stop": stop, "begin": begin, "finish": finish, "hours": (finish - begin).total_seconds() / 3600.0, "day": day,
                      "cause": cause.get("name") or "Not classified", "group": cause.get("category") or "", "planned": bool(cause.get("planned"))})
    stops_by_run = {}
    for entry in stops:
        stops_by_run.setdefault(entry["stop"].get("runId"), []).append(entry)

    parallel = _parallel(chosen)
    totals, by_month, by_machine = _blank(), {}, {}
    cells = {}
    shift_ratio = {}
    rated_runs = 0
    good_total = scrap_total = 0.0
    for entry in chosen:
        run = entry["run"]
        good = domain.num(run.get("good")) or 0
        scrap = sum(domain.num(line.get("quantity")) or 0 for line in run.get("scrap") or [])
        good_total += good
        scrap_total += scrap
        cell = cells.setdefault((entry["machine"], entry["day"]), {"good": 0.0, "rated": False, "shifts": set(), "pieces": 0, "items": set()})
        cell["shifts"].add(entry["shift"])
        cell["pieces"] += good
        cell["items"].add(entry["item"])
        rate = _rate(run)
        if not rate:
            continue
        rated_runs += 1
        shift_h = entry["shiftHours"]
        run_h = (entry["finish"] - entry["begin"]).total_seconds() / 3600.0
        own = stops_by_run.get(run["id"]) or []
        stop_in = sum(_overlap(entry["begin"], entry["finish"], stop["begin"], stop["finish"]) for stop in own)
        planned_h = sum(stop["hours"] for stop in own if stop["planned"])
        unplanned_h = sum(stop["hours"] for stop in own if not stop["planned"])
        stop_out = max(0.0, planned_h + unplanned_h - stop_in)
        running = max(0.0, run_h - stop_in)
        needed = (good + scrap) / rate
        fit = min(1.0, running / needed) if needed else 1.0
        hours = {
            "good": good / rate * fit, "scrap": scrap / rate * fit, "slow": max(0.0, running - needed),
            "planned": planned_h, "unplanned": unplanned_h, "idle": max(0.0, shift_h - run_h - stop_out),
        }
        spare = shift_h - sum(hours.values())
        if spare < 0:
            hours["idle"] = max(0.0, hours["idle"] + spare)
        together = parallel.get(run["id"], 1)
        if together > 1:
            hours = {key: value / together for key, value in hours.items()}
        _add(totals, hours)
        _add(by_month.setdefault(entry["day"].month, _blank()), hours)
        _add(by_machine.setdefault(entry["machine"], _blank()), hours)
        cell["good"] += hours["good"]
        cell["rated"] = True
        if running > 0.5 and needed:
            shift_ratio.setdefault(entry["shift"], []).append((entry["machine"], entry["day"], needed / running))

    staffed = sum(totals.values())
    machine_names = {entry["id"]: entry.get("name") or entry["id"] for entry in machines}
    shown_machines = [entry["id"] for entry in machines if not machine or entry["id"] == machine]
    days = sorted({entry["day"] for entry in runs if wanted_day(entry["day"])})
    first = datetime.date(year, month or 1, 1)
    last = (datetime.date(year + (month == 12), (month % 12) + 1, 1) - datetime.timedelta(days=1)) if month else datetime.date(year, 12, 31)
    if through or days:
        last = min(last, through or max(days))
    calendar_days = (last - first).days + 1 if last >= first else 0

    used_slots = {}
    for entry in every_machine_runs:
        used_slots.setdefault(entry["machine"], set()).add((entry["day"], entry["shift"]))
    capacity = []
    for code in shown_machines:
        slots = used_slots.get(code) or set()
        by_day = {}
        for day, _ in slots:
            by_day[day] = by_day.get(day, 0) + 1
        capacity.append({
            "machine": machine_names.get(code), "id": code, "used": len(slots), "possible": calendar_days * len(shift_order),
            "pct": round(100.0 * len(slots) / (calendar_days * len(shift_order)), 1) if calendar_days else 0,
            "oneShiftDays": sum(1 for value in by_day.values() if value == 1), "idleDays": calendar_days - len(by_day),
        })
    capacity.sort(key=lambda row: row["pct"])
    possible = sum(row["possible"] for row in capacity)
    used = sum(row["used"] for row in capacity)

    calendar_machines = [code for code in shown_machines if code in used_slots or machine]
    machine_row = {code: number for number, code in enumerate(calendar_machines)}
    calendar_items, item_number = [], {}
    calendar = []
    for (code, day), cell in cells.items():
        if code not in machine_row or not first <= day <= last:
            continue
        share = min(100.0, round(100.0 * cell["good"] / 24.0, 1)) if cell["rated"] else None
        numbers = []
        for item in sorted(cell["items"]):
            if item not in item_number:
                item_number[item] = len(calendar_items)
                calendar_items.append(domain.name_of(index, "items", item))
            numbers.append(item_number[item])
        calendar.append([(day - first).days, machine_row[code], share, len(cell["shifts"]), int(cell["pieces"]), numbers])

    causes_out = {}
    for entry in stops:
        row = causes_out.setdefault(entry["cause"], {"cause": entry["cause"], "group": entry["group"], "planned": entry["planned"], "hours": 0.0, "count": 0})
        row["hours"] += entry["hours"]
        row["count"] += 1
    cause_rows = sorted(({**row, "hours": round(row["hours"], 1)} for row in causes_out.values()), key=lambda row: -row["hours"])

    changeovers, lengths = _changeovers(chosen, machine_names)
    changeover_days = {(entry["machine"], entry["day"]) for entry in changeovers}
    shift_rows = []
    for code in shift_order:
        values = shift_ratio.get(code) or []
        on_change = [ratio for machine_code, day, ratio in values if (machine_code, day) in changeover_days]
        normal = [ratio for machine_code, day, ratio in values if (machine_code, day) not in changeover_days]
        shift_rows.append({
            "shift": (shifts.get(code) or {}).get("name") or code,
            "all": _median_pct(values and [ratio for _, _, ratio in values]), "changeover": _median_pct(on_change), "normal": _median_pct(normal),
            "count": len(values),
        })
    change_by_month = {}
    for entry in changeovers:
        change_by_month[entry["day"].month] = change_by_month.get(entry["day"].month, 0) + 1

    scrap_items, scrap_machines = _scrap(chosen, index, machine_names)
    fit = _fit(every_machine_runs, stops_by_run, index, machine_names, machine)
    months = sorted(by_month)
    unplanned = sum(entry["hours"] for entry in stops if not entry["planned"])
    return {
        "year": year, "month": month, "machine": machine, "years": years,
        "machines": [{"value": entry["id"], "label": entry.get("name") or entry["id"]} for entry in machines if entry["id"] in used_slots or entry["id"] == machine],
        "kpis": {
            "good": int(good_total), "scrapPct": round(100.0 * scrap_total / (good_total + scrap_total), 2) if good_total + scrap_total else None,
            "oee": round(100.0 * totals["good"] / staffed, 1) if staffed else None, "staffedHours": round(staffed),
            "lostHours": round(staffed - totals["good"]), "capacityPct": round(100.0 * used / possible, 1) if possible else None,
            "unplannedHours": round(unplanned), "changeovers": len(changeovers), "runs": len(chosen), "ratedRuns": rated_runs,
        },
        "buckets": [{"key": key, "label": label, "hours": round(totals[key], 1)} for key, label in BUCKETS],
        "byMonth": {"labels": [MONTHS[number - 1] for number in months], "series": [
            {"key": key, "label": label, "values": [round(by_month[number][key], 1) for number in months]} for key, label in BUCKETS],
            "oee": [round(100.0 * by_month[number]["good"] / sum(by_month[number].values()), 1) if sum(by_month[number].values()) else None for number in months]},
        "byMachine": sorted(({"machine": machine_names.get(code, code), "id": code, **_round(bucket),
                              "oee": round(100.0 * bucket["good"] / sum(bucket.values()), 1) if sum(bucket.values()) else None}
                             for code, bucket in by_machine.items() if sum(bucket.values()) >= 24), key=lambda row: row["oee"] or 0),
        "calendar": calendar, "calendarMachines": [machine_names[code] for code in calendar_machines], "calendarItems": calendar_items,
        "calendarRange": [first.isoformat(), last.isoformat()],
        "capacity": capacity, "causes": cause_rows,
        "changeovers": {"byMonth": {"labels": [MONTHS[number - 1] for number in sorted(change_by_month)],
                                    "values": [change_by_month[number] for number in sorted(change_by_month)]},
                        "lengths": lengths, "shifts": shift_rows,
                        "plannedHours": round(sum(entry["hours"] for entry in stops if entry["planned"]))},
        "scrapItems": scrap_items, "scrapMachines": scrap_machines, "fit": fit,
    }


def _median_pct(values):
    values = [value for value in values or [] if 0 < value < 3]
    return round(100.0 * statistics.median(values)) if values else None


def _changeovers(chosen, machine_names):
    """Each time a machine went from one item to another, and how many days each campaign lasted."""
    changes, lengths = [], {label: 0 for label, _, _ in RUN_LENGTHS}
    by_machine = {}
    for entry in chosen:
        by_machine.setdefault(entry["machine"], []).append(entry)
    for code, entries in by_machine.items():
        entries.sort(key=lambda entry: entry["begin"])
        current, days = None, set()
        for entry in entries:
            if entry["item"] != current:
                if current is not None:
                    changes.append({"machine": code, "day": entry["day"]})
                    _count_length(lengths, len(days))
                current, days = entry["item"], set()
            days.add(entry["day"])
        if current is not None:
            _count_length(lengths, len(days))
    return changes, [{"label": label, "count": lengths[label]} for label, _, _ in RUN_LENGTHS]


def _count_length(lengths, days):
    for label, low, high in RUN_LENGTHS:
        if low <= days <= high:
            lengths[label] += 1
            return


def _scrap(chosen, index, machine_names):
    items, machines = {}, {}
    for entry in chosen:
        good = domain.num(entry["run"].get("good")) or 0
        scrap = sum(domain.num(line.get("quantity")) or 0 for line in entry["run"].get("scrap") or [])
        for table, key in ((items, entry["item"]), (machines, entry["machine"])):
            row = table.setdefault(key, [0.0, 0.0])
            row[0] += good
            row[1] += scrap
    total = sum(row[1] for row in items.values()) or 1.0
    ranked = sorted(items.items(), key=lambda pair: -pair[1][1])[:15]
    running, item_rows = 0.0, []
    for code, (good, scrap) in ranked:
        if not scrap:
            break
        running += scrap
        item_rows.append({"item": domain.name_of(index, "items", code), "id": code, "scrap": int(scrap),
                          "pct": round(100.0 * scrap / (good + scrap), 2) if good + scrap else 0, "cumulative": round(100.0 * running / total, 1)})
    machine_rows = sorted(({"machine": machine_names.get(code, code), "id": code, "scrap": int(scrap),
                            "pct": round(100.0 * scrap / (good + scrap), 2) if good + scrap else 0}
                           for code, (good, scrap) in machines.items() if good + scrap), key=lambda row: -row["pct"])
    return item_rows, machine_rows


def _fit(runs, stops_by_run, index, machine_names, machine=""):
    """Items made on more than one machine: the rated and the actual pieces per hour on each."""
    seen = {}
    for entry in runs:
        rate = _rate(entry["run"])
        if not rate:
            continue
        run_h = (entry["finish"] - entry["begin"]).total_seconds() / 3600.0
        stopped = sum(_overlap(entry["begin"], entry["finish"], stop["begin"], stop["finish"]) for stop in stops_by_run.get(entry["run"]["id"]) or [])
        running = run_h - stopped
        pieces = (domain.num(entry["run"].get("good")) or 0) + sum(domain.num(line.get("quantity")) or 0 for line in entry["run"].get("scrap") or [])
        row = seen.setdefault(entry["item"], {}).setdefault(entry["machine"], {"rated": [], "actual": [], "shifts": 0})
        row["rated"].append(rate)
        if running > 0.5:
            row["actual"].append(pieces / running)
        row["shifts"] += 1
    rows = []
    for item, by_machine in seen.items():
        usable = {code: data for code, data in by_machine.items() if data["actual"] and data["shifts"] >= 3}
        if len(usable) < 2 or (machine and machine not in usable):
            continue
        options = sorted(({"machine": machine_names.get(code, code), "id": code, "rated": round(statistics.median(data["rated"])),
                           "actual": round(statistics.median(data["actual"])), "shifts": data["shifts"]} for code, data in usable.items()),
                         key=lambda option: -option["actual"])
        best, worst = options[0]["actual"], options[-1]["actual"] or 1
        rows.append({"item": domain.name_of(index, "items", item), "id": item, "options": options, "gain": round(100.0 * (best - worst) / worst)})
    rows.sort(key=lambda row: -row["gain"])
    return rows[:20]
