"""A Textual widget that embeds w3m via a pseudo-terminal."""

from __future__ import annotations

import asyncio
import shutil
from dataclasses import dataclass
from typing import Iterable

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.message import Message
from textual.widget import Widget
from textual.widgets import Label, ListItem, ListView, Static

from .terminal_widget import TerminalPane, TerminalExited


@dataclass
class Page:
    """Bookmark for a remote page."""

    label: str
    url: str


class PageSelected(Message):
    """Notification that a bookmark was activated."""

    def __init__(self, sender: Widget, page: Page) -> None:
        super().__init__()
        self.set_sender(sender)
        self.page = page


class BrowserWidget(Widget):
    """Bookmark-driven wrapper that embeds w3m inside Textual."""

    DEFAULT_CSS = """
    BrowserWidget {
        layout: vertical;
        height: 1fr;
    }

    #browser-status {
        height: auto;
        padding: 0 1;
        color: $text-muted;
    }

    #browser-content-area {
        layout: horizontal;
        height: 1fr;
    }

    #browser-pages {
        width: 32;
        border: round $surface;
    }

    #browser-pages ListItem.-active {
        background: $boost;
    }
    """

    def __init__(
        self,
        pages: Iterable[tuple[str, str]] | dict[str, str],
        *,
        initial_label: str | None = None,
        w3m_path: str = "w3m",
        w3m_args: list[str] | tuple[str, ...] | None = None,
    ) -> None:
        super().__init__()
        page_iter = pages.items() if isinstance(pages, dict) else pages
        self.pages = [Page(label, url) for label, url in page_iter]
        self.initial_label = initial_label or (self.pages[0].label if self.pages else None)
        self.w3m_path = w3m_path
        self.w3m_args = list(w3m_args or [])
        self._current_page: Page | None = None

        if shutil.which(self.w3m_path) is None:
            raise RuntimeError(f"w3m not found (expected executable '{self.w3m_path}').")

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Static("Select a page to open.", id="browser-status")
            with Horizontal(id="browser-content-area"):
                yield ListView(id="browser-pages")
                yield TerminalPane(id="browser-terminal")

    def on_mount(self) -> None:
        self._populate_pages()
        if self.initial_label:
            self.call_after_refresh(lambda: asyncio.create_task(self._open_by_label(self.initial_label)))

    async def on_list_view_selected(self, event: ListView.Selected) -> None:
        if isinstance(event.item, _PageListItem):
            await self._open_page(event.item.page)
            self.post_message(PageSelected(self, event.item.page))

    def on_terminal_exited(self, message: TerminalExited) -> None:
        if message.returncode is None:
            text = "w3m exited."
        elif message.returncode == 0:
            text = "w3m exited normally."
        else:
            text = f"w3m exited with code {message.returncode}."
        self._update_status(text)

    async def _open_by_label(self, label: str) -> None:
        page = next((p for p in self.pages if p.label == label), None)
        if page:
            await self._open_page(page)

    async def _open_page(self, page: Page) -> None:
        terminal = self.query_one("#browser-terminal", TerminalPane)
        try:
            argv = [self.w3m_path, *self.w3m_args, page.url]
            await terminal.start(argv)
        except Exception as exc:  # pragma: no cover - runtime environment dependent
            self._update_status(str(exc))
            return
        self._current_page = page
        self._highlight_page(page)
        self._update_status(f"Opening {page.url}")
        terminal.focus()

    def _populate_pages(self) -> None:
        pages_list = self.query_one("#browser-pages", ListView)
        pages_list.clear()
        for index, page in enumerate(self.pages, start=1):
            pages_list.append(_PageListItem(page, index))

    def _highlight_page(self, page: Page) -> None:
        pages_list = self.query_one("#browser-pages", ListView)
        for item in pages_list.children:
            if isinstance(item, _PageListItem):
                item.set_highlight(item.page == page)

    def _update_status(self, message: str) -> None:
        self.query_one("#browser-status", Static).update(message)


class _PageListItem(ListItem):
    """Bookmark entry in the list view."""

    def __init__(self, page: Page, index: int) -> None:
        super().__init__(Label(f"[{index}] {page.label}"))
        self.page = page

    def set_highlight(self, active: bool) -> None:
        self.set_class(active, "-active")

