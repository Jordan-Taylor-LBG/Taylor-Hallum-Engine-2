"""SplashWindow: the program's entry point - choose between the full data generator or a standalone JDW session."""

import tkinter as tk

from ui.app import App
from ui.bigquery_schema_window import BigQuerySchemaWindow
from ui.bigquery_spooler_window import BigQuerySpoolerWindow
from ui.bigquery_uploader_window import BigQueryUploaderWindow
from ui.icon import load_icon_image, set_window_icon
from ui.jdw_window import JDWWindow
from ui.session_picker import SessionPickerDialog
from ui.sound import play_startup_sound


class SplashWindow(tk.Tk):
    """
    First window shown when the program launches. Offers two entry points:
      - "Launch Data Generator (JDW-integrated)": the existing dataset/settings/run-window App, with JDW
        reachable from a running step-through session (unchanged).
      - "Launch JDW": opens JDWWindow standalone (no engine) against a chosen/created save_data/<name>/
        "JDW session", for browsing/querying previously saved or imported parquets on their own.
    """

    def __init__(self):
        super().__init__()
        self.title("The Taylor-Hallum Data Generator Mk4")
        self.resizable(False, False)
        set_window_icon(self)
        play_startup_sound()

        frame = tk.Frame(self, padx=24, pady=24)
        frame.pack()

        splash_icon = load_icon_image(subsample=4)
        if splash_icon is not None:
            self._splash_icon_ref = splash_icon  # PhotoImage needs a kept reference or it gets blanked
            tk.Label(frame, image=splash_icon).pack(pady=(0, 8))

        tk.Label(frame, text="The Taylor-Hallum Data Generator Mk4", font=("Segoe UI", 14, "bold")).pack(pady=(0, 16))

        tk.Button(
            frame, text="1. Launch Data Generator (JDW-integrated)", width=40,
            command=self._launch_app,
        ).pack(pady=4)
        tk.Button(
            frame, text="2. Launch JDW", width=40,
            command=self._launch_jdw_standalone,
        ).pack(pady=4)
        tk.Button(
            frame, text="3. Download BigQuery Schemas", width=40,
            command=self._launch_bigquery_schema_downloader,
        ).pack(pady=4)
        tk.Button(
            frame, text="4. BigQuery Spooler", width=40,
            command=self._launch_bigquery_spooler,
        ).pack(pady=4)
        tk.Button(
            frame, text="5. BigQuery Uploader", width=40,
            command=self._launch_bigquery_uploader,
        ).pack(pady=4)

    def _launch_app(self) -> None:
        self.destroy()
        App().mainloop()

    # Standalone JDW has no engine, so it needs a "JDW session" (a save_data/<name>/ folder) picked/created
    # up front instead - see ui/session_picker.py.
    def _launch_jdw_standalone(self) -> None:
        dialog = SessionPickerDialog(self)
        session_name = dialog.result
        if session_name is None:
            return

        self.destroy()
        root = tk.Tk()
        root.withdraw()
        set_window_icon(root)
        jdw = JDWWindow(root, sim_engine=None, session_name=session_name)

        def _on_jdw_closed():
            jdw.destroy()
            root.quit()

        jdw.protocol("WM_DELETE_WINDOW", _on_jdw_closed)
        root.mainloop()
        root.destroy()

    def _launch_bigquery_schema_downloader(self) -> None:
        self.destroy()
        BigQuerySchemaWindow().mainloop()

    def _launch_bigquery_spooler(self) -> None:
        self.destroy()
        BigQuerySpoolerWindow().mainloop()

    def _launch_bigquery_uploader(self) -> None:
        self.destroy()
        BigQueryUploaderWindow().mainloop()
