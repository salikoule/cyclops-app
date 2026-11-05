"""Reads the plant tables for one request, in the shape the domain module works on.

A request names what it shows: a product, a press, a list. The loader reads those rows and what
decides their status, closed over the links: a product brings its molds, a mold its recipes, a
recipe its material and color lines and its logs. Presses, materials, and colors are short
reference lists and are always read whole. Nothing is cached between requests; the tables are
the record.
"""

import anvil.tables.query as q
from anvil.tables import app_tables

import domain
import records

CHILDREN = ("materials", "colors", "issues", "runs")
_OWNER = q.fetch_only("code", mold=q.fetch_only("code", product=q.fetch_only("code")))


def _table(name):
    return getattr(app_tables, name)


def _by_id(rows):
    return {row.get_id(): row for row in rows}


def _id(linked):
    return linked.get_id() if linked is not None else None


def owners(recipe_rows):
    """(product, mold, recipe) codes that bring these recipes in: the product when the mold has
    one, else the mold, else the recipe itself. Read the rows with ``_OWNER``."""
    products, molds, recipes = set(), set(), set()
    for row in recipe_rows:
        mold = row["mold"]
        if mold is None:
            recipes.add(row["code"])
        elif mold["product"] is None:
            molds.add(mold["code"])
        else:
            products.add(mold["product"]["code"])
    return products, molds, recipes


def recipes_on_press(press_row):
    return app_tables.recipes.search(_OWNER, press=press_row)


def recipes_using(table, column, row):
    """Recipes with a material or color line for ``row``."""
    return [line["recipe"] for line in _table(table).search(q.fetch_only(recipe=_OWNER), **{column: row}) if line["recipe"] is not None]


class Plant:
    def __init__(self, whole=False, children=CHILDREN, workers=False, codes=()):
        self.whole = whole
        self.children = tuple(children)
        self.press_rows = list(app_tables.presses.search(q.fetch_only(*records.PRESS_COLUMNS, mounted_product=q.fetch_only("code", "name"))))
        self.material_rows = list(app_tables.materials.search())
        self.color_rows = list(app_tables.colors.search())
        self.products, self.molds, self.recipes = {}, {}, {}
        self._closed = set()
        if whole:
            self.products = _by_id(self._products())
            self.molds = _by_id(app_tables.molds.search())
            self.recipes = _by_id(app_tables.recipes.search())
        self.workers = workers or any(kind in self.children for kind in ("issues", "runs"))
        self.codes = {kind: [row["code"] for row in _table(kind).search(q.fetch_only("code"))] for kind in codes}
        self.spans = None
        self.worker_rows = []
        self.line_rows = {}
        self._read_lines = set()

    def rows(self):
        """((table, code), row) for every record row read, workers by name."""
        for table, rows in (("presses", self.press_rows), ("materials", self.material_rows), ("colors", self.color_rows),
                            ("products", self.products.values()), ("molds", self.molds.values()), ("recipes", self.recipes.values())):
            for row in rows:
                yield (table, row["code"]), row
        for row in self.worker_rows:
            yield ("workers", row["name"]), row

    def lines(self, recipe_row, table):
        """The ``table`` rows read for this recipe, or None when that table was not read."""
        if recipe_row.get_id() not in self.recipes or table not in self._read_lines:
            return None
        return self.line_rows.get((recipe_row.get_id(), table), [])

    def press(self, code):
        return next((row for row in self.press_rows if row["code"] == code), None)

    def material(self, code):
        return next((row for row in self.material_rows if row["code"] == code), None)

    def color(self, code):
        return next((row for row in self.color_rows if row["code"] == code), None)

    def _products(self, **filters):
        return app_tables.products.search(q.fetch_only(*records.PRODUCT_COLUMNS, lid=q.fetch_only("code")), **filters)

    def add(self, products=(), molds=(), recipes=()):
        """Codes to show; each comes with the molds and recipes its status depends on."""
        if self.whole:
            return self
        known = {row["code"] for row in self.products.values()}
        wanted = [code for code in set(products) if code and code not in known]
        if wanted:
            self.products.update(_by_id(self._products(code=q.any_of(*wanted))))
        self._close()
        known = {row["code"] for row in self.molds.values()}
        wanted = [code for code in set(molds) if code and code not in known]
        if wanted:
            self.molds.update(_by_id(app_tables.molds.search(code=q.any_of(*wanted))))
        self._close()
        known = {row["code"] for row in self.recipes.values()}
        wanted = [code for code in set(recipes) if code and code not in known]
        if wanted:
            self.recipes.update(_by_id(app_tables.recipes.search(code=q.any_of(*wanted))))
        return self

    def add_recipes(self, recipe_rows):
        """Recipes read with ``_OWNER``, brought in through their product or mold."""
        products, molds, recipes = owners(recipe_rows)
        return self.add(products, molds, recipes)

    def _close(self):
        while True:
            products = [row for key, row in self.products.items() if key not in self._closed]
            if products:
                self._closed.update(row.get_id() for row in products)
                self.molds.update(_by_id(app_tables.molds.search(product=q.any_of(*products))))
                continue
            molds = [row for key, row in self.molds.items() if key not in self._closed]
            if not molds:
                return
            self._closed.update(row.get_id() for row in molds)
            self.recipes.update(_by_id(app_tables.recipes.search(mold=q.any_of(*molds))))

    def add_spans(self, press_codes):
        """Every stop on these presses, so a run's downtime counts stops logged on any recipe there."""
        presses = [row for row in self.press_rows if row["code"] in press_codes]
        on_press = list(app_tables.recipes.search(q.fetch_only("press"), press=q.any_of(*presses))) if presses else []
        press_of = {row.get_id(): _id(row["press"]) for row in on_press}
        press_code = {row.get_id(): row["code"] for row in self.press_rows}
        stops = app_tables.stoppages.search(q.fetch_only("start_date", "start_time", "end_date", "end_time", "recipe"),
                                            recipe=q.any_of(*on_press)) if on_press else []
        self.spans = domain.stop_spans(
            (press_code.get(press_of.get(_id(row["recipe"]))), records.stop_times(row)) for row in stops)
        return self

    def _lines(self, table):
        self._read_lines.add(table)
        if self.whole:
            found = _table(table).search()
        else:
            rows = list(self.recipes.values())
            found = _table(table).search(recipe=q.any_of(*rows)) if rows else []
        for row in found:
            self.line_rows.setdefault((_id(row["recipe"]), table), []).append(row)
            yield row

    def graph(self):
        press_code = {row.get_id(): row["code"] for row in self.press_rows}
        material_code = {row.get_id(): row["code"] for row in self.material_rows}
        color_code = {row.get_id(): row["code"] for row in self.color_rows}
        product_code = {key: row["code"] for key, row in self.products.items()}
        mold_code = {key: row["code"] for key, row in self.molds.items()}
        self.worker_rows = list(app_tables.workers.search()) if self.workers else []
        worker_name = {row.get_id(): row["name"] for row in self.worker_rows}

        def code(linked, known):
            if linked is None:
                return None
            return known.get(linked.get_id()) or linked["code"]

        products = [records.product_item(row, [press_code[linked.get_id()] for linked in row["approved_presses"] or []
                                               if linked.get_id() in press_code], code(row["lid"], product_code))
                    for row in self.products.values()]
        presses = []
        for row in self.press_rows:
            mounted = row["mounted_product"]
            names = {mounted["code"]: mounted["name"] or ""} if mounted is not None else {}
            presses.append(records.press_item(row, mounted["code"] if mounted is not None else None, names))
        molds = [records.mold_item(row, product_code.get(_id(row["product"]))) for row in self.molds.values()]
        mold_product = {item["id"]: item["productId"] for item in molds}

        recipes, by_row = [], {}
        for key, row in self.recipes.items():
            mold = mold_code.get(_id(row["mold"]))
            item = records.recipe_item(row, mold, mold_product.get(mold), press_code.get(_id(row["press"])))
            recipes.append(item)
            by_row[key] = item

        lines = {"materialSlots": [], "colorSlots": [], "issues": [], "runs": []}
        if "materials" in self.children:
            for row in self._lines("recipe_materials"):
                lines["materialSlots"].append((by_row.get(_id(row["recipe"])), row["slot"], records.material_slot_item(row, material_code.get(_id(row["material"])))))
        if "colors" in self.children:
            for row in self._lines("recipe_colors"):
                lines["colorSlots"].append((by_row.get(_id(row["recipe"])), row["slot"], records.color_slot_item(row, color_code.get(_id(row["color"])))))
        if "issues" in self.children:
            for row in self._lines("stoppages"):
                lines["issues"].append((by_row.get(_id(row["recipe"])), row["position"], records.stoppage_item(row, worker_name.get(_id(row["worker"])))))
        if "runs" in self.children:
            for row in self._lines("production_runs"):
                lines["runs"].append((by_row.get(_id(row["recipe"])), row["position"], records.run_item(row, worker_name.get(_id(row["operator"])))))
        for key, entries in lines.items():
            for item, order, value in sorted((entry for entry in entries if entry[0] is not None), key=lambda entry: entry[1] or 0):
                item[key].append(value)

        plant = {
            "products": products,
            "molds": molds,
            "presses": presses,
            "materials": [records.material_item(row) for row in self.material_rows],
            "colors": [records.color_item(row) for row in self.color_rows],
            "recipes": recipes,
            "workers": sorted(name for name in worker_name.values() if name),
        }
        for kind in ("products", "molds", "presses", "materials", "colors", "recipes"):
            plant[kind].sort(key=lambda item: item["id"])
        domain.normalize(plant)
        if self.codes:
            plant["codes"] = self.codes
        if self.spans is not None:
            plant["spans"] = self.spans
        domain.reindex(plant)
        return plant
