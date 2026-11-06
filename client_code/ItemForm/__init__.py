from ._anvil_designer import ItemFormTemplate
from anvil import *
from cyclops_app.Pages import mount_detail


class ItemForm(ItemFormTemplate):
    def __init__(self, routing_context=None, **properties):
        self.init_components(**properties)
        mount_detail(self, "item", routing_context)
