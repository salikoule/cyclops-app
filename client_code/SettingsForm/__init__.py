from ._anvil_designer import SettingsFormTemplate
from anvil import *
from cyclops_app.Pages import mount_settings


class SettingsForm(SettingsFormTemplate):
    def __init__(self, routing_context=None, **properties):
        self.init_components(**properties)
        mount_settings(self, routing_context)
