from ._anvil_designer import FloorFormTemplate
from anvil import *
from anvil.js import window
from cyclops_app.pages import mount_floor


class FloorForm(FloorFormTemplate):
    def __init__(self, routing_context=None, **properties):
        self.init_components(**properties)
        self._ctx = routing_context
        self.content = ColumnPanel(spacing_above="none", spacing_below="none")
        self._timer = Timer(interval=20)
        self._timer.set_event_handler("tick", self._tick)
        self.add_component(self.content, full_width_row=True)
        self.add_component(self._timer)
        self._paint()

    def _busy(self):
        from cyclops_app.ui.Editor import _OPEN

        drawer = _OPEN.get("drawer")
        if drawer is not None and getattr(drawer, "is_open", False):
            return True
        try:
            tag = (window.document.activeElement.tagName or "").lower()
        except Exception:
            tag = ""
        return tag in ("input", "textarea", "select")

    def _paint(self):
        mount_floor(self.content, self._ctx)

    def _tick(self, **event_args):
        if self._busy():
            return
        self._paint()

    def form_hide(self, **event_args):
        self._timer.interval = 0
