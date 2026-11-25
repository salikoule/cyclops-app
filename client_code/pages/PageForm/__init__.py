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
        self._route = routing_context.route
        self._ctx = routing_context
        self.first_load = True
        self.set_event_handler("show", self.form_show)

    def form_show(self, **event_args):
        if not self.first_load:
            return
        self.first_load = False
        route = self._route
        mode = getattr(route, "mode", "")
        if mode == "list":
            mount_list(self, route.kind, self._ctx)
        elif mode == "detail":
            mount_detail(self, route.kind, self._ctx)
        else:
            _PAGE[route.page](self, self._ctx)
