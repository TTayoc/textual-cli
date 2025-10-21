"""Reusable Textual widget that embeds a PTY-backed terminal."""

from __future__ import annotations

import asyncio
from typing import Iterable, Mapping, Sequence

from rich.style import Style
from rich.text import Text

from textual import events
from textual.message import Message
from textual.widget import Widget

try:
    import pyte
except ImportError as exc:  # pragma: no cover - optional dependency feedback
    raise ImportError(
        "TerminalPane requires the 'pyte' package. Install it with `pip install pyte`."
    ) from exc

from .pty_process import PTYProcess

__all__ = ["TerminalPane", "TerminalExited"]


class _CompatScreen(pyte.Screen):
    """Pyte screen that tolerates newer escape parameters."""

    def set_margins(
        self,
        top: int | None = None,
        bottom: int | None = None,
        **_ignored,
    ) -> None:
        super().set_margins(top, bottom)


class TerminalExited(Message):
    """Notification that the embedded terminal process ended."""

    def __init__(self, sender: Widget, returncode: int | None) -> None:
        super().__init__()
        self.set_sender(sender)
        self.returncode = returncode


class TerminalPane(Widget):
    """General-purpose terminal widget backed by a PTY subprocess."""

    can_focus = True
    DEFAULT_CSS = """
    TerminalPane {
        border: round $secondary;
        height: 1fr;
        width: 1fr;
    }
    """

    def __init__(
        self,
        *,
        default_command: Sequence[str] | None = None,
        default_env: Mapping[str, str] | None = None,
        **widget_kwargs,
    ) -> None:
        super().__init__(**widget_kwargs)
        self.default_command = list(default_command) if default_command else None
        self.default_env = dict(default_env or {})
        self._process: PTYProcess | None = None
        self._screen = _CompatScreen(80, 24)
        self._stream = pyte.Stream(self._screen)
        self._display = Text()
        self._open_lock = asyncio.Lock()

    async def start(
        self,
        argv: Iterable[str] | None = None,
        *,
        env: Mapping[str, str] | None = None,
    ) -> None:
        """Launch a subprocess in the PTY."""
        command = list(argv) if argv is not None else self.default_command
        if not command:
            raise ValueError("No command specified for TerminalPane.start")
        command_env = dict(self.default_env)
        if env:
            command_env.update(env)

        async with self._open_lock:
            await self.stop()
            cols, rows = self._current_dimensions()
            self._screen = _CompatScreen(cols, rows)
            self._stream = pyte.Stream(self._screen)
            self._display = Text()
            process = PTYProcess(command, cols=cols, rows=rows, env=command_env)
            await process.spawn(self._handle_output, self._handle_exit)
            self._process = process
            self.refresh()

    async def stop(self) -> None:
        """Terminate the running subprocess, if any."""
        if self._process is None:
            return
        process = self._process
        self._process = None
        await process.terminate()

    def render(self) -> Text:
        return self._display

    def on_mount(self) -> None:
        self.set_interval(0.5, self._sync_dimensions)

    def on_unmount(self) -> None:
        if self._process:
            asyncio.create_task(self.stop())

    def on_resize(self, event: events.Resize) -> None:
        cols = max(10, event.size.width)
        rows = max(5, event.size.height)
        self._resize(cols, rows)

    def on_key(self, event: events.Key) -> None:
        if self._process is None:
            return
        data = self._translate_key(event)
        if data:
            self._process.write(data)
            event.stop()

    def on_mouse_down(self, event: events.MouseDown) -> None:
        if self._process is None:
            return
        code = self._button_code(event.button)
        self._send_mouse(event.offset.x, event.offset.y, code, pressed=True, modifiers=event)
        event.stop()

    def on_mouse_up(self, event: events.MouseUp) -> None:
        if self._process is None:
            return
        code = 3
        self._send_mouse(event.offset.x, event.offset.y, code, pressed=False, modifiers=event)
        event.stop()

    def on_mouse_move(self, event: events.MouseMove) -> None:
        if self._process is None:
            return
        if event.button is None:
            return
        code = self._button_code(event.button) | 32
        self._send_mouse(event.offset.x, event.offset.y, code, pressed=True, modifiers=event)
        event.stop()

    def on_mouse_scroll_up(self, event: events.MouseScrollUp) -> None:
        if self._process is None:
            return
        code = 64
        self._send_mouse(event.offset.x, event.offset.y, code, pressed=True, modifiers=event)
        event.stop()

    def on_mouse_scroll_down(self, event: events.MouseScrollDown) -> None:
        if self._process is None:
            return
        code = 65
        self._send_mouse(event.offset.x, event.offset.y, code, pressed=True, modifiers=event)
        event.stop()

    def _translate_key(self, event: events.Key) -> bytes | None:
        key_candidates = [event.key.lower(), *(alias.lower() for alias in event.aliases)]

        key_map = {
            "enter": b"\n",
            "return": b"\r",
            "tab": b"\t",
            "escape": b"\x1b",
            "esc": b"\x1b",
            "backspace": b"\x7f",
            "shift+tab": b"\x1b[Z",
            "up": b"\x1b[A",
            "down": b"\x1b[B",
            "right": b"\x1b[C",
            "left": b"\x1b[D",
            "home": b"\x1b[H",
            "end": b"\x1b[F",
            "pageup": b"\x1b[5~",
            "pagedown": b"\x1b[6~",
            "insert": b"\x1b[2~",
            "delete": b"\x1b[3~",
        }

        for candidate in key_candidates:
            if candidate in key_map:
                return key_map[candidate]

        for candidate in key_candidates:
            if candidate.startswith("ctrl+") or candidate.startswith("control+"):
                suffix = candidate.split("+")[-1]
                ctrl_bytes = self._ctrl_sequence(suffix)
                if ctrl_bytes is not None:
                    return ctrl_bytes

        if event.character:
            return event.character.encode("utf-8")
        return None

    def _ctrl_sequence(self, suffix: str) -> bytes | None:
        special = {
            "space": b"\x00",
            "@": b"\x00",
            "[": b"\x1b",
            "\\": b"\x1c",
            "]": b"\x1d",
            "^": b"\x1e",
            "_": b"\x1f",
            "?": b"\x7f",
        }
        if suffix in special:
            return special[suffix]
        if len(suffix) == 1:
            ch = suffix.upper()
            return bytes([ord(ch) & 0x1F])
        return None

    def _button_code(self, button) -> int:
        mapping = {
            0: 0,
            1: 1,
            2: 2,
            "left": 0,
            "middle": 1,
            "right": 2,
        }
        return mapping.get(button, 0)

    def _modifier_bits(self, event: events.MouseEvent) -> int:
        bits = 0
        if event.shift:
            bits |= 4
        if getattr(event, "meta", False):
            bits |= 8
        if event.ctrl:
            bits |= 16
        return bits

    def _send_mouse(
        self,
        x: int,
        y: int,
        button_code: int,
        *,
        pressed: bool,
        modifiers: events.MouseEvent,
    ) -> None:
        if self._process is None:
            return
        mods = button_code | self._modifier_bits(modifiers)
        col = max(0, x) + 1
        row = max(0, y) + 1
        suffix = "M" if pressed else "m"
        sgr = f"\x1b[<{mods};{col};{row}{suffix}".encode("ascii", "ignore")
        self._process.write(sgr)

        legacy = self._encode_x10(button_code, col, row, pressed, modifiers)
        if legacy:
            self._process.write(legacy)

    def _encode_x10(
        self,
        button_code: int,
        col: int,
        row: int,
        pressed: bool,
        modifiers: events.MouseEvent,
    ) -> bytes | None:
        base = button_code
        if base < 0:
            return None
        if not pressed:
            base = 3
        legacy_mods = 0
        if modifiers.shift:
            legacy_mods |= 4
        if getattr(modifiers, "meta", False):
            legacy_mods |= 8
        if modifiers.ctrl:
            legacy_mods |= 16
        legacy_button = (base & 0x3) | legacy_mods
        if base >= 64:
            legacy_button = base
        try:
            return bytes(
                [
                    0x1B,
                    ord("["),
                    ord("M"),
                    legacy_button + 32,
                    min(col, 255) + 32,
                    min(row, 255) + 32,
                ]
            )
        except ValueError:
            return None

    def _handle_output(self, data: bytes) -> None:
        try:
            text = data.decode("utf-8", errors="ignore")
        except UnicodeDecodeError:
            text = data.decode("latin-1", errors="ignore")
        self._stream.feed(text)
        self._update_display()

    def _handle_exit(self, returncode: int | None) -> None:
        self._process = None
        self.post_message(TerminalExited(self, returncode))

    def _update_display(self) -> None:
        text = Text()
        cursor = self._screen.cursor
        cursor_pos = None
        if cursor and not getattr(cursor, "hidden", False):
            cursor_pos = (cursor.x, cursor.y)
        for row in range(self._screen.lines):
            buffer_row = self._screen.buffer[row]
            line = Text()
            for col in range(self._screen.columns):
                cell = buffer_row.get(col)
                char = cell.data if cell and cell.data else " "
                if char == "\x00":
                    char = " "
                is_cursor = cursor_pos == (col, row)
                display_char = "█" if is_cursor and char == " " else char
                style = self._style_from_cell(cell, is_cursor=is_cursor)
                line.append(display_char, style=style)
            line.rstrip()
            text += line
            if row < self._screen.lines - 1:
                text.append("\n")
        self._display = text
        self.refresh()

    def _style_from_cell(self, cell, *, is_cursor: bool = False) -> Style | None:
        if not cell:
            fg = None
            bg = None
            bold = False
            italic = False
            underline = False
            strike = False
            blink = False
            reverse = False
        else:
            fg = self._normalize_color(cell.fg)
            bg = self._normalize_color(cell.bg)
            bold = bool(cell.bold)
            italic = bool(cell.italics)
            underline = bool(cell.underscore)
            strike = bool(cell.strikethrough)
            blink = bool(cell.blink)
            reverse = bool(cell.reverse)

        if is_cursor:
            reverse = not reverse

        if fg is None and bg is None and not any([bold, italic, underline, strike, blink, reverse]):
            return None
        return Style(
            color=fg,
            bgcolor=bg,
            bold=bold,
            italic=italic,
            underline=underline,
            strike=strike,
            blink=blink,
            reverse=reverse,
        )

    @staticmethod
    def _normalize_color(value):
        if value in (None, "default"):
            return None
        if isinstance(value, int):
            return f"color({value})"
        value_str = str(value)
        color_map = {
            "brightblack": "bright_black",
            "brightred": "bright_red",
            "brightgreen": "bright_green",
            "brightbrown": "bright_yellow",
            "brightblue": "bright_blue",
            "brightmagenta": "bright_magenta",
            "brightcyan": "bright_cyan",
            "brightwhite": "bright_white",
            "brown": "yellow",
            "bfightmagenta": "bright_magenta",
        }
        if value_str in color_map:
            return color_map[value_str]
        if len(value_str) == 6 and all(c in "0123456789abcdefABCDEF" for c in value_str):
            return f"#{value_str.lower()}"
        if value_str.startswith("bright") and "_" not in value_str:
            value_str = "bright_" + value_str[len("bright") :]
        return value_str

    def _resize(self, cols: int, rows: int) -> None:
        changed = False
        if cols != self._screen.columns or rows != self._screen.lines:
            self._screen.resize(rows, cols)
            changed = True
        if self._process:
            self._process.resize(rows, cols)
        if changed:
            self._update_display()

    def _current_dimensions(self) -> tuple[int, int]:
        width = max(10, getattr(self.size, "width", 80))
        height = max(5, getattr(self.size, "height", 24))
        return width, height

    def _sync_dimensions(self) -> None:
        cols, rows = self._current_dimensions()
        self._resize(cols, rows)
