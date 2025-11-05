from textual import events
from textual.widgets import Input, ListView, ListItem, Label, Static
from rich.text import Text
from rich.style import Style

PREVIEW_TITLE = "[bold]Preview:[/bold]"
PREVIEW_PLACEHOLDER = f"{PREVIEW_TITLE}\n  (waiting for input)"


def format_preview_text(content: str | None) -> str:
    if not content:
        return PREVIEW_PLACEHOLDER
    lines = [PREVIEW_TITLE]
    for line in content.splitlines():
        lines.append(f"  {line}")
    return "\n".join(lines)


class TabInput(Input):
    def __init__(self):
        super().__init__()
        self.id = "input_content"
        self.prev_input = ""
        self.sugg_matches = []
        self.match_index = 0

    async def on_input_changed(self, event: Input.Changed) -> None:
        suggestions = self.app.query_one("#suggestions", SuggestionsView)
        trailing_space = self.value.endswith(" ")
        matches = []

        arg_suggestions = getattr(
            self.app.commands,
            "find_argument_suggestions",
            None,
        )

        if callable(arg_suggestions):
            matches = arg_suggestions(self.value, trailing_space)

        if not matches:
            matches = self.app.commands.find_suggestions(self.value)

        cur_input = self.value.strip()
        if cur_input == '.':
            suggestions.hide()
            self.sugg_matches = []
            self.value = ""
            self.cursor_position = 0
            return

        if not cur_input:
            self.value = ""
            self.cursor_position = 0

        if matches != self.sugg_matches:
            self.sugg_matches = matches
            self.match_index = 0
            self.prev_input = cur_input

        if self.sugg_matches:
            suggestions.show(self.sugg_matches)
        else:
            suggestions.hide()

        preview = ""
        if hasattr(self.app, "commands"):
            preview = getattr(self.app.commands, "preview_full_command", lambda *_: "")(
                self.value
            )

        try:
            preview_widget = self.app.query_one("#command_preview", Static)
        except Exception:
            preview_widget = None
        if preview_widget is not None:
            preview_widget.update(format_preview_text(preview))

        event.prevent_default()
        event.stop()

    async def on_key(self, event: events.Key) -> None:
        suggest = self.app.query_one("#suggestions", SuggestionsView)

        if suggest.popup_visible and event.key in ("up", "down"):
            if event.key == "down":
                suggest.action_cursor_down()
            else:
                suggest.action_cursor_up()
            event.prevent_default()
            event.stop()

        if event.key == "tab":
            if suggest.popup_visible and self.sugg_matches:
                index = suggest.index if suggest.index is not None else 0
                suggestion = self.sugg_matches[index][0]
                self.value = suggestion + " "
                self.cursor_position = len(self.value)
                self.post_message(Input.Changed(self, self.value))
            elif not self.value or not self.value.strip():
                self.value = " "
                self.cursor_position = len(self.value)
                self.post_message(Input.Changed(self, self.value))

            self.app.set_focus(self)
            event.prevent_default()
            event.stop()


class SuggestionsView(ListView):
    def __init__(self):
        super().__init__()
        self.id = "suggestions"
        self.classes = "hidden"
        self.popup_visible = False
        self.border_title = "Suggestions"

    def show(self, matches):
        self.clear()

        self.index = 0

        self.border_subtitle = ""
        self.border_title = "Suggestions"

        if not matches:
            self.hide()
            return

        for cmd, desc in matches:
            text = Text()
            last_token = cmd.split()[-1] if cmd else ""
            text.append("• ", style=Style(color="cyan", bold=True))
            text.append(last_token, style=Style(color="white", bold=True))
            if desc:
                text.append("\n  ", style=Style(color="grey70"))
                text.append(desc, style=Style(color="green"))
            self.append(ListItem(Label(text, expand=True)))

        self.styles.height = max(3, 2 + (len(matches) * 2))
        self.styles.border = ("round", "cyan")
        self.styles.background = "black"
        self.styles.padding = (0, 1)
        self.styles.color = "white"

        self.add_class("show")
        self.remove_class("hidden")
        self.popup_visible = True
        self.refresh(layout=True)

    def hide(self):
        self.add_class("hidden")
        self.remove_class("show")
        self.popup_visible = False
        self.border_title = ""
        self.border_subtitle = ""
        self.refresh(layout=True)
