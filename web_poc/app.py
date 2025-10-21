"""Minimal Textual app demonstrating the BrowserWidget."""

from __future__ import annotations

from textual.app import App, ComposeResult
from textual.containers import Container
from textual.widgets import Footer, Header

from textual_browser import BrowserWidget


PAGES = {
    "Example.org": "https://reddit.com/",
    "Textual Docs": "https://textual.textualize.io/",
    "Python Docs": "https://docs.python.org/3/",
}


class BrowserApp(App):
    """Simple wrapper app to showcase the browser widget."""

    def compose(self) -> ComposeResult:
        yield Header()
        with Container():
            yield BrowserWidget(PAGES.items(), initial_label="Example.org")
        yield Footer()


if __name__ == "__main__":
    BrowserApp().run()
