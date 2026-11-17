"""
BigQuerySchemaWindow: downloads BigQuery table schema(s) as JSON (+ a schema_entity_relationships.yaml-
shaped YAML copy - see core/bigquery_schema_export.py) to a chosen folder. Opened from the splash screen.
"""

import subprocess
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from core import bigquery_schema_export
from core import config_manager
from ui.file_utils import open_folder
from ui.icon import load_icon_image, set_window_icon

DEFAULT_SCHEMAS_DIR = config_manager.BASE_PATH / "saved_schemas"


class BigQuerySchemaWindow(tk.Tk):
    """
    Standalone window (its own root, like the splash-launched standalone JDW) for downloading one table's -
    or, if left blank, every table's - BigQuery schema into a chosen destination folder as JSON, plus a
    converted YAML copy in our own schema format. Has its own "Back" button, returning to the splash screen.
    """

    def __init__(self):
        super().__init__()
        self.title("BigQuery Schema Downloader")
        self.resizable(False, False)
        set_window_icon(self)

        frame = tk.Frame(self, padx=16, pady=16)
        frame.pack()

        splash_icon = load_icon_image(subsample=8)
        if splash_icon is not None:
            self._icon_ref = splash_icon
            tk.Label(frame, image=splash_icon).grid(row=0, column=0, columnspan=3, pady=(0, 8))

        tk.Label(frame, text="BigQuery Schema Downloader", font=("Segoe UI", 12, "bold")).grid(row=1, column=0, columnspan=3, pady=(0, 12))

        self.project_var = tk.StringVar()
        self.dataset_var = tk.StringVar()
        self.table_var = tk.StringVar()
        DEFAULT_SCHEMAS_DIR.mkdir(parents=True, exist_ok=True)
        self.destination_var = tk.StringVar(value=str(DEFAULT_SCHEMAS_DIR))

        self._add_row(frame, 2, "GCP Project:", self.project_var)
        self._add_row(frame, 3, "GCP Dataset:", self.dataset_var)
        self._add_row(frame, 4, "Table (optional):", self.table_var)

        tk.Label(frame, text="Destination folder:").grid(row=5, column=0, sticky="w", pady=2)
        tk.Entry(frame, textvariable=self.destination_var, width=40).grid(row=5, column=1, sticky="w", pady=2)
        tk.Button(frame, text="Browse...", command=self._on_browse_destination).grid(row=5, column=2, sticky="w", padx=(4, 0))

        buttons_frame = tk.Frame(frame)
        buttons_frame.grid(row=6, column=0, columnspan=3, pady=(12, 4))
        self.auth_button = tk.Button(buttons_frame, text="Authenticate with gcloud", command=self._on_authenticate)
        self.auth_button.pack(side="left", padx=4)
        self.download_button = tk.Button(buttons_frame, text="Download Schema(s)", command=self._on_download)
        self.download_button.pack(side="left", padx=4)

        self.status_var = tk.StringVar(value="Ready.")
        tk.Label(frame, textvariable=self.status_var, fg="#333333", wraplength=380, justify="left").grid(row=7, column=0, columnspan=3, sticky="w", pady=(8, 4))

        self.progress_bar = ttk.Progressbar(frame, orient="horizontal", mode="determinate", maximum=1, value=0)
        self.progress_bar.grid(row=8, column=0, columnspan=3, sticky="ew", pady=(0, 8))

        ttk.Separator(frame, orient="horizontal").grid(row=9, column=0, columnspan=3, sticky="ew", pady=8)
        tk.Button(frame, text="< Back", command=self._on_back).grid(row=10, column=0, sticky="w")

    def _add_row(self, frame: tk.Frame, row: int, label_text: str, var: tk.StringVar) -> None:
        tk.Label(frame, text=label_text).grid(row=row, column=0, sticky="w", pady=2)
        tk.Entry(frame, textvariable=var, width=40).grid(row=row, column=1, columnspan=2, sticky="w", pady=2)

    def _on_browse_destination(self) -> None:
        folder = filedialog.askdirectory(
            parent=self, title="Select Destination Folder",
            initialdir=self.destination_var.get() or str(DEFAULT_SCHEMAS_DIR),
        )
        if folder:
            self.destination_var.set(folder)

    def _on_back(self) -> None:
        self.destroy()
        from ui.splash_window import SplashWindow
        SplashWindow().mainloop()

    # Opens a real, visible cmd window to run both logins in (the user can see gcloud's own output/prompts
    # there) - /c (not /k) closes the window automatically once both commands have finished.
    def _on_authenticate(self) -> None:
        try:
            subprocess.Popen(
                'start "gcloud auth" cmd /c "gcloud auth login && gcloud auth application-default login"',
                shell=True,
            )
        except Exception as e:
            messagebox.showerror("Authentication failed", str(e))
            return
        self.status_var.set("Opened a command prompt window - complete gcloud sign-in there.")

    def _on_download(self) -> None:
        project = self.project_var.get().strip()
        dataset = self.dataset_var.get().strip()
        table = self.table_var.get().strip()
        destination = self.destination_var.get().strip()

        if not project or not dataset:
            messagebox.showerror("Missing input", "GCP Project and GCP Dataset are both required.")
            return
        if not destination:
            messagebox.showerror("Missing input", "Please choose a destination folder.")
            return
        if not table:
            if not messagebox.askyesno(
                "No table specified",
                f"No table was specified - ALL tables in dataset '{dataset}' will have their schema downloaded. Continue?",
            ):
                return

        self.download_button.config(state="disabled")
        self.status_var.set("Downloading schema(s) from BigQuery...")
        self.progress_bar["maximum"] = 1
        self.progress_bar["value"] = 0

        def on_progress(completed, total, table_name):
            self.after(0, self._update_download_progress, completed, total, table_name)

        def worker():
            try:
                results = bigquery_schema_export.download_dataset_schemas(project, dataset, table, Path(destination), on_progress=on_progress)
                self.after(0, self._on_download_finished, True, results)
            except Exception as e:
                self.after(0, self._on_download_finished, False, str(e))

        threading.Thread(target=worker, daemon=True).start()

    # on_progress fires from the background worker thread, so it schedules this via self.after(0, ...)
    # rather than touching widgets directly.
    def _update_download_progress(self, completed: int, total: int, table_name: str) -> None:
        self.progress_bar["maximum"] = total
        self.progress_bar["value"] = completed
        self.status_var.set(f"Downloaded + converted {completed}/{total}: {table_name}")

    def _on_download_finished(self, success: bool, result) -> None:
        self.download_button.config(state="normal")
        if not success:
            self.status_var.set(f"Download failed: {result}")
            messagebox.showerror("Download failed", str(result))
            return
        table_names = ", ".join(r["table"] for r in result)
        self.status_var.set(f"Downloaded schema (JSON + YAML) for {len(result)} table(s): {table_names}.")
        try:
            open_folder(Path(self.destination_var.get()))
        except Exception:
            pass
