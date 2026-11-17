"""Main application window (App): dataset selection, settings, run-window configuration, and run launching."""

import threading
import tkinter as tk
from datetime import date, datetime, time, timedelta
from tkinter import messagebox, simpledialog, ttk

from core import config_manager
from core import engine as engine_module
from ui import schema_viewer
from ui import actions_viewer
from parsers import schema_parser
from ui.dag_window import DagWindow
from ui.file_utils import open_folder
from ui.icon import set_window_icon
from ui.step_through_window import StepThroughWindow
from ui.widgets import ClockWidget, CalendarPopup

OUTPUT_COLOR = "#2ca02c"
NONE_COLOR = "#dddddd"


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("The Taylor-Hallum Data Generator Mk4")
        self.resizable(False, False)
        set_window_icon(self)

        menubar = tk.Menu(self)
        self.file_menu = tk.Menu(menubar, tearoff=0)
        self.file_menu.add_command(label="Refresh", command=self._refresh_preview)
        self.file_menu.add_separator()
        self.file_menu.add_command(label="Save Config", command=self._save_config)
        self.file_menu.add_separator()
        self.file_menu.add_command(label="Execute Headless Run", command=self._run_simulation)
        self.file_menu.add_command(label="Execute Interactive Run", command=self._open_step_through_window)
        self.file_menu.add_separator()
        self.file_menu.add_command(label="Open Snapshots Folder", command=self._open_snapshots_folder)
        self.file_menu.add_command(label="Clear Deltas & Snapshots", command=self._clear_deltas_and_snapshots)
        menubar.add_cascade(label="File", menu=self.file_menu)
        self.config(menu=menubar)

        self.start_date: date | None = None
        self.num_days_var = tk.StringVar(value="")
        self.dag_window: DagWindow | None = None

        self.attr_gen_functions_module_var = tk.StringVar()
        self.selection_functions_module_var = tk.StringVar()
        self.seconds_per_time_step_var = tk.StringVar()
        self.schema_path_var = tk.StringVar()
        self.actions_path_var = tk.StringVar()
        self.start_date_var = tk.StringVar()
        self.status_var = tk.StringVar(value="Select a dataset to begin.")

        self._build_dataset_frame()
        self._build_settings_frame()
        self._build_run_window_frame()

        tk.Button(self, text="< Back", command=self._on_back).pack(anchor="w", padx=8, pady=(0, 4))

        tk.Label(self, textvariable=self.status_var, fg="#333333").pack(fill="x", padx=8, pady=(0, 8))

        # Nothing is selected/loaded until the user explicitly picks a dataset - everything starts blank.
        self._refresh_preview()

    # --- layout ---------------------------------------------------------

    def _build_dataset_frame(self) -> None:
        frame = tk.LabelFrame(self, text="Dataset")
        frame.pack(fill="x", padx=8, pady=8)

        tk.Label(frame, text="Config folder:").grid(row=0, column=0, sticky="w", padx=4, pady=4)
        self.dataset_combo = ttk.Combobox(frame, values=config_manager.list_dataset_names(), state="readonly", width=20)
        self.dataset_combo.grid(row=0, column=1, sticky="w", padx=4, pady=4)
        self.dataset_combo.bind("<<ComboboxSelected>>", lambda event: self._on_dataset_selected())
        tk.Button(frame, text="New Dataset...", command=self._on_new_dataset).grid(row=0, column=2, sticky="w", padx=4, pady=4)

    def _build_settings_frame(self) -> None:
        frame = tk.LabelFrame(self, text="Settings (from config/<dataset>/settings.yaml)")
        frame.pack(fill="x", padx=8, pady=(0, 8))

        rows = [
            ("Schema/relationships file:", self.schema_path_var, True),
            ("Actions file:", self.actions_path_var, True),
            ("Attribute-generation module:", self.attr_gen_functions_module_var, False),
            ("Selection functions module:", self.selection_functions_module_var, False),
            ("Seconds per time step:", self.seconds_per_time_step_var, False),
        ]
        for row, (label_text, var, read_only) in enumerate(rows):
            tk.Label(frame, text=label_text).grid(row=row, column=0, sticky="w", padx=4, pady=2)
            if var is self.selection_functions_module_var:
                combo = ttk.Combobox(frame, textvariable=var, width=42, values=config_manager.list_selection_function_modules())
                combo.grid(row=row, column=1, sticky="w", padx=4, pady=2)
            else:
                entry = tk.Entry(frame, textvariable=var, width=45, state="readonly" if read_only else "normal")
                entry.grid(row=row, column=1, sticky="w", padx=4, pady=2)

        schema_row = rows.index(("Schema/relationships file:", self.schema_path_var, True))
        tk.Button(frame, text="View/Edit Schema...", command=self._on_view_edit_schema).grid(row=schema_row, column=2, sticky="w", padx=4, pady=2)

        actions_row = rows.index(("Actions file:", self.actions_path_var, True))
        tk.Button(frame, text="View/Edit Actions...", command=self._on_view_edit_actions).grid(row=actions_row, column=2, sticky="w", padx=4, pady=2)

    def _build_run_window_frame(self) -> None:
        frame = tk.LabelFrame(self, text="Run window")
        frame.pack(fill="x", padx=8, pady=(0, 8))

        top = tk.Frame(frame)
        top.pack(fill="x", padx=4, pady=4)

        tk.Label(top, text="Start date:").grid(row=0, column=0, sticky="w")
        tk.Entry(top, textvariable=self.start_date_var, width=12, state="readonly").grid(row=0, column=1, padx=(4, 4))
        tk.Button(top, text="Pick...", command=self._open_calendar).grid(row=0, column=2)

        tk.Label(top, text="Number of days:").grid(row=0, column=3, sticky="w", padx=(16, 4))
        num_days_spin = tk.Spinbox(top, from_=1, to=366, width=5, textvariable=self.num_days_var, command=self._refresh_preview)
        num_days_spin.grid(row=0, column=4)
        num_days_spin.bind("<KeyRelease>", lambda event: self._refresh_preview())

        clock_frame = tk.Frame(frame)
        clock_frame.pack(pady=4)
        self.clock = ClockWidget(clock_frame, time(0, 0), time(0, 0), checkpoint_times=[], on_change=self._refresh_preview)
        self.clock.pack()

        tk.Label(frame, text="Days in run (colour = whether a checkpoint falls within the run period that day):").pack(anchor="w", padx=4)
        self.days_strip = tk.Frame(frame)
        self.days_strip.pack(fill="x", padx=4, pady=(0, 4))

        legend = tk.Frame(frame)
        legend.pack(anchor="w", padx=4, pady=(0, 4))
        for color, text in ((OUTPUT_COLOR, "output"), (NONE_COLOR, "none")):
            swatch = tk.Label(legend, bg=color, width=2)
            swatch.pack(side="left", padx=(0, 2))
            tk.Label(legend, text=text).pack(side="left", padx=(0, 8))

    # --- behaviour --------------------------------------------------------

    def _on_dataset_selected(self) -> None:
        dataset_name = self.dataset_combo.get()
        if not dataset_name:
            return

        config_manager.ensure_save_data_dirs(dataset_name)

        # Copy this dataset's stored settings into master_config.yaml, then load the GUI from that file -
        # master_config.yaml is always the single source of truth for what's currently loaded in the GUI.
        dataset_settings = config_manager.load_dataset_settings(dataset_name)
        daily_windows = config_manager.build_daily_windows(
            start_date=dataset_settings["start_date"],
            num_days=dataset_settings["num_days"],
            daily_start_time=dataset_settings["daily_start_time"],
            daily_end_time=dataset_settings["daily_end_time"],
        )
        config_manager.write_master_config(dataset_name, dataset_settings, daily_windows)

        loaded = config_manager.load_master_config_for_gui()
        self.schema_path_var.set(loaded["schema_entity_relationships_filepath"])
        self.actions_path_var.set(loaded["actions_config"])
        self.attr_gen_functions_module_var.set(loaded["attr_gen_functions_module"])
        self.selection_functions_module_var.set(loaded["selection_functions_module"])
        self.seconds_per_time_step_var.set(str(loaded["seconds_per_time_step"]))
        self.num_days_var.set(str(loaded["num_days"]))
        self.clock.set_run_period(loaded["daily_start_time"], loaded["daily_end_time"])
        self.clock.set_checkpoint_times(loaded["checkpoint_times"])
        self._set_start_date(loaded["start_date"])
        self.status_var.set(f"Loaded '{dataset_name}' into config/master_config.yaml.")

    def _on_new_dataset(self) -> None:
        dataset_name = simpledialog.askstring("New Dataset", "Name for the new config/<dataset>/ folder:", parent=self)
        if not dataset_name:
            return
        try:
            config_manager.create_dataset(dataset_name)
        except Exception as e:
            messagebox.showerror("Failed to create dataset", str(e))
            return

        self.dataset_combo.config(values=config_manager.list_dataset_names())
        self.dataset_combo.set(dataset_name)
        self._on_dataset_selected()
        self.status_var.set(f"Created new dataset '{dataset_name}'. Edit its schema, then Save Config when ready.")

    def _on_view_edit_schema(self) -> None:
        schema_path_str = self.schema_path_var.get()
        if not schema_path_str:
            messagebox.showerror("No dataset", "Please select a dataset first.")
            return
        schema_viewer.SchemaViewerWindow(self, config_manager.BASE_PATH / schema_path_str)

    def _on_view_edit_actions(self) -> None:
        actions_path_str = self.actions_path_var.get()
        schema_path_str = self.schema_path_var.get()
        if not actions_path_str or not schema_path_str:
            messagebox.showerror("No dataset", "Please select a dataset first.")
            return
        actions_viewer.ActionsViewerWindow(self, config_manager.BASE_PATH / actions_path_str, config_manager.BASE_PATH / schema_path_str)

    def _open_calendar(self) -> None:
        CalendarPopup(self, self.start_date or date.today(), self._set_start_date)

    def _set_start_date(self, new_date: date) -> None:
        self.start_date = new_date
        self.start_date_var.set(new_date.strftime("%Y-%m-%d"))
        self._refresh_preview()

    def _refresh_preview(self) -> None:
        self._render_days_strip()

    def _render_days_strip(self) -> None:
        for widget in self.days_strip.winfo_children():
            widget.destroy()

        if self.start_date is None:
            tk.Label(self.days_strip, text="Select a dataset to configure the run window.", fg="#666666").pack(anchor="w")
            return

        daily_start_time, daily_end_time = self.clock.start_time, self.clock.end_time
        if daily_end_time <= daily_start_time:
            tk.Label(self.days_strip, text="Daily end time must be after daily start time.", fg="red").pack(anchor="w")
            return

        has_output = any(daily_start_time <= checkpoint <= daily_end_time for checkpoint in self.clock.checkpoint_times)
        color = OUTPUT_COLOR if has_output else NONE_COLOR

        num_days = max(1, self._parse_num_days())
        columns = min(14, num_days)
        for day_offset in range(num_days):
            day = self.start_date + timedelta(days=day_offset)
            cell = tk.Label(self.days_strip, text=day.strftime("%d %b"), bg=color, width=8, relief="ridge")
            cell.grid(row=day_offset // columns, column=day_offset % columns, padx=1, pady=1)

    def _parse_num_days(self) -> int:
        try:
            return int(self.num_days_var.get())
        except ValueError:
            return 1

    def _collect_settings(self) -> dict:
        return {
            "attr_gen_functions_module": self.attr_gen_functions_module_var.get(),
            "selection_functions_module": self.selection_functions_module_var.get(),
            "seconds_per_time_step": int(self.seconds_per_time_step_var.get()),
            "checkpoint_times": self.clock.checkpoint_times,
            "daily_start_time": self.clock.start_time,
            "daily_end_time": self.clock.end_time,
            "start_date": self.start_date,
            "num_days": self._parse_num_days(),
        }

    def _build_daily_windows(self) -> list[tuple[datetime, datetime]]:
        if self.start_date is None:
            raise ValueError("Please select a dataset and a start date first.")
        return config_manager.build_daily_windows(
            start_date=self.start_date,
            num_days=self._parse_num_days(),
            daily_start_time=self.clock.start_time,
            daily_end_time=self.clock.end_time,
        )

    def _save_config(self) -> bool:
        dataset_name = self.dataset_combo.get()
        if not dataset_name:
            messagebox.showerror("No dataset", "Please select a dataset first.")
            return False
        try:
            settings = self._collect_settings()
            daily_windows = self._build_daily_windows()
        except Exception as e:
            messagebox.showerror("Invalid configuration", str(e))
            return False

        config_manager.write_master_config(dataset_name, settings, daily_windows)
        config_manager.save_dataset_settings(dataset_name, settings)
        self.status_var.set(f"Saved '{dataset_name}' settings and config/master_config.yaml ({len(daily_windows)} day(s), {len(settings['checkpoint_times'])} checkpoint(s)).")
        return True

    def _build_engine_from_master_config(self):
        attr_gen_functions = engine_module.load_attr_gen_functions_module_from_master_config()
        selection_functions = engine_module.load_selection_functions_module_from_master_config()
        engine_kwargs = engine_module.load_engine_kwargs_from_master_config()
        return engine_module.Engine(attr_gen_functions=attr_gen_functions, selection_functions=selection_functions, **engine_kwargs)

    def _open_dag_window(self, sim_engine) -> DagWindow:
        # Replace any previous DAG window (e.g. from an earlier run) rather than accumulating stale ones.
        if self.dag_window is not None and self.dag_window.winfo_exists():
            self.dag_window.destroy()
        self.dag_window = DagWindow(self, sim_engine.get_table_dependency_dag(), self._get_independent_qualifier_tables())
        return self.dag_window

    def _get_independent_qualifier_tables(self) -> set:
        schema_path_str = self.schema_path_var.get()
        if not schema_path_str:
            return set()
        try:
            tables = schema_parser.load_schema(config_manager.BASE_PATH / schema_path_str)["tables"]
        except Exception:
            return set()
        return {name for name, info in tables.items() if info.get("independent_qualifiers")}

    def _run_simulation(self) -> None:
        if not self._save_config():
            return
        try:
            # Built on the main thread (Tkinter windows must be created here) - only run_fuzzing() itself
            # (which never touches Tkinter) is offloaded to a background thread below.
            sim_engine = self._build_engine_from_master_config()
        except Exception as e:
            messagebox.showerror("Failed to start simulation", str(e))
            return

        self._open_dag_window(sim_engine)

        self.file_menu.entryconfig("Execute Headless Run", state="disabled")
        self.status_var.set("Running simulation... see console for progress.")

        def worker():
            try:
                sim_engine.run_fuzzing()
                self.after(0, self._on_run_finished, True, "Simulation complete.")
            except Exception as e:
                self.after(0, self._on_run_finished, False, f"Simulation failed: {e}")

        threading.Thread(target=worker, daemon=True).start()

    def _on_run_finished(self, success: bool, message: str) -> None:
        self.file_menu.entryconfig("Execute Headless Run", state="normal")
        self.status_var.set(message)
        if not success:
            messagebox.showerror("Simulation failed", message)

    def _open_step_through_window(self) -> None:
        if not self._save_config():
            return
        try:
            sim_engine = self._build_engine_from_master_config()
            sim_engine.clear_deltas_and_snapshots(sim_engine.dataset_name)
        except Exception as e:
            messagebox.showerror("Failed to start step-through run", str(e))
            return
        dag_window = self._open_dag_window(sim_engine)
        StepThroughWindow(self, sim_engine, dag_window=dag_window, dataset_name=self.dataset_combo.get())

    def _open_snapshots_folder(self) -> None:
        dataset_name = self.dataset_combo.get()
        if not dataset_name:
            messagebox.showerror("No dataset", "Please select a dataset first.")
            return
        try:
            open_folder(config_manager.BASE_PATH / "generated_data_files" / dataset_name)
        except Exception as e:
            messagebox.showerror("Failed to open snapshots folder", str(e))

    def _clear_deltas_and_snapshots(self) -> None:
        dataset_name = self.dataset_combo.get()
        if not dataset_name:
            messagebox.showerror("No dataset", "Please select a dataset first.")
            return
        if not messagebox.askyesno("Clear output", f"Delete all contents of generated_data_files/{dataset_name}/?"):
            return
        try:
            engine_module.Engine.clear_deltas_and_snapshots(dataset_name)
        except Exception as e:
            messagebox.showerror("Failed to clear output", str(e))
            return
        self.status_var.set(f"Cleared generated_data_files/{dataset_name}/.")

    def _on_back(self) -> None:
        self.destroy()
        from ui.splash_window import SplashWindow
        SplashWindow().mainloop()
