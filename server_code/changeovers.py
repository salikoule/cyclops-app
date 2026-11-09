"""Changeovers: each time a machine went from one item to another, when it happened and the
production time it cost.

A production log rarely writes changeovers down, so they are derived from the runs by rules that
hold for any plant:

- A changeover is a new item on a machine after another one. Two items made side by side in the
  same shifts are one mold making both (a family mold), not a changeover.
- A stoppage logged between the two runs, with a cause flagged as a changeover, gives the times.
- Otherwise the time is the output the shifts around the change did not make: the pieces logged
  against what each recipe usually makes in an hour while running. When the new item's first
  shift ran at its usual speed and the machine stood between the two jobs, the change was done
  while nothing was being produced and cost no output.
- When both items are logged for the whole of one shift, the shift held the first item's pieces,
  then the change, then the second item's pieces.

The runs stay as logged. A changeover's start and end say where the first run really ended and
the next one began, and the Performance view reads them that way. Changeovers entered by hand are
kept when the derivation runs again.
"""

import datetime
import statistics

import domain
import performance
import records

NOISE_H = 0.25
SAMPLES = 5
MIN_RUNNING_H = 2.0


def _hours(begin, end):
    return max(0.0, (end - begin).total_seconds() / 3600.0)


def _clip(begin, end, start, finish):
    return performance._overlap(begin, end, start, finish)


def _pieces(run):
    return (domain.num(run.get("good")) or 0) + sum(domain.num(line.get("quantity")) or 0 for line in run.get("scrap") or [])


def _n(value):
    return "{:,}".format(int(round(value)))


def _h(value):
    return "%s h" % records.number_text(round(value, 1))


class _Machine:
    """One machine's staffed shifts in order, each with its runs and the items they made."""

    def __init__(self):
        self.slots = {}

    def add(self, entry):
        slot = self.slots.setdefault(entry["slot"], {"key": entry["slot"], "start": entry["window"][0], "end": entry["window"][1],
                                                     "shift": entry["shift"], "runs": [], "items": set()})
        slot["runs"].append(entry)
        slot["items"].add(entry["item"])

    def ordered(self):
        found = sorted(self.slots.values(), key=lambda slot: (slot["start"], slot["key"][1]))
        for slot in found:
            slot["runs"].sort(key=lambda entry: (entry["begin"], entry["run"]["id"]))
        return found


class _Derivation:
    def __init__(self, graph):
        self.graph = graph
        self.index = domain.reindex(dict(graph))
        self.zone = performance._zone()
        self.shifts = {entry["id"]: entry for entry in graph.get("shifts") or []}
        flagged = {entry["id"]: entry.get("name") or entry["id"] for entry in graph.get("stoppage_causes") or [] if entry.get("changeover")}
        self.machines = {}
        self.stops_of_run = {}
        self.change_stops = {}
        for stop in graph.get("stoppages") or []:
            begin, finish = records.parse_moment(stop.get("startedAt")), records.parse_moment(stop.get("endedAt"))
            if begin is None or finish is None or finish <= begin:
                continue
            entry = {"stop": stop, "begin": begin, "finish": finish}
            if stop.get("causeId") in flagged:
                entry["cause"] = flagged[stop["causeId"]]
                self.change_stops.setdefault(stop.get("machineId"), []).append(entry)
            elif stop.get("runId"):
                self.stops_of_run.setdefault(stop["runId"], []).append(entry)
        for found in self.change_stops.values():
            found.sort(key=lambda entry: entry["begin"])
        self.used_stops = set()
        for run in graph.get("production_runs") or []:
            entry = self._entry(run)
            if entry is not None:
                self.machines.setdefault(entry["machine"], _Machine()).add(entry)
        self.sequences = {code: machine.ordered() for code, machine in self.machines.items()}
        self.usual = self._usual_speeds()

    def _entry(self, run):
        begin, finish = records.parse_moment(run.get("startedAt")), records.parse_moment(run.get("endedAt"))
        recipe = self.index["recipes"].get(run.get("recipeId")) or {}
        if begin is None or finish is None or finish <= begin or not recipe.get("machineId") or not recipe.get("itemId"):
            return None
        shift = self.shifts.get(run.get("shiftId")) or {}
        day = performance.run_day(begin, shift, self.zone)
        window = performance.slot_window(day, shift, self.zone) or (begin, finish)
        return {"run": run, "recipe": recipe, "begin": begin, "finish": finish, "machine": recipe["machineId"], "item": recipe["itemId"],
                "shift": run.get("shiftId") or "", "slot": (day, run.get("shiftId") or begin.isoformat()), "window": window,
                "pieces": _pieces(run)}

    # Usual speed --------------------------------------------------------------------------

    def _running(self, entry):
        stopped = sum(_clip(entry["begin"], entry["finish"], stop["begin"], stop["finish"]) for stop in self.stops_of_run.get(entry["run"]["id"]) or [])
        return _hours(entry["begin"], entry["finish"]) - stopped

    def _usual_speeds(self):
        """Pieces per running hour of each recipe, and of each item on its machine, from shifts in the middle of a campaign:
        one item alone in the shift, the same item before and after."""
        by_recipe, by_pair = {}, {}
        for slots in self.sequences.values():
            for position in range(1, len(slots) - 1):
                slot = slots[position]
                if len(slot["runs"]) != 1 or not (slots[position - 1]["items"] == slot["items"] == slots[position + 1]["items"]):
                    continue
                entry = slot["runs"][0]
                running = self._running(entry)
                if running < MIN_RUNNING_H or not entry["pieces"]:
                    continue
                speed = entry["pieces"] / running
                by_recipe.setdefault(entry["recipe"]["id"], []).append(speed)
                by_pair.setdefault((entry["item"], entry["machine"]), []).append(speed)
        return {"recipe": by_recipe, "pair": by_pair}

    def speed(self, entry):
        """(pieces per hour, how it is known) for the run's recipe."""
        for found in (self.usual["recipe"].get(entry["recipe"]["id"]), self.usual["pair"].get((entry["item"], entry["machine"]))):
            if found and len(found) >= SAMPLES:
                return statistics.median(found), "its usual %s pcs/h (median of %d shifts)" % (_n(statistics.median(found)), len(found))
        found = self.usual["recipe"].get(entry["recipe"]["id"]) or self.usual["pair"].get((entry["item"], entry["machine"])) or []
        rated = performance._rate(entry["run"])
        if found:
            return statistics.median(found), "%s pcs/h (only %d shift%s to go by)" % (_n(statistics.median(found)), len(found), "" if len(found) == 1 else "s")
        if rated:
            return rated, "its rated %s pcs/h (no usual speed yet)" % _n(rated)
        return None, ""

    # Shortfall ----------------------------------------------------------------------------

    def _available(self, slot):
        seen, stopped = set(), 0.0
        for entry in slot["runs"]:
            for stop in self.stops_of_run.get(entry["run"]["id"]) or []:
                if stop["stop"]["id"] not in seen:
                    seen.add(stop["stop"]["id"])
                    stopped += _clip(slot["start"], slot["end"], stop["begin"], stop["finish"])
        return max(0.0, _hours(slot["start"], slot["end"]) - stopped)

    def _needed(self, entries):
        """Hours the runs' pieces take at their usual speed, whether every speed is well known, and how each was known."""
        hours, sure, notes = 0.0, True, []
        for entry in entries:
            speed, how = self.speed(entry)
            if not speed:
                return None, False, []
            hours += entry["pieces"] / speed
            sure = sure and how.startswith("its usual")
            notes.append((entry, speed, how))
        return hours, sure, notes

    def shortfall(self, slot, entries=None):
        """Hours of the shift's staffed time its runs' pieces do not account for; None when a speed is unknown."""
        needed, sure, notes = self._needed(entries if entries is not None else slot["runs"])
        if needed is None:
            return None, False, []
        lost = max(0.0, self._available(slot) - needed)
        return (lost if lost >= NOISE_H else 0.0), sure, notes

    # Changes ------------------------------------------------------------------------------

    def _logged(self, machine, start, end):
        for stop in self.change_stops.get(machine) or []:
            if stop["stop"]["id"] not in self.used_stops and start <= stop["begin"] < end:
                self.used_stops.add(stop["stop"]["id"])
                return stop
        return None

    def kind(self, before, after):
        mold_before, mold_after = before["recipe"].get("moldId"), after["recipe"].get("moldId")
        if mold_before and mold_after and mold_before != mold_after:
            return "mold"
        if not mold_before or not mold_after:
            return "unknown"
        base_before = set(domain.inputs_with_role(self.index, before["recipe"], "base"))
        base_after = set(domain.inputs_with_role(self.index, after["recipe"], "base"))
        if base_before and base_after and base_before != base_after:
            return "material"
        if set(domain.colorants(self.index, before["recipe"])) != set(domain.colorants(self.index, after["recipe"])):
            return "color"
        return "other"

    def changes(self, keep=()):
        found = []
        for machine, slots in sorted(self.sequences.items()):
            for position in range(1, len(slots)):
                before_slot, slot = slots[position - 1], slots[position]
                new = slot["items"] - before_slot["items"]
                if not new:
                    continue
                stay = slot["items"] & before_slot["items"]
                after_slot = slots[position + 1] if position + 1 < len(slots) else None
                if stay and after_slot is not None and stay & after_slot["items"] and new & after_slot["items"]:
                    continue
                to_item = sorted(new)[0]
                after = next(entry for entry in slot["runs"] if entry["item"] == to_item)
                if stay:
                    from_item = sorted(stay)[0]
                    before = next(entry for entry in slot["runs"] if entry["item"] == from_item)
                else:
                    gone = before_slot["items"] - slot["items"]
                    before = [entry for entry in before_slot["runs"] if entry["item"] in gone][-1]
                if (before["run"]["id"], after["run"]["id"]) in keep:
                    continue
                change = self._inside(slot, before, after, stay, new) if stay else self._between(before_slot, slot, before, after)
                change.update({"machineId": machine, "fromRunId": before["run"]["id"], "toRunId": after["run"]["id"],
                               "fromItemId": before["item"], "toItemId": after["item"], "kind": self.kind(before, after), "notes": ""})
                found.append(change)
        return found

    def _from_stop(self, stop, staffed):
        lost = sum(_clip(stop["begin"], stop["finish"], start, end) for start, end in staffed)
        return {"startedAt": records.moment_text(stop["begin"]), "endedAt": records.moment_text(stop["finish"]), "lostHours": round(lost, 2),
                "source": "stop", "confidence": "high", "stoppageId": stop["stop"]["id"],
                "basis": "Logged as a «%s» stoppage (%s)." % (stop["cause"], stop["stop"]["id"])}

    def _derived(self, start, end, lost, sure, basis):
        return {"startedAt": records.moment_text(start), "endedAt": records.moment_text(end), "lostHours": round(lost, 2), "source": "derived",
                "confidence": "medium" if sure else "low", "stoppageId": "", "basis": basis}

    def _shift_name(self, slot):
        return ((self.shifts.get(slot["shift"]) or {}).get("name") or "").lower()

    def _inside(self, slot, before, after, stay, new):
        stop = self._logged(before["machine"], slot["start"], slot["end"])
        if stop is not None:
            return self._from_stop(stop, [(slot["start"], slot["end"])])
        old = [entry for entry in slot["runs"] if entry["item"] in stay]
        fresh = [entry for entry in slot["runs"] if entry["item"] in new]
        needed_old, sure_old, notes_old = self._needed(old)
        needed_new, sure_new, notes_new = self._needed(fresh)
        shift = self._shift_name(slot)
        if needed_old is None or needed_new is None:
            middle = slot["start"] + (slot["end"] - slot["start"]) / 2
            return self._derived(middle, middle, 0.0, False, "Both items were logged for the whole %s shift, and one has no speed to split it by; "
                                 "the change is put in the middle of the shift." % shift)
        available = self._available(slot)
        lost = max(0.0, available - needed_old - needed_new)
        lost = lost if lost >= NOISE_H else 0.0
        start = min(slot["start"] + datetime.timedelta(hours=needed_old), slot["end"] - datetime.timedelta(hours=lost))
        start = max(start, slot["start"])
        parts = ["%s pcs of the previous item at %s take %s" % (_n(entry["pieces"]), how, _h(entry["pieces"] / speed)) for entry, speed, how in notes_old]
        parts += ["%s pcs of the new item at %s take %s" % (_n(entry["pieces"]), how, _h(entry["pieces"] / speed)) for entry, speed, how in notes_new]
        tail = "That leaves %s of the %s staffed for the change." % (_h(lost), _h(available)) if lost else \
            "That fills the %s staffed, so the change was quick or the speeds are off." % _h(available)
        return self._derived(start, start + datetime.timedelta(hours=lost), lost, sure_old and sure_new,
                             "Both items were logged for the whole %s shift. %s. %s" % (shift, "; ".join(parts), tail))

    def _between(self, before_slot, slot, before, after):
        stop = self._logged(after["machine"], before_slot["start"], slot["end"])
        if stop is not None:
            return self._from_stop(stop, [(before_slot["start"], before_slot["end"]), (slot["start"], slot["end"])])
        joined = abs((slot["start"] - before_slot["end"]).total_seconds()) < 60
        lost_after, sure_after, notes_after = self.shortfall(slot)
        if lost_after is None:
            return self._derived(slot["start"], slot["start"], 0.0, False,
                                 "The new item has no speed to compare its first shift with, so the change time is unknown.")
        lost_before, sure_before = 0.0, True
        if joined and len(before_slot["runs"]) == 1:
            found, sure_before, _ = self.shortfall(before_slot)
            lost_before = found or 0.0
        sure = sure_after and sure_before
        made = "The new item's first %s shift made %s pcs at %s" % (
            self._shift_name(slot), _n(sum(entry["pieces"] for entry, _, _ in notes_after)), "; ".join(how for _, _, how in notes_after))
        if not lost_after and not lost_before:
            if joined:
                return self._derived(slot["start"], slot["start"], 0.0, sure,
                                     "%s, a normal shift, and the previous item's last shift was normal too, so the change was quick or "
                                     "prepared ahead." % made)
            return self._derived(before_slot["end"], slot["start"], 0.0, sure,
                                 "The machine stood between the two jobs. %s, a normal shift, so the change was done while nothing was being "
                                 "produced." % made)
        start = before_slot["end"] - datetime.timedelta(hours=lost_before) if joined else slot["start"]
        end = slot["start"] + datetime.timedelta(hours=lost_after)
        if lost_after:
            basis = "%s: %s of work in %s staffed, so the change took about %s." % (
                made, _h(self._available(slot) - lost_after), _h(self._available(slot)), _h(lost_after))
            if lost_before:
                basis += " The previous item's last shift also made %s less than usual, counted as the start of the change." % _h(lost_before)
        else:
            basis = "%s, a normal shift. The previous item's last shift made %s less than usual, so the change was done then." % (made, _h(lost_before))
        return self._derived(start, end, lost_before + lost_after, sure, basis)


def derive(graph):
    """The changeovers in ``graph``'s runs, the hand-entered ones kept, numbered in time order after the kept ones' codes."""
    kept = [entry for entry in graph.get("changeovers") or [] if entry.get("source") == "entered"]
    keep = {(entry.get("fromRunId"), entry.get("toRunId")) for entry in kept}
    found = _Derivation(graph).changes(keep)
    found.sort(key=lambda entry: (entry["endedAt"], entry["machineId"]))
    taken = [entry["id"] for entry in kept]
    prefix, width = domain.PREFIX["changeovers"]
    for entry in found:
        entry["id"] = domain.next_code(prefix, taken, width)
        taken.append(entry["id"])
    return found


def summary(found):
    """Counts by kind and source, for the import's report and the page that runs the derivation."""
    counted = {"found": len(found), "hours lost": round(sum(entry.get("lostHours") or 0 for entry in found), 1)}
    for key, label in domain.CHANGEOVER_KINDS:
        counted[label] = sum(1 for entry in found if entry.get("kind") == key)
    for key, label in domain.CHANGEOVER_SOURCES:
        counted[label] = sum(1 for entry in found if entry.get("source") == key)
    return counted
