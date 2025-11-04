import argparse 
import rich_argparse
from typing import Dict, Union, Callable, Iterable, Optional
import inspect
import shlex

class BabysFirstFormatter(rich_argparse.RichHelpFormatter):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        
    def add_usage(self, usage, actions, groups, prefix=""):
        return super().add_usage(usage, actions, groups, prefix)    

class CommandEntry:
    def __init__(self, runnable, name: str, description: str):
        self.name = name
        self.description = description
        self.run = runnable
        self.parser = self._init_parser()
        self.dynamic_templates: list[argparse.Namespace] = []
        self._usage_cache: Optional[str] = None

    def _init_parser(self) -> argparse.ArgumentParser:
        return argparse.ArgumentParser(
            prog=self.name,
            description=self.description,
            add_help=False,
            formatter_class=BabysFirstFormatter
        )

    def convert_args(self, arg_tokens: list[str]) -> list[str]:
        if not arg_tokens:
            return []

        if self.parser is None:
            return arg_tokens

        converter = getattr(self.parser, "convert_arg_line_to_args", None)
        if not callable(converter):
            return arg_tokens

        line = " ".join(arg_tokens)
        if not line:
            return []

        converted = converter(line)
        if converted is None:
            return []

        if isinstance(converted, str):
            converted = [converted]

        tokens: list[str] = []
        for item in converted:
            if isinstance(item, str):
                split_items = shlex.split(item)
                if not split_items:
                    continue
                tokens.extend(split_items)
            else:
                tokens.append(str(item))

        return tokens or arg_tokens

    def set_dynamic_templates(self, templates: Iterable[argparse.Namespace]) -> None:
        """Attach ready-to-use argparse.Namespace templates for completions."""
        self.dynamic_templates = list(templates)
        self._usage_cache = None

    def usage_summary(self) -> str:
        if self._usage_cache is not None:
            return self._usage_cache

        default_values = self._collect_default_values()
        variants: list[str] = []
        seen: set[str] = set()

        base_variant = self._format_usage_variant(default_values, default_values)
        if base_variant:
            variants.append(base_variant)
            seen.add(base_variant)

        for template in self.dynamic_templates:
            values = {key: getattr(template, key) for key in vars(template)}
            variant = self._format_usage_variant(values, default_values)
            if variant and variant not in seen:
                variants.append(variant)
                seen.add(variant)

        if not variants:
            variants = [self.name]

        summary = " | ".join(variants)
        self._usage_cache = summary
        return summary

    @staticmethod
    def _stringify_default(value) -> str:
        if isinstance(value, (list, tuple, set)):
            return ",".join(str(item) for item in value)
        return str(value)

    @staticmethod
    def _format_preview_value(value: object, is_default: bool) -> str:
        value_str = CommandEntry._stringify_default(value)

        max_len = 28
        if len(value_str) > max_len:
            value_str = value_str[: max_len - 3] + "..."

        if is_default:
            return f"[{value_str}]"
        return value_str

    def _format_usage_variant(self, values: dict[str, object], default_values: dict[str, object]) -> str:
        if self.parser is None:
            return self.name

        parts = [self.name]
        for action in self.parser._actions:
            if not action.option_strings or action.nargs == 0:
                continue
            dest = action.dest
            if dest not in values:
                continue
            value = values[dest]
            if value is None or value is argparse.SUPPRESS:
                continue
            option = next((opt for opt in action.option_strings if opt.startswith("--")), action.option_strings[0])
            value_text = self._stringify_default(value)
            is_default = dest in default_values and default_values[dest] == value
            if is_default:
                parts.append(f"[{option} {value_text}]")
            else:
                parts.append(f"{option} {value_text}")
        return " ".join(parts)

    def _collect_default_values(self) -> dict[str, object]:
        defaults: dict[str, object] = {}
        if self.parser is None:
            return defaults
        for action in self.parser._actions:
            if not action.option_strings or action.nargs == 0:
                continue
            default = action.default
            if default is None or default is argparse.SUPPRESS:
                continue
            defaults[action.dest] = default
        return defaults


    def build_preview_command(
        self, command_tokens: list[str], arg_tokens: list[str]
    ) -> str:
        parser = self.parser
        if parser is None:
            return " ".join(command_tokens) if command_tokens else self.name

        option_map: dict[str, argparse.Action] = {}
        values: dict[str, object] = {}
        sources: dict[str, str] = {}

        for action in parser._actions:
            if not action.option_strings or action.nargs == 0:
                continue
            for option in action.option_strings:
                option_map[option] = action

            default = action.default
            if default is not None and default is not argparse.SUPPRESS:
                values[action.dest] = default
                sources[action.dest] = "default"

        idx = 0
        while idx < len(arg_tokens):
            token = arg_tokens[idx]
            if token.startswith("--"):
                option = token
                value_token = None
                if "=" in token:
                    option, value_token = token.split("=", 1)
                else:
                    if idx + 1 < len(arg_tokens) and not arg_tokens[idx + 1].startswith("-"):
                        value_token = arg_tokens[idx + 1]
                        idx += 1

                action = option_map.get(option)
                if action is not None and value_token is not None:
                    values[action.dest] = value_token
                    sources[action.dest] = "input"
                idx += 1
                continue
            elif token.startswith("-") and len(token) > 1:
                action = option_map.get(token)
                if action is not None:
                    if action.nargs == 0:
                        values[action.dest] = True
                    elif idx + 1 < len(arg_tokens):
                        values[action.dest] = arg_tokens[idx + 1]
                        idx += 1
                    sources[action.dest] = "input"
                idx += 1
                continue
            else:
                idx += 1

        base_line = " ".join(command_tokens) if command_tokens else self.name
        option_lines: list[str] = []

        for action in parser._actions:
            if not action.option_strings or action.nargs == 0:
                continue
            dest = action.dest
            value = values.get(dest)
            if value is None or value is argparse.SUPPRESS:
                continue
            option = next((opt for opt in action.option_strings if opt.startswith("--")), action.option_strings[0])
            source = sources.get(dest, "default")
            formatted_value = self._format_preview_value(value, source != "input")
            option_lines.append(f"{option} {formatted_value}")

        if not option_lines:
            return base_line

        lines = [base_line]
        for index, option_line in enumerate(option_lines):
            branch = "└──" if index == len(option_lines) - 1 else "├──"
            lines.append(f"{branch} {option_line}")
        return "\n".join(lines)

class CommandCatalog:
    
    def __init__(self):
        self.commands = self.get_commands()
  
    def get_commands(self):
        
        start_command = CommandEntry(self.start, "start_server", "start web server")
        start_command.parser.add_argument("--host", default="localhost")
        start_command.parser.add_argument("--port", type=int, default=8000)
        
        stop_command = CommandEntry(self.stop, "stop_server", "stop web server")

        inspect_devices = CommandEntry(
            self.inspect_device_status,
            "inspect_device_status",
            "inspect a connected device",
        )
        inspect_devices.parser.add_argument(
            "--device-id",
            dest="device_id",
            default="11111111-1111-1111-1111-111111111111",
            help="UUID for the device to inspect",
        )
        inspect_devices.parser.add_argument(
            "--detail",
            dest="detail_level",
            choices=["summary", "full"],
            default="summary",
            help="Detail level for inspection output",
        )
        inspect_devices.parser.add_argument(
            "--color",
            dest="color",
            default="blue",
            help="Color profile to apply",
        )
        inspect_devices.parser.add_argument(
            "--shape",
            dest="shape",
            default="square",
            help="Shape configuration for the device",
        )
        inspect_devices.parser.add_argument(
            "--vehicle",
            dest="vehicle",
            default="car",
            help="Vehicle association for routing",
        )

        return {
            "web": {
                "_description": "Web interface commands",
                "server": {
                    "_description": "Manage the server stuff",
                    "start": start_command,
                    "stop": stop_command,
                },
            },
            "devices": {
                "_description": "Device commands",
                "status": {
                    "_description": "Inspect device status",
                    "inspect": inspect_devices,
                },
            },
        }


    def start(self):
        print("called start with args")
    
    def stop(self):
        print("called stop")

    def inspect_device_status(self, args=None):
        if args is None:
            print("expected argparse Namespace with device_id")
        else:
            detail = getattr(args, "detail_level", "summary")
            color = getattr(args, "color", "blue")
            shape = getattr(args, "shape", "square")
            vehicle = getattr(args, "vehicle", "car")
            print(f"inspect device {args.device_id}")
            print(f"  detail: {detail}")
            print(f"  color: {color}")
            print(f"  shape: {shape}")
            print(f"  vehicle: {vehicle}")
    
    def resolve(self, user_input: str):
        stripped = user_input.strip()
        tokens = stripped.split() if stripped else []
        node, remaining, _, _ = self._parse_tree(tokens)

        if isinstance(node, CommandEntry):
            converted = node.convert_args(remaining)
            return node, converted
        return None, remaining
    
    def find_command_entry(self, command_path: str) -> Optional[CommandEntry]:
        """Return a CommandEntry for a space-delimited command path."""
        tokens = [token for token in command_path.strip().split() if token]
        if not tokens:
            return None

        node, _, _, _ = self._parse_tree(tokens)
        return node if isinstance(node, CommandEntry) else None

    def register_dynamic_templates(
        self, command_path: str, templates: Iterable[argparse.Namespace]
    ) -> None:
        """Attach dynamic argparse templates to the given command entry."""
        entry = self.find_command_entry(command_path)
        if entry is not None:
            entry.set_dynamic_templates(templates)

    def get_dynamic_templates(self, command_path: str) -> list[argparse.Namespace]:
        """Fetch dynamic templates registered for a command path."""
        entry = self.find_command_entry(command_path)
        if entry is None:
            return []
        return entry.dynamic_templates

    def preview_full_command(self, user_input: str) -> str:
        entry, arg_tokens = self.resolve(user_input)

        stripped = user_input.strip()
        tokens = stripped.split() if stripped else []
        _, _, matched, _ = self._parse_tree(tokens)

        if not isinstance(entry, CommandEntry):
            return ""

        return entry.build_preview_command(matched, arg_tokens)

    def find_options(self, user_input: str) -> list[tuple[str, str]]:
        entry, arg_tokens = self.resolve(user_input)
        stripped = user_input.strip()
        tokens = stripped.split() if stripped else []
        _, _, matched, _ = self._parse_tree(tokens)
        trailing_space = user_input.endswith(" ")

        if isinstance(entry, CommandEntry):
            return self._argument_suggestions(
                entry=entry,
                command_tokens=matched,
                arg_tokens=arg_tokens,
                trailing_space=trailing_space,
            )

        return self._command_suggestions(tokens)

    def find_suggestions(self, user_input: str) -> list[tuple[str, str]]:
        stripped = user_input.strip()
        tokens = stripped.split() if stripped else []
        return self._command_suggestions(tokens)

    def find_argument_suggestions(
        self, user_input: str, trailing_space: bool
    ) -> list[tuple[str, str]]:
        entry, arg_tokens = self.resolve(user_input)
        stripped = user_input.strip()
        tokens = stripped.split() if stripped else []
        _, _, matched, _ = self._parse_tree(tokens)

        if not isinstance(entry, CommandEntry):
            return []

        if not arg_tokens and not trailing_space:
            return []

        return self._argument_suggestions(
            entry=entry,
            command_tokens=matched,
            arg_tokens=arg_tokens,
            trailing_space=trailing_space,
        )

    # -----------------------
    # Internal helpers
    # -----------------------
    def _command_suggestions(
        self,
        tokens: list[str],
    ) -> list[tuple[str, str]]:
        current = self.commands
        prefix: list[str] = []
        matches: list[tuple[str, str]] = []

        for token in tokens:
            if isinstance(current, dict) and token in current:
                current = current[token]
                prefix.append(token)
            else:
                partial = token
                if isinstance(current, dict):
                    candidates = {
                        name: entry
                        for name, entry in current.items()
                        if not name.startswith("_")
                    }
                else:
                    return matches
                for name, entry in candidates.items():
                    if name.startswith(partial):
                        full_name = " ".join(prefix + [name])
                        matches.append((full_name, self._describe_entry(entry)))
                        if isinstance(entry, dict):
                            for sub_name, sub_entry in entry.items():
                                if sub_name.startswith("_"):
                                    continue
                                child_full = f"{full_name} {sub_name}"
                                matches.append((child_full, self._describe_entry(sub_entry)))
                return matches

        # All tokens matched exactly; suggest child commands/options
        if isinstance(current, dict):
            for name, entry in current.items():
                if name.startswith("_"):
                    continue
                full_name = " ".join(prefix + [name])
                matches.append((full_name, self._describe_entry(entry)))
        # CommandEntry has no further suggestions

        return matches

    def _argument_suggestions(
        self,
        entry: CommandEntry,
        command_tokens: list[str],
        arg_tokens: list[str],
        trailing_space: bool,
    ) -> list[tuple[str, str]]:
        parser = getattr(entry, "parser", None)
        if parser is None:
            return []

        option_entries = self._collect_option_entries(parser)
        if not option_entries:
            return []

        option_map = {
            alias: (display, action)
            for display, aliases, action in option_entries
            for alias in aliases
        }

        option_pairs, active_option, active_values = self._split_option_tokens(arg_tokens)

        used_dests: set[str] = set()
        active_dest: Optional[str] = None

        for option, values in option_pairs:
            display_action = option_map.get(option)
            if not display_action:
                continue
            _, action = display_action
            if action and values:
                used_dests.add(action.dest)

        if active_option:
            display_action = option_map.get(active_option)
            if display_action:
                _, action = display_action
                if action:
                    active_dest = action.dest
                    if active_values:
                        used_dests.add(action.dest)

        matches: list[tuple[str, str]] = []

        if not arg_tokens:
            base_tokens = command_tokens.copy()
            return self._build_option_matches(
                base_tokens, "", option_entries, used_dests, active_dest
            )

        last_token = arg_tokens[-1]
        if (
            active_option
            and not active_values
            and not trailing_space
            and last_token == active_option
        ):
            # Typing an option; filter by current prefix
            base_tokens = command_tokens + arg_tokens[:-1]
            return self._build_option_matches(
                base_tokens, last_token, option_entries, used_dests, active_dest
            )

        if active_option:
            display_option, action = option_map.get(active_option, (active_option, None))
            expected = self._expected_values(action)
            if trailing_space and expected is not None and len(active_values) >= expected:
                # Option fulfilled; fall through to offer more options
                active_option = None
                active_dest = None
            else:
                # Offer option values
                if trailing_space and last_token == active_option:
                    base_tokens = command_tokens + arg_tokens
                    value_prefix = ""
                elif trailing_space:
                    base_tokens = command_tokens + arg_tokens
                    value_prefix = ""
                else:
                    base_tokens = command_tokens + arg_tokens[:-1]
                    value_prefix = active_values[-1] if active_values else ""

                value_candidates = self._collect_value_candidates(entry, action)
                return self._build_value_matches(
                    base_tokens,
                    value_prefix,
                    value_candidates,
                    display_option,
                )

        # Default: offer other options, filtering if the last token looks like one
        if arg_tokens and last_token.startswith("-") and not trailing_space:
            base_tokens = command_tokens + arg_tokens[:-1]
            prefix = last_token
        else:
            base_tokens = command_tokens + arg_tokens
            prefix = ""

        return self._build_option_matches(
            base_tokens, prefix, option_entries, used_dests, active_dest
        )

    def _collect_option_entries(
        self, parser: argparse.ArgumentParser
    ) -> list[tuple[str, list[str], argparse.Action]]:
        entries: list[tuple[str, list[str], argparse.Action]] = []
        for action in parser._actions:
            if not action.option_strings:
                continue
            aliases = list(action.option_strings)
            display = max(aliases, key=len)
            entries.append((display, aliases, action))
        return entries

    def _split_option_tokens(
        self, tokens: list[str]
    ) -> tuple[list[tuple[str, list[str]]], Optional[str], list[str]]:
        pairs: list[tuple[str, list[str]]] = []
        active_option: Optional[str] = None
        active_values: list[str] = []

        for token in tokens:
            if token.startswith("-") and "=" in token:
                option, value = token.split("=", 1)
                if active_option is not None:
                    pairs.append((active_option, active_values))
                pairs.append((option, [value]))
                active_option = None
                active_values = []
            elif token.startswith("-"):
                if active_option is not None:
                    pairs.append((active_option, active_values))
                active_option = token
                active_values = []
            else:
                if active_option is None:
                    pairs.append(("", [token]))
                else:
                    active_values.append(token)

        return pairs, active_option, active_values

    def _expected_values(self, action: Optional[argparse.Action]) -> Optional[int]:
        if action is None:
            return None

        nargs = action.nargs
        if nargs is None:
            return 1
        if isinstance(nargs, int):
            return nargs
        if nargs in ("?", "*", "+"):
            return None
        return None

    def _allows_multiple(self, action: argparse.Action) -> bool:
        nargs = action.nargs
        if nargs in ("*", "+"):
            return True
        if isinstance(nargs, int) and nargs != 1:
            return True
        return False

    def _collect_value_candidates(
        self,
        entry: CommandEntry,
        action: Optional[argparse.Action],
    ) -> list[tuple[str, str]]:
        if action is None:
            return []

        candidates: list[tuple[str, str]] = []
        seen: set[str] = set()

        default = getattr(action, "default", None)
        if default is not None and default is not argparse.SUPPRESS:
            text = CommandEntry._stringify_default(default)
            if text not in seen:
                candidates.append((text, "default"))
                seen.add(text)

        if action.choices:
            values = (
                action.choices.keys()
                if isinstance(action.choices, dict)
                else action.choices
            )
            for value in values:
                text = str(value)
                if text not in seen:
                    candidates.append((text, "choice"))
                    seen.add(text)

        for template in getattr(entry, "dynamic_templates", []):
            if not hasattr(template, action.dest):
                continue
            value = getattr(template, action.dest)
            if value is None:
                continue
            iterable = value if isinstance(value, (list, tuple, set)) else [value]
            for item in iterable:
                text = CommandEntry._stringify_default(item)
                if text not in seen:
                    candidates.append((text, "from payload"))
                    seen.add(text)

        return candidates

    def _build_option_matches(
        self,
        base_tokens: list[str],
        prefix: str,
        option_entries: list[tuple[str, list[str], argparse.Action]],
        used_dests: set[str],
        active_dest: Optional[str],
    ) -> list[tuple[str, str]]:
        matches: list[tuple[str, str]] = []
        for display, aliases, action in option_entries:
            match_alias = None
            if prefix:
                for alias in aliases:
                    if alias.startswith(prefix):
                        match_alias = alias
                        break
                if match_alias is None:
                    continue
            completion = match_alias or display
            if action is not None and action.dest in used_dests and action.dest != active_dest and not self._allows_multiple(action):
                continue
            suggestion_tokens = base_tokens + [completion]
            description = action.help or action.dest or ""
            matches.append((" ".join(suggestion_tokens), description))
        return matches

    def _describe_entry(self, entry: Union[dict, CommandEntry]) -> str:
        if isinstance(entry, CommandEntry):
            return entry.usage_summary()
        if isinstance(entry, dict):
            return str(entry.get("_description", ""))
        return ""

    def _build_value_matches(
        self,
        base_tokens: list[str],
        prefix: str,
        candidates: list[tuple[str, str]],
        option_label: str,
    ) -> list[tuple[str, str]]:
        matches: list[tuple[str, str]] = []
        for value, source in candidates:
            if prefix and not value.startswith(prefix):
                continue
            suggestion_tokens = base_tokens + [value]
            description = f"{option_label} ← {source}"
            matches.append((" ".join(suggestion_tokens), description))
        return matches


    def _parse_tree(self, tokens: list[str]):
        """
        Traverse the command tree based on the given tokens.

        Returns:
            tuple:
                - node: The last matched CommandEntry or nested dict, or None.
                - remaining_tokens: Tokens not consumed by matching.
                - matched: List of tokens that were successfully matched.
                - current_level: The current dictionary or mapping.
        """
        current_level = self.commands
        node = None
        matched = []

        for i, token in enumerate(tokens):
            # Try exact match
            if isinstance(current_level, dict) and token in current_level:
                node = current_level[token]
            else:
                # No exact match
                return node or current_level, tokens[i:], matched, current_level

            # Record matched token
            matched.append(token)

            if isinstance(node, dict):
                current_level = node
            elif isinstance(node, CommandEntry):
                # We've reached a leaf (command entry)
                return node, tokens[i + 1:], matched, {}
            else:
                return node, tokens[i + 1:], matched, {}

        return node or current_level, [], matched, current_level
    
    def has_args(self, func: Callable) -> bool:
        sig = inspect.signature(func)
        params = list(sig.parameters.values())

        # Skip 'self' if it's a bound method
        if hasattr(func, "__self__") and params and params[0].name == "self":
            params = params[1:]

        return len(params) > 0 