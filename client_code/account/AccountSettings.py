"""Account-menu settings sections (not sidebar pages)."""

import anvil.server
from anvil import *
from cyclops_app.ui import Layout


def plant_alerts_panel():
    try:
        prefs = anvil.server.call("cyclops_notification_prefs") or {}
    except Exception:
        prefs = {}
    maintenance = CheckBox(text="Planned maintenance", checked=bool(prefs.get("maintenance")))
    breakdowns = CheckBox(text="Breakdowns", checked=bool(prefs.get("breakdowns")))

    def save(**event_args):
        try:
            anvil.server.call("cyclops_save_notification_prefs", bool(maintenance.checked), bool(breakdowns.checked))
        except Exception as error:
            Notification(str(error) or "Settings were not saved.", style="danger", timeout=5).show()
            return
        Notification("Plant alert preferences saved.", style="success", timeout=3).show()

    panel = ColumnPanel(spacing_above="none", spacing_below="none")
    panel.add_component(Label(text="In-app notifications when stoppages are logged. Email is sent when the Anvil email service is configured."))
    panel.add_component(maintenance)
    panel.add_component(breakdowns)
    panel.add_component(Layout.button("Save", save, primary=True))
    return panel
