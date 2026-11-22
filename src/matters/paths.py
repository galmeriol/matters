import os
from pathlib import Path


def state_dir() -> Path:
    """Where matters keeps its own files: pid records and the knowledge database.

    $MATTERS_STATE_DIR, else $XDG_STATE_HOME/matters, else ~/.local/state/matters.
    """
    if explicit := os.environ.get("MATTERS_STATE_DIR"):
        return Path(explicit)
    base = os.environ.get("XDG_STATE_HOME") or str(Path.home() / ".local" / "state")
    return Path(base) / "matters"
