"""Plays assets/sounds/tada.wav on startup (see ui/splash_window.py)."""

import subprocess
import sys

from app_paths import get_base_path

SOUND_PATH = get_base_path() / "assets" / "sounds" / "tada.wav"

# The splash screen is recreated each time a sub-window's "Back" button returns to it - only the very
# first startup should play the sound, not every return trip within the same run.
_played_this_run = False


def play_startup_sound() -> None:
    """Plays SOUND_PATH asynchronously (non-blocking) the first time this is called in this run of the
    program, if present - subsequent calls (e.g. returning to the splash screen) are no-ops."""
    global _played_this_run
    if _played_this_run:
        return
    _played_this_run = True

    if not SOUND_PATH.exists():
        return
    try:
        if sys.platform.startswith("win"):
            import winsound
            winsound.PlaySound(str(SOUND_PATH), winsound.SND_FILENAME | winsound.SND_ASYNC)
        elif sys.platform == "darwin":
            subprocess.Popen(["afplay", str(SOUND_PATH)])
        else:
            subprocess.Popen(["aplay", str(SOUND_PATH)])
    except Exception:
        pass

