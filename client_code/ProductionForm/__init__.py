from ._anvil_designer import ProductionFormTemplate
from anvil import *
from cyclops_app.Pages import mount_list


class ProductionForm(ProductionFormTemplate):
    def __init__(self, routing_context=None, **properties):
        self.init_components(**properties)
        mount_list(self, "run", routing_context)
