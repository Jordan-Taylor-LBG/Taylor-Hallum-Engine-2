"""
'Jordan's Data Warehouse' (JDWWindow) - a lightweight, BigQuery-style SQL explorer over the engine's live
tables, opened from StepThroughWindow's File menu.
"""

import os
import shutil
import subprocess
import sys
import tempfile
import tkinter as tk
import uuid
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk

import pandas as pd

from core import config_manager
from core import csv_import
from core import sql_macro_helpers
from ui.file_utils import open_folder


class JDWWindow(tk.Toplevel):
    """
    "Jordan's Data Warehouse" - a lightweight, BigQuery-style SQL explorer. Usually opened (with a live
    sim_engine) from StepThroughWindow's File menu, but can also run standalone (sim_engine=None, launched
    from the splash screen against a chosen save_data/<session_name>/ "JDW session") purely over previously
    saved/imported parquets. Single-click a table on the left to preview it, or write/run any DuckDB SQL
    against the same tables (see core/sql_macro_helpers.query()) - INSERT/UPDATE/DELETE take effect on the
    live engine tables (if any), same as a macro.
    """

    # How often the Saved Parquets list re-scans save_data/<session>/saved_tables/ for new/removed files.
    PARQUET_REFRESH_INTERVAL_MS = 3000

    # Wide enough that most columns are readable without resizing - scrolling sideways is fine.
    RESULT_COLUMN_WIDTH = 75
    # Hard floor so columns never get squeezed below this - stretch is disabled on each column (see
    # _display_results()) so the horizontal scrollbar kicks in instead of Tk silently shrinking columns.
    RESULT_COLUMN_MIN_WIDTH = 30

    # pandas' own dtype names (e.g. "object" for any string column) aren't meaningful to end users.
    _FRIENDLY_DTYPE_NAMES = {
        "object": "string",
        "int64": "integer",
        "int32": "integer",
        "float64": "float",
        "float32": "float",
        "bool": "boolean",
        "datetime64[ns]": "datetime",
    }

    @classmethod
    def _friendly_dtype(cls, dtype) -> str:
        return cls._FRIENDLY_DTYPE_NAMES.get(str(dtype), str(dtype))

    def __init__(self, master, sim_engine=None, session_name: str = None):
        super().__init__(master)
        self.title("JDW (Jordan's Data Warehouse) Session")
        self.geometry("900x600")
        self.engine = sim_engine
        self.session_name = session_name
        self._last_result_df = None
        # Parquets loaded from save_data/<session_name>/saved_tables/ (name -> dataframe), queryable
        # alongside the engine's own live tables (if any), but never written back into the engine itself.
        self._loaded_parquets: dict = {}
        self._saved_parquet_paths: list = []

        menubar = tk.Menu(self)
        file_menu = tk.Menu(menubar, tearoff=0)
        if self.engine is not None:
            file_menu.add_command(label="Take Snapshot", command=self._on_take_snapshot)
            file_menu.add_separator()
        file_menu.add_command(label="Import Parquet...", command=self._on_import_parquet)
        file_menu.add_command(label="Import CSV...", command=self._on_import_csv)
        file_menu.add_command(label="View Imported Parquets", command=self._on_view_imported_parquets)
        file_menu.add_separator()
        file_menu.add_command(label="Save Query...", command=self._on_save_query)
        file_menu.add_command(label="Load Query...", command=self._on_load_query)
        file_menu.add_separator()
        file_menu.add_command(label="Save Result as CSV...", command=self._on_save_result_csv)
        file_menu.add_command(label="Save Result as Parquet...", command=self._on_save_result_parquet)
        menubar.add_cascade(label="File", menu=file_menu)
        self.config(menu=menubar)

        main_pane = tk.PanedWindow(self, orient=tk.HORIZONTAL, sashwidth=4)
        main_pane.pack(fill="both", expand=True)

        left_frame = tk.Frame(main_pane, width=180)
        tables_frame = tk.Frame(left_frame)
        tables_frame.pack(fill="both", expand=True, side="top")
        tk.Label(tables_frame, text="Tables", anchor="w").pack(fill="x", padx=4, pady=(4, 0))
        self.table_listbox = tk.Listbox(tables_frame)
        self.table_listbox.pack(fill="both", expand=True, padx=4, pady=4)
        self.table_listbox.bind("<<ListboxSelect>>", self._on_table_selected)

        parquets_frame = tk.Frame(left_frame)
        parquets_frame.pack(fill="both", expand=True, side="top")
        tk.Label(parquets_frame, text="Saved Parquets", anchor="w").pack(fill="x", padx=4, pady=(4, 0))
        self.saved_parquets_listbox = tk.Listbox(parquets_frame)
        self.saved_parquets_listbox.pack(fill="both", expand=True, padx=4, pady=4)
        self.saved_parquets_listbox.bind("<<ListboxSelect>>", self._on_saved_parquet_selected)

        self._refresh_table_listbox()
        self._refresh_saved_parquets_listbox()
        self.after(self.PARQUET_REFRESH_INTERVAL_MS, self._periodic_refresh_saved_parquets)
        main_pane.add(left_frame, minsize=140)

        right_pane = tk.PanedWindow(main_pane, orient=tk.VERTICAL, sashwidth=4)
        main_pane.add(right_pane, minsize=300)

        query_frame = tk.Frame(right_pane)
        self.query_text = tk.Text(query_frame, height=10, wrap="none", undo=True)
        self.query_text.pack(fill="both", expand=True, side="top", padx=4, pady=(4, 0))
        self.query_text.bind("<Control-Return>", self._on_run_query)
        run_button = tk.Button(query_frame, text="Run Query (Ctrl+Enter)", command=self._on_run_query)
        run_button.pack(side="right", padx=4, pady=4)
        right_pane.add(query_frame, minsize=120)

        results_frame = tk.Frame(right_pane)
        self.results_tree = ttk.Treeview(results_frame, show="headings")
        results_vscroll = ttk.Scrollbar(results_frame, orient="vertical", command=self.results_tree.yview)
        results_hscroll = ttk.Scrollbar(results_frame, orient="horizontal", command=self.results_tree.xview)
        self.results_tree.configure(yscrollcommand=results_vscroll.set, xscrollcommand=results_hscroll.set)
        self.results_tree.grid(row=0, column=0, sticky="nsew")
        results_vscroll.grid(row=0, column=1, sticky="ns")
        results_hscroll.grid(row=1, column=0, sticky="ew")
        results_frame.rowconfigure(0, weight=1)
        results_frame.columnconfigure(0, weight=1)
        tk.Button(results_frame, text="Open in Excel", command=self._on_open_in_excel).grid(row=2, column=0, columnspan=2, sticky="ew", pady=(4, 0))
        right_pane.add(results_frame, minsize=150)

        self.status_var = tk.StringVar(value="Ready.")
        tk.Label(self, textvariable=self.status_var, anchor="w").pack(fill="x", padx=8, pady=(0, 4))

    def _on_table_selected(self, event) -> None:
        selection = self.table_listbox.curselection()
        if not selection:
            return
        table_name = self.table_listbox.get(selection[0])
        self.query_text.delete("1.0", "end")
        self.query_text.insert("1.0", f"SELECT * FROM {table_name} LIMIT 25")
        self._run_query()

    # Exports as .xlsx (not .csv): Excel renders each cell using the type openpyxl wrote it as, rather than
    # re-guessing types on import, so leading zeros / large integers / etc. survive exactly as stored.
    # os.startfile()/subprocess.Popen() hand off to the OS and return immediately - opening Excel never blocks.
    def _on_open_in_excel(self) -> None:
        if self._last_result_df is None:
            messagebox.showinfo("No result", "Run a query first.")
            return
        tmp_path = Path(tempfile.gettempdir()) / f"jdw_result_{uuid.uuid4().hex[:8]}.xlsx"
        try:
            self._last_result_df.to_excel(tmp_path, index=False, engine="openpyxl")
            if sys.platform.startswith("win"):
                os.startfile(tmp_path)
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(tmp_path)])
            else:
                subprocess.Popen(["xdg-open", str(tmp_path)])
        except Exception as e:
            messagebox.showerror("Open in Excel failed", str(e))
            return
        self.status_var.set(f"Opened result in Excel ({tmp_path}).")

    # dataframe names cannot collide: a parquet whose stem already matches an existing (live or loaded) table
    # name is refused, since running a query against that name would then be ambiguous.
    def _on_saved_parquet_selected(self, event) -> None:
        selection = self.saved_parquets_listbox.curselection()
        if not selection:
            return
        path = self._saved_parquet_paths[selection[0]]
        name = path.stem
        if name in self._engine_tables() and name not in self._loaded_parquets:
            messagebox.showerror(
                "Name collision",
                f"Cannot load '{name}' - a table with that name already exists. Dataframe names cannot collide.",
            )
            return
        try:
            self._loaded_parquets[name] = pd.read_parquet(path)
        except Exception as e:
            messagebox.showerror("Load failed", str(e))
            return
        self._refresh_saved_parquets_listbox()
        self._refresh_table_listbox()
        self.status_var.set(f"Loaded '{name}' - query it via SELECT * FROM {name}.")

    # No live engine when running standalone (see class docstring) - just an empty dict in that case.
    def _engine_tables(self) -> dict:
        return self.engine.get_all_table_dataframes() if self.engine is not None else {}

    def _refresh_table_listbox(self) -> None:
        self.table_listbox.delete(0, "end")
        names = sorted(set(self._engine_tables().keys()) | set(self._loaded_parquets.keys()))
        for name in names:
            self.table_listbox.insert("end", name)

    def _refresh_saved_parquets_listbox(self) -> None:
        self.saved_parquets_listbox.delete(0, "end")
        results_dir_str = self._save_data_subfolder("saved_tables")
        results_dir = Path(results_dir_str) if results_dir_str else None
        self._saved_parquet_paths = sorted(results_dir.glob("*.parquet")) if results_dir and results_dir.exists() else []
        for path in self._saved_parquet_paths:
            icon = "\u2714 " if path.stem in self._loaded_parquets else "   "
            self.saved_parquets_listbox.insert("end", f"{icon}{path.stem}")

    # Picks up parquet files added/removed outside this window (e.g. via Save Result, or manually on disk).
    def _periodic_refresh_saved_parquets(self) -> None:
        if not self.winfo_exists():
            return
        self._refresh_saved_parquets_listbox()
        self.after(self.PARQUET_REFRESH_INTERVAL_MS, self._periodic_refresh_saved_parquets)

    def _on_run_query(self, event=None) -> None:
        self._run_query()

    def _run_query(self) -> None:
        sql = self.query_text.get("1.0", "end-1c").strip()
        if not sql:
            return
        tables = {**self._engine_tables(), **self._loaded_parquets}
        try:
            result_df = sql_macro_helpers.query(tables, sql)
        except Exception as e:
            messagebox.showerror("Query failed", str(e))
            self.status_var.set("Query failed.")
            return
        self._last_result_df = result_df
        self._display_results(result_df)
        self.status_var.set(f"{len(result_df)} row(s) returned.")

    def _display_results(self, result_df) -> None:
        self.results_tree.delete(*self.results_tree.get_children())
        columns = list(result_df.columns)
        self.results_tree["columns"] = columns
        for column in columns:
            self.results_tree.heading(column, text=f"{column} ({self._friendly_dtype(result_df[column].dtype)})")
            self.results_tree.column(column, width=self.RESULT_COLUMN_WIDTH, minwidth=self.RESULT_COLUMN_MIN_WIDTH, anchor="w", stretch=False)
        for row in result_df.itertuples(index=False):
            self.results_tree.insert("", "end", values=row)

    def _on_take_snapshot(self) -> None:
        try:
            self.engine.take_snapshot()
        except Exception as e:
            messagebox.showerror("Take snapshot failed", str(e))
            return
        self.status_var.set(f"Saved deltas + snapshot at simulated_datetime={self.engine.get_simulated_datetime()}.")

    def _save_data_subfolder(self, name: str) -> str | None:
        if not self.session_name:
            return None
        return str(config_manager.SAVE_DATA_DIR / self.session_name / name)

    # Copies one or more externally-selected parquet files into this session's saved_tables/ folder (they
    # then show up in the Saved Parquets list, same as anything saved from a query result).
    def _on_import_parquet(self) -> None:
        saved_tables_dir_str = self._save_data_subfolder("saved_tables")
        if not saved_tables_dir_str:
            messagebox.showerror("No session", "This JDW window has no session folder to import into.")
            return
        source_paths = filedialog.askopenfilenames(
            parent=self, title="Import Parquet",
            filetypes=[("Parquet files", "*.parquet"), ("All files", "*.*")],
        )
        if not source_paths:
            return
        saved_tables_dir = Path(saved_tables_dir_str)
        saved_tables_dir.mkdir(parents=True, exist_ok=True)
        imported_names = []
        for source_path_str in source_paths:
            source_path = Path(source_path_str)
            shutil.copy2(source_path, saved_tables_dir / source_path.name)
            imported_names.append(source_path.name)
        self._refresh_saved_parquets_listbox()
        self.status_var.set(f"Imported {len(imported_names)} parquet file(s): {', '.join(imported_names)}.")

    # One CSV at a time only (see core/csv_import.py) - datatype coercion needs reviewing per file. Reads
    # every column as a raw string by default (never guessed - no risk of losing leading zeros etc.); an
    # optional user-supplied YAML/JSON schema can instead cast specific columns to a declared datatype.
    def _on_import_csv(self) -> None:
        saved_tables_dir_str = self._save_data_subfolder("saved_tables")
        if not saved_tables_dir_str:
            messagebox.showerror("No session", "This JDW window has no session folder to import into.")
            return
        csv_path_str = filedialog.askopenfilename(
            parent=self, title="Import CSV",
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")],
        )
        if not csv_path_str:
            return

        column_schema = None
        if messagebox.askyesno("Column schema", "Use a column-datatype schema (YAML/JSON) for this import?"):
            schema_path_str = filedialog.askopenfilename(
                parent=self, title="Select Column Schema",
                filetypes=[("YAML/JSON files", "*.yaml *.yml *.json"), ("All files", "*.*")],
            )
            if not schema_path_str:
                return
            schema_path = Path(schema_path_str)
            try:
                table_names = csv_import.list_schema_table_names(schema_path)
                table_name = None
                if len(table_names) > 1:
                    table_name = simpledialog.askstring(
                        "Select Table",
                        f"This schema defines multiple tables: {', '.join(table_names)}\nWhich one describes this CSV?",
                        parent=self,
                    )
                    if not table_name:
                        return
                column_schema = csv_import.load_column_schema(schema_path, table_name=table_name)
            except Exception as e:
                messagebox.showerror("Failed to load schema", str(e))
                return

        try:
            parquet_path = csv_import.import_csv_to_parquet(Path(csv_path_str), Path(saved_tables_dir_str), column_schema)
        except Exception as e:
            messagebox.showerror("Import CSV failed", str(e))
            return
        self._refresh_saved_parquets_listbox()
        self.status_var.set(f"Imported '{Path(csv_path_str).name}' as '{parquet_path.name}'.")

    # Opens the session's saved_tables/ folder directly in the OS file explorer, so the underlying parquet
    # files (imported or saved from query results) can be viewed/managed outside the app too.
    def _on_view_imported_parquets(self) -> None:
        saved_tables_dir_str = self._save_data_subfolder("saved_tables")
        if not saved_tables_dir_str:
            messagebox.showerror("No session", "This JDW window has no session folder to view.")
            return
        try:
            open_folder(Path(saved_tables_dir_str))
        except Exception as e:
            messagebox.showerror("Failed to open folder", str(e))

    def _on_load_query(self) -> None:
        path = filedialog.askopenfilename(
            parent=self, title="Load Query",
            initialdir=self._save_data_subfolder("sql_queries"),
            filetypes=[("SQL/Text files", "*.sql *.txt"), ("All files", "*.*")],
        )
        if not path:
            return
        with open(path, "r") as f:
            content = f.read()
        self.query_text.delete("1.0", "end")
        self.query_text.insert("1.0", content)
        self.status_var.set(f"Loaded query from {path}.")

    def _on_save_query(self) -> None:
        path = filedialog.asksaveasfilename(
            parent=self, title="Save Query", defaultextension=".sql",
            initialdir=self._save_data_subfolder("sql_queries"),
            filetypes=[("SQL files", "*.sql"), ("All files", "*.*")],
        )
        if not path:
            return
        with open(path, "w") as f:
            f.write(self.query_text.get("1.0", "end-1c"))
        self.status_var.set(f"Query saved to {path}.")

    def _on_save_result_csv(self) -> None:
        if self._last_result_df is None:
            messagebox.showinfo("No result", "Run a query first.")
            return
        path = filedialog.asksaveasfilename(
            parent=self, title="Save Result as CSV", defaultextension=".csv",
            initialdir=self._save_data_subfolder("saved_tables"),
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")],
        )
        if not path:
            return
        self._last_result_df.to_csv(path, index=False)
        self.status_var.set(f"Result saved to {path}.")

    def _on_save_result_parquet(self) -> None:
        if self._last_result_df is None:
            messagebox.showinfo("No result", "Run a query first.")
            return
        path = filedialog.asksaveasfilename(
            parent=self, title="Save Result as Parquet", defaultextension=".parquet",
            initialdir=self._save_data_subfolder("saved_tables"),
            filetypes=[("Parquet files", "*.parquet"), ("All files", "*.*")],
        )
        if not path:
            return
        self._last_result_df.to_parquet(path, index=False)
        self._refresh_saved_parquets_listbox()
        self.status_var.set(f"Result saved to {path}.")
