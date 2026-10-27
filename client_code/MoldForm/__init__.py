from ._anvil_designer import MoldFormTemplate
from anvil import *
from cyclops_app.Pages import mount_detail


class MoldForm(MoldFormTemplate):
    def __init__(self, routing_context=None, **properties):
        self.init_components(**properties)
        mount_detail(self, "mold", routing_context)
