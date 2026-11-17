"""Step-through debugging window (StepThroughWindow) that drives an Engine one phase at a time."""

import tkinter as tk
from tkinter import messagebox

from core import config_manager
from ui.dag_window import DagWindow
from ui.file_utils import open_folder
from ui.jdw_window import JDWWindow
from ui.widgets import ClockWidget


class StepThroughWindow(tk.Toplevel):
    """
    Step-through debugging window: drives sim_engine one phase at a time via its decoupled
    run_step_display() / run_step_select() / run_step_orchestrate() API. This window only ever calls that
    API and reads its return values - it has no knowledge of the engine's internals (DAGs, tables, etc), and
    the engine has no knowledge of this window.
    """

    # Simulates clicking "1. Display", "2. Select" and "3. Orchestrate" in turn, spread over ~0.1s so each
    # step's effect is still visible, rather than calling them all synchronously in one go.
    AUTO_STEP_DELAY_MS = 50

    def __init__(self, master, sim_engine, dag_window: DagWindow = None, dataset_name: str = None):
        super().__init__(master)
        self.title("Step-Through Run")
        self.resizable(False, False)
        self.engine = sim_engine
        self.dag_window = dag_window
        self.dataset_name = dataset_name
        self._last_orchestrate_saved = False
        self._jdw_window: "JDWWindow | None" = None

        menubar = tk.Menu(self)
        self.file_menu = tk.Menu(menubar, tearoff=0)
        self.file_menu.add_command(label="Open Live JDW Session", command=self._on_open_jdw)
        self.file_menu.add_separator()
        self.file_menu.add_command(label="Take Snapshot", command=self._on_take_snapshot)
        self.file_menu.add_command(label="Open Snapshots Folder", command=self._open_snapshots_folder)
        menubar.add_cascade(label="File", menu=self.file_menu)
        self.config(menu=menubar)

        window_start, window_end = self.engine.daily_windows[0]
        self.clock = ClockWidget(
            self, window_start.time(), window_end.time(),
            checkpoint_times=self.engine.checkpoint_times, interactive=False,
        )
        self.clock.pack(padx=8, pady=8)

        self.info_var = tk.StringVar()
        tk.Label(self, textvariable=self.info_var, justify="left", anchor="w").pack(fill="x", padx=8)

        buttons_frame = tk.Frame(self)
        buttons_frame.pack(fill="x", padx=8, pady=8)
        self.display_button = tk.Button(buttons_frame, text="1. Display possible actions", command=self._on_display)
        self.display_button.pack(side="left")
        self.select_button = tk.Button(buttons_frame, text="2. Select action", command=self._on_select, state="disabled")
        self.select_button.pack(side="left", padx=8)
        self.orchestrate_button = tk.Button(buttons_frame, text="3. Orchestrate + advance", command=self._on_orchestrate, state="disabled")
        self.orchestrate_button.pack(side="left")
        self.auto_step_button = tk.Button(buttons_frame, text="4. Auto-step", command=self._on_auto_step)
        self.auto_step_button.pack(side="left", padx=8)
        self.run_to_snapshot_button = tk.Button(buttons_frame, text="5. Run to next snapshot", command=self._on_run_to_next_snapshot)
        self.run_to_snapshot_button.pack(side="left")

        self.log_text = tk.Text(self, width=76, height=14, state="disabled")
        self.log_text.pack(fill="both", expand=True, padx=8, pady=(0, 8))

        self._refresh()
        self._log(f"Ready. Simulated time starts at {self.engine.get_simulated_datetime()}.")

    def _format_info(self) -> str:
        return f"Time step: {self.engine.time_steps}\nSimulated datetime: {self.engine.get_simulated_datetime()}"

    def _log(self, message: str) -> None:
        self.log_text.config(state="normal")
        self.log_text.insert("end", message + "\n")
        self.log_text.see("end")
        self.log_text.config(state="disabled")

    def _refresh(self) -> None:
        self.info_var.set(self._format_info())
        self.clock.set_current_time(self.engine.get_simulated_datetime().time())

    def _on_display(self) -> bool:
        try:
            possible_actions = self.engine.run_step_display()
        except Exception as e:
            messagebox.showerror("Step failed", str(e))
            return False
        self._log(f"[1. display] possible actions: {possible_actions}")
        self._refresh()
        if self.dag_window is not None and self.dag_window.winfo_exists():
            self.dag_window.clear_highlights()

            create_tables = {
                table
                for action in possible_actions
                for table, cruds in self.engine.get_action_table_cruds(action).items()
                if "create" in cruds
            }
            self.dag_window.highlight_outlines(create_tables)
            update_tables = {
                table
                for action in possible_actions
                for table, cruds in self.engine.get_action_table_cruds(action).items()
                if "update" in cruds
            }
            self.dag_window.show_update_badges(update_tables)
            macro_tables = {
                table
                for action in possible_actions
                for table, cruds in self.engine.get_action_table_cruds(action).items()
                if "macro" in cruds
            }
            for action in possible_actions:
                macro_tables |= self.engine.get_action_post_action_tables(action)
            self.dag_window.show_macro_badges(macro_tables)
        self.display_button.config(state="disabled")
        self.select_button.config(state="normal")
        return True

    def _on_select(self) -> bool:
        try:
            selected_action = self.engine.run_step_select()
        except Exception as e:
            messagebox.showerror("Step failed", str(e))
            return False
        self._log(f"[2. select] selected action: {selected_action}")
        if self.dag_window is not None and self.dag_window.winfo_exists():
            self.dag_window.clear_outlines()
            action_cruds = self.engine.get_action_table_cruds(selected_action)
            create_tables = {table for table, cruds in action_cruds.items() if "create" in cruds}
            update_tables = {table for table, cruds in action_cruds.items() if "update" in cruds}
            macro_tables = {table for table, cruds in action_cruds.items() if "macro" in cruds}
            macro_tables |= self.engine.get_action_post_action_tables(selected_action)
            self.dag_window.highlight_nodes(create_tables)
            self.dag_window.fill_update_badges(update_tables)
            self.dag_window.fill_macro_badges(macro_tables)
        self.select_button.config(state="disabled")
        self.orchestrate_button.config(state="normal")
        return True

    def _on_orchestrate(self) -> bool:
        try:
            result = self.engine.run_step_orchestrate()
        except Exception as e:
            messagebox.showerror("Step failed", str(e))
            return False
        self._log(f"[3. orchestrate] action={result['action']}, simulated_datetime={result['simulated_datetime']}, saved={result['saved']}")
        self._refresh()
        if self.dag_window is not None and self.dag_window.winfo_exists():
            self.dag_window.mark_orchestrated(self.engine.get_action_tables(result["action"]))
            self.dag_window.clear_update_badges()
            self.dag_window.clear_macro_badges()
        self.orchestrate_button.config(state="disabled")
        self._last_orchestrate_saved = result["saved"]

        if result["run_complete"]:
            self._log("Run complete - no more time steps remain.")
        else:
            self.display_button.config(state="normal")
        return True

    def _on_take_snapshot(self) -> None:
        try:
            self.engine.take_snapshot()
        except Exception as e:
            messagebox.showerror("Take snapshot failed", str(e))
            return
        self._log(f"[take snapshot] saved deltas + snapshot at simulated_datetime={self.engine.get_simulated_datetime()}.")

    def _open_snapshots_folder(self) -> None:
        try:
            open_folder(config_manager.BASE_PATH / "generated_data_files" / self.engine.dataset_name)
        except Exception as e:
            messagebox.showerror("Failed to open snapshots folder", str(e))

    # Reuses the same JDWWindow instance (rather than accumulating stale ones) if already open.
    def _on_open_jdw(self) -> None:
        if self._jdw_window is not None and self._jdw_window.winfo_exists():
            self._jdw_window.lift()
            self._jdw_window.focus_force()
            return
        self._jdw_window = JDWWindow(self, self.engine, session_name=self.dataset_name)

    def _set_take_snapshot_enabled(self, enabled: bool) -> None:
        self.file_menu.entryconfig("Take Snapshot", state="normal" if enabled else "disabled")

    def _on_auto_step(self) -> None:
        self.auto_step_button.config(state="disabled")
        self._set_take_snapshot_enabled(False)
        if self._on_display():
            self.after(self.AUTO_STEP_DELAY_MS, self._auto_step_select)
        else:
            self.auto_step_button.config(state="normal")
            self._set_take_snapshot_enabled(True)

    def _auto_step_select(self) -> None:
        if self._on_select():
            self.after(self.AUTO_STEP_DELAY_MS, self._auto_step_orchestrate)
        else:
            self.auto_step_button.config(state="normal")
            self._set_take_snapshot_enabled(True)

    def _auto_step_orchestrate(self) -> None:
        self._on_orchestrate()
        if not self.engine.is_run_complete():
            self.auto_step_button.config(state="normal")
            self._set_take_snapshot_enabled(True)

    # Repeatedly auto-steps (same paced display/select/orchestrate cycle, and visuals, as "4. Auto-step")
    # until a checkpoint (delta + snapshot) is saved, or the run completes - "fast-forward to the next snapshot".
    def _on_run_to_next_snapshot(self) -> None:
        self.run_to_snapshot_button.config(state="disabled")
        self.auto_step_button.config(state="disabled")
        self._set_take_snapshot_enabled(False)
        self._run_to_snapshot_display()

    def _run_to_snapshot_display(self) -> None:
        if self.engine.is_run_complete() or not self._on_display():
            self._finish_run_to_next_snapshot()
            return
        self.after(self.AUTO_STEP_DELAY_MS, self._run_to_snapshot_select)

    def _run_to_snapshot_select(self) -> None:
        if not self._on_select():
            self._finish_run_to_next_snapshot()
            return
        self.after(self.AUTO_STEP_DELAY_MS, self._run_to_snapshot_orchestrate)

    def _run_to_snapshot_orchestrate(self) -> None:
        if not self._on_orchestrate():
            self._finish_run_to_next_snapshot()
            return
        if self._last_orchestrate_saved or self.engine.is_run_complete():
            self._finish_run_to_next_snapshot()
            return
        self.after(self.AUTO_STEP_DELAY_MS, self._run_to_snapshot_display)

    def _finish_run_to_next_snapshot(self) -> None:
        if not self.engine.is_run_complete():
            self.run_to_snapshot_button.config(state="normal")
            self.auto_step_button.config(state="normal")
            self._set_take_snapshot_enabled(True)
