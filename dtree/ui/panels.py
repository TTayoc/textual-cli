import argparse
from collections import deque
from copy import deepcopy

from rich.text import Text

from textual.app import ComposeResult
from textual.containers import Vertical, VerticalScroll
from textual.widget import Widget
from textual.widgets import Button, Static, Tree

from ui.cli import Output

MOCK_SERVER_RESPONSES = [
    {
        "521d2b8e-05e9-4b91-9bf4-75103e2f9b92": {
            "serial": "521d2b8e-05e9-4b91-9bf4-75103e2f9b92",
            "name": "ingest-proxy-01",
            "status": "online",
        },
    },
    {
        "7b2fdd61-bceb-4a01-bfa2-13ed44c2bc8f": {
            "serial": "7b2fdd61-bceb-4a01-bfa2-13ed44c2bc8f",
            "name": "analytics-node-a",
            "status": "degraded",
        },
    },
    {
        "e83f015c-44b9-48a5-ae35-84a07f85dd14": {
            "serial": "e83f015c-44b9-48a5-ae35-84a07f85dd14",
            "name": "edge-cache-west",
            "status": "offline",
        },
    },
    {
        "521d2b8e-05e9-4b91-9bf4-75103e2f9b92": {
            "serial": "521d2b8e-05e9-4b91-9bf4-75103e2f9b92",
            "name": "ingest-proxy-01",
            "status": "degraded",
        },
        "7b2fdd61-bceb-4a01-bfa2-13ed44c2bc8f": {
            "serial": "7b2fdd61-bceb-4a01-bfa2-13ed44c2bc8f",
            "name": "analytics-node-a",
            "status": "online",
        },
    },
]

class StatusPanel(Widget):
    def __init__(self) -> None:
        super().__init__()
        self.id = "status_panel"
        self.border_title = "Status"

    def compose(self) -> ComposeResult:
        yield VerticalScroll(Static(id="status_content"))

class WebPanel(Widget):
    def __init__(self) -> None:
        super().__init__()
        self.border_title = "Web Server"

    def compose(self) -> ComposeResult:
        yield VerticalScroll(Static(id="web_content"))
        
    async def on_cli_output(self, message: Output):
        log = self.query_one("#web_content", Static)
        existing = getattr(log, "renderable", "") or ""
        if not isinstance(existing, str):
            existing = getattr(existing, "plain", str(existing))
        new_text = f"{existing}\n{message.data}" if existing else message.data
        log.update(new_text)


class OtherPanel(Widget):
    def __init__(self) -> None:
        super().__init__()
        self.id = "other_panel"
        self.border_title = "Other Logs"

    def compose(self) -> ComposeResult:
        yield VerticalScroll(Static(id="other_content"))


class ResponseTreePanel(Widget):
    """Visualise payloads via ``Tree.add_json`` and surface argparse templates."""

    def __init__(
        self,
        command_path: str = "devices status inspect",
        responses: list[dict[str, object]] | None = None,
    ) -> None:
        super().__init__()
        self.command_path = command_path
        self.border_title = "Mock Server Payloads"
        self.id = "response_tree_panel"
        self._history: list[dict[str, object]] = []
        self._mock_queue: deque[dict[str, object]] = deque(
            deepcopy(responses) if responses is not None else deepcopy(MOCK_SERVER_RESPONSES)
        )
        self._namespace_builders = {
            "devices status inspect": self._build_device_namespaces,
        }
        self._rendered_count = 0
        self.styles.width = "1fr"
        self.styles.min_width = 48
        self.styles.height = "1fr"
        self._namespaces: dict[str, list[argparse.Namespace]] = {}

    def compose(self) -> ComposeResult:
        tree = Tree("", id="response_tree")
        tree.show_root = True
        yield Vertical(
            Button("Simulate Server Response", id="trigger_response", variant="success"),
            VerticalScroll(tree, id="response_tree_scroll"),
            id="response_tree_wrapper",
        )

    async def on_mount(self) -> None:
        tree = self.query_one("#response_tree", Tree)
        tree.root.set_label(Text(f"{self.command_path} responses"))
        self._register_templates()

    def set_response(
        self, payload: dict[str, object], command_path: str | None = None
    ) -> None:
        self.handle_server_response(payload, command_path)

    def _render_new_payloads(self, tree: Tree) -> None:
        root = tree.root
        root.set_label(Text(f"{self.command_path} responses"))
        for index in range(self._rendered_count, len(self._history)):
            payload = self._history[index]
            self._attach_payload_node(tree, payload)
            self._rendered_count += 1
        root.expand_all()
        tree.refresh(layout=True)

    def _attach_payload_node(
        self, tree: Tree, payload: dict[str, object]
    ) -> None:
        tree.show_root = False
        root = tree.root
        for device_id, info in payload.items():
            device_node = root.add(device_id)
            self._attach_dict(device_node, info)
            device_node.expand_all()

    def _attach_dict(self, node, data: dict[str, object]) -> None:
        from rich.highlighter import ReprHighlighter
        highlighter = ReprHighlighter()

        for key, value in data.items():
            if isinstance(value, dict):
                child = node.add(key)
                self._attach_dict(child, value)
                child.expand_all()
            elif isinstance(value, list):
                list_node = node.add(f"{key} [list]")
                for index, item in enumerate(value):
                    if isinstance(item, dict):
                        entry = list_node.add(f"[{index}]")
                        self._attach_dict(entry, item)
                        entry.expand_all()
                    else:
                        label = Text.assemble(Text.from_markup(f"[b]{key}[{index}][/b]="), highlighter(repr(item)))
                        list_node.add_leaf(label)
            else:
                label = Text.assemble(Text.from_markup(f"[b]{key}[/b]="), highlighter(repr(value)))
                node.add_leaf(label)

    def handle_server_response(
        self, payload: dict[str, object], command_path: str | None = None
    ) -> None:
        if not payload:
            return

        payload_copy = deepcopy(payload)
        if command_path is not None:
            self.command_path = command_path

        self._history.append(payload_copy)
        self._namespaces = self._build_namespaces()

        if self.is_mounted:
            tree = self.query_one("#response_tree", Tree)
            self._render_new_payloads(tree)
            self._register_templates()

    def _next_mock_payload(self) -> dict[str, object] | None:
        if not self._mock_queue:
            return None
        payload = self._mock_queue.popleft()
        self._mock_queue.append(payload)
        return deepcopy(payload)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "trigger_response":
            payload = self._next_mock_payload()
            if payload:
                self.handle_server_response(payload)

    def _flatten_payload(self, payload, container: dict[str, object], prefix: str = "") -> None:
        if isinstance(payload, dict):
            for key, value in payload.items():
                next_prefix = f"{prefix}_{key}" if prefix else key
                self._flatten_payload(value, container, next_prefix)
        elif isinstance(payload, list):
            if not payload:
                return
            if all(isinstance(item, (str, int, float, bool)) for item in payload):
                container[prefix] = payload
            else:
                for index, item in enumerate(payload):
                    next_prefix = f"{prefix}_{index}" if prefix else str(index)
                    self._flatten_payload(item, container, next_prefix)
        else:
            container[prefix] = payload

    def _register_templates(self) -> None:
        if not self.is_attached:
            return
        try:
            app = self.app
        except Exception:
            return

        if not hasattr(app, "commands"):
            return

        register = getattr(app.commands, "register_dynamic_templates", None)
        if not callable(register):
            return

        for command_path, templates in self._namespaces.items():
            register(command_path, templates)

    def _build_namespaces(self) -> dict[str, list[argparse.Namespace]]:
        if not self._history:
            return {}

        builder = self._namespace_builders.get(
            self.command_path, self._build_default_namespaces
        )
        aggregated: dict[tuple[tuple[str, object], ...], argparse.Namespace] = {}
        for payload in self._history:
            for template in builder(payload):
                key = tuple(sorted(vars(template).items()))
                aggregated[key] = template

        if not aggregated:
            return {}
        return {self.command_path: list(aggregated.values())}

    def _build_default_namespaces(
        self, payload: object
    ) -> list[argparse.Namespace]:
        flattened: dict[str, object] = {}
        self._flatten_payload(payload, flattened)
        if not flattened:
            return []
        return [argparse.Namespace(**flattened)]

    def _build_device_namespaces(
        self, payload: dict[str, dict]
    ) -> list[argparse.Namespace]:
        namespaces: list[argparse.Namespace] = []
        for device_id, info in payload.items():
            info = info or {}
            namespaces.append(
                argparse.Namespace(
                    device_id=device_id,
                    device_serial=info.get("serial", device_id),
                    device_name=info.get("name"),
                    device_status=info.get("status"),
                )
            )
        return namespaces
