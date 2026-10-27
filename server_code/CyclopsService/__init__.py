"""Server API for the Cyclops plant record."""

import anvil.server
from anvil.tables import app_tables
from craftify_library.CraftifyAuth import craftify_require_user

import domain
import store


def _guard():
    return craftify_require_user()


def _payload(value):
    if not value:
        return {}
    try:
        return dict(value)
    except (TypeError, ValueError):
        return {}


@anvil.server.callable
def cyclops_enable_new_user(email):
    """The local Users service creates accounts disabled. Enable one that has never signed in."""
    email = (email or "").strip()
    if not email or "@" not in email:
        return
    row = app_tables.users.get(email=email)
    if row is None or row["last_login"] is not None:
        return
    row["enabled"] = True
    row["confirmed_email"] = True
    row.update()


@anvil.server.callable
def cyclops_nav():
    _guard()
    plant = store.graph()
    counted = domain.counts(plant)
    return {
        "products": counted["products"],
        "molds": counted["molds"],
        "presses": counted["presses"],
        "recipes": counted["recipes"],
        "materials": counted["materials"],
        "colors": counted["colors"],
    }


@anvil.server.callable
def cyclops_overview(who="all"):
    _guard()
    return domain.overview(store.graph(), who or "all")


@anvil.server.callable
def cyclops_structure():
    _guard()
    return domain.structure(store.graph())


@anvil.server.callable
def cyclops_list(kind, gap=None):
    _guard()
    if gap == "":
        gap = None
    return domain.list_view(store.graph(), kind, gap)


@anvil.server.callable
def cyclops_detail(kind, code):
    _guard()
    return domain.detail(store.graph(), kind, code)


@anvil.server.callable
def cyclops_search(term):
    _guard()
    return domain.search(store.graph(), term or "")


@anvil.server.callable
def cyclops_choices():
    _guard()
    return domain.choices(store.graph())


@anvil.server.callable
def cyclops_apply(action, payload=None):
    _guard()
    return store.apply_action(action, _payload(payload))
