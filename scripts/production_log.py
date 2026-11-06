"""Cyclops' yearly production log: one sheet per machine, a row per day with counter readings,
pieces per shift, scrap, cycle time, the shift crews and a free-text note.

This is client code. The sheet layout and its quirks (wrong years, cycle times typed as text,
downtime written into notes) are read here and nowhere else. The result is plain core records:
one production run per machine and shift, a completed order per campaign (the days a machine
ran one product in a row), and stoppages from the notes with an auto-classified cause.

Names are matched through ``production_log_map.json``: machines, operators and products. The
file is written on the first run with every match found and the closest names for the rest, and
read as it stands after that, so corrections made in it are kept.
"""

import collections
import datetime
import difflib
import json
import re
import statistics
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOG = Path.home() / "Downloads" / "ΠΑΡΑΓΩΓΗ 2025.xlsx"
MAP_FILE = ROOT / "scripts" / "production_log_map.json"
YEAR = 2025
NOTE_MARK = "Auto-classified from the 2025 log note"
FROM_LOG = "From the 2025 production log."

MACHINES = {
    "NEGRI BOSSI 130": "NOVA 130T", "NEGRI BOSSI 150 A(Β)": "NB 150", "NEGRI BOSSI 160": "VE 160", "NEGRI BOSSI 180T": "NOVA 180T",
    "NEGRI BOSSI 210": "VE 210", "NEGRI BOSSI V 300": "VE 300", "NEGRI BOSSI 320": "VE 320", "NEGRI BOSSI VESTA 330 A": "VESTA 330",
    "NEGRI BOSSI CANBIO 330": "CANBIO S330T", "NEGRI BOSSI NOVAe 350T": "NOVA 350T", "MIR 400": "MIR 400",
    "NEGRI BOSSI  450": "NOVA 450T", "NEGRI BOSSI CANBIO 500": "CANBIO S500T", "NEGRI BOSSI 550": "VE 550", "EKIN 600": "EKIN 600",
    "NEGRI BOSSI MULTIMAΤ 330": "MULTIMAT", "ΗΑΙΤΙΑΝ ΜΑ 8000 ΙΙΙΙ": "HAITIAN 800", "NEGRI BOSSI V 1000": "V 1000",
    "MIR 140": "MIR 140", "NEGRI BOSSI VESTA 330 B": "VESTA 330 B",
}
PEOPLE = {
    "Edyta G.": "EDYTA MAGDALENA GOUTZERIS", "Ήρα": "IRA VLAEVA", "Αζνταρίδης Γ.": "ΙΩΑΝΝΗΣ ΑΖΝΤΑΡΙΔΗΣ",
    "Σιαντίδης Βλ.": "ΜΑΡΙΟΣ-ΒΛΑΣΙΟΣ ΣΙΑΝΤΙΔΗΣ", "Σακιζλή Κ.": "ΑΙΚΑΤΕΡΙΝΗ ΣΑΚΙΖΛΗ", "Καδόπουλος Β.": "ΕΥΑΓΓΕΛΟΣ ΚΑΔΟΠΟΥΛΟΣ",
    "Κουτουκίδης Τ.": "ΑΝΑΣΤΑΣΙΟΣ ΚΟΥΤΟΥΚΙΔΗΣ", "Γεννάδιος": "ΓΕΝΝΑΔΙΟΣ ΚΑΡΑΓΚΙΟΖΙΔΗΣ", "Αλτάι": "ΑΛΤΑΪ ΙΜΠΡΑΧΗΜ",
    "Μαρία": "ΜΑΡΙΑ ΚΑΝΙΔΟΥ", "Χρύσα": "ΧΡΥΣΗ ΛΑΜΠΙΔΟΥ", "Σιδεράς Σωτ.": "Σιδηράς Σωτ.",
}
SHIFT_COLUMNS = (
    ("ΠΡΟΪΟΝΤΑ ΠΡΩΙ", "ΠΡΩΙΝΗ ΒΑΡΔΙΑ", "2ο ΑΤΟΜΟ ΠΡΩΙΝΗ ΒΑΡΔΙΑ"),
    ("ΠΡΟΪΟΝΤΑ ΑΠΟΓΕΥΜΑ", "ΑΠΟΓΕΥΜΑΤΙΝΗ ΒΑΡΔΙΑ", "2ο ΑΤΟΜΟ ΑΠΟΓΕΥΜΑΤΙΝΗ ΒΑΡΔΙΑ"),
    ("ΠΡΟΪΟΝΤΑ ΒΡΑΔΥ", "ΝΥΧΤΕΡΙΝΗ ΒΑΡΔΙΑ", "2ο ΑΤΟΜΟ ΝΥΧΤΕΡΙΝΗ ΒΑΡΔΙΑ"),
)
SHIFT_HOURS = ((6, 14), (14, 22), (22, 30))
LIST_SHEETS = ("ΕΡΓΑΤΟΤΕΧΝΙΤΕΣ", "ΧΡΩΜΑΤΑ", "ΥΛΙΚΑ")
CAUSE_WORDS = (
    ("Power or utilities", r"ρευμα|ηλεκτρ|νερο δεν|αερα"),
    ("Robot fault", r"ρομποτ"),
    ("Mold fault", r"καλουπ|εξολκ|εκτοξ|πιανε κομματ|κολλαγ|κολλου"),
    ("Material problem", r"υλικ|πρωτη υλη|χρωμα|τροφοδοτ|στεγνωτ"),
    ("No operator", r"ατομ|προσωπικ|εργατ|χωρις χειρισ"),
    ("Quality hold", r"ποιοτ|σκαρτ|ελεγχ"),
    ("Process setting", r"ρυθμισ|παραμετρ|θερμοκρασ"),
    ("Machine breakdown", r"βλαβ|χαλασ|αντλι|λαδι|υδραυλ|μοτερ|σπασ|διαρρο"),
)
START_WORDS = r"αρχη|ξεκιν|αρχισ|μπηκε"
END_WORDS = r"τελος|τελειωσ|μεχρι|εως"
STOP_WORDS = r"σταματ|βλαβ|χαλασ|διακοπ|επεσε|κολλησ"
SPELLING = {"ΟΡΘ": "ΟΡΘΟΓΩΝΙΟ", "ΟΡΘΟΓ": "ΟΡΘΟΓΩΝΙΟ", "ΤΕΤΡ": "ΤΕΤΡΑΓΩΝΟ", "ΑΠΟΘ": "ΑΠΟΘΗΚΕΥΣΗΣ", "ΧΕΙΟΥ": "ΧΕΙΟ",
            "ΠΕΝΤΑΛ": "ΠΕΤΑΛ", "ΜΙΚΡΟΚΥΜΜΑΤΩΝ": "ΜΙΚΡΟΚΥΜΑΤΩΝ", "ΑΙΩΡ": "ΑΙΩΡΟΥΜΕΝΟΥ", "NO": "ΝΟ"}


def fold(text):
    text = unicodedata.normalize("NFD", str(text or "").lower())
    return "".join(ch for ch in text if unicodedata.category(ch) != "Mn")


def canon(name):
    """A product name with spelling differences removed: accents, case, "ΓΙΑ", Latin "No", abbreviations."""
    text = fold(name).upper()
    text = re.sub(r"([A-ZΑ-Ω])(\d)", r"\1 \2", text)
    words = [SPELLING.get(word, word) for word in re.split(r"[^A-ZΑ-Ω0-9]+", text) if word and word != "ΓΙΑ"]
    return " ".join(words)


def _num(value):
    if value is None or value == "" or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    match = re.search(r"-?\d+(?:[.,]\d+)?", str(value))
    return float(match.group().replace(",", ".")) if match else None


class Checks:
    """What the log gets wrong or cannot hold, counted with a few examples each."""

    def __init__(self):
        self.found = collections.OrderedDict()

    def add(self, key, label, detail, example=None, count=1):
        entry = self.found.setdefault(key, {"label": label, "detail": detail, "count": 0, "examples": []})
        entry["count"] += count
        if example and len(entry["examples"]) < 3:
            entry["examples"].append(example)

    def rows(self):
        return list(self.found.values())


def read(path=LOG):
    """The log rows, with the dates put in the log's year, and the checks found on the way."""
    import openpyxl

    workbook = openpyxl.load_workbook(path, data_only=True)
    checks = Checks()
    rows, empty = [], []
    for ws in workbook.worksheets:
        if ws.title.startswith("ΣΥΝΟΛΟ") or ws.title in LIST_SHEETS:
            continue
        head = [str(value or "").strip() for value in next(ws.iter_rows(values_only=True))]
        column = {}
        for index, name in enumerate(head):
            column.setdefault(name, index)

        def cell(values, name):
            index = column.get(name)
            return values[index] if index is not None and index < len(values) else None

        units = [index for index, name in enumerate(head) if name == "ΜΟΝΑΔΑ ΜΕΤΡΗΣΗΣ"]
        found = 0
        for line, values in enumerate(ws.iter_rows(min_row=2, values_only=True), start=2):
            product = str(cell(values, "ΟΝΟΜΑΣΙΑ ΠΡΟΪΟΝΤΟΣ") or "").strip()
            day = cell(values, "ΗΜΕΡΟΜΗΝΙΑ")
            if not product or not isinstance(day, datetime.datetime):
                continue
            found += 1
            where = "%s, row %d" % (ws.title.strip(), line)
            day = day.date()
            if day.year != YEAR:
                checks.add("year", "Dates typed with the wrong year", "Read as %d." % YEAR, "%s: %s" % (where, day.isoformat()))
                day = day.replace(year=YEAR)
            for name in ("ΚΥΚΛΟΣ ΜΗΧΑΝΗΣ/SEC", "ΚΥΚΛΟΣ ΜΗΧΑΝΗΣ/HOUR"):
                if isinstance(cell(values, name), str):
                    checks.add("text", "Cycle times and speeds typed as text",
                               "Excel cannot calculate with them; read as numbers.", "%s: %s" % (where, cell(values, name)))
            shifts = []
            for out_name, crew_name, second_name in SHIFT_COLUMNS:
                out = _num(cell(values, out_name))
                if out is not None and out < 0:
                    checks.add("negative", "Shifts with negative output",
                               "The counter reading is lower than the one before; that shift is left out.", "%s: %d" % (where, out))
                    out = None
                shifts.append({"out": out, "crew": [str(cell(values, crew_name) or "").strip(), str(cell(values, second_name) or "").strip()]})
            made = _num(cell(values, "ΠΑΡΑΓΩΓΗ ΗΜΕΡΑΣ"))
            if made is not None and made < 0:
                checks.add("negativeday", "Days with a negative day total", "A counter typed wrong; the shift figures are used.",
                           "%s: %d" % (where, made))
            rate = _num(cell(values, "ΚΥΚΛΟΣ ΜΗΧΑΝΗΣ/HOUR"))
            for entry in shifts:
                if rate and entry["out"] and entry["out"] > rate * 8 * 1.5:
                    checks.add("impossible", "Shifts with more pieces than the machine can make",
                               "Over 1.5 times an 8-hour shift at the machine's rated speed, usually a counter reading typed as output; left out.",
                               "%s: %d pieces at %d an hour" % (where, entry["out"], rate))
                    entry["out"] = None
            outs = [entry["out"] for entry in shifts if entry["out"] is not None]
            if made is not None and outs and abs(sum(outs) - made) > 0.5:
                checks.add("sum", "Days whose shifts do not add up to the day total",
                           "The shift figures are used.", "%s: %d against %d" % (where, sum(outs), made))
            scrap = _num(cell(values, "ΣΚΑΡΤΑ"))
            if scrap is None and made:
                checks.add("scrap", "Days with the scrap left blank", "Read as no scrap, so the scrap rate is likely understated.")
            containers = sorted({str(values[index]).strip() for index in units if index < len(values) and values[index]} - {"kg", "κιλά"})
            if containers:
                checks.add("units", "Material and colour counted in containers, not kg",
                           "Sacks, boxes, buckets and shakers cannot be turned into kg, so material use is not imported.",
                           "%s: %s" % (where, ", ".join(containers)))
            note = str(cell(values, "ΕΠΕΞΗΓΗΣΗ") or "").strip()
            if re.search(r"\d{1,2}[:.]\d{2}", note):
                checks.add("notes", "Downtime written only as a note",
                           "Turned into stoppages with an auto-classified cause.", "%s: %s" % (where, note))
            rows.append({
                "sheet": ws.title.strip(), "line": line, "day": day, "product": product, "made": made, "scrap": scrap,
                "cycle": _num(cell(values, "ΚΥΚΛΟΣ ΜΗΧΑΝΗΣ/SEC")), "rate": _num(cell(values, "ΚΥΚΛΟΣ ΜΗΧΑΝΗΣ/HOUR")),
                "shifts": shifts, "note": note,
            })
        if not found:
            empty.append(ws.title.strip())
    for name in empty:
        checks.add("empty", "Machine sheets with no rows", "Formatted but never filled in.", name)
    _summary_checks(workbook, checks)
    listed = {str(values[0]).strip() for values in workbook["ΕΡΓΑΤΟΤΕΧΝΙΤΕΣ"].iter_rows(values_only=True) if values[0]}
    unlisted = collections.Counter(name for row in rows for shift in row["shifts"] for name in shift["crew"] if name and name != "-" and name not in listed)
    for name, times in unlisted.most_common():
        checks.add("unlisted", "Operator names typed outside the workers list", "Matched by hand in the mapping file.",
                   "%s (%d shifts)" % (name, times))
    return rows, checks


def _summary_checks(workbook, checks):
    for ws in workbook.worksheets:
        if not ws.title.startswith("ΣΥΝΟΛΟ"):
            continue
        for values in ws.iter_rows(values_only=True):
            for value in values:
                if isinstance(value, str) and value.strip().startswith("#"):
                    checks.add("errors", "Formula errors in the monthly summaries", "Such as #DIV/0!, from totals retyped by hand.",
                               "%s: %s" % (ws.title, value.strip()))
                elif isinstance(value, str) and re.match(r"^\d{2}/\d{2}/\d{4}\s*-\s*\d{2}/\d{2}/\d{4}$", value.strip()):
                    checks.add("ranges", "Date ranges typed as text in the monthly summaries", "They cannot be sorted or filtered as dates.",
                               "%s: %s" % (ws.title, value.strip()))


# Matching ---------------------------------------------------------------------------------

def _person_key(name):
    return [word for word in re.split(r"[^A-ZΑ-Ω]+", fold(name).upper()) if word]


def _match_person(name, people):
    words = _person_key(name)
    if not words:
        return ""
    if len(words) == 1:
        found = [person for person in people if _person_key(person)[:1] == words]
    else:
        surname, initial = words[0], words[1]
        found = [person for person in people
                 if _person_key(person)[-1] == surname and any(word.startswith(initial) for word in _person_key(person)[:-1])]
    return found[0] if len(found) == 1 else ""


def draft_map(plant, rows):
    """The mapping file's content: machines, operators and products, matched where the names agree."""
    people = [person["name"] for person in plant["personnel"]]
    names = collections.Counter(name for row in rows for shift in row["shifts"] for name in shift["crew"] if name and name != "-")
    operators = {}
    for name, _ in names.most_common():
        target = PEOPLE.get(name) or _match_person(name, people)
        operators[name] = {"to": target, "how": "suggested" if name in PEOPLE else ("same person" if target else "new")}
    items = [item for item in plant["items"] if item["type"] in ("SFG", "FG")]
    by_canon = {}
    for item in items:
        by_canon.setdefault(canon(item["name"]), []).append(item["name"])
    keys = list(by_canon)
    products = {}
    for name, days in collections.Counter(row["product"] for row in rows).most_common():
        same = by_canon.get(canon(name)) or []
        if len(same) == 1:
            how = "same name" if same[0] == name else "spelling"
            products[name] = {"to": same[0], "how": how, "days": days}
            continue
        close = difflib.get_close_matches(canon(name), keys, n=1, cutoff=0.8)
        products[name] = {"to": "", "how": "new", "days": days, "closest": by_canon[close[0]][0] if close else ""}
    return {"machines": dict(MACHINES), "operators": operators, "products": products}


def load_map(plant, rows, path=MAP_FILE):
    mapping = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    fresh = draft_map(plant, rows)
    for part in ("machines", "operators", "products"):
        known = mapping.setdefault(part, {})
        for key, value in fresh[part].items():
            known.setdefault(key, value)
    path.write_text(json.dumps(mapping, ensure_ascii=False, indent=1), encoding="utf-8")
    return mapping


# Building ---------------------------------------------------------------------------------

def _code(prefix, number, width):
    return "%s-%s" % (prefix, str(number).zfill(width))


def _next_code(rows, prefix, width):
    numbers = [int(row["id"][len(prefix) + 1:]) for row in rows if str(row.get("id", "")).startswith(prefix + "-") and row["id"][len(prefix) + 1:].isdigit()]
    return _code(prefix, max(numbers or [0]) + 1, width)


def _utc(day, hours, minutes=0):
    from zoneinfo import ZoneInfo

    local = datetime.datetime.combine(day, datetime.time()) + datetime.timedelta(hours=hours, minutes=minutes)
    return local.replace(tzinfo=ZoneInfo("Europe/Athens")).astimezone(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _note_events(note):
    """The times in a note with what happened at each: start, end, stop or restart, in order."""
    events, text, stopped = [], fold(note), False
    last = 0
    for match in re.finditer(r"(\d{1,2})[:.](\d{2})", text):
        hour, minute = int(match.group(1)), int(match.group(2))
        if hour > 23 or minute > 59:
            continue
        before = text[last:match.start()]
        last = match.end()
        clock = hour + minute / 60.0
        if re.search(STOP_WORDS, before):
            events.append(("stop", clock))
            stopped = True
        elif re.search(START_WORDS, before):
            events.append(("restart" if stopped else "start", clock))
            stopped = False
        elif re.search(END_WORDS, before):
            events.append(("end", clock))
    return events


def _cause(note, causes):
    text = fold(note)
    for name, pattern in CAUSE_WORDS:
        if re.search(pattern, text):
            return causes.get(name, "")
    return ""


def _shift_of(clock):
    """The shift (0, 1, 2) and the hour on the production day's clock (night hours run 22 to 30)."""
    if clock < 6:
        clock += 24
    for index, (start, end) in enumerate(SHIFT_HOURS):
        if start <= clock < end:
            return index, clock
    return 2, clock


def add_to_plant(plant, rows, mapping):
    """Add the log to ``plant`` (the workbook import) as orders, runs and stoppages. Returns counts."""
    counted = collections.OrderedDict()
    machine_by_name = {machine["name"]: machine for machine in plant["machines"]}
    press_type = next((entry["id"] for entry in plant["machine_types"] if entry["name"] == "Injection press"), "")
    used_sheets = {row["sheet"] for row in rows}
    machine_of = {}
    for sheet, name in mapping["machines"].items():
        if sheet not in used_sheets or not name:
            continue
        if name not in machine_by_name:
            entry = {"id": _next_code(plant["machines"], "MCH", 2), "name": name, "alias": "", "typeId": press_type, "attachedToId": "",
                     "floor": None, "serial": "", "euromap": "", "year": "", "changeoverMin": None, "location": "", "status": "active",
                     "notes": FROM_LOG}
            plant["machines"].append(entry)
            machine_by_name[name] = entry
        machine_of[sheet] = machine_by_name[name]["id"]

    person_by_name = {person["name"]: person["id"] for person in plant["personnel"]}
    operator_role = next((entry["id"] for entry in plant["person_roles"] if entry["name"] == "Operator"), "")

    def person(name):
        name = (name or "").strip()
        if not name or name == "-":
            return ""
        target = (mapping["operators"].get(name) or {}).get("to") or name
        target = (mapping["operators"].get(target) or {}).get("to") or target
        if target not in person_by_name:
            entry = {"id": _next_code(plant["personnel"], "PER", 3), "name": target, "roleId": operator_role, "status": "active",
                     "machineIds": []}
            plant["personnel"].append(entry)
            person_by_name[target] = entry["id"]
        return person_by_name[target]

    category = {(entry["type"], entry["name"]): entry["id"] for entry in plant["item_categories"]}
    pcs = next((entry["id"] for entry in plant["units"] if entry["name"] == "pcs"), "")
    item_by_name = {}
    for item in plant["items"]:
        item_by_name.setdefault(item["name"], item)

    def item_for(product, machine_id):
        target = (mapping["products"].get(product) or {}).get("to") or product
        item = item_by_name.get(target)
        if item is None:
            lid = re.match(r"^ΚΑΠΑΚΙ", target, re.IGNORECASE)
            item = {"id": _next_code(plant["items"], "ITM", 5), "name": target, "type": "SFG",
                    "categoryId": category.get(("SFG", "Lid" if lid else "Part"), ""), "uomId": pcs, "erpCode": "",
                    "approvedMachineIds": [], "supplier": "", "properties": {}, "status": "active", "notes": FROM_LOG}
            plant["items"].append(item)
            item_by_name[target] = item
            counted["new items"] = counted.get("new items", 0) + 1
        if machine_id not in item["approvedMachineIds"]:
            item["approvedMachineIds"].append(machine_id)
        return item

    recipes_by_pair = collections.defaultdict(list)
    for recipe in plant["recipes"]:
        recipes_by_pair[(recipe["itemId"], recipe["machineId"])].append(recipe)
    cycles = collections.defaultdict(list)
    for row in rows:
        if row["cycle"]:
            cycles[(row["product"], row["sheet"])].append(row["cycle"])

    def recipe_for(item, machine_id, product, sheet):
        found = recipes_by_pair.get((item["id"], machine_id))
        if found:
            return sorted(found, key=lambda recipe: (not recipe.get("standard"), recipe.get("status") != "approved"))[0]
        seen = cycles.get((product, sheet))
        recipe = {"id": _next_code(plant["recipes"], "REC", 4), "itemId": item["id"], "moldId": "", "machineId": machine_id,
                  "status": "approved", "standard": False, "cycle": round(statistics.median(seen), 2) if seen else None,
                  "cooling": "", "screwRpm": "", "temps": {}, "settings": [], "px": "", "py": "", "printPieces": "", "printTotal": "",
                  "settingsNote": "", "comment": FROM_LOG + " The mold was not recorded.", "inputs": []}
        plant["recipes"].append(recipe)
        recipes_by_pair[(item["id"], machine_id)].append(recipe)
        counted["new recipes"] = counted.get("new recipes", 0) + 1
        return recipe

    causes = {entry["name"]: entry["id"] for entry in plant["stoppage_causes"]}
    shift_ids = [entry["id"] for entry in plant["shifts"]]
    orders, runs, stoppages = [], [], []
    by_sheet = collections.defaultdict(list)
    for row in rows:
        if row["sheet"] in machine_of:
            by_sheet[row["sheet"]].append(row)

    for sheet, sheet_rows in sorted(by_sheet.items()):
        machine_id = machine_of[sheet]
        order = None
        for row in sorted(sheet_rows, key=lambda entry: (entry["day"], entry["line"])):
            item = item_for(row["product"], machine_id)
            recipe = recipe_for(item, machine_id, row["product"], sheet)
            changed = order is None or order["itemId"] != item["id"]
            changeover = changed and order is not None
            if changed:
                order = {"id": _next_code(orders, "PO", 5), "itemId": item["id"], "quantity": 0, "dueDate": "", "status": "done",
                         "erpOrderNo": "", "first": row["day"], "notes": ""}
                orders.append(order)
            order["dueDate"] = row["day"].isoformat()
            order["notes"] = "Rebuilt from the 2025 production log: %s, %s to %s." % (sheet, order["first"].isoformat(), row["day"].isoformat())

            shifts = row["shifts"]
            outs = [entry["out"] for entry in shifts]
            if all(out is None for out in outs) and row["made"]:
                staffed = [index for index, entry in enumerate(shifts) if entry["crew"][0]] or [0]
                outs = [row["made"] if index == staffed[0] else None for index in range(3)]
            windows = [[float(start), float(end)] for start, end in SHIFT_HOURS]
            events = _note_events(row["note"])
            for kind, clock in events:
                index, at = _shift_of(clock)
                if kind == "start":
                    windows[index][0] = at
                elif kind == "end":
                    windows[index][1] = at
            cavities = None
            if row["rate"] and row["cycle"]:
                cavities = max(1, round(row["rate"] * row["cycle"] / 3600.0))
            day_runs = {}
            for index, entry in enumerate(shifts):
                out = outs[index]
                if out is None or (out == 0 and not entry["crew"][0]):
                    continue
                start, end = windows[index]
                if end <= start:
                    start, end = SHIFT_HOURS[index]
                second = entry["crew"][1]
                run = {"id": "", "orderId": order["id"], "recipeId": recipe["id"], "shiftId": shift_ids[index],
                       "operatorId": person(entry["crew"][0]), "startedAt": _utc(row["day"], int(start), round((start % 1) * 60)),
                       "endedAt": _utc(row["day"], int(end), round((end % 1) * 60)), "good": out, "cavities": cavities,
                       "cycle": row["cycle"], "status": "done", "notes": ("Second person: %s." % second) if second and second != "-" else "",
                       "scrap": [], "inputs": [], "day": row["day"]}
                if second and second != "-":
                    person(second)
                day_runs[index] = run
                runs.append(run)
            if day_runs and row["scrap"]:
                last = day_runs[max(day_runs)]
                last["scrap"] = [{"reasonId": "", "quantity": row["scrap"]}]
                last["good"] = max(0, (last["good"] or 0) - row["scrap"])
            order["quantity"] += sum(run["good"] or 0 for run in day_runs.values())

            for position, (kind, clock) in enumerate(events):
                if kind != "stop":
                    continue
                index, at = _shift_of(clock)
                restart = next((later for later_kind, later in events[position + 1:] if later_kind in ("restart", "start")), None)
                until = _shift_of(restart)[1] if restart is not None else windows[index][1]
                if until <= at:
                    until = SHIFT_HOURS[index][1]
                run = day_runs.get(index)
                stoppages.append({
                    "machineId": machine_id, "runId": "", "run": run, "startedAt": _utc(row["day"], int(at), round((at % 1) * 60)),
                    "endedAt": _utc(row["day"], int(until), round((until % 1) * 60)), "causeId": _cause(row["note"], causes),
                    "description": "%s: «%s»%s" % (NOTE_MARK, row["note"], "" if restart is not None else " The restart time was not written; set to the end of the shift."),
                    "fix": "", "reportedById": person(shifts[index]["crew"][0]),
                })
            if changeover and events and events[0][0] == "start":
                index, at = _shift_of(events[0][1])
                begin = SHIFT_HOURS[index][0]
                if at > begin:
                    stoppages.append({
                        "machineId": machine_id, "runId": "", "run": day_runs.get(index), "startedAt": _utc(row["day"], begin),
                        "endedAt": _utc(row["day"], int(at), round((at % 1) * 60)), "causeId": causes.get("Mold change", ""),
                        "description": "%s: «%s» The product changed, so the time before the start is counted as a mold change." % (NOTE_MARK, row["note"]),
                        "fix": "", "reportedById": person(shifts[index]["crew"][0]),
                    })
    for order in orders:
        order.pop("first", None)

    runs.sort(key=lambda run: (run.pop("day"), run["startedAt"], run["orderId"]))
    for number, run in enumerate(runs, start=1):
        run["id"] = _code("RUN", number, 5)
    for stoppage in stoppages:
        run = stoppage.pop("run", None)
        stoppage["runId"] = run["id"] if run else ""
    every = plant["stoppages"] + stoppages
    every.sort(key=lambda entry: entry.get("startedAt") or "9999")
    for number, entry in enumerate(every, start=1):
        entry["id"] = _code("STP", number, 5)
    plant["stoppages"] = every
    plant["production_orders"] = orders
    plant["production_runs"] = runs
    counted.update({"orders": len(orders), "runs": len(runs), "stoppages from notes": len(stoppages),
                    "auto-classified causes": sum(1 for entry in stoppages if entry["causeId"]),
                    "machines": len(machine_of)})
    return counted
