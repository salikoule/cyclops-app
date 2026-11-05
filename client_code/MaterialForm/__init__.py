from ._anvil_designer import MaterialFormTemplate
from anvil import *
from cyclops_app.Pages import mount_detail


class MaterialForm(MaterialFormTemplate):
    def __init__(self, routing_context=None, **properties):
        self.init_components(**properties)
        mount_detail(self, "material", routing_context)
