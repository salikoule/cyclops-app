"""One place for a server call that reports its own failure."""

import anvil.server
from anvil import Notification


def call(name, *args):
    """Run ``name`` and show the error. Returns None when the call fails."""
    try:
        return anvil.server.call(name, *args)
    except Exception as error:
        Notification(str(error), style="danger", timeout=5).show()
        return None
