"""A11y-first source routing: the content-bearing test + the AT-SPI reader.

The locked v2 rule (spec #20): a window's a11y tree wins when it exposes >=5
real-text nodes beyond the shell frame/titlebar; otherwise the frame stores NULL
text and the OCR fallback owns it. This module holds the pure test/flatten
logic (unit-tested) and the AT-SPI reader behind it (interface, not tested —
the bus is env/flag-dependent, prototype-verified in #16).
"""

from __future__ import annotations

from typing import Iterable

# Roles that make up the shell frame/titlebar wrapper — never content. The
# window title lives on frame/window/application nodes, so excluding them drops
# the titlebar text that every window (even a blank one) exposes.
SHELL_ROLES = frozenset(
    {"application", "frame", "window", "panel", "filler", "unknown", "desktop"}
)

# Titlebar window controls rendered by client-side-decorated apps (Electron
# titles VS Code's window). Excluded on exact name match only, so a real button
# like "Close side panel" still counts. Both spellings occur in the wild.
TITLEBAR_NAMES = frozenset(
    {"minimize", "minimise", "maximize", "maximise", "restore", "close"}
)

CONTENT_MIN_NODES = 5

# AT-SPI -> hyprctl window-class hints, from prototype #16 (used only to narrow
# the bus search; matching is still on window title overlap).
CLASS_HINTS = {
    "google-chrome": ["google chrome", "chrome"],
    "chromium": ["chromium"],
    "brave-browser": ["brave"],
    "discord": ["discord"],
    "thunar": ["thunar"],
    "vlc": ["vlc"],
    "sidra": ["sidra"],
    "code": ["code", "visual studio code", "electron"],
    "obsidian": ["obsidian", "electron"],
    "kitty": ["kitty"],
}

_MAX_DEPTH = 12
_MAX_CHILDREN = 500
_MAX_NODES = 4000


# ---- pure routing logic (secondary seam) ----

def node_text(node: dict) -> str:
    """The node's display text: explicit text, else its accessible name."""
    text = (node.get("text") or "").strip()
    if text:
        return text
    return (node.get("name") or "").strip()


def is_content_node(node: dict) -> bool:
    """A node counts toward content-bearing when it carries real text beyond
    the shell frame/titlebar."""
    if node.get("role") in SHELL_ROLES:
        return False
    text = node_text(node)
    if not text:
        return False
    if text.lower() in TITLEBAR_NAMES:
        return False
    return True


def iter_nodes(tree: Iterable[dict]) -> Iterable[dict]:
    """Depth-first walk over a normalized tree (each node has `children`)."""
    for node in tree:
        yield node
        yield from iter_nodes(node.get("children") or [])


def content_bearing(tree: Iterable[dict]) -> bool:
    """>=5 real-text nodes beyond the shell frame/titlebar."""
    return sum(1 for n in iter_nodes(tree) if is_content_node(n)) >= CONTENT_MIN_NODES


def flatten_text(tree: Iterable[dict]) -> str:
    """Flatten the winner into a frame: line-joined real text, reading order.

    Shell frames/titlebars and empty nodes are skipped, so a11y_text is the
    page's content rather than the window chrome.
    """
    return "\n".join(node_text(n) for n in iter_nodes(tree) if is_content_node(n))


def prune_tabs(tree: Iterable[dict]) -> list[dict]:
    """Keep only the current page inside tab wrappers (#64).

    Browsers expose the tab row as a PageTabList whose children are the tab
    buttons; the active tab is state-marked `active`. Storing all of them
    pollutes a11y_text/a11y_json with every open tab's title. This prunes
    each tab *list* to its active tab (state `active` or `focused`), or drops
    the list entirely when nothing looks selected. Applied to the walk result
    before any flatten/serialization.
    """
    out: list[dict] = []
    for node in tree:
        role = (node.get("role") or "").lower()
        if role == "page tab list":
            kept = [c for c in (node.get("children") or [])
                    if is_tab_selected(c)]
            if not kept:
                continue
            node["children"] = kept
        children = (node.get("children") or [])
        if children:
            node["children"] = prune_tabs(children)
        out.append(node)
    return out


def is_tab_selected(node: dict) -> bool:
    states = {s.lower() for s in (node.get("states") or [])}
    return bool({"active", "focused"} & states)


# AT-SPI/web roles that hold the actual page content inside a browser
# window: the tab, toolbar, and bookmarks chrome are their *siblings*.
PAGE_DOCUMENT_ROLES = frozenset({"document web", "document frame", "document"})

_DOC_CHROME_NOTE = """\
Browsers expose the whole window in one tree: the browser chrome (toolbar,
omnibox, tab strip, bookmarks bar) hangs off chrome-era nodes while the page
lives in a DOCUMENT node (Chrome: 'document web'; others: 'document'/'document
frame'). Storing the full tree makes a11y_text read like a browser menu, so
only the page-document subtrees are kept; non-browser apps with no DOCUMENT
node pass through untouched.
"""


def page_documents(tree: Iterable[dict]) -> list[dict]:
    """Keep only the outermost page-document subtrees of a window.

    Browsers expose the whole window in one tree: the toolbar, omnibox, tab
    strip and bookmarks bar hang off chrome nodes that are *siblings* of the
    page, which lives in a DOCUMENT node (Chrome: 'document web'; others:
    'document'/'document frame'). Keeping every node makes a11y_text read
    like a browser menu; this reduces the tree to the page. Windows without
    any DOCUMENT node (Thunar, kitty, …) pass through untouched — no-op.
    """
    docs = [n for n in _outermost_documents(tree)]
    return docs or list(tree)


def _outermost_documents(nodes: Iterable[dict]) -> Iterable[dict]:
    for node in nodes:
        if (node.get("role") or "").lower() in PAGE_DOCUMENT_ROLES:
            # Nested documents (iframe / shadow roots) stay inside this
            # subtree, so only the outermost document is yielded.
            yield node
        else:
            yield from _outermost_documents(node.get("children") or [])


# ---- AT-SPI reader (interface, exercised manually) ----

def _atspi():
    """Lazy AT-SPI binding; None when pygobject/atspi is unavailable."""
    try:
        import gi  # type: ignore

        gi.require_version("Atspi", "2.0")
        from gi.repository import Atspi  # type: ignore

        return Atspi
    except Exception:
        return None


def class_hints(window_class: str) -> list[str]:
    """Hint names to narrow the AT-SPI bus search for a window class.

    Exact hint key wins; otherwise a key contained in the class matches too
    (e.g. `md.Obsidian` -> the `obsidian`/`electron` hints, so the reader does
    not scan the whole desktop). Empty list means "scan every app on the bus".
    """
    exact = CLASS_HINTS.get(window_class or "", [])
    if exact:
        return exact
    wc = (window_class or "").lower()
    return next((hints for key, hints in CLASS_HINTS.items() if key in wc), [])


def read_window_tree(window_class: str, window_title: str) -> list[dict] | None:
    """AT-SPI tree for the window matching (class, title), normalized.

    Returns None when the a11y bus is unreachable (gi missing) or no window
    matches — the caller stores NULL text for those frames. The full-tree walk
    is ~50 ms for a content window (measured in #16).
    """
    atspi = _atspi()
    if atspi is None:
        return None
    desktop = atspi.get_desktop(0)
    hints = class_hints(window_class)
    candidates: list[int] = []
    for i in range(desktop.get_child_count()):
        try:
            app = desktop.get_child_at_index(i)
            if app is None:
                continue
            if not hints or any(h in (app.get_name() or "").lower() for h in hints):
                candidates.append(i)
        except Exception:
            continue
    if not candidates:
        return None
    best_tree, best_score = None, 0.0
    for i in candidates:
        try:
            app = desktop.get_child_at_index(i)
            tree = _walk(app, atspi, 0, 0)
        except Exception:
            continue
        if not tree:
            continue
        frames = list(_frame_names(tree))
        if not frames:
            continue
        score = max(_overlap(window_title, name) for name in frames)
        if score > best_score:
            best_score, best_tree = score, tree
    if best_tree is None or best_score < 0.55:
        return None
    # Drop browser chrome (toolbar / omnibox / tab strip / bookmarks) that
    # siblings the page in the same window tree, keeping only the page docs.
    return page_documents(prune_tabs(best_tree))


def _walk(node, atspi, depth: int, count: int) -> list[dict]:
    """Normalize an AT-SPI node subtree into {role, name, text, state, children}."""
    if node is None or depth > _MAX_DEPTH or count > _MAX_NODES:
        return []
    rec = {
        "role": _role_name(node, atspi),
        "name": _node_name(node),
        "text": _atspi_text(node),
        "state": _node_states(node, atspi),
        "children": [],
    }
    n = 0
    try:
        child_count = node.get_child_count()
    except Exception:
        child_count = 0
    for i in range(min(child_count, _MAX_CHILDREN)):
        try:
            child = node.get_child_at_index(i)
        except Exception:
            child = None
        children = _walk(child, atspi, depth + 1, count + n)
        rec["children"] += children
        n += len(children)
    return [rec]


def _role_name(node, atspi) -> str:
    try:
        return atspi.Role.get_name(node.get_role())
    except Exception:
        return "?"


def _node_name(node) -> str:
    try:
        return node.get_name() or ""
    except Exception:
        return ""


def _atspi_text(node) -> str:
    """Raw AT-SPI text accessor — distinct from the pure `node_text` above,
    which reads a normalized {role, name, text} dict."""
    try:
        t = node.query_text()
        return t.get_text(0, -1) or ""
    except Exception:
        return ""


def _node_states(node, atspi) -> list[str]:
    try:
        ss = node.get_state_set()
        want = ("FOCUSED", "SHOWING", "EDITABLE", "SELECTABLE", "SENSITIVE")
        return [s for s in want if ss.contains(getattr(atspi.StateType, s))]
    except Exception:
        return []


def _frame_names(tree: Iterable[dict]) -> Iterable[str]:
    for n in iter_nodes(tree):
        if n.get("role") in ("frame", "window") and n.get("name"):
            yield n["name"]


def _norm(s: str) -> str:
    return "".join(ch.lower() for ch in s if ch.isalnum())


def _overlap(a: str, b: str) -> float:
    """Longest-common-substring overlap, normalized by the shorter string."""
    a, b = _norm(a), _norm(b)
    if not a or not b:
        return 0.0
    if a in b or b in a:
        return min(len(a), len(b)) / max(len(a), len(b), 1)
    short, long_ = (a, b) if len(a) < len(b) else (b, a)
    best = 0
    for i in range(len(short)):
        for j in range(i + best + 1, len(short) + 1):
            if short[i:j] in long_:
                best = j - i
            else:
                break
    return best / len(short)
