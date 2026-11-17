from app_paths import ensure_base_path_on_sys_path

# Must run before importing gui/engine, so that mock_attr_gen_functions.py, acbsuk_attr_gen_functions.py and
# selection_functions/ can still be found via importlib when packaged as a standalone executable, since those
# stay as editable loose files next to the exe rather than being bundled into it.
ensure_base_path_on_sys_path()

from ui.gui import launch_gui

if __name__ == '__main__':
    launch_gui()

