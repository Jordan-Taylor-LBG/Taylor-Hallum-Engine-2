"""Shared helper for opening a local folder in the OS's file explorer (Explorer/Finder/xdg-open)."""

import os
import subprocess
import sys
from pathlib import Path


def open_folder(path: Path) -> None:
    """Opens path (creating it first if it doesn't exist yet) in the OS's default file explorer."""
    path = Path(path)
    path.mkdir(parents=True, exist_ok=True)
    folder = str(path)
    if sys.platform.startswith("win"):
        os.startfile(folder)
    elif sys.platform == "darwin":
        subprocess.run(["open", folder])
    else:
        subprocess.run(["xdg-open", folder])
