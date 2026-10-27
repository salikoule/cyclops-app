from ._anvil_designer import ProductsFormTemplate
from anvil import *
import anvil.google.auth, anvil.google.drive
from anvil.google.drive import app_files
from cyclops_app.Pages import mount_list


class ProductsForm(ProductsFormTemplate):
    def __init__(self, routing_context=None, **properties):
        self.init_components(**properties)
        mount_list(self, "product", routing_context)
