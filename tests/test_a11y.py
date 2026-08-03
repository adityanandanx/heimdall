"""Source-routing seam: the content-bearing test and tree flattening.

The test is the locked v2 routing rule (spec #20): a window's a11y tree wins
when >=5 nodes carry real text beyond the shell frame/titlebar; otherwise the
frame stores NULL text and the OCR fallback (ticket #34) owns it. The synthetic
trees below mirror the measured live trees from prototype #16.
"""

from __future__ import annotations

from heimdall.capture.a11y import (
    CONTENT_MIN_NODES,
    TITLEBAR_NAMES,
    content_bearing,
    flatten_text,
    is_content_node,
    node_text,
)

from conftest import content_tree


def node(role: str, name: str = "", text: str = "", children: tuple = ()) -> dict:
    return {"role": role, "name": name, "text": text, "children": list(children)}


# ---- the measured cases (prototype #16) ----

def test_flagged_chromium_tree_is_content_bearing():
    assert content_bearing(content_tree()) is True


def test_unflagged_chromium_shell_only_is_not_content_bearing():
    tree = [node("application", "Google Chrome", children=[
        node("frame", "Heimdall day-browser — prototype v2 - Google Chrome"),
        node("frame", "Heimdall day-browser — prototype v2 - Google Chrome"),
    ])]
    assert content_bearing(tree) is False


def test_code_editor_empty_body_is_not_content_bearing():
    """VS Code with the flag exposes 19 nodes but the editor body is empty
    without SR-mode: the titlebar buttons and panels are all shell chrome."""
    tree = [node("application", "code", children=[
        node("frame", "a11y_bench.py - Visual Studio Code", children=[
            node("panel", children=[
                node("button", "Minimize"),
                node("button", "Maximize"),
                node("button", "Restore"),
                node("button", "Close"),
            ]),
            node("panel", children=[
                node("document web", "a11y_bench.py - Visual Studio Code", children=[
                    node("section", children=[node("embedded")]),
                ]),
            ]),
        ]),
    ])]
    assert content_bearing(tree) is False


def test_obsidian_ribbon_is_content_bearing():
    tree = [node("application", "electron", children=[
        node("frame", "theemailgame.com - trag - Obsidian 1.13.4", children=[
            node("document web", "theemailgame.com - trag - Obsidian 1.13.4", children=[
                node("section", "Open quick switcher"),
                node("section", "Open graph view"),
                node("section", "Create new canvas"),
                node("section", "Open today's daily note"),
                node("section", "Insert template"),
                node("section", "Open command palette"),
            ]),
        ]),
    ])]
    assert content_bearing(tree) is True


def test_thunar_status_and_sidebar_is_content_bearing():
    tree = [node("application", "thunar", children=[
        node("frame", "heimdall - Thunar", children=[
            node("tool bar", children=[
                node("button", "Back"), node("button", "Forward"),
                node("button", "Home"), node("button", "New Tab"),
            ]),
            node("split pane", children=[
                node("table cell", "Home"),
                node("table cell", "Desktop"),
                node("table cell", "Documents"),
                node("table cell", "Downloads"),
                node("table cell", "Pictures"),
            ]),
            node("status bar", "163.2 KiB (1,67,113 bytes) | Free space: 153.4 GiB"),
        ]),
    ])]
    assert content_bearing(tree) is True


def test_kitty_off_bus_is_empty():
    assert content_bearing([]) is False


# ---- threshold boundary ----

def test_threshold_is_five_real_text_nodes():
    base = [node("panel", children=[
        node("static", "", "one"),
        node("static", "", "two"),
        node("static", "", "three"),
        node("static", "", "four"),
        node("static", "", "five"),
    ])]
    assert content_bearing(base) is True
    base[0]["children"].pop()
    assert content_bearing(base) is False
    assert CONTENT_MIN_NODES == 5


def test_empty_name_and_text_do_not_count():
    tree = [node("panel", children=[node("static"), node("static", " "),
                                    node("static", "", "  "), node("panel"),
                                    node("filler", "five")])]
    assert content_bearing(tree) is False


def test_titlebar_buttons_never_count():
    for name in TITLEBAR_NAMES:
        tree = [node("frame", "window", children=[
            node("button", name),
            node("button", "Minimize"),
            node("button", "Maximize"),
            node("button", "Restore"),
            node("button", "Close"),
        ])]
        assert content_bearing(tree) is False, name
    # a real button sharing a titlebar word is still excluded only on exact match
    tree = [node("button", "Close this view")]
    assert is_content_node(tree[0]) is True
    assert content_bearing(tree) is False


def test_shell_roles_do_not_count():
    for role in ("application", "frame", "window", "panel", "filler", "unknown", "desktop"):
        # a lone shell node's title text is never content
        assert content_bearing([node(role, "title text")]) is False, role
        # shell text + only 4 real nodes still fails (titlebar never tips it)
        tree = [node(role, "title text"),
                node("static", "", "a"), node("static", "", "b"),
                node("static", "", "c"), node("static", "", "d")]
        assert content_bearing(tree) is False, role


# ---- flattening / per-node helpers ----

def test_node_text_prefers_text_over_name():
    assert node_text(node("button", "name", "text")) == "text"
    assert node_text(node("button", "name")) == "name"
    assert node_text(node("button", "  ", "  ")) == ""


def test_flatten_text_joins_real_text_in_order():
    tree = [node("application", "Google Chrome", children=[
        node("frame", "page - Google Chrome", children=[
            node("button", "Minimize"),
            node("document web", children=[
                node("heading", "", "Accessibility Test Page"),
                node("paragraph", "", "Hello world, the quick brown fox"),
            ]),
        ]),
    ])]
    assert flatten_text(tree) == (
        "Accessibility Test Page\nHello world, the quick brown fox"
    )


def test_flatten_text_empty_tree():
    assert flatten_text([]) == ""
