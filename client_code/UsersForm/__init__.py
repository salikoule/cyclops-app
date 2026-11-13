from ._anvil_designer import UsersFormTemplate
from anvil import *
from cyclops_app.Pages import mount_users


class UsersForm(UsersFormTemplate):
    def __init__(self, routing_context=None, **properties):
        self.init_components(**properties)
        mount_users(self, routing_context)
