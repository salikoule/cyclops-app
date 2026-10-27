from ._anvil_designer import ProductFormTemplate
from anvil import *
from cyclops_app.Pages import mount_detail


class ProductForm(ProductFormTemplate):
    def __init__(self, routing_context=None, **properties):
        self.init_components(**properties)
        mount_detail(self, "product", routing_context)
