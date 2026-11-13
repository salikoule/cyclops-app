from ._anvil_designer import NotificationsFormTemplate
from anvil import *
from cyclops_app.Pages import mount_notifications


class NotificationsForm(NotificationsFormTemplate):
    def __init__(self, routing_context=None, **properties):
        self.init_components(**properties)
        mount_notifications(self, routing_context)
