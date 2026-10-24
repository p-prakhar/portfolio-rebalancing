"""Show Markdown reports as formatted terminal output (tables, bold, headings); plain text if rich is missing or output is piped."""
import sys


def show_md(text: str) -> None:
    try:
        from rich.console import Console
        from rich.markdown import Markdown
        if sys.stdout.isatty():
            Console().print(Markdown(text))
            return
    except Exception:
        pass
    print(text)
