"""How the plant used its time: the production log and stoppages turned into hours and losses.

Every staffed shift is split into hours: good pieces and scrap at the rated speed (the run's
cavities and cycle), running slower than that, changing over, stopped (planned or not, by the
cause's flag), and idle with no reason given. A run logged for a whole shift is cut at its
changeover (see ``changeovers``), so two items in one shift share it instead of both filling it.
Pages filter by year, month and machine.
"""

import datetime
import statistics

import domain
import records

PLANT_ZONE = "Europe/Athens"
MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
BUCKETS = (
    ("good", "Good pieces"), ("scrap", "Scrap"), ("slow", "Running slow"), ("changeover", "Changeovers"),
    ("planned", "Planned stops"), ("unplanned", "Breakdowns and other stops"), ("idle", "Idle, no reason given"),
)
RUN_LENGTHS = (("1 day", 1, 1), ("2–3 days", 2, 3), ("4–7 days", 4, 7), ("1–2 weeks", 8, 14), ("Over 2 weeks", 15, 10000))


def _zone():
    try:
        from zoneinfo import ZoneInfo
        return ZoneInfo(PLANT_ZONE)
    except Exception:
        return datetime.timezone(datetime.timedelta(hours=2))


def _clock(text):
    """Hours after midnight of an "HH:MM" time, or None."""
    try:
        parts = [int(part) for part in (text or "").split(":")[:2]]
    except ValueError:
        return None
    return parts[0] + parts[1] / 60.0 if len(parts) == 2 else None


def _shift_hours(shift):
    start, end = _clock(shift.get("start")), _clock(shift.get("end"))
    if start is None or end is None:
        return 8.0
    hours = end - start
    return hours + 24 if hours <= 0 else hours


def run_day(begin, shift, zone=None):
    """The plant day of a run starting at ``begin``: a night shift's hours after midnight count for the day it started."""
    start_local = begin.astimezone(zone or _zone())
    day = start_local.date()
    if shift and start_local.hour < 6 and (shift.get("start") or "") > (shift.get("end") or ""):
        day = day - datetime.timedelta(days=1)
    return day


def slot_window(day, shift, zone=None):
    """The UTC start and end of ``shift`` on plant day ``day``, or None when the shift has no times."""
    start = _clock(shift.get("start")) if shift else None
    if start is None:
        return None
    zone = zone or _zone()
    begin = datetime.datetime(day.year, day.month, day.day, int(start), int(round((start % 1) * 60)), tzinfo=zone).astimezone(datetime.timezone.utc)
    return begin, begin + datetime.timedelta(hours=_shift_hours(shift))


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


def local_bounds(start, end):
    """The UTC moments at the plant's midnight starting ``start`` and ``end`` (dates)."""
    zone = _zone()
    return tuple(datetime.datetime(day.year, day.month, day.day, tzinfo=zone).astimezone(datetime.timezone.utc) for day in (start, end))


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
        day = run_day(begin, shift, zone)
        runs.append({"run": run, "begin": begin, "finish": finish, "day": day, "machine": recipe.get("machineId") or "",
                     "item": recipe.get("itemId") or "", "shift": run.get("shiftId") or "", "shiftHours": _shift_hours(shift),
                     "window": slot_window(day, shift, zone)})
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
    changes = _changeover_windows(graph.get("changeovers") or [])
    counted_stops = {change["stoppageId"] for change in changes if change["stoppageId"]}
    stops_by_run = {}
    for entry in stops:
        if entry["stop"]["id"] not in counted_stops:
            stops_by_run.setdefault(entry["stop"].get("runId"), []).append(entry)
    _cut_at_changeovers(chosen, changes)
    changes_by_machine = {}
    for change in changes:
        changes_by_machine.setdefault(change["machine"], []).append(change)
    change_runs = {code for change in changes for code in (change["fromRun"], change["toRun"])}

    totals, by_month, by_machine = _blank(), {}, {}
    cells = {}
    shift_ratio = {}
    rated_runs = 0
    good_total = scrap_total = 0.0
    slots = {}
    for entry in chosen:
        slots.setdefault((entry["machine"], entry["day"], entry["shift"]), []).append(entry)
    for (code, day, shift_code), group in slots.items():
        shift_h = group[0]["shiftHours"]
        window = group[0]["window"] or (min(entry["begin0"] for entry in group), max(entry["finish0"] for entry in group))
        cell = cells.setdefault((code, day), {"good": 0.0, "rated": False, "shifts": set(), "pieces": 0, "items": set()})
        cell["shifts"].add(shift_code)
        hours = _blank()
        rated = False
        on_change = any(entry["run"]["id"] in change_runs for entry in group)
        together = _parallel(group)
        seen_stops = set()
        for entry in group:
            run = entry["run"]
            good = domain.num(run.get("good")) or 0
            scrap = sum(domain.num(line.get("quantity")) or 0 for line in run.get("scrap") or [])
            good_total += good
            scrap_total += scrap
            cell["pieces"] += good
            cell["items"].add(entry["item"])
            own = stops_by_run.get(run["id"]) or []
            for stop in own:
                if stop["stop"]["id"] not in seen_stops:
                    seen_stops.add(stop["stop"]["id"])
                    hours["planned" if stop["planned"] else "unplanned"] += stop["hours"]
            rate = _rate(run)
            if not rate:
                continue
            rated = True
            rated_runs += 1
            run_h = (entry["finish"] - entry["begin"]).total_seconds() / 3600.0
            stop_in = sum(_overlap(entry["begin"], entry["finish"], stop["begin"], stop["finish"]) for stop in own)
            running = max(0.0, run_h - stop_in)
            needed = (good + scrap) / rate
            fit = min(1.0, running / needed) if needed else 1.0
            share = 1.0 / together.get(run["id"], 1)
            hours["good"] += good / rate * fit * share
            hours["scrap"] += scrap / rate * fit * share
            hours["slow"] += max(0.0, running - needed) * share
            if running > 0.5 and needed:
                shift_ratio.setdefault(shift_code, []).append((on_change, needed / running))
        if not rated:
            continue
        hours["changeover"] = min(shift_h, sum(_overlap(change["begin"], change["end"], window[0], window[1])
                                               for change in changes_by_machine.get(code) or []))
        hours["idle"] = max(0.0, shift_h - sum(hours.values()))
        _add(totals, hours)
        _add(by_month.setdefault(day.month, _blank()), hours)
        _add(by_machine.setdefault(code, _blank()), hours)
        cell["good"] += hours["good"]
        cell["rated"] = True

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

    lengths = _campaigns(chosen)
    shown_runs = {entry["run"]["id"] for entry in chosen}
    changeovers = [change for change in changes if change["toRun"] in shown_runs]
    shift_rows = []
    for code in shift_order:
        values = shift_ratio.get(code) or []
        shift_rows.append({
            "shift": (shifts.get(code) or {}).get("name") or code, "all": _median_pct([ratio for _, ratio in values]),
            "changeover": _median_pct([ratio for flag, ratio in values if flag]), "normal": _median_pct([ratio for flag, ratio in values if not flag]),
            "count": len(values),
        })
    change_summary = _changeover_summary(changeovers, shifts, shift_order, machine_names, zone)
    change_summary.update({"lengths": lengths, "shifts": shift_rows, "hours": round(sum(change["lost"] for change in changeovers), 1),
                           "plannedHours": round(sum(entry["hours"] for entry in stops if entry["planned"] and entry["stop"]["id"] not in counted_stops))})

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
            "unplannedHours": round(unplanned), "changeovers": len(changeovers), "changeoverHours": round(sum(change["lost"] for change in changeovers)),
            "runs": len(chosen), "ratedRuns": rated_runs,
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
        "changeovers": change_summary,
        "scrapItems": scrap_items, "scrapMachines": scrap_machines, "fit": fit,
    }


def _median_pct(values):
    values = [value for value in values or [] if 0 < value < 3]
    return round(100.0 * statistics.median(values)) if values else None


def _changeover_windows(found):
    """The stored changeovers with a start and end, as moments."""
    changes = []
    for change in found:
        begin, end = records.parse_moment(change.get("startedAt")), records.parse_moment(change.get("endedAt"))
        if begin is None or end is None or end < begin:
            continue
        changes.append({"id": change["id"], "machine": change.get("machineId") or "", "fromRun": change.get("fromRunId") or "",
                        "toRun": change.get("toRunId") or "", "begin": begin, "end": end, "stoppageId": change.get("stoppageId") or "",
                        "kind": change.get("kind") or "unknown", "lost": domain.num(change.get("lostHours")) or 0.0,
                        "source": change.get("source") or "", "confidence": change.get("confidence") or ""})
    return changes


def _cut_at_changeovers(entries, changes):
    """A run logged for the whole shift really ended where its changeover began, and the next run began where it ended."""
    ends = {change["fromRun"]: change["begin"] for change in changes}
    starts = {change["toRun"]: change["end"] for change in changes}
    for entry in entries:
        entry["begin0"], entry["finish0"] = entry["begin"], entry["finish"]
        code = entry["run"]["id"]
        if code in ends and entry["begin"] < ends[code] < entry["finish"]:
            entry["finish"] = ends[code]
        if code in starts and entry["begin"] < starts[code] < entry["finish"]:
            entry["begin"] = starts[code]


def _shift_at(moment, shifts, shift_order, zone):
    shown = moment.astimezone(zone)
    clock = shown.hour + shown.minute / 60.0
    for code in shift_order:
        shift = shifts[code]
        start, end = _clock(shift.get("start")), _clock(shift.get("end"))
        if start is None or end is None:
            continue
        if (start <= clock < end) if start < end else (clock >= start or clock < end):
            return shift.get("name") or code
    return ""


def _changeover_summary(changes, shifts, shift_order, machine_names, zone):
    """Counts and hours by kind, shift, machine and month; how each was known."""
    with_loss = [change for change in changes if change["lost"] > 0]
    kinds = []
    for key, label in domain.CHANGEOVER_KINDS:
        found = [change for change in changes if change["kind"] == key]
        lost = [change["lost"] for change in found if change["lost"] > 0]
        if found:
            kinds.append({"key": key, "label": label, "count": len(found), "hours": round(sum(lost), 1),
                          "median": round(statistics.median(lost), 1) if lost else None})
    by_shift = {}
    for change in with_loss:
        name = _shift_at(change["begin"], shifts, shift_order, zone) or "Other"
        by_shift[name] = by_shift.get(name, 0) + 1
    by_machine = {}
    for change in changes:
        row = by_machine.setdefault(change["machine"], {"machine": machine_names.get(change["machine"], change["machine"]), "id": change["machine"],
                                                        "count": 0, "hours": 0.0, "lost": []})
        row["count"] += 1
        row["hours"] += change["lost"]
        if change["lost"] > 0:
            row["lost"].append(change["lost"])
    machine_rows = sorted(({"machine": row["machine"], "id": row["id"], "count": row["count"], "hours": round(row["hours"], 1),
                            "median": round(statistics.median(row["lost"]), 1) if row["lost"] else None} for row in by_machine.values()),
                          key=lambda row: -row["hours"])
    by_month = {}
    for change in changes:
        number = local_day(change["end"]).month
        row = by_month.setdefault(number, [0, 0.0])
        row[0] += 1
        row[1] += change["lost"]
    lost = [change["lost"] for change in with_loss]
    return {
        "count": len(changes), "withLoss": len(with_loss), "median": round(statistics.median(lost), 1) if lost else None,
        "kinds": kinds, "unknownMold": sum(1 for change in changes if change["kind"] == "unknown"),
        "byShift": [{"shift": (shifts.get(code) or {}).get("name") or code, "count": by_shift.get((shifts.get(code) or {}).get("name") or code, 0)}
                    for code in shift_order],
        "sources": [{"key": key, "label": label, "count": sum(1 for change in changes if change["source"] == key)}
                    for key, label in domain.CHANGEOVER_SOURCES],
        "lowConfidence": sum(1 for change in changes if change["confidence"] == "low"),
        "byMachine": machine_rows,
        "byMonth": {"labels": [MONTHS[number - 1] for number in sorted(by_month)], "values": [by_month[number][0] for number in sorted(by_month)],
                    "hours": [round(by_month[number][1], 1) for number in sorted(by_month)]},
    }


def _campaigns(chosen):
    """How many days each campaign (one item on one machine in a row) lasted."""
    lengths = {label: 0 for label, _, _ in RUN_LENGTHS}
    by_machine = {}
    for entry in chosen:
        by_machine.setdefault(entry["machine"], []).append(entry)
    for entries in by_machine.values():
        entries.sort(key=lambda entry: entry["begin0"])
        current, days = None, set()
        for entry in entries:
            if entry["item"] != current:
                if current is not None:
                    _count_length(lengths, len(days))
                current, days = entry["item"], set()
            days.add(entry["day"])
        if current is not None:
            _count_length(lengths, len(days))
    return [{"label": label, "count": lengths[label]} for label, _, _ in RUN_LENGTHS]


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
