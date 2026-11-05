import anvil.tables as tables
import anvil.tables.query as q
from anvil.tables import app_tables
"""Path helpers for the Cyclops routes."""

SLUG = {
    "overview": "overview",
    "structure": "structure",
    "product": "products",
    "mold": "molds",
    "press": "presses",
    "recipe": "recipes",
    "material": "materials",
    "color": "colors",
    "issue": "stoppages",
    "run": "production",
}
KIND = {slug: kind for kind, slug in SLUG.items()}
LABEL = {
    "overview": "Overview",
    "structure": "Structure",
    "product": "Product",
    "mold": "Mold",
    "press": "Press",
    "recipe": "Recipe",
    "material": "Raw material",
    "color": "Color",
    "issue": "Stoppage",
    "run": "Production run",
}
COUNT_KEY = {
    "product": "products",
    "mold": "molds",
    "press": "presses",
    "recipe": "recipes",
    "material": "materials",
    "color": "colors",
    "issue": "stoppages",
    "run": "runs",
}


def path(kind, code=None):
    slug = SLUG.get(kind) or "overview"
    if code:
        return "/%s/%s" % (slug, code)
    return "/%s" % slug


def kind_for(slug):
    return KIND.get(slug)


def params(ctx):
    if ctx is None:
        return {}
    raw = getattr(ctx, "params", None) or {}
    try:
        return dict(raw)
    except Exception:
        return {}


def query(ctx):
    if ctx is None:
        return {}
    raw = getattr(ctx, "query", None) or {}
    try:
        return dict(raw)
    except Exception:
        return {}


def go(kind, code=None, query=None):
    from craftify_library.CraftifyRouting import navigate

    slug = SLUG.get(kind) or "overview"
    if code:
        navigate(path="/%s/:code" % slug, params={"code": code}, query=query or {})
    else:
        navigate(path="/%s" % slug, query=query or {})


def open_path(url):
    parts = [part for part in (url or "").split("?")[0].split("/") if part]
    if not parts:
        go("overview")
        return
    kind = KIND.get(parts[0])
    if not kind:
        go("overview")
        return
    code = parts[1] if len(parts) > 1 else None
    go(kind, code)
