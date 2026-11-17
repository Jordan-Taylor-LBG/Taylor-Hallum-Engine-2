"""Shared app icon (assets/images/icon.png): small window-titlebar icon and a larger splash-screen image."""

import tkinter as tk

from app_paths import get_base_path

ICON_PATH = get_base_path() / "assets" / "images" / "icon.png"


def load_icon_image(subsample: int = None) -> tk.PhotoImage | None:
    """Loads assets/images/icon.png as a tk.PhotoImage (optionally downscaled by subsample), or None if the
    file is missing - callers should handle that gracefully rather than erroring out."""
    if not ICON_PATH.exists():
        return None
    image = tk.PhotoImage(file=str(ICON_PATH))
    if subsample and subsample > 1:
        image = image.subsample(subsample)
    return image


def set_window_icon(window) -> None:
    """
    Sets window's titlebar icon to assets/images/icon.png, if present - since iconphoto(True, ...) marks it
    as the default, every Toplevel later created under this same root inherits it automatically, so this
    only needs calling once per root window (App, SplashWindow, and the standalone JDW's hidden root).
    """
    image = load_icon_image(subsample=8)
    if image is None:
        return
    try:
        window.iconphoto(True, image)
    except tk.TclError:
        return
    window._icon_image_ref = image  # PhotoImage is garbage-collected (and the icon blanks) without a ref
