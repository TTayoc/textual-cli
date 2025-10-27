import asyncio
from typing import Optional, Callable

from textual.app import ComposeResult
from textual.containers import Vertical, VerticalScroll
from textual.widget import Widget
from textual.widgets import Input, Static
from textual.message import Message

# External modules you already have
from ui.tab import TabInput, SuggestionsView, PREVIEW_PLACEHOLDER, format_preview_text
from commands import CommandEntry  # assuming these types exist in your project


class Output(Message):
    """Message carrying output text to append to the console view."""

    def __init__(self, data: str, dest: str = "#output_content") -> None:
        self.data = data
        self.dest = dest
        super().__init__()


class CLI(Widget):
    """Console-like widget providing command input + scrollable output."""

    def __init__(self) -> None:
        super().__init__()
        self.id = "console"

    # -----------------------
    # Layout / Mount
    # -----------------------
    def compose(self) -> ComposeResult:
        yield Vertical(
            Static("[bold]CONSOLE INPUT[/bold]", id="console_label"),
            TabInput(),
            SuggestionsView(),
            Static(format_preview_text(None), id="command_preview"),
            Static("[bold]OUTPUT[/bold]", id="output_label"),
            VerticalScroll(Static(id="output_content"), id="output_container"),
        )

    def on_mount(self) -> None:
        input_widget = self.query_one("#input_content", Input)
        input_widget.border_title = "Console"
        self.app.set_focus(input_widget)

        output_container = self.query_one("#output_container", VerticalScroll)
        output_container.border_title = ""
        preview_widget = self.query_one("#command_preview", Static)
        preview_widget.border_title = ""

    # -----------------------
    # Event handlers
    # -----------------------
    async def on_input_submitted(self, event: Input.Submitted) -> None:
        """Handle the user pressing Enter in the input box."""
        user_input = event.value.strip()
        if not user_input:
            return

        # Echo the entered command to the output pane
        resolved_preview = self.app.commands.preview_full_command(user_input)
        preview_text = resolved_preview or user_input
        self._append_output("#output_content", f"> {preview_text}\n")

        # Resolve command + args via your command catalog hanging off the App
        cmd, arg_tokens = self.app.commands.resolve(user_input)

        if isinstance(cmd, CommandEntry):
            # If the command has an argparse parser, parse args safely
            parsed = None
            if hasattr(cmd, "parser") and cmd.parser is not None:
                try:
                    # argparse raises SystemExit on -h/--help or parse errors
                    parsed = cmd.parser.parse_args(arg_tokens)
                except SystemExit:
                    # Show help instead of letting argparse exit the app
                    help_text = cmd.parser.format_help()
                    self._append_output("#output_content", help_text + "\n")
                    await self._post_execute_cleanup()
                    return
            try:
                # Prefer CommandEntry.execute if present, else fall back to run()
                if hasattr(cmd, "execute") and callable(getattr(cmd, "execute")):
                    result = cmd.execute(parsed)
                else:
                    # Back-compat: some run() accept Namespace, some accept none
                    if parsed is not None:
                        try:
                            result = cmd.run(parsed)
                        except TypeError:
                            result = cmd.run()
                    else:
                        result = cmd.run()
                # If the command returns a string, append it
                if isinstance(result, str) and result:
                    self._append_output("#output_content", result + "\n")
            except Exception as exc:  # never crash the UI on command errors
                self._append_output("#output_content", f"[error] {exc}\n")
        else:
            # Unknown/partial command: show suggestions
            suggestions = []
            if hasattr(self.app.commands, "find_suggestions"):
                suggestions = self.app.commands.find_suggestions(user_input) or []

            if suggestions:
                self._append_output("#output_content", "Did you mean:\n")
                # Limit to a handful to avoid flooding the UI
                for full, desc in suggestions[:8]:
                    desc_part = f" — {desc}" if desc else ""
                    self._append_output("#output_content", f"  {full}{desc_part}\n")
            else:
                self._append_output("#output_content", "Unknown command.\n")

        await self._post_execute_cleanup()

    async def _post_execute_cleanup(self) -> None:
        # Clear input and keep focus pinned to input
        input_widget = self.query_one("#input_content", Input)
        input_widget.value = ""
        self.app.set_focus(input_widget)
        await self.safe_scroll_to_bottom()
        self.update_preview(None)

    async def safe_scroll_to_bottom(self) -> None:
        """Scroll the output view to the end after updates."""
        scroll_view = self.query_one("#output_container", VerticalScroll)
        if scroll_view is None:
            return
        result = scroll_view.scroll_end(animate=False)
        if asyncio.iscoroutine(result):
            await result

    # -----------------------
    # Output helpers (thread-safe)
    # -----------------------
    def handle_output(self, dest: str, line: str) -> None:
        """Thread-safe API for background tasks to append to the output pane."""
        self.app.call_from_thread(self._append_output, dest, line)

    def update_preview(self, text: str | None) -> None:
        preview_widget = self.query_one("#command_preview", Static)
        preview_widget.update(format_preview_text(text))

    def _append_output(self, dest: str, line: str) -> None:
        output = self.app.query_one(dest, Static)
        existing = getattr(output, "renderable", None)
        # Normalise to plain string
        if existing is None:
            current = ""
        elif isinstance(existing, str):
            current = existing
        else:
            # Rich Text or other renderable; best-effort plain extraction
            current = getattr(existing, "plain", str(existing))
        output.update(current + line)

    async def on_output(self, message: Output) -> None:
        """Handle Output messages posted from other parts of the app."""
        self._append_output(message.dest, message.data)
        await self.safe_scroll_to_bottom()
