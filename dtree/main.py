from textual.app import App, ComposeResult
from textual.widgets import Header
from textual.containers import Horizontal
from commands import CommandCatalog
from ui.cli import CLI
from ui.panels import ResponseTreePanel

class MainApp(App):
    CSS = """
    #workspace {
        height: 1fr;
    }

    #console {
        width: 3fr;
    }

    #response_tree_panel {
        width: 2fr;
        min-width: 48;
    }

    #response_tree {
        height: 1fr;
    }

    #command_preview {
        padding: 0 1;
        margin-top: 1;
    }

    #suggestions {
        margin-top: 1;
    }

    #console_label,
    #output_label {
        padding: 0 1;
    }

    #output_label {
        margin-top: 1;
    }
    """
    
    def __init__(self):
        super().__init__()
        self.commands = CommandCatalog()
    
    def on_mount(self) -> None:
        self.theme = "tokyo-night"
        self.title = "Work in Progress"
        
    def compose(self)  -> ComposeResult:
        yield Header(show_clock=True)
        yield Horizontal(
            CLI(),
            ResponseTreePanel(),
            id="workspace",
        )
        
if __name__ == "__main__":
    MainApp().run()
