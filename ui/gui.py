"""
Tkinter GUI launched by main.py. Shows a splash screen first (see ui/splash_window.py), letting the user
either launch the full data generator (dataset selection/settings/run window - as described below) or a
standalone JDW session:
  - pick which dataset (config/<dataset>/) to populate config/master_config.yaml from
  - view/edit that dataset's settings (attr_gen_functions_module, selection_functions_module, seconds_per_time_step)
  - choose a run window via a calendar (start date + number of days) and a single clock: drag the two hands
    to set the daily active run period (shaded), right-click to add/remove a snapshot+delta checkpoint time
  - save config/master_config.yaml and/or launch the simulation

This module is now a thin entry point - actual window implementations live in one file per window
(ui/splash_window.py, ui/app.py, ui/dag_window.py, ui/step_through_window.py, ui/jdw_window.py,
ui/session_picker.py, ui/bigquery_schema_window.py) plus shared utility modules (ui/widgets.py,
ui/badges.py). Everything is re-exported here for convenience/backward compatibility.
"""

from ui.app import App
from ui.badges import draw_macro_badge, draw_update_badge
from ui.bigquery_schema_window import BigQuerySchemaWindow
from ui.dag_window import DagWindow
from ui.jdw_window import JDWWindow
from ui.session_picker import SessionPickerDialog
from ui.splash_window import SplashWindow
from ui.step_through_window import StepThroughWindow
from ui.widgets import CalendarPopup, ClockWidget


def launch_gui() -> None:
    SplashWindow().mainloop()


if __name__ == "__main__":
    launch_gui()
