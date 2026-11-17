"""
Resolves the "external" base directory containing the editable config/, ref_data/, selection_functions/,
and attribute-generation modules (mock_attr_gen_functions.py, acbsuk_attr_gen_functions.py, etc.).

When running from source this is simply the repo root. When packaged into a standalone PyInstaller
executable, the bundled code runs from a temporary extraction folder (sys._MEIPASS) - so anything that
must stay editable/visible to end users (and not baked into the exe) has to be resolved relative to the
folder containing the executable instead, via get_base_path() below.
"""

import sys
from pathlib import Path


def get_base_path() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).parent


def ensure_base_path_on_sys_path() -> None:
    """
    Adds get_base_path() to sys.path (if not already present) so that modules named only by string in config
    (attr_gen_functions_module, selection_functions_module) can be found via importlib.import_module() even
    when those .py files live next to a frozen executable rather than being bundled inside it.
    """
    base_path_str = str(get_base_path())
    if base_path_str not in sys.path:
        sys.path.insert(0, base_path_str)
