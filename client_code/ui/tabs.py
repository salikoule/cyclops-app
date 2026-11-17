"""The tab bar shared by a record page and the performance page."""

from cyclops_app.ui import Layout


def tab_bar(tabs, active, on_select):
    """``tabs`` are (key, label, count or None). ``on_select(key)`` runs when another tab is chosen."""
    state = {"tab": active}

    def on_tab(mode, node):
        key = Layout.attr(node, "data-item")
        if not key or key == state["tab"]:
            return
        state["tab"] = key
        for link in node.parentElement.querySelectorAll(".cy-tab"):
            link.classList.toggle("is-active", Layout.attr(link, "data-item") == key)
        on_select(key)

    links = []
    for key, label, count in tabs:
        badge = "" if count is None else " <span>%s</span>" % count
        links.append(
            '<a class="cy-tab%s" href="javascript:void(0)" data-action="tab" data-item="%s">%s%s</a>'
            % (" is-active" if key == active else "", key, Layout.esc(label), badge)
        )
    return Layout.interactive('<nav class="cy-tabs">%s</nav>' % "".join(links), on_tab)
