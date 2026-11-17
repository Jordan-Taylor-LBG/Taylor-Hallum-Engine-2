"""
Graphical viewer/editor for config/<dataset>/actions.yaml files. Opened from the main App's
"View/Edit Actions..." button. Lists every action name; selecting one draws a 3-column diagram:
prerequisite tables (left) -> the action (middle) -> its base_actions tables with their CRUD op (right).
Reads schema_entity_relationships.yaml read-only to look up each table's primary_keys/depends_on.
"""

import tkinter as tk
import os
import subprocess
import sys
from pathlib import Path
from tkinter import messagebox

from parsers import actions_parser
from parsers import schema_parser
from ui.badges import MACRO_BADGE_COLOR, MACRO_BADGE_OUTLINE, draw_macro_badge

ACTION_BOX_COLOR = "#dbe9f8"
ACTION_BOX_OUTLINE = "#1f5fa8"
PREREQUISITE_BOX_COLOR = "#f5f5f5"
BASE_ACTION_BOX_COLOR = "#eafaf1"
BOX_OUTLINE = "#333333"
CONNECTOR_COLOR = "#555555"
IQ_BADGE_COLOR = "#e74c3c"
IQ_BADGE_RADIUS = 11
POST_ACTION_BOX_WIDTH = 110
POST_ACTION_BOX_HEIGHT = 40


def _open_containing_folder(path: Path) -> None:
    folder = str(path.parent)
    if sys.platform.startswith("win"):
        os.startfile(folder)
    elif sys.platform == "darwin":
        subprocess.run(["open", folder])
    else:
        subprocess.run(["xdg-open", folder])


def _draw_iq_marker(canvas: tk.Canvas, x: float, y: float) -> None:
    """Draws a red 'IQ' badge centered at (x, y), marking a table that has independent_qualifiers."""
    r = IQ_BADGE_RADIUS
    canvas.create_oval(x - r, y - r, x + r, y + r, fill=IQ_BADGE_COLOR, outline="#7a1f13")
    canvas.create_text(x, y, text="IQ", font=("Segoe UI", 7, "bold"), fill="white")


def _normalize_crud(crud) -> set:
    """CRUD may be a single string or a list of strings in the YAML - normalize to a lowercase set."""
    if crud is None:
        return set()
    if isinstance(crud, str):
        return {crud.strip().lower()}
    return {str(c).strip().lower() for c in crud}


class ActionsViewerWindow(tk.Toplevel):
    BOX_WIDTH = 190
    BOX_HEIGHT = 64
    BOX_GAP_Y = 20
    COLUMN_GAP_X = 260

    def __init__(self, master, actions_path: Path, schema_path: Path):
        super().__init__(master)
        self.actions_path = Path(actions_path)
        self.schema_path = Path(schema_path)
        self.title(f"Actions Viewer - {self.actions_path}")
        self.geometry("1100x760")

        self._actions: dict = {}
        self._schema_tables: dict = {}
        self._selected_action: str | None = None

        self._build_toolbar()
        self._build_body()
        self._load_and_render()

    # --- layout ---------------------------------------------------------

    def _build_toolbar(self) -> None:
        toolbar = tk.Frame(self)
        toolbar.pack(fill="x", padx=8, pady=4)
        tk.Button(toolbar, text="Reload", command=self._load_and_render).pack(side="left")
        tk.Button(toolbar, text="Open Containing Folder", command=lambda: _open_containing_folder(self.actions_path)).pack(side="left", padx=8)
        self.status_var = tk.StringVar(value=str(self.actions_path))
        tk.Label(toolbar, textvariable=self.status_var, fg="#333333").pack(side="left", padx=8)

    def _build_body(self) -> None:
        paned = tk.PanedWindow(self, orient="horizontal", sashwidth=6)
        paned.pack(fill="both", expand=True, padx=8, pady=4)

        list_frame = tk.Frame(paned)
        tk.Label(list_frame, text="Actions:").pack(anchor="w")
        list_scroll = tk.Scrollbar(list_frame, orient="vertical")
        self.actions_listbox = tk.Listbox(list_frame, width=32, yscrollcommand=list_scroll.set, exportselection=False)
        list_scroll.config(command=self.actions_listbox.yview)
        self.actions_listbox.pack(side="left", fill="both", expand=True)
        list_scroll.pack(side="right", fill="y")
        self.actions_listbox.bind("<<ListboxSelect>>", self._on_listbox_select)

        diagram_frame = tk.Frame(paned)
        diagram_frame.rowconfigure(0, weight=1)
        diagram_frame.columnconfigure(0, weight=1)
        h_scroll = tk.Scrollbar(diagram_frame, orient="horizontal")
        v_scroll = tk.Scrollbar(diagram_frame, orient="vertical")
        self.canvas = tk.Canvas(diagram_frame, bg="white", xscrollcommand=h_scroll.set, yscrollcommand=v_scroll.set)
        h_scroll.config(command=self.canvas.xview)
        v_scroll.config(command=self.canvas.yview)
        self.canvas.grid(row=0, column=0, sticky="nsew")
        v_scroll.grid(row=0, column=1, sticky="ns")
        h_scroll.grid(row=1, column=0, sticky="ew")

        self.canvas.bind("<MouseWheel>", lambda event: self.canvas.yview_scroll(int(-1 * (event.delta / 120)), "units"))
        self.canvas.bind("<Shift-MouseWheel>", lambda event: self.canvas.xview_scroll(int(-1 * (event.delta / 120)), "units"))

        paned.add(list_frame, stretch="never", width=220)
        paned.add(diagram_frame, stretch="always")

        tk.Label(self, text="Raw YAML (read-only - use Open Containing Folder to edit in a text editor):").pack(anchor="w", padx=8)
        text_frame = tk.Frame(self)
        text_frame.pack(fill="both", expand=False, padx=8, pady=(0, 8))
        text_scroll = tk.Scrollbar(text_frame, orient="vertical")
        self.text_editor = tk.Text(text_frame, height=12, wrap="none", yscrollcommand=text_scroll.set)
        text_scroll.config(command=self.text_editor.yview)
        self.text_editor.pack(side="left", fill="both", expand=True)
        text_scroll.pack(side="right", fill="y")

    # --- data / rendering -------------------------------------------------

    def _load_and_render(self) -> None:
        try:
            raw_text = actions_parser.load_actions_raw_text(self.actions_path)
            schema = schema_parser.load_schema(self.schema_path)
        except Exception as e:
            messagebox.showerror("Failed to load", str(e))
            return

        self.text_editor.config(state="normal")
        self.text_editor.delete("1.0", "end")
        self.text_editor.insert("1.0", raw_text)
        self.text_editor.config(state="disabled")
        self._schema_tables = schema["tables"]
        self.status_var.set(f"Loaded {self.actions_path}")
        self._refresh_actions_from_text(select_previous=True)

    def _refresh_actions_from_text(self, select_previous: bool) -> None:
        import yaml
        text = self.text_editor.get("1.0", "end")
        try:
            self._actions = yaml.safe_load(text) or {}
        except Exception as e:
            messagebox.showerror("Invalid YAML", str(e))
            return

        previous = self._selected_action
        action_names = sorted(self._actions)
        self.actions_listbox.delete(0, "end")
        for name in action_names:
            self.actions_listbox.insert("end", name)

        if select_previous and previous in self._actions:
            self.actions_listbox.selection_set(action_names.index(previous))
            self._render_action(previous)
        else:
            self._selected_action = None
            self.canvas.delete("all")

    def _on_listbox_select(self, event) -> None:
        selection = self.actions_listbox.curselection()
        if not selection:
            return
        self._render_action(self.actions_listbox.get(selection[0]))

    def _prerequisite_tables(self, base_actions: dict) -> list:
        """Tables required to already exist before this action can run: any depends_on ancestor of a
        base_actions table (excluding tables already in the action), plus any base_actions table itself
        whose CRUD doesn't include 'create' - read/update/macro all require the table to already exist."""
        base_action_tables = set(base_actions)
        prerequisites = set()
        for table in base_action_tables:
            prerequisites.update(self._schema_tables.get(table, {}).get("depends_on", []))
        prerequisites -= base_action_tables
        for table, details in base_actions.items():
            crud = _normalize_crud((details or {}).get("CRUD"))
            if crud and "create" not in crud:
                prerequisites.add(table)
        return sorted(prerequisites)

    def _column_positions(self, count: int, x: float, canvas_height: float) -> list:
        total_height = count * self.BOX_HEIGHT + max(count - 1, 0) * self.BOX_GAP_Y
        start_y = (canvas_height - total_height) / 2 + self.BOX_HEIGHT / 2
        return [(x, start_y + i * (self.BOX_HEIGHT + self.BOX_GAP_Y)) for i in range(count)]

    def _render_action(self, action_name: str) -> None:
        self._selected_action = action_name
        action = self._actions.get(action_name) or {}
        base_actions = action.get("base_actions") or {}
        base_action_tables = sorted(base_actions)
        prerequisite_tables = self._prerequisite_tables(base_actions)
        post_actions = action.get("post_actions") or []

        c = self.canvas
        c.delete("all")
        half_w, half_h = self.BOX_WIDTH / 2, self.BOX_HEIGHT / 2

        left_x = 130
        mid_x = left_x + self.COLUMN_GAP_X
        right_x = mid_x + self.COLUMN_GAP_X
        max_rows = max(len(prerequisite_tables), len(base_action_tables), 1)
        canvas_height = 80 + max_rows * self.BOX_HEIGHT + max(max_rows - 1, 0) * self.BOX_GAP_Y
        mid_y = canvas_height / 2

        left_positions = self._column_positions(len(prerequisite_tables), left_x, canvas_height)
        right_positions = self._column_positions(len(base_action_tables), right_x, canvas_height)

        for table_name, (x, y) in zip(prerequisite_tables, left_positions):
            self._draw_table_box(table_name, x, y, PREREQUISITE_BOX_COLOR, None)
            c.create_line(x + half_w, y, mid_x - half_w, mid_y, fill=CONNECTOR_COLOR, width=2, arrow=tk.LAST, arrowshape=(8, 10, 4))
        if not prerequisite_tables:
            c.create_text(left_x, mid_y, text="(no prerequisite tables)", font=("Segoe UI", 8, "italic"), width=self.BOX_WIDTH)

        for table_name, (x, y) in zip(base_action_tables, right_positions):
            crud = (base_actions.get(table_name) or {}).get("CRUD", "?")
            self._draw_table_box(table_name, x, y, BASE_ACTION_BOX_COLOR, crud)
            c.create_line(mid_x + half_w, mid_y, x - half_w, y, fill=CONNECTOR_COLOR, width=2, arrow=tk.LAST, arrowshape=(8, 10, 4))
        if not base_action_tables:
            c.create_text(right_x, mid_y, text="(no base actions)", font=("Segoe UI", 8, "italic"), width=self.BOX_WIDTH)

        c.create_rectangle(mid_x - half_w, mid_y - half_h, mid_x + half_w, mid_y + half_h, fill=ACTION_BOX_COLOR, outline=ACTION_BOX_OUTLINE, width=3)
        c.create_text(mid_x, mid_y, text=action_name, font=("Segoe UI", 10, "bold"), width=self.BOX_WIDTH - 10)

        post_action_x = right_x + half_w + 70
        if post_actions:
            c.create_line(right_x + half_w, mid_y, post_action_x - POST_ACTION_BOX_WIDTH / 2, mid_y, fill=CONNECTOR_COLOR, width=2, arrow=tk.LAST, arrowshape=(8, 10, 4))
            self._draw_post_action_box(post_action_x, mid_y, post_actions)
            canvas_width = post_action_x + POST_ACTION_BOX_WIDTH / 2 + 60
        else:
            canvas_width = right_x + half_w + 60
        c.configure(scrollregion=(0, 0, canvas_width, canvas_height))

    def _draw_post_action_box(self, x: float, y: float, post_actions: list) -> None:
        """Draws a small grey 'macro' box to the right of an action's output tables, marking that this
        action runs post_actions (macro functions that run after base_actions, bypassing the DAG)."""
        c = self.canvas
        half_w, half_h = POST_ACTION_BOX_WIDTH / 2, POST_ACTION_BOX_HEIGHT / 2
        c.create_rectangle(x - half_w, y - half_h, x + half_w, y + half_h, fill=MACRO_BADGE_COLOR, outline=MACRO_BADGE_OUTLINE, width=2)
        draw_macro_badge(c, x - half_w + 16, y, filled=True)
        c.create_text(x + 10, y, text="macro", font=("Segoe UI", 9, "bold"), fill="white")
        function_names = ", ".join(post_action.get("function", "?") for post_action in post_actions)
        c.create_text(x, y + half_h + 12, text=function_names, font=("Segoe UI", 7), width=POST_ACTION_BOX_WIDTH + 80)

    def _draw_table_box(self, table_name: str, x: float, y: float, fill_color: str, crud) -> None:
        c = self.canvas
        half_w, half_h = self.BOX_WIDTH / 2, self.BOX_HEIGHT / 2
        x1, y1, x2, y2 = x - half_w, y - half_h, x + half_w, y + half_h
        c.create_rectangle(x1, y1, x2, y2, fill=fill_color, outline=BOX_OUTLINE, width=2)
        c.create_line(x1, y - 10, x2, y - 10, fill=BOX_OUTLINE)
        title = table_name if crud is None else f"{table_name}  [{crud}]"
        c.create_text(x, y1 + 12, text=title, font=("Segoe UI", 9, "bold"), width=self.BOX_WIDTH - 10)
        primary_keys = self._schema_tables.get(table_name, {}).get("primary_keys", [])
        pk_text = "PK: " + ", ".join(primary_keys) if primary_keys else "(not in schema / no primary_keys)"
        c.create_text(x, y + (half_h - 10) / 2, text=pk_text, font=("Segoe UI", 7), width=self.BOX_WIDTH - 10)
        if self._schema_tables.get(table_name, {}).get("independent_qualifiers"):
            _draw_iq_marker(c, x2, y1)
