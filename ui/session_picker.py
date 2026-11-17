"""SessionPickerDialog: modal dialog for choosing or creating a standalone JDW session (save_data/<name>/)."""

import tkinter as tk
from pathlib import Path
from tkinter import messagebox, simpledialog

from core import config_manager


class SessionPickerDialog(tk.Toplevel):
    """
    Modal dialog listing existing save_data/<name>/ JDW sessions (folders with both sql_queries/ and
    saved_tables/ subfolders - see config_manager.list_save_data_sessions()), plus a way to create a new
    one. Sets self.result to the chosen session name (str) if the user picks/creates one, or None if
    cancelled - the constructor blocks (it's modal) until the dialog closes, so self.result is ready to
    read immediately after construction returns.
    """

    def __init__(self, master):
        super().__init__(master)
        self.title("Select JDW Session")
        self.resizable(False, False)
        self.result: str | None = None

        tk.Label(
            self,
            text="A JDW session is a save_data/<name>/ folder. Pick an existing one or create a new one.",
            wraplength=320, justify="left",
        ).pack(fill="x", padx=8, pady=(8, 4))

        self.listbox = tk.Listbox(self, width=40, height=8)
        self.listbox.pack(fill="both", expand=True, padx=8, pady=4)
        self.listbox.bind("<Double-Button-1>", lambda event: self._on_open())
        for session_name in config_manager.list_save_data_sessions():
            self.listbox.insert("end", session_name)

        buttons_frame = tk.Frame(self)
        buttons_frame.pack(fill="x", padx=8, pady=(0, 8))
        tk.Button(buttons_frame, text="New Session...", command=self._on_new).pack(side="left")
        tk.Button(buttons_frame, text="Open", command=self._on_open).pack(side="right")
        tk.Button(buttons_frame, text="Cancel", command=self._on_cancel).pack(side="right", padx=8)

        self.protocol("WM_DELETE_WINDOW", self._on_cancel)
        self.transient(master)
        self.grab_set()
        self.wait_window(self)

    def _on_new(self) -> None:
        session_name = simpledialog.askstring("New JDW Session", "Name for the new save_data/<name>/ session folder:", parent=self)
        if not session_name:
            return
        session_name = session_name.strip()
        if not session_name or session_name != Path(session_name).name:
            messagebox.showerror("Invalid name", "Session name must not be empty or contain path separators.", parent=self)
            return
        config_manager.ensure_save_data_dirs(session_name)
        self.result = session_name
        self.destroy()

    def _on_open(self) -> None:
        selection = self.listbox.curselection()
        if not selection:
            messagebox.showinfo("No session selected", "Select a session, or create a new one.", parent=self)
            return
        self.result = self.listbox.get(selection[0])
        self.destroy()

    def _on_cancel(self) -> None:
        self.result = None
        self.destroy()
