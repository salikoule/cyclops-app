from ._anvil_designer import LotFormTemplate
from anvil import *
from cyclops_app.Pages import mount_detail


class LotForm(LotFormTemplate):
    def __init__(self, routing_context=None, **properties):
        self.init_components(**properties)
        mount_detail(self, "lot", routing_context)
