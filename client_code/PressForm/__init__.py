from ._anvil_designer import PressFormTemplate
from anvil import *
from cyclops_app.Pages import mount_detail


class PressForm(PressFormTemplate):
    def __init__(self, routing_context=None, **properties):
        self.init_components(**properties)
        mount_detail(self, "press", routing_context)
