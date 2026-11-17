"""
BigQuerySpoolerWindow: queues up multiple run-name + SQL-query jobs against BigQuery and downloads each
one's result as a single CSV of any size (see core/bigquery_spooler.py for the single-query streaming +
10MB-per-part-file logic). GCP project + destination folder are shared across the whole queue. Opened from
the splash screen.
"""

import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
import subprocess

from core import bigquery_spooler
from core import config_manager
from ui.file_utils import open_folder
from ui.icon import load_icon_image, set_window_icon

DEFAULT_SPOOLED_DOWNLOADS_DIR = config_manager.SAVE_DATA_DIR / "spooled_downloads"


class _AddJobDialog(tk.Toplevel):
    """Modal dialog collecting one job's run name + SQL query. Sets self.result to (run_name, query) on
    OK, or leaves it None if cancelled."""

    def __init__(self, parent: tk.Tk, existing_names: set):
        super().__init__(parent)
        self.title("Add Spooler Job")
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()
        self.result = None
        self._existing_names = existing_names

        frame = tk.Frame(self, padx=16, pady=16)
        frame.pack()

        tk.Label(frame, text="Run name:").grid(row=0, column=0, sticky="w", pady=2)
        self.run_name_var = tk.StringVar()
        tk.Entry(frame, textvariable=self.run_name_var, width=50).grid(row=0, column=1, sticky="w", pady=2)

        tk.Label(frame, text="SQL query (becomes the body of a \"base\" CTE - write a full SELECT):").grid(
            row=1, column=0, columnspan=2, sticky="w", pady=(8, 2)
        )
        text_frame = tk.Frame(frame)
        text_frame.grid(row=2, column=0, columnspan=2, pady=(0, 8))
        self.query_text = tk.Text(text_frame, width=70, height=14, wrap="none")
        self.query_text.pack(side="left", fill="both", expand=True)
        query_scroll = ttk.Scrollbar(text_frame, orient="vertical", command=self.query_text.yview)
        query_scroll.pack(side="right", fill="y")
        self.query_text.config(yscrollcommand=query_scroll.set)

        buttons_frame = tk.Frame(frame)
        buttons_frame.grid(row=3, column=0, columnspan=2, pady=(4, 0))
        tk.Button(buttons_frame, text="OK", command=self._on_ok, width=10).pack(side="left", padx=4)
        tk.Button(buttons_frame, text="Cancel", command=self._on_cancel, width=10).pack(side="left", padx=4)

        self.protocol("WM_DELETE_WINDOW", self._on_cancel)
        self.wait_window(self)

    def _on_ok(self) -> None:
        run_name = self.run_name_var.get().strip()
        query = self.query_text.get("1.0", "end").strip()
        if not run_name:
            messagebox.showerror("Missing input", "Please enter a run name.", parent=self)
            return
        if run_name in self._existing_names:
            messagebox.showerror("Duplicate run name", f"A job named '{run_name}' is already queued.", parent=self)
            return
        if not query:
            messagebox.showerror("Missing input", "Please enter a SQL query.", parent=self)
            return
        self.result = (run_name, query)
        self.destroy()

    def _on_cancel(self) -> None:
        self.result = None
        self.destroy()


class BigQuerySpoolerWindow(tk.Tk):
    """
    Standalone window (its own root, like the splash-launched BigQuerySchemaWindow) for queuing up
    several run-name + SQL-query jobs, authenticating with gcloud, and running the whole queue - each
    job's full result saved as its own CSV, however large - into a shared destination folder. Has its own
    "Back" button, returning to the splash screen.
    """

    def __init__(self):
        super().__init__()
        self.title("BigQuery Spooler")
        self.resizable(False, False)
        set_window_icon(self)

        menu_bar = tk.Menu(self)
        file_menu = tk.Menu(menu_bar, tearoff=False)
        file_menu.add_command(label="Open Spooled Downloads Folder", command=self._on_open_spooled_downloads_folder)
        menu_bar.add_cascade(label="File", menu=file_menu)
        self.config(menu=menu_bar)

        self.jobs = []  # each: {"run_name", "query", "status", "rows", "size_mb", "message"}

        frame = tk.Frame(self, padx=16, pady=16)
        frame.pack()

        splash_icon = load_icon_image(subsample=8)
        if splash_icon is not None:
            self._icon_ref = splash_icon
            tk.Label(frame, image=splash_icon).grid(row=0, column=0, columnspan=3, pady=(0, 8))

        tk.Label(frame, text="BigQuery Spooler", font=("Segoe UI", 12, "bold")).grid(row=1, column=0, columnspan=3, pady=(0, 12))

        DEFAULT_SPOOLED_DOWNLOADS_DIR.mkdir(parents=True, exist_ok=True)
        self.destination_var = tk.StringVar(value=str(DEFAULT_SPOOLED_DOWNLOADS_DIR))
        self.project_var = tk.StringVar()

        tk.Label(frame, text="GCP Project:").grid(row=2, column=0, sticky="w", pady=2)
        tk.Entry(frame, textvariable=self.project_var, width=50).grid(row=2, column=1, sticky="w", pady=2)
        tk.Button(frame, text="Set as gcloud Project", command=self._on_set_project).grid(row=2, column=2, sticky="w", padx=(4, 0))

        tk.Label(frame, text="Destination folder:").grid(row=3, column=0, sticky="w", pady=2)
        tk.Entry(frame, textvariable=self.destination_var, width=50).grid(row=3, column=1, sticky="w", pady=2)
        tk.Button(frame, text="Browse...", command=self._on_browse_destination).grid(row=3, column=2, sticky="w", padx=(4, 0))

        ttk.Separator(frame, orient="horizontal").grid(row=4, column=0, columnspan=3, sticky="ew", pady=8)

        tk.Label(frame, text="Job queue:").grid(row=5, column=0, columnspan=3, sticky="w")
        tree_frame = tk.Frame(frame)
        tree_frame.grid(row=6, column=0, columnspan=3, pady=(2, 4), sticky="ew")
        tree_frame.grid_rowconfigure(0, weight=1)
        tree_frame.grid_columnconfigure(0, weight=1)
        self.jobs_tree = ttk.Treeview(
            tree_frame, columns=("run_name", "status", "rows", "size_mb", "message"), show="headings", height=8,
        )
        for col, heading, width in (
            ("run_name", "Run Name", 120),
            ("status", "Status", 70),
            ("rows", "Rows", 70),
            ("size_mb", "Size (MB)", 80),
            ("message", "Message", 600),
        ):
            self.jobs_tree.heading(col, text=heading)
            self.jobs_tree.column(col, width=width, stretch=False)
        self.jobs_tree.grid(row=0, column=0, sticky="nsew")
        jobs_vscroll = ttk.Scrollbar(tree_frame, orient="vertical", command=self.jobs_tree.yview)
        jobs_vscroll.grid(row=0, column=1, sticky="ns")
        jobs_hscroll = ttk.Scrollbar(tree_frame, orient="horizontal", command=self.jobs_tree.xview)
        jobs_hscroll.grid(row=1, column=0, sticky="ew")
        self.jobs_tree.config(yscrollcommand=jobs_vscroll.set, xscrollcommand=jobs_hscroll.set)
        self.jobs_tree.bind("<Control-c>", self._on_jobs_tree_copy)
        self.jobs_tree.bind("<Button-3>", self._on_jobs_tree_right_click)

        job_buttons_frame = tk.Frame(frame)
        job_buttons_frame.grid(row=7, column=0, columnspan=3, pady=(4, 8))
        tk.Button(job_buttons_frame, text="Add Job...", command=self._on_add_job).pack(side="left", padx=4)
        tk.Button(job_buttons_frame, text="Remove Selected", command=self._on_remove_selected_job).pack(side="left", padx=4)
        tk.Button(job_buttons_frame, text="Clear Completed", command=self._on_clear_completed_jobs).pack(side="left", padx=4)

        buttons_frame = tk.Frame(frame)
        buttons_frame.grid(row=8, column=0, columnspan=3, pady=(4, 4))
        self.auth_button = tk.Button(buttons_frame, text="Authenticate with gcloud", command=self._on_authenticate)
        self.auth_button.pack(side="left", padx=4)
        self.start_queue_button = tk.Button(buttons_frame, text="Start Queue", command=self._on_start_queue)
        self.start_queue_button.pack(side="left", padx=4)

        self.status_var = tk.StringVar(value="Ready.")
        tk.Label(frame, textvariable=self.status_var, fg="#333333", wraplength=460, justify="left").grid(
            row=9, column=0, columnspan=3, sticky="w", pady=(8, 4)
        )

        self.progress_bar = ttk.Progressbar(frame, orient="horizontal", mode="determinate", maximum=1, value=0)
        self.progress_bar.grid(row=10, column=0, columnspan=3, sticky="ew", pady=(0, 8))

        ttk.Separator(frame, orient="horizontal").grid(row=11, column=0, columnspan=3, sticky="ew", pady=8)
        tk.Button(frame, text="< Back", command=self._on_back).grid(row=12, column=0, sticky="w")

    def _on_browse_destination(self) -> None:
        folder = filedialog.askdirectory(
            parent=self, title="Select Destination Folder",
            initialdir=self.destination_var.get() or str(DEFAULT_SPOOLED_DOWNLOADS_DIR),
        )
        if folder:
            self.destination_var.set(folder)

    def _on_open_spooled_downloads_folder(self) -> None:
        try:
            open_folder(DEFAULT_SPOOLED_DOWNLOADS_DIR)
        except Exception as e:
            messagebox.showerror("Failed to open folder", str(e))

    def _on_back(self) -> None:
        self.destroy()
        from ui.splash_window import SplashWindow
        SplashWindow().mainloop()

    # Opens a real, visible cmd window to run both logins in (same pattern as BigQuerySchemaWindow) - /c
    # (not /k) closes the window automatically once both commands have finished.
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

    # Sets both the gcloud CLI's default project and the ADC quota project (so the bigquery.Client() built
    # from those credentials bills/runs queries against this project too), in a visible cmd window.
    def _on_set_project(self) -> None:
        project = self.project_var.get().strip()
        if not project:
            messagebox.showerror("Missing input", "Please enter a GCP Project ID first.")
            return
        try:
            subprocess.Popen(
                f'start "gcloud project" cmd /c "gcloud config set project {project} '
                f'&& gcloud auth application-default set-quota-project {project}"',
                shell=True,
            )
        except Exception as e:
            messagebox.showerror("Failed to set project", str(e))
            return
        self.status_var.set(f"Opened a command prompt window - setting gcloud project to '{project}'.")

    def _on_add_job(self) -> None:
        existing_names = {job["run_name"] for job in self.jobs}
        dialog = _AddJobDialog(self, existing_names)
        if dialog.result is None:
            return
        run_name, query = dialog.result
        self.jobs.append({
            "run_name": run_name, "query": query, "status": "Pending", "rows": "", "size_mb": "", "message": "",
        })
        self._refresh_jobs_tree()

    def _on_remove_selected_job(self) -> None:
        selected_run_names = {self.jobs_tree.item(iid, "values")[0] for iid in self.jobs_tree.selection()}
        if not selected_run_names:
            return
        still_running = selected_run_names & {job["run_name"] for job in self.jobs if job["status"] == "Running"}
        if still_running:
            messagebox.showerror("Cannot remove", f"Job(s) currently running can't be removed: {', '.join(still_running)}")
            return
        self.jobs = [job for job in self.jobs if job["run_name"] not in selected_run_names]
        self._refresh_jobs_tree()

    def _on_clear_completed_jobs(self) -> None:
        self.jobs = [job for job in self.jobs if job["status"] not in ("Done", "Failed")]
        self._refresh_jobs_tree()

    def _refresh_jobs_tree(self) -> None:
        self.jobs_tree.delete(*self.jobs_tree.get_children())
        for job in self.jobs:
            self.jobs_tree.insert("", "end", iid=job["run_name"], values=(
                job["run_name"], job["status"], job["rows"], job["size_mb"], job["message"],
            ))

    def _copy_to_clipboard(self, text: str) -> None:
        self.clipboard_clear()
        self.clipboard_append(text)

    # Ctrl+C copies every selected row's full values (tab-separated, so e.g. pasting into Excel lines up
    # into columns) - the point is to get a long, right-scrolled-off message out without needing to select
    # text in a widget that doesn't support text selection at all (ttk.Treeview).
    def _on_jobs_tree_copy(self, event=None) -> None:
        selected = self.jobs_tree.selection()
        if not selected:
            return
        lines = ["\t".join(str(v) for v in self.jobs_tree.item(iid, "values")) for iid in selected]
        self._copy_to_clipboard("\n".join(lines))

    def _on_jobs_tree_right_click(self, event) -> None:
        row_id = self.jobs_tree.identify_row(event.y)
        if not row_id:
            return
        self.jobs_tree.selection_set(row_id)
        col_id = self.jobs_tree.identify_column(event.x)
        values = self.jobs_tree.item(row_id, "values")
        col_index = int(col_id.replace("#", "")) - 1
        cell_text = str(values[col_index]) if 0 <= col_index < len(values) else ""

        menu = tk.Menu(self, tearoff=0)
        menu.add_command(label="Copy Cell", command=lambda: self._copy_to_clipboard(cell_text))
        menu.add_command(label="Copy Row", command=lambda: self._copy_to_clipboard("\t".join(str(v) for v in values)))
        menu.tk_popup(event.x_root, event.y_root)

    def _on_start_queue(self) -> None:
        destination = self.destination_var.get().strip()
        project = self.project_var.get().strip() or None
        pending_jobs = [job for job in self.jobs if job["status"] == "Pending"]

        if not destination:
            messagebox.showerror("Missing input", "Please choose a destination folder.")
            return
        if not pending_jobs:
            messagebox.showerror("Nothing to run", "Add at least one job to the queue first.")
            return

        self.start_queue_button.config(state="disabled")
        self.status_var.set(f"Starting queue ({len(pending_jobs)} job(s))...")

        def on_progress(event):
            self.after(0, self._update_progress, event)

        def worker():
            try:
                client = bigquery_spooler.get_client(project)
            except Exception as e:
                self.after(0, self._on_queue_finished, str(e))
                return

            for job in pending_jobs:
                self.after(0, self._mark_job_running, job)
                try:
                    result = bigquery_spooler.download_query_to_csv(
                        job["query"], Path(destination), job["run_name"], client=client, on_progress=on_progress
                    )
                    self.after(0, self._mark_job_done, job, result)
                except Exception as e:
                    self.after(0, self._mark_job_failed, job, str(e))

            self.after(0, self._on_queue_finished, None)

        threading.Thread(target=worker, daemon=True).start()

    def _mark_job_running(self, job: dict) -> None:
        job["status"] = "Running"
        job["message"] = "Running..."
        self._refresh_jobs_tree()
        self.progress_bar["mode"] = "determinate"
        self.progress_bar["maximum"] = 1
        self.progress_bar["value"] = 0
        self.status_var.set(f"Running job '{job['run_name']}'...")

    def _mark_job_done(self, job: dict, result: dict) -> None:
        job["status"] = "Done"
        job["rows"] = result["total_rows"]
        job["size_mb"] = f"{result['total_bytes'] / 1_000_000:.2f}"
        job["message"] = f"Saved to {result['result_csv_path']}"
        self._refresh_jobs_tree()

    def _mark_job_failed(self, job: dict, error: str) -> None:
        job["status"] = "Failed"
        job["message"] = error
        self._refresh_jobs_tree()

    # on_progress fires from the background worker thread, so it's always marshaled onto the UI thread via
    # self.after(0, ...). The canary (COUNT(*)) runs concurrently with the download rather than blocking it,
    # so total_rows_expected may be None for a while - the bar just grows to fit rows_downloaded until a
    # row_count_known event arrives, rather than ever sitting in an indeterminate/pulsing state.
    def _update_progress(self, event: dict) -> None:
        stage = event.get("stage")
        if stage == "row_count_known":
            self.progress_bar["maximum"] = max(event["total_rows_expected"], self.progress_bar["value"], 1)
            return

        if stage == "downloading":
            rows_downloaded = event.get("rows_downloaded", 0)
            total_rows_expected = event.get("total_rows_expected")
            if total_rows_expected is not None:
                self.progress_bar["maximum"] = max(total_rows_expected, rows_downloaded, 1)
            elif rows_downloaded >= self.progress_bar["maximum"]:
                self.progress_bar["maximum"] = rows_downloaded + 1
            self.progress_bar["value"] = rows_downloaded
            self.status_var.set(event["message"])
            return

        if stage in ("collating", "done"):
            self.status_var.set(event["message"])

    def _on_queue_finished(self, fatal_error: str) -> None:
        self.start_queue_button.config(state="normal")
        if fatal_error:
            self.status_var.set(f"Queue aborted: {fatal_error}")
            messagebox.showerror("Queue aborted", fatal_error)
            return

        failed = [job["run_name"] for job in self.jobs if job["status"] == "Failed"]
        done_count = sum(1 for job in self.jobs if job["status"] == "Done")
        self.status_var.set(
            f"Queue finished - {done_count} job(s) done" + (f", {len(failed)} failed: {', '.join(failed)}" if failed else ".")
        )
        try:
            open_folder(Path(self.destination_var.get()))
        except Exception:
            pass

