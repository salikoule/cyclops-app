from ._anvil_designer import MaterialsFormTemplate
from anvil import *
from cyclops_app.Pages import mount_list


class MaterialsForm(MaterialsFormTemplate):
    def __init__(self, routing_context=None, **properties):
        self.init_components(**properties)
        mount_list(self, "material", routing_context)
