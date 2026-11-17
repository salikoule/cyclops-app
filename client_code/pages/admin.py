"""Configure, users, audit history, and notifications."""

from .common import SETTING_SECTIONS
from cyclops_app.session import Data
from cyclops_app.ui import Editor
from cyclops_app.ui import Format
from cyclops_app.ui import Layout
from cyclops_app.ui import Nav
from cyclops_app.ui import Tables
from cyclops_app.ui.query import call as _call


class Admin:
    def _configure_page(self):
        section = next((entry for entry in SETTING_SECTIONS if entry[2] == self.code), None)
        if section is None:
            Nav.go("configure", SETTING_SECTIONS[0][2])
            return
        data = _call("cyclops_detail", "settings", "")
        if not data:
            self.show(Layout.empty_state("The lists could not be loaded."))
            return
        self.data = data
        kind, key, slug, title, subtitle = section
        tabs = "".join('<a class="cy-tab%s" href="javascript:void(0)" data-nav="%s">%s <span>%s</span></a>' % (
            " is-active" if entry[2] == slug else "", Layout.esc(Nav.path("configure", entry[2])), Layout.esc(entry[3]), len(data.get(entry[1]) or []))
            for entry in SETTING_SECTIONS)
        rows = [self._setting_row(kind, entry) for entry in data.get(key) or []]
        card = Layout.section(title, subtitle, padded=False, actions=(Layout.button("Add", lambda **e: self._edit_setting(kind, "")),))
        Layout.body(card, Tables.mount(rows, kind, Tables.columns_for(kind), height="640px" if len(rows) > 12 else None,
                                       on_edit=lambda row: self._edit_setting(kind, row.get("id")), edit_on_click=True))
        self.show(
            Layout.page_header("Configure", description="The lists the records choose from. Retire a value instead of deleting it, so older records keep it."),
            self.block('<nav class="cy-tabs">%s</nav>' % tabs),
            card,
        )

    def _setting_row(self, kind, entry):
        retired = entry.get("status") == "retired"
        row = dict(entry, status="Retired" if retired else "Active", tone="muted" if retired else "ok")
        if kind == "cause":
            row["planned"] = "Yes" if entry.get("planned") else "No"
            row["changeover"] = "Yes" if entry.get("changeover") else "No"
        if kind == "role":
            row["runsMachines"] = "Yes" if entry.get("runsMachines") else "No"
        if kind == "category":
            row["roleLabel"] = entry.get("roleLabel") or "—"
        if kind == "person":
            row["roleLabel"] = entry.get("roleLabel") or "Not set"
            row["machines"] = ", ".join(entry.get("machines") or [])
        return row

    def _edit_setting(self, kind, code):
        key = next(section[1] for section in SETTING_SECTIONS if section[0] == kind)
        entry = next((entry for entry in (self.data or {}).get(key) or [] if entry.get("id") == code), {})
        Editor.open_editor(self, "save-setting", {"settingKind": kind, "row": entry})

    def _variants(self, data):
        rows = data.get("variants") or []
        card = self._table_section("Variants", "Items whose shared product is this one. Each keeps its own SKU.", rows, "item", empty="No variants. Set this item as the shared product on another item.")
        return card

    def _record_history(self):
        rows = _call("cyclops_history", self.kind, self.code) or []
        return self._audit_table("Audit log", "Who changed what on this record, with before and after values.", rows)

    def _audit_table(self, title, subtitle, rows):
        card = Layout.section(title, subtitle)
        if not rows:
            Layout.body(card, Layout.note("No changes recorded yet."))
            return card
        bits = [
            '<thead><tr><th>When</th><th>Who</th><th>Where</th><th>Change</th><th>Before</th><th>After</th></tr></thead><tbody>',
        ]
        for row in rows:
            lines = row.get("lines") or []
            if not lines:
                lines = [{"label": row.get("summary") or row.get("action"), "before": "—", "after": "—"}]
            for index, line in enumerate(lines):
                head = ""
                if index == 0:
                    head = '<td rowspan="%s">%s</td><td rowspan="%s">%s</td><td rowspan="%s">%s</td>' % (
                        len(lines), Layout.esc(Format.when(row.get("at"))),
                        len(lines), Layout.esc(row.get("email") or ""),
                        len(lines), Layout.esc(row.get("place") or row.get("record") or ""),
                    )
                bits.append(
                    "<tr>%s<td>%s</td><td>%s</td><td>%s</td></tr>"
                    % (head, Layout.esc(line.get("label") or ""), Layout.esc(line.get("before") or "—"), Layout.esc(line.get("after") or "—"))
                )
        bits.append("</tbody>")
        Layout.body(card, self.block('<div class="cy-audit-wrap"><table class="cy-table cy-audit">%s</table></div>' % "".join(bits)))
        return card

    def _users(self):
        data = _call("cyclops_users")
        if not data:
            self.show(Layout.empty_state("Users could not be loaded."))
            return
        self.data = data
        rows = []
        for user in data.get("users") or []:
            rows.append({
                "email": user.get("email"),
                "role": user.get("roleLabel") or user.get("role"),
                "status": "Active" if user.get("active") else "Deactivated",
                "tone": "ok" if user.get("active") else "muted",
                "screens": "All screens" if user.get("role") == "administrator" else (", ".join(user.get("screens") or []) or "Notifications and account"),
                "lastLogin": Format.when(user.get("lastLogin"), ""),
                "id": user.get("email"),
            })
        card = Layout.section("Users", "Activate an account, set its role, and choose the screens it sees. Administrator, User, and Observer are the three roles the app branches on.", padded=False)
        Layout.body(card, Tables.mount(rows, "user", [
            Tables._col("Email", "email", min_width=220, formatter=Tables._text),
            Tables._col("Role", "role", width=140, formatter=Tables._text),
            Tables._status_col(120),
            Tables._col("Screens", "screens", min_width=220, formatter=Tables._clip),
            Tables._col("Last sign-in", "lastLogin", width=160, formatter=Tables._text),
        ], height="640px" if len(rows) > 12 else None, on_edit=self._edit_user, edit_on_click=True))
        self.show(Layout.page_header("Users", description="The first signed-in account is an administrator. One active administrator always remains."), card)

    def _edit_user(self, row):
        user = next((entry for entry in (self.data or {}).get("users") or [] if entry.get("email") == row.get("email")), None)
        if user is not None:
            Editor.open_editor(self, "save-access", {"row": user})

    def _history_page(self):
        rows = _call("cyclops_history") or []
        self.show(Layout.page_header("Audit log", description="Who changed what, where, and when. Before and after values are stored for every save."),
                  self._audit_table("Latest changes", "Recipes, orders, runs, master data, and user access.", rows))

    def _notifications(self):
        rows = _call("cyclops_notifications") or []
        bits = []
        for row in rows:
            bits.append(
                '<div class="cy-row%s"><div class="cy-when">%s</div><div class="cy-grow"><b>%s</b><div class="cy-sub">%s</div></div></div>'
                % ("" if row.get("read") else " cy-unread", Layout.esc(Format.when(row.get("at"))), Layout.esc(row.get("title")), Layout.esc(row.get("body")))
            )
        card = Layout.section("Notifications", "Maintenance and breakdowns you asked to hear about.",
                              actions=(Layout.button("Mark all read", self._mark_read),))
        body = '<div class="cy-list">%s</div>' % "".join(bits) if bits else '<p class="cy-muted">Nothing yet. Turn alerts on from the account menu (Plant alerts).</p>'
        Layout.body(card, self.block(body))
        self.show(Layout.page_header("Notifications"), card)

    def _mark_read(self, **event_args):
        _call("cyclops_mark_notifications")
        Data.invalidate_session()
        self.render()
