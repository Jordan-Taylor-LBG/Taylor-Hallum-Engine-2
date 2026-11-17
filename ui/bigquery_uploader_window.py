"""
BigQueryUploaderWindow: queues up multiple CSV-to-BigQuery-table upload jobs, validating each CSV's
columns against its target table's schema before loading (see core/bigquery_uploader.py). GCP project is
shared across the whole queue; per job, the user picks an insert method (SQL INSERT or streaming buffer)
and can optionally truncate the target table first. Queues can be saved/loaded as JSON so a configured
batch of uploads can be re-run quickly later. Opened from the splash screen.
"""

import json
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
import subprocess

from core import bigquery_uploader
from core import config_manager
from ui.file_utils import open_folder
from ui.icon import load_icon_image, set_window_icon

DEFAULT_UPLOAD_CONFIGS_DIR = config_manager.SAVE_DATA_DIR / "upload_configs"
GENERATED_DATA_FILES_DIR = config_manager.BASE_PATH / "generated_data_files"

_METHOD_LABELS = {"sql": "SQL Insert", "stream": "Stream Buffer"}


class _AddUploadJobDialog(tk.Toplevel):
    """Modal dialog collecting one job's name, source CSV, target table, insert method, and truncate
    flag. Sets self.result to a job dict on OK, or leaves it None if cancelled."""

    def __init__(self, parent: tk.Tk, existing_names: set):
        super().__init__(parent)
        self.title("Add Upload Job")
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()
        self.result = None
        self._existing_names = existing_names

        frame = tk.Frame(self, padx=16, pady=16)
        frame.pack()

        self.job_name_var = tk.StringVar()
        self.csv_path_var = tk.StringVar()
        self.target_table_var = tk.StringVar()
        self.method_var = tk.StringVar(value="sql")
        self.truncate_var = tk.BooleanVar(value=False)

        tk.Label(frame, text="Job name:").grid(row=0, column=0, sticky="w", pady=2)
        tk.Entry(frame, textvariable=self.job_name_var, width=50).grid(row=0, column=1, columnspan=2, sticky="w", pady=2)

        tk.Label(frame, text="Source CSV:").grid(row=1, column=0, sticky="w", pady=2)
        tk.Entry(frame, textvariable=self.csv_path_var, width=50).grid(row=1, column=1, sticky="w", pady=2)
        tk.Button(frame, text="Browse...", command=self._on_browse_csv).grid(row=1, column=2, sticky="w", padx=(4, 0))

        tk.Label(frame, text="Target table (project.dataset.table):").grid(row=2, column=0, columnspan=3, sticky="w", pady=(8, 2))
        tk.Entry(frame, textvariable=self.target_table_var, width=50).grid(row=3, column=0, columnspan=3, sticky="w", pady=2)

        tk.Label(frame, text="Insert method:").grid(row=4, column=0, columnspan=3, sticky="w", pady=(8, 2))
        tk.Radiobutton(
            frame, text="1. SQL Insert - default, for small datasets", variable=self.method_var, value="sql",
        ).grid(row=5, column=0, columnspan=3, sticky="w")
        tk.Radiobutton(
            frame, text="2. Stream Buffer - for large datasets", variable=self.method_var, value="stream",
        ).grid(row=6, column=0, columnspan=3, sticky="w")

        tk.Checkbutton(
            frame, text="Truncate target table before upload", variable=self.truncate_var,
        ).grid(row=7, column=0, columnspan=3, sticky="w", pady=(8, 0))
        tk.Label(
            frame, text="\u26a0 This permanently deletes ALL existing rows in the target table first - cannot be undone.",
            fg="#b00000", wraplength=380, justify="left",
        ).grid(row=8, column=0, columnspan=3, sticky="w")

        buttons_frame = tk.Frame(frame)
        buttons_frame.grid(row=9, column=0, columnspan=3, pady=(12, 0))
        tk.Button(buttons_frame, text="OK", command=self._on_ok, width=10).pack(side="left", padx=4)
        tk.Button(buttons_frame, text="Cancel", command=self._on_cancel, width=10).pack(side="left", padx=4)

        self.protocol("WM_DELETE_WINDOW", self._on_cancel)
        self.wait_window(self)

    def _on_browse_csv(self) -> None:
        path = filedialog.askopenfilename(
            parent=self, title="Select Source CSV", filetypes=[("CSV files", "*.csv"), ("All files", "*.*")],
        )
        if path:
            self.csv_path_var.set(path)

    def _on_ok(self) -> None:
        job_name = self.job_name_var.get().strip()
        csv_path = self.csv_path_var.get().strip()
        target_table = self.target_table_var.get().strip()
        method = self.method_var.get()
        truncate = self.truncate_var.get()

        if not job_name:
            messagebox.showerror("Missing input", "Please enter a job name.", parent=self)
            return
        if job_name in self._existing_names:
            messagebox.showerror("Duplicate job name", f"A job named '{job_name}' is already queued.", parent=self)
            return
        if not csv_path:
            messagebox.showerror("Missing input", "Please choose a source CSV.", parent=self)
            return
        if not Path(csv_path).exists():
            messagebox.showerror("File not found", f"CSV file does not exist:\n{csv_path}", parent=self)
            return
        if target_table.count(".") < 2:
            messagebox.showerror("Missing input", "Please enter a target table as project.dataset.table.", parent=self)
            return

        if method == "sql" and Path(csv_path).stat().st_size > bigquery_uploader.ADVISORY_STREAM_THRESHOLD_BYTES:
            messagebox.showwarning(
                "Large file",
                "This CSV is over 100MB - Stream Buffer is recommended for large datasets, "
                "but SQL Insert will still work if you'd rather continue with it.",
                parent=self,
            )

        self.result = {
            "job_name": job_name, "csv_path": csv_path, "target_table": target_table,
            "method": method, "truncate": truncate, "status": "Pending", "rows": "", "message": "",
        }
        self.destroy()

    def _on_cancel(self) -> None:
        self.result = None
        self.destroy()


class _BulkUploadWizardDialog(tk.Toplevel):
    """
    Bulk upload configurator: pick several CSVs (Ctrl-click in the file dialog, which defaults to
    generated_data_files/), give a BigQuery project + dataset, and this resolves each file to a same-named
    (or <name>_view) table in that dataset - see core.bigquery_uploader.resolve_bulk_upload_jobs(). Sets
    self.result to a list of ready-to-queue job dicts once every file resolves cleanly (no unmatched files,
    no job-name collisions with the existing queue); otherwise reports the problem and lets the user retry
    or cancel. Leaves self.result None if cancelled, or if no files were selected in the first place.
    """

    def __init__(self, parent: tk.Tk, existing_names: set, get_client_fn):
        super().__init__(parent)
        self.title("Bulk Upload Configurator")
        self.resizable(False, False)
        self.transient(parent)
        self.result = None
        self._existing_names = existing_names
        self._get_client_fn = get_client_fn

        # Hidden until we know files were actually picked - no point showing an empty wizard window behind
        # the (modal) file-selection dialog.
        self.withdraw()
        selected = filedialog.askopenfilenames(
            parent=parent, title="Select Source CSV Files (Ctrl-click to select multiple)",
            initialdir=str(GENERATED_DATA_FILES_DIR) if GENERATED_DATA_FILES_DIR.exists() else None,
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")],
        )
        if not selected:
            self.destroy()
            return
        self._file_paths = [Path(p) for p in selected]
        self.deiconify()
        self.grab_set()

        frame = tk.Frame(self, padx=16, pady=16)
        frame.pack()

        tk.Label(frame, text=f"{len(self._file_paths)} file(s) selected:", font=("Segoe UI", 10, "bold")).grid(
            row=0, column=0, columnspan=2, sticky="w"
        )
        files_list = tk.Listbox(frame, width=70, height=min(8, len(self._file_paths)))
        for file_path in self._file_paths:
            files_list.insert("end", file_path.name)
        files_list.config(state="disabled")
        files_list.grid(row=1, column=0, columnspan=2, pady=(2, 8), sticky="w")

        self.project_var = tk.StringVar()
        self.dataset_var = tk.StringVar()
        tk.Label(frame, text="GCP Project:").grid(row=2, column=0, sticky="w", pady=2)
        tk.Entry(frame, textvariable=self.project_var, width=40).grid(row=2, column=1, sticky="w", pady=2)
        tk.Label(frame, text="BigQuery Dataset:").grid(row=3, column=0, sticky="w", pady=2)
        tk.Entry(frame, textvariable=self.dataset_var, width=40).grid(row=3, column=1, sticky="w", pady=2)

        self.method_var = tk.StringVar(value="sql")
        tk.Label(frame, text="Insert method (applied to every matched job):").grid(
            row=4, column=0, columnspan=2, sticky="w", pady=(8, 2)
        )
        tk.Radiobutton(
            frame, text="1. SQL Insert - default, for small datasets", variable=self.method_var, value="sql",
        ).grid(row=5, column=0, columnspan=2, sticky="w")
        tk.Radiobutton(
            frame, text="2. Stream Buffer - for large datasets", variable=self.method_var, value="stream",
        ).grid(row=6, column=0, columnspan=2, sticky="w")

        self.truncate_var = tk.BooleanVar(value=False)
        tk.Checkbutton(
            frame, text="Truncate target tables before upload", variable=self.truncate_var,
        ).grid(row=7, column=0, columnspan=2, sticky="w", pady=(8, 0))
        tk.Label(
            frame, text="\u26a0 This permanently deletes ALL existing rows in EVERY matched table first - cannot be undone.",
            fg="#b00000", wraplength=420, justify="left",
        ).grid(row=8, column=0, columnspan=2, sticky="w")

        self.status_var = tk.StringVar(value="")
        tk.Label(frame, textvariable=self.status_var, fg="#333333", wraplength=460, justify="left").grid(
            row=9, column=0, columnspan=2, sticky="w", pady=(8, 4)
        )

        buttons_frame = tk.Frame(frame)
        buttons_frame.grid(row=10, column=0, columnspan=2, pady=(8, 0))
        self.resolve_button = tk.Button(buttons_frame, text="Resolve + Add to Queue", command=self._on_resolve, width=22)
        self.resolve_button.pack(side="left", padx=4)
        tk.Button(buttons_frame, text="Cancel", command=self._on_cancel, width=10).pack(side="left", padx=4)

        self.protocol("WM_DELETE_WINDOW", self._on_cancel)
        self.wait_window(self)

    def _on_resolve(self) -> None:
        project = self.project_var.get().strip()
        dataset = self.dataset_var.get().strip()
        if not project or not dataset:
            messagebox.showerror("Missing input", "Please enter both a GCP Project and a BigQuery Dataset.", parent=self)
            return

        self.resolve_button.config(state="disabled")
        self.status_var.set("Authenticating...")

        def on_progress(event):
            self.after(0, self.status_var.set, event["message"])

        def worker():
            try:
                client = self._get_client_fn(project)
                jobs, unmatched_stems = bigquery_uploader.resolve_bulk_upload_jobs(
                    project, dataset, self._file_paths, method=self.method_var.get(), truncate=self.truncate_var.get(),
                    on_progress=on_progress, client=client,
                )
                self.after(0, self._on_resolve_finished, True, (jobs, unmatched_stems))
            except Exception as e:
                self.after(0, self._on_resolve_finished, False, str(e))

        threading.Thread(target=worker, daemon=True).start()

    def _on_resolve_finished(self, success: bool, payload) -> None:
        self.resolve_button.config(state="normal")
        if not success:
            self.status_var.set("")
            messagebox.showerror("Failed to resolve tables", str(payload), parent=self)
            return

        jobs, unmatched_stems = payload
        colliding_names = {job["job_name"] for job in jobs} & self._existing_names
        if unmatched_stems or colliding_names:
            problems = []
            if unmatched_stems:
                problems.append(f"No matching table (or <name>_view) found for: {', '.join(unmatched_stems)}")
            if colliding_names:
                problems.append(f"Job name(s) already in the queue: {', '.join(colliding_names)}")
            self.status_var.set("Not added - see details.")
            messagebox.showerror("Could not bulk-configure every file", "\n\n".join(problems), parent=self)
            return

        self.result = jobs
        self.destroy()

    def _on_cancel(self) -> None:
        self.result = None
        self.destroy()


class BigQueryUploaderWindow(tk.Tk):
    """
    Standalone window (its own root, like the splash-launched BigQuerySpoolerWindow) for queuing up
    several CSV-to-BigQuery-table upload jobs, authenticating with gcloud, and running the whole queue.
    Has its own "Back" button, returning to the splash screen.
    """

    def __init__(self):
        super().__init__()
        self.title("BigQuery Uploader")
        self.resizable(False, False)
        set_window_icon(self)

        menu_bar = tk.Menu(self)
        file_menu = tk.Menu(menu_bar, tearoff=False)
        file_menu.add_command(label="Bulk Upload Configurator...", command=self._on_bulk_upload_configurator)
        file_menu.add_command(label="Save Queue...", command=self._on_save_queue)
        file_menu.add_command(label="Load Queue...", command=self._on_load_queue)
        file_menu.add_separator()
        file_menu.add_command(label="Open Upload Configs Folder", command=self._on_open_upload_configs_folder)
        menu_bar.add_cascade(label="File", menu=file_menu)
        self.config(menu=menu_bar)

        self.jobs = []  # each: {"job_name", "csv_path", "target_table", "method", "truncate", "status", "rows", "message"}
        # Cached per-project bigquery.Client - credential/ADC resolution is often the slow part of any
        # BigQuery call, so every operation in this window (bulk wizard, Start Queue) reuses one client
        # per project rather than re-authenticating from scratch each time.
        self._client = None
        self._client_project = None

        frame = tk.Frame(self, padx=16, pady=16)
        frame.pack()

        splash_icon = load_icon_image(subsample=8)
        if splash_icon is not None:
            self._icon_ref = splash_icon
            tk.Label(frame, image=splash_icon).grid(row=0, column=0, columnspan=3, pady=(0, 8))

        tk.Label(frame, text="BigQuery Uploader", font=("Segoe UI", 12, "bold")).grid(row=1, column=0, columnspan=3, pady=(0, 12))

        self.project_var = tk.StringVar()
        tk.Label(frame, text="GCP Project:").grid(row=2, column=0, sticky="w", pady=2)
        tk.Entry(frame, textvariable=self.project_var, width=50).grid(row=2, column=1, sticky="w", pady=2)
        tk.Button(frame, text="Set as gcloud Project", command=self._on_set_project).grid(row=2, column=2, sticky="w", padx=(4, 0))

        ttk.Separator(frame, orient="horizontal").grid(row=3, column=0, columnspan=3, sticky="ew", pady=8)

        tk.Label(frame, text="Job queue:").grid(row=4, column=0, columnspan=3, sticky="w")
        tree_frame = tk.Frame(frame)
        tree_frame.grid(row=5, column=0, columnspan=3, pady=(2, 4), sticky="ew")
        tree_frame.grid_rowconfigure(0, weight=1)
        tree_frame.grid_columnconfigure(0, weight=1)
        self.jobs_tree = ttk.Treeview(
            tree_frame, columns=("job_name", "target_table", "method", "truncate", "status", "rows", "message"),
            show="headings", height=8,
        )
        for col, heading, width in (
            ("job_name", "Job Name", 100),
            ("target_table", "Target Table", 160),
            ("method", "Method", 90),
            ("truncate", "Truncate", 65),
            ("status", "Status", 70),
            ("rows", "Rows", 60),
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
        job_buttons_frame.grid(row=6, column=0, columnspan=3, pady=(4, 8))
        tk.Button(job_buttons_frame, text="Add Job...", command=self._on_add_job).pack(side="left", padx=4)
        tk.Button(job_buttons_frame, text="Remove Selected", command=self._on_remove_selected_job).pack(side="left", padx=4)
        tk.Button(job_buttons_frame, text="Clear Completed", command=self._on_clear_completed_jobs).pack(side="left", padx=4)

        buttons_frame = tk.Frame(frame)
        buttons_frame.grid(row=7, column=0, columnspan=3, pady=(4, 4))
        self.auth_button = tk.Button(buttons_frame, text="Authenticate with gcloud", command=self._on_authenticate)
        self.auth_button.pack(side="left", padx=4)
        self.start_queue_button = tk.Button(buttons_frame, text="Start Queue", command=self._on_start_queue)
        self.start_queue_button.pack(side="left", padx=4)

        self.status_var = tk.StringVar(value="Ready.")
        tk.Label(frame, textvariable=self.status_var, fg="#333333", wraplength=460, justify="left").grid(
            row=8, column=0, columnspan=3, sticky="w", pady=(8, 4)
        )

        self.progress_bar = ttk.Progressbar(frame, orient="horizontal", mode="determinate", maximum=1, value=0)
        self.progress_bar.grid(row=9, column=0, columnspan=3, sticky="ew", pady=(0, 8))

        ttk.Separator(frame, orient="horizontal").grid(row=10, column=0, columnspan=3, sticky="ew", pady=8)
        tk.Button(frame, text="< Back", command=self._on_back).grid(row=11, column=0, sticky="w")

    def _on_open_upload_configs_folder(self) -> None:
        try:
            DEFAULT_UPLOAD_CONFIGS_DIR.mkdir(parents=True, exist_ok=True)
            open_folder(DEFAULT_UPLOAD_CONFIGS_DIR)
        except Exception as e:
            messagebox.showerror("Failed to open folder", str(e))

    def _on_back(self) -> None:
        self.destroy()
        from ui.splash_window import SplashWindow
        SplashWindow().mainloop()

    # Opens a real, visible cmd window to run both logins in (same pattern as BigQuerySpoolerWindow) - /c
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
        existing_names = {job["job_name"] for job in self.jobs}
        dialog = _AddUploadJobDialog(self, existing_names)
        if dialog.result is None:
            return
        self.jobs.append(dialog.result)
        self._refresh_jobs_tree()

    def _get_cached_client(self, project):
        if self._client is None or self._client_project != project:
            self._client = bigquery_uploader.get_client(project)
            self._client_project = project
        return self._client

    def _on_bulk_upload_configurator(self) -> None:
        existing_names = {job["job_name"] for job in self.jobs}
        dialog = _BulkUploadWizardDialog(self, existing_names, self._get_cached_client)
        if not dialog.result:
            return
        self.jobs.extend(dialog.result)
        self._refresh_jobs_tree()
        self.status_var.set(f"Bulk-configured {len(dialog.result)} job(s) from the wizard.")

    def _on_remove_selected_job(self) -> None:
        selected_job_names = {self.jobs_tree.item(iid, "values")[0] for iid in self.jobs_tree.selection()}
        if not selected_job_names:
            return
        still_running = selected_job_names & {job["job_name"] for job in self.jobs if job["status"] == "Running"}
        if still_running:
            messagebox.showerror("Cannot remove", f"Job(s) currently running can't be removed: {', '.join(still_running)}")
            return
        self.jobs = [job for job in self.jobs if job["job_name"] not in selected_job_names]
        self._refresh_jobs_tree()

    def _on_clear_completed_jobs(self) -> None:
        self.jobs = [job for job in self.jobs if job["status"] not in ("Done", "Failed")]
        self._refresh_jobs_tree()

    def _refresh_jobs_tree(self) -> None:
        self.jobs_tree.delete(*self.jobs_tree.get_children())
        for job in self.jobs:
            self.jobs_tree.insert("", "end", iid=job["job_name"], values=(
                job["job_name"], job["target_table"], _METHOD_LABELS.get(job["method"], job["method"]),
                "Yes" if job["truncate"] else "No", job["status"], job["rows"], job["message"],
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

    def _on_save_queue(self) -> None:
        if not self.jobs:
            messagebox.showerror("Nothing to save", "Add at least one job first.")
            return
        DEFAULT_UPLOAD_CONFIGS_DIR.mkdir(parents=True, exist_ok=True)
        path = filedialog.asksaveasfilename(
            parent=self, title="Save Upload Queue", defaultextension=".json",
            initialdir=str(DEFAULT_UPLOAD_CONFIGS_DIR), filetypes=[("JSON files", "*.json")],
        )
        if not path:
            return
        data = {
            "project": self.project_var.get().strip(),
            "jobs": [
                {
                    "job_name": job["job_name"], "csv_path": job["csv_path"], "target_table": job["target_table"],
                    "method": job["method"], "truncate": job["truncate"],
                }
                for job in self.jobs
            ],
        }
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            messagebox.showerror("Failed to save queue", str(e))
            return
        self.status_var.set(f"Saved queue to {path}.")

    def _on_load_queue(self) -> None:
        DEFAULT_UPLOAD_CONFIGS_DIR.mkdir(parents=True, exist_ok=True)
        path = filedialog.askopenfilename(
            parent=self, title="Load Upload Queue",
            initialdir=str(DEFAULT_UPLOAD_CONFIGS_DIR), filetypes=[("JSON files", "*.json")],
        )
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            messagebox.showerror("Failed to load queue", str(e))
            return

        if data.get("project"):
            self.project_var.set(data["project"])

        existing_names = {job["job_name"] for job in self.jobs}
        added = 0
        for job_data in data.get("jobs", []):
            job_name = job_data.get("job_name", "")
            if not job_name or job_name in existing_names:
                continue
            self.jobs.append({
                "job_name": job_name, "csv_path": job_data.get("csv_path", ""),
                "target_table": job_data.get("target_table", ""), "method": job_data.get("method", "sql"),
                "truncate": bool(job_data.get("truncate", False)), "status": "Pending", "rows": "", "message": "",
            })
            existing_names.add(job_name)
            added += 1
        self._refresh_jobs_tree()
        self.status_var.set(f"Loaded {added} job(s) from {path}.")

    def _on_start_queue(self) -> None:
        project = self.project_var.get().strip() or None
        pending_jobs = [job for job in self.jobs if job["status"] == "Pending"]

        if not pending_jobs:
            messagebox.showerror("Nothing to run", "Add at least one job to the queue first.")
            return

        truncating_jobs = [job for job in pending_jobs if job["truncate"]]
        if truncating_jobs:
            names = ", ".join(f"{job['job_name']} ({job['target_table']})" for job in truncating_jobs)
            if not messagebox.askyesno(
                "Confirm truncate",
                f"This will PERMANENTLY DELETE all existing rows in the following target table(s) before "
                f"uploading - this cannot be undone:\n\n{names}\n\nContinue?",
                icon="warning",
            ):
                return

        self.start_queue_button.config(state="disabled")
        self.status_var.set(f"Starting queue ({len(pending_jobs)} job(s))...")

        def on_progress(event):
            self.after(0, self._update_progress, event)

        def worker():
            try:
                client = self._get_cached_client(project)
            except Exception as e:
                self.after(0, self._on_queue_finished, str(e))
                return

            for job in pending_jobs:
                self.after(0, self._mark_job_running, job)
                try:
                    result = bigquery_uploader.upload_job(
                        client, job["csv_path"], job["target_table"], job["method"],
                        truncate=job["truncate"], on_progress=on_progress,
                    )
                    self.after(0, self._mark_job_done, job, result)
                except Exception as e:
                    self.after(0, self._mark_job_failed, job, str(e))

            self.after(0, self._on_queue_finished, None)

        threading.Thread(target=worker, daemon=True).start()

    def _mark_job_running(self, job: dict) -> None:
        job["status"] = "Running"
        job["message"] = "Starting..."
        self._refresh_jobs_tree()
        self.progress_bar["maximum"] = 1
        self.progress_bar["value"] = 0
        self.status_var.set(f"Running job '{job['job_name']}'...")

    def _mark_job_done(self, job: dict, result: dict) -> None:
        job["status"] = "Done"
        job["rows"] = result["rows_uploaded"]
        job["message"] = f"Uploaded to {result['table_ref']} via {_METHOD_LABELS.get(result['method'], result['method'])}."
        self._refresh_jobs_tree()

    def _mark_job_failed(self, job: dict, error: str) -> None:
        job["status"] = "Failed"
        job["message"] = error
        self._refresh_jobs_tree()

    # on_progress fires from the background worker thread, so it's always marshaled onto the UI thread via
    # self.after(0, ...).
    def _update_progress(self, event: dict) -> None:
        stage = event.get("stage")
        if stage in ("validating", "truncating", "done"):
            self.status_var.set(event["message"])
            return

        if stage == "uploading":
            rows_uploaded = event.get("rows_uploaded", 0)
            total_rows = event.get("total_rows", 0)
            self.progress_bar["maximum"] = max(total_rows, rows_uploaded, 1)
            self.progress_bar["value"] = rows_uploaded
            self.status_var.set(event["message"])

    def _on_queue_finished(self, fatal_error: str) -> None:
        self.start_queue_button.config(state="normal")
        if fatal_error:
            self.status_var.set(f"Queue aborted: {fatal_error}")
            messagebox.showerror("Queue aborted", fatal_error)
            return

        failed = [job["job_name"] for job in self.jobs if job["status"] == "Failed"]
        done_count = sum(1 for job in self.jobs if job["status"] == "Done")
        self.status_var.set(
            f"Queue finished - {done_count} job(s) done" + (f", {len(failed)} failed: {', '.join(failed)}" if failed else ".")
        )
