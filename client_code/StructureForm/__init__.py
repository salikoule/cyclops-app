from ._anvil_designer import StructureFormTemplate
from anvil import *
import anvil.google.auth, anvil.google.drive
from anvil.google.drive import app_files
from cyclops_app.Pages import mount_structure


class StructureForm(StructureFormTemplate):
    def __init__(self, routing_context=None, **properties):
        self.init_components(**properties)
        mount_structure(self, routing_context)
