"""Page building blocks on the Craftify standard page."""

from anvil import *


def esc(value):
    text = "" if value is None else str(value)
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def attr(node, name):
    try:
        value = node.getAttribute(name)
    except Exception:
        return ""
    return value or ""


def closest(node, selector):
    try:
        return node.closest(selector)
    except Exception:
        return None


def flat(component):
    try:
        component.spacing_above = "none"
        component.spacing_below = "none"
    except Exception:
        pass
    return component


def stack(*children):
    page = flat(HtmlTemplate(html="@theme:bc-stack.html"))
    for child in children:
        add(page, child)
    return page


def grid(columns="repeat(auto-fit, minmax(180px, 1fr))", *children):
    panel = flat(HtmlTemplate(html="@theme:bc-grid.html"))
    panel.dom_nodes["grid"].style.gridTemplateColumns = columns
    for child in children:
        add(panel, child)
    return panel


def add(container, child):
    if child is None:
        return None
    container.add_component(flat(child), slot="default")
    return child


def page_header(title, eyebrow="", description="", actions=()):
    head = flat(HtmlTemplate(html="@theme:page-header.html"))
    head.dom_nodes["eyebrow"].textContent = eyebrow or ""
    head.dom_nodes["title"].textContent = title or ""
    head.dom_nodes["description"].textContent = description or ""
    if not actions:
        head.dom_nodes["actions"].classList.add("is-empty")
    for action in actions:
        head.add_component(flat(action), slot="actions")
    return head


def section(title, subtitle="", padded=True, actions=(), lead=False):
    """A card. ``lead`` makes it the page itself (title, description, page actions) when it is the page's only card."""
    card = flat(HtmlTemplate(html="@theme:table-section.html"))
    card.dom_nodes["title"].textContent = title or ""
    card.dom_nodes["subtitle"].textContent = subtitle or ""
    if padded:
        card.dom_nodes["body"].classList.add("is-padded")
    if lead:
        card.dom_nodes["card"].classList.add("is-lead")
    for action in actions:
        card.add_component(flat(action), slot="actions")
    return card


def body(card, *children):
    for child in children:
        card.add_component(flat(child), slot="body")
    return card


def footer(card, *children):
    for child in children:
        card.add_component(flat(child), slot="foot")
    return card


def field(label, component, hint=""):
    box = flat(HtmlTemplate(html="@theme:bc-field.html"))
    box.dom_nodes["label"].textContent = label or ""
    box.dom_nodes["hint"].textContent = hint or ""
    box.add_component(flat(component), slot="input")
    return box


def html(markup):
    return flat(HtmlTemplate(html=markup))


def interactive(markup, handler):
    view = flat(HtmlTemplate(html='<div class="cy-block" anvil-name="root">%s</div>' % markup))

    def on_click(event):
        target = getattr(event, "target", None)
        if target is None:
            return
        action_el = closest(target, "[data-action]")
        nav_el = None if action_el else closest(target, "[data-nav]")
        chosen = action_el or nav_el
        if chosen is None:
            return
        try:
            event.preventDefault()
        except Exception:
            pass
        handler("action" if action_el else "nav", chosen)

    try:
        view.dom_nodes["root"].addEventListener("click", on_click)
    except Exception:
        pass
    return view


def note(text, tone="muted"):
    return html('<p class="bc-note bc-note-%s">%s</p>' % (tone, esc(text)))


def button(text, handler=None, primary=False, danger=False, icon=""):
    role = None
    if primary:
        role = "primary-color"
    elif danger:
        role = "cy-danger"
    btn = Button(text=text, icon=icon, role=role)
    flat(btn)
    btn.align = "left"
    if handler is not None:
        btn.set_event_handler("click", handler)
    return btn


def empty_state(message, action_text="", handler=None):
    card = section("Nothing here yet")
    body(card, note(message))
    if action_text and handler is not None:
        body(card, button(action_text, handler, primary=True))
    return card
