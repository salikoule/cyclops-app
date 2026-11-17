from ._anvil_designer import PageFormTemplate

from cyclops_app.pages import (
    mount_configure,
    mount_detail,
    mount_history,
    mount_list,
    mount_notifications,
    mount_overview,
    mount_performance,
    mount_structure,
    mount_users,
)

_PAGE = {
    "overview": mount_overview,
    "structure": mount_structure,
    "configure": mount_configure,
    "performance": mount_performance,
    "users": mount_users,
    "history": mount_history,
    "notify": mount_notifications,
}


class PageForm(PageFormTemplate):
    """One form for every record list, record detail, and plain page. The route says which."""

    def __init__(self, routing_context=None, **properties):
        self.init_components(**properties)
        route = routing_context.route
        mode = getattr(route, "mode", "")
        if mode == "list":
            mount_list(self, route.kind, routing_context)
        elif mode == "detail":
            mount_detail(self, route.kind, routing_context)
        else:
            _PAGE[route.page](self, routing_context)
