"""Production-flow tree. Treant draws it; the cards below still list every setup."""

from anvil import *
import anvil.google.auth, anvil.google.drive
from anvil.google.drive import app_files

from cyclops_app import Format, Layout, Nav

_LABELS = {
    "product": "Product",
    "mold": "Mold",
    "press": "Press",
    "recipe": "Recipe",
    "material": "Raw material",
    "color": "Color",
}


def _node(kind, title, meta, nav=None, extra=""):
    classes = "cy-tn cy-%s" % kind
    if extra:
        classes += " " + extra
    if not nav:
        classes += " cy-static"
    nav_attr = (' data-nav="%s"' % Layout.esc(nav)) if nav else ""
    root_attr = ' data-root="1"' if extra and "root" in extra.split() else ""
    return (
        '<div class="%s"%s%s><div class="k">%s</div><div class="n">%s</div><div class="m">%s</div></div>'
        % (classes, nav_attr, root_attr, Layout.esc(_LABELS.get(kind, kind)), Layout.esc(title or ""), Layout.esc(meta or ""))
    )


def _empty(text):
    return {"innerHTML": '<div class="cy-tn cy-empty cy-static"><div class="n">%s</div></div>' % Layout.esc(text)}


def _feed(recipe):
    nodes = []
    for item in recipe.get("materials") or []:
        account = (" · " + item["account"]) if item.get("account") else " · no code"
        nodes.append({"innerHTML": _node("material", item.get("label"), "%s%s" % (item.get("id") or "", account), Nav.path("material", item.get("id")))})
    for item in recipe.get("colors") or []:
        account = (" · " + item["account"]) if item.get("account") else ""
        nodes.append({"innerHTML": _node("color", item.get("label"), "%s%s" % (item.get("id") or "", account), Nav.path("color", item.get("id")))})
    if not nodes:
        nodes.append(_empty("No material or color written"))
    return nodes


def _recipe_node(recipe, depth):
    bits = [recipe.get("id") or ""]
    if recipe.get("cycle") is None:
        bits.append("no cycle")
    else:
        bits.append("%s s" % Format.trim(recipe.get("cycle")))
    if recipe.get("standard"):
        bits.append("standard")
    if recipe.get("trial"):
        bits.append("trial row")
    return {
        "innerHTML": _node("recipe", recipe.get("label"), " · ".join(bit for bit in bits if bit), Nav.path("recipe", recipe.get("id")), "trial" if recipe.get("trial") else ""),
        "children": _feed(recipe) if depth >= 5 else [],
    }


def _press_meta(group, recipes):
    cycles = [recipe.get("cycle") for recipe in recipes if recipe.get("cycle") is not None]
    rates = [recipe.get("pph") for recipe in recipes if recipe.get("pph")]
    cycle = "no cycle" if not cycles else ("%s s" % Format.trim(min(cycles)))
    rate = (" · %s pcs/h" % max(rates)) if rates else ""
    return "%s · %s · %s%s" % (group.get("pressId") or "", Format.plural(len(recipes), "recipe"), cycle, rate)


def build(flow, depth, include_trial):
    flow = flow or {}
    erp = (" · " + flow["erpCode"]) if flow.get("erpCode") else ""
    root = {
        "innerHTML": _node("product", flow.get("productName"), "%s%s" % (flow.get("productId") or "", erp), None, "root"),
        "children": [],
    }
    mold = flow.get("mold")
    if not mold:
        root["children"].append(_empty("No mold and no recipe recorded"))
        return root
    cavities = ("%s cavities" % mold.get("cavities")) if mold.get("cavities") else "cavities unknown"
    mold_node = {
        "innerHTML": _node("mold", mold.get("name"), "%s · %s" % (mold.get("id") or "", cavities), Nav.path("mold", mold.get("id"))),
        "children": [],
    }
    root["children"].append(mold_node)
    hidden = False
    for group in flow.get("groups") or []:
        recipes = group.get("recipes") or []
        visible = recipes if include_trial else [recipe for recipe in recipes if not recipe.get("trial")]
        if recipes and not visible:
            hidden = True
        if not visible:
            continue
        mold_node["children"].append({
            "innerHTML": _node("press", group.get("pressName"), _press_meta(group, visible), Nav.path("press", group.get("pressId"))),
            "children": [_recipe_node(recipe, depth) for recipe in visible] if depth >= 4 else [],
        })
    if not mold_node["children"]:
        mold_node["children"].append(_empty("Only trial rows exist. Show trial rows to see them." if hidden else "No recipe"))
    return root


class FlowView:
    def __init__(self, flow):
        self.flow = flow or {}
        self.depth = 4 if (self.flow.get("liveCount") or 0) > 6 else 5
        self.fit = "fit"
        self.trial = False
        self._depth_buttons = []
        self._zoom_buttons = []
        self.host = HtmlTemplate(html='<div class="cy-tree-wrap" anvil-name="wrap"><div class="cy-tree" anvil-name="tree"></div></div>')
        self.host.set_event_handler("show", self.draw)
        self._bind_nav()

    def _bind_nav(self):
        def on_click(event):
            target = getattr(event, "target", None)
            node = Layout.closest(target, "[data-nav]") if target is not None else None
            if node is None:
                return
            try:
                event.preventDefault()
            except Exception:
                pass
            Nav.open_path(Layout.attr(node, "data-nav"))

        try:
            self.host.dom_nodes["wrap"].addEventListener("click", on_click)
        except Exception:
            pass

    def component(self):
        tools = FlowPanel(spacing="small", align="left")
        for value, label in ((5, "Full flow"), (4, "Recipes"), (3, "Presses")):
            button = Layout.button(label, lambda value=value, **e: self._set_depth(value), primary=value == self.depth)
            self._depth_buttons.append((value, button))
            tools.add_component(button)
        for value, label in (("fit", "Fit"), ("1", "100%"), ("0.75", "75%"), ("0.5", "50%")):
            button = Layout.button(label, lambda value=value, **e: self._set_fit(value), primary=value == self.fit)
            self._zoom_buttons.append((value, button))
            tools.add_component(button)
        self._trial_button = Layout.button("Show trial rows", self._toggle_trial)
        tools.add_component(self._trial_button)
        tools.add_component(Layout.html(
            '<div class="cy-legend"><span><i class="cy-material"></i>raw material</span>'
            '<span><i class="cy-color"></i>color</span><span><i class="cy-recipe"></i>recipe</span>'
            '<span><i class="cy-press"></i>press</span><span><i class="cy-mold"></i>mold</span>'
            '<span><i class="cy-product"></i>product</span></div>'
        ))
        return Layout.stack(
            tools,
            Layout.flat(self.host),
            Layout.note("Read left to right: material and color feed a recipe, the recipe runs on a press with the mold, and the product comes out. Dashed recipes are trial rows."),
        )

    def _mark(self, pairs, current):
        for value, button in pairs:
            button.role = "primary-color" if value == current else None

    def _set_depth(self, value):
        self.depth = value
        self._mark(self._depth_buttons, value)
        self.draw()

    def _set_fit(self, value):
        self.fit = value
        self._mark(self._zoom_buttons, value)
        self.draw()

    def _toggle_trial(self, **event_args):
        self.trial = not self.trial
        self._trial_button.role = "primary-color" if self.trial else None
        self.draw()

    def draw(self, **event_args):
        try:
            node = self.host.dom_nodes["tree"]
        except Exception:
            return
        structure = build(self.flow, self.depth, self.trial)
        try:
            from anvil.js.window import cyclopsMountTree
            cyclopsMountTree(node, structure, "EAST", self.fit)
        except Exception:
            node.innerHTML = '<p class="bc-note">The flow chart could not be drawn. The color cards below list the same setups.</p>'
