from ._anvil_designer import AccountFormTemplate
from anvil import *
from cyclops_app.Pages import mount_account


class AccountForm(AccountFormTemplate):
    def __init__(self, routing_context=None, **properties):
        self.init_components(**properties)
        mount_account(self, routing_context)
