from ._anvil_designer import AccountFormTemplate
from craftify_library.CraftifyRouting import navigate


class AccountForm(AccountFormTemplate):
    def __init__(self, routing_context=None, **properties):
        self.init_components(**properties)

    def form_show(self, **event_args):
        navigate(path="/floor", query={"settings": "account"})
