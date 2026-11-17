"""
Builds a standalone, shareable folder (dist/release/) that colleagues can run without needing Python or
access to the source code:
  - TaylorHallumEngine.exe (+ supporting files) - the compiled GUI app. The core/ (engine.py,
    config_manager.py, helper_functions.py), ui/ (gui.py, schema_viewer.py, actions_viewer.py) and
    parsers/ (schema_parser.py, actions_parser.py) packages are all baked into this and are not
    visible/editable afterwards.
  - config/, ref_data/, selection_functions/, assets/, mock_attr_gen_functions.py,
    acbsuk_attr_gen_functions.py - copied in as plain, editable files/folders next to the exe. app_paths.py
    makes the compiled app look for these next to the exe (not inside itself), and main.py adds that folder
    to sys.path so the dynamically-loaded attr_gen_functions_module/selection_functions_module modules can
    still be found there at runtime.

Requires PyInstaller: `pip install pyinstaller`. Run with: python build_standalone.py
"""

import shutil
import subprocess
import sys
from pathlib import Path

BASE_PATH = Path(__file__).parent
APP_NAME = "TaylorHallumEngine"
DIST_APP_DIR = BASE_PATH / "dist" / APP_NAME
RELEASE_DIR = BASE_PATH / "dist" / "release"
# Regenerated from assets/images/icon.png on every build (see build_exe_icon()) - Pillow is only needed here,
# by this build script on the dev machine, never bundled into the app itself.
ICON_PNG_PATH = BASE_PATH / "assets" / "images" / "icon.png"
ICON_ICO_PATH = BASE_PATH / "assets" / "images" / "icon.ico"

# Left as plain, editable files/folders alongside the exe - never bundled into it.
EXPOSED_ITEMS = [
    "config",
    "ref_data",
    "selection_functions",
    "assets",
    "mock_attr_gen_functions.py",
    "acbsuk_attr_gen_functions.py",
    "summit_attr_gen_functions.py"
]


def build_exe_icon() -> Path | None:
    """Converts assets/images/icon.png into a multi-resolution assets/images/icon.ico for PyInstaller's
    --icon option (the exe's own file icon, shown in Explorer/taskbar - separate from the app's own runtime
    iconphoto() window-icon calls in ui/icon.py). Returns None if icon.png doesn't exist."""
    if not ICON_PNG_PATH.exists():
        return None
    from PIL import Image
    Image.open(ICON_PNG_PATH).save(ICON_ICO_PATH, sizes=[(16, 16), (32, 32), (48, 48), (256, 256)])
    return ICON_ICO_PATH


def run_pyinstaller(icon_path: Path | None) -> None:
    command = [
        sys.executable, "-m", "PyInstaller",
        "--name", APP_NAME,
        "--windowed",
        "--collect-all", "pyarrow",
        "--collect-all", "faker",
        "--collect-all", "tzdata",
        "--collect-all", "google.cloud.bigquery",
        "--noconfirm",
    ]
    if icon_path is not None:
        command += ["--icon", str(icon_path)]
    command.append("main.py")
    subprocess.run(command, check=True, cwd=BASE_PATH)


def assemble_release_folder() -> None:
    if RELEASE_DIR.exists():
        shutil.rmtree(RELEASE_DIR)
    shutil.copytree(DIST_APP_DIR, RELEASE_DIR)

    for item_name in EXPOSED_ITEMS:
        source = BASE_PATH / item_name
        destination = RELEASE_DIR / item_name
        if source.is_dir():
            shutil.copytree(source, destination)
        else:
            shutil.copy2(source, destination)


if __name__ == "__main__":
    run_pyinstaller(build_exe_icon())
    assemble_release_folder()
    print(f"Standalone release folder ready: {RELEASE_DIR}")
    print(f"Zip/share the whole '{RELEASE_DIR.name}' folder - colleagues run {APP_NAME}.exe inside it.")
