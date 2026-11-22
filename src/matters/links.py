from matters.session import SourceRef


def editor_url(ref: SourceRef) -> str:
    """Opens the source file at the exact line in VS Code."""
    return f"vscode://file{ref.path}:{ref.line}"
