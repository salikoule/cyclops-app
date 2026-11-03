from ._anvil_designer import ColorFormTemplate
from anvil import *
from cyclops_app.Pages import mount_detail


class ColorForm(ColorFormTemplate):
    def __init__(self, routing_context=None, **properties):
        self.init_components(**properties)
        mount_detail(self, "color", routing_context)
