import argparse

from textual import events
from textual.app import App, ComposeResult
from textual.containers import Vertical
from textual.widgets import Input, ListView, ListItem, Static
from rich.text import Text

from commands import CommandCatalog  # uses the logic we already built


class DemoInput(Input):
    def __init__(self, catalog: CommandCatalog) -> None:
        super().__init__()
        self.catalog = catalog
        self.matches: list[tuple[str, str]] = []

    async def on_input_changed(self, event: Input.Changed) -> None:
        text = self.value
        trailing_space = text.endswith(" ")

        # first try option completions, otherwise fall back to subcommands
        self.matches = (
            self.catalog.find_options(text) or self.catalog.find_suggestions(text)
        )

        list_view = self.app.query_one(ListView)
        list_view.clear()
        for cmd, desc in self.matches[:8]:
            entry = self.catalog.find_command_entry(cmd)
            if entry:
                renderable = entry.rich_usage()
            else:
                renderable = Text.from_markup(cmd)
                if desc:
                    renderable.append("\n")
                    renderable.append(desc, style="dim")
            list_view.append(ListItem(Static(renderable)))

        event.stop()  # keep Textual from handling the event further

    async def on_key(self, event: events.Key) -> None:
        if event.key == "tab" and self.matches:
            suggestion_value = self.matches[0][0]
            self.value = suggestion_value + " "
            self.cursor_position = len(self.value)
            self.post_message(Input.Changed(self, self.value))
            self.app.set_focus(self)
            event.stop()


class DemoApp(App):
    BINDINGS = [("ctrl+c", "quit", "Quit")]

    def __init__(self) -> None:
        super().__init__()
        self.catalog = CommandCatalog()
        self.catalog.register_dynamic_templates(
            "devices status inspect",
            [
                argparse.Namespace(
                    device_id="521d2b8e-05e9-4b91-9bf4-75103e2f9b92",
                    detail_level="full",
                    color="purple",
                    shape="triangle",
                    vehicle="plane",
                )
            ],
        )

    def compose(self) -> ComposeResult:
        # Show the user what to try, including a dynamic example
        yield Vertical(
            Static("Try typing: devices status inspect --device-id", id="instructions"),
            Static("Dynamic devices available: 521d2b8e-05e9-4b91-9bf4-75103e2f9b92", id="info"),
            DemoInput(self.catalog),
            ListView(),
        )

    async def on_mount(self) -> None:
        self.query_one(DemoInput).focus()


if __name__ == "__main__":
    DemoApp().run()
