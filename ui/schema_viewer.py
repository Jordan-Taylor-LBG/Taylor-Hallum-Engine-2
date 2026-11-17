"""
Graphical viewer/editor for config/<dataset>/schema_entity_relationships.yaml files. Opened from the main
App's "View/Edit Schema..." button. Draws an ERD: black crow's-foot lines for entries under `relationships`,
red arrows for each table's `depends_on` list, and each table's `primary_keys` listed under its name.
"""

import math
import os
import subprocess
import sys
import tkinter as tk
from pathlib import Path
from tkinter import messagebox

from parsers import schema_parser

RELATIONSHIP_LINE_COLOR = "#111111"
DEPENDS_ON_LINE_COLOR = "#c0392b"
RELATIONSHIP_HIGHLIGHT_COLOR = "#ff8c00"
DEPENDS_ON_HIGHLIGHT_COLOR = "#27ae60"
DEPENDS_ON_OFFSET = 8
TABLE_BOX_COLOR = "#f5f5f5"
TABLE_OUTLINE_COLOR = "#333333"
IQ_BADGE_COLOR = "#e74c3c"
IQ_BADGE_RADIUS = 11


def _normalize(dx: float, dy: float) -> tuple[float, float]:
    length = math.hypot(dx, dy)
    if length == 0:
        return 0.0, 0.0
    return dx / length, dy / length


def _clip_point_to_box(cx: float, cy: float, half_width: float, half_height: float, towards_x: float, towards_y: float) -> tuple[float, float]:
    """Point on the box (centered at cx,cy) boundary, along the line from (cx,cy) towards (towards_x,towards_y)."""
    dx, dy = towards_x - cx, towards_y - cy
    if dx == 0 and dy == 0:
        return cx, cy
    scale_candidates = []
    if dx != 0:
        scale_candidates.append(half_width / abs(dx))
    if dy != 0:
        scale_candidates.append(half_height / abs(dy))
    scale = min(scale_candidates)
    return cx + dx * scale, cy + dy * scale


def _draw_crow_foot(canvas: tk.Canvas, x: float, y: float, dx: float, dy: float, color: str, tags: tuple = ()) -> None:
    """Draws a crow's-foot (many) marker whose three prongs touch (x, y), spread perpendicular to the
    connector, converging to a single apex point further along direction (dx, dy)."""
    ux, uy = _normalize(dx, dy)
    px, py = -uy, ux
    foot_length, spread = 12, 6
    apex_x, apex_y = x + ux * foot_length, y + uy * foot_length
    for offset in (-spread, 0, spread):
        canvas.create_line(apex_x, apex_y, x + px * offset, y + py * offset, fill=color, width=2, tags=tags)


def _draw_one_tick(canvas: tk.Canvas, x: float, y: float, dx: float, dy: float, color: str, tags: tuple = ()) -> None:
    """Draws a single perpendicular tick (one) near (x, y), along direction (dx, dy)."""
    ux, uy = _normalize(dx, dy)
    px, py = -uy, ux
    tick_distance, tick_half_length = 10, 6
    cx, cy = x + ux * tick_distance, y + uy * tick_distance
    canvas.create_line(cx - px * tick_half_length, cy - py * tick_half_length, cx + px * tick_half_length, cy + py * tick_half_length, fill=color, width=2, tags=tags)


def _offset_perpendicular(x1: float, y1: float, x2: float, y2: float, offset: float) -> tuple[tuple[float, float], tuple[float, float]]:
    """Shifts both endpoints sideways by `offset`, so a line drawn through them clears an overlapping line
    between the same two points."""
    ux, uy = _normalize(x2 - x1, y2 - y1)
    px, py = -uy, ux
    return (x1 + px * offset, y1 + py * offset), (x2 + px * offset, y2 + py * offset)


def _open_containing_folder(path: Path) -> None:
    folder = str(path.parent)
    if sys.platform.startswith("win"):
        os.startfile(folder)  # noqa: S606 - opening a local folder in Explorer, not user input
    elif sys.platform == "darwin":
        subprocess.run(["open", folder])
    else:
        subprocess.run(["xdg-open", folder])


def _draw_iq_marker(canvas: tk.Canvas, x: float, y: float, tags: tuple = ()) -> None:
    """Draws a red 'IQ' badge centered at (x, y), marking a table that has independent_qualifiers."""
    r = IQ_BADGE_RADIUS
    canvas.create_oval(x - r, y - r, x + r, y + r, fill=IQ_BADGE_COLOR, outline="#7a1f13", tags=tags)
    canvas.create_text(x, y, text="IQ", font=("Segoe UI", 7, "bold"), fill="white", tags=tags)


class SchemaViewerWindow(tk.Toplevel):
    NODE_WIDTH = 170
    NODE_HEIGHT = 60
    LAYER_GAP_Y = 90
    NODE_GAP_X = 30

    def __init__(self, master, schema_path: Path):
        super().__init__(master)
        self.schema_path = Path(schema_path)
        self.title(f"Schema Viewer - {self.schema_path}")
        self.geometry("1000x720")

        self._node_positions: dict[str, tuple[float, float]] = {}
        self._selected_table: str | None = None
        self._tables: dict = {}
        self._relationships: list = []

        self._build_toolbar()
        self._build_diagram_canvas()
        self._build_text_editor()

        self._load_and_render()

    # --- layout ---------------------------------------------------------

    def _build_toolbar(self) -> None:
        toolbar = tk.Frame(self)
        toolbar.pack(fill="x", padx=8, pady=4)
        tk.Button(toolbar, text="Reload", command=self._load_and_render).pack(side="left")
        tk.Button(toolbar, text="Open Containing Folder", command=lambda: _open_containing_folder(self.schema_path)).pack(side="left", padx=8)
        self.status_var = tk.StringVar(value=str(self.schema_path))
        tk.Label(toolbar, textvariable=self.status_var, fg="#333333").pack(side="left", padx=8)

        legend = tk.Frame(self)
        legend.pack(fill="x", padx=8)
        self.show_relationships_var = tk.BooleanVar(value=True)
        self.show_depends_on_var = tk.BooleanVar(value=True)
        tk.Checkbutton(
            legend, text="\u2014 black: relationships (crow's foot = many)", fg=RELATIONSHIP_LINE_COLOR,
            variable=self.show_relationships_var, command=self._render_diagram,
        ).pack(side="left", padx=(0, 16))
        tk.Checkbutton(
            legend, text="- - red: depends_on", fg=DEPENDS_ON_LINE_COLOR,
            variable=self.show_depends_on_var, command=self._render_diagram,
        ).pack(side="left")

    def _build_diagram_canvas(self) -> None:
        paned = tk.PanedWindow(self, orient="horizontal", sashwidth=6)
        paned.pack(fill="both", expand=True, padx=8, pady=4)

        container = tk.Frame(paned)
        container.rowconfigure(0, weight=1)
        container.columnconfigure(0, weight=1)

        h_scroll = tk.Scrollbar(container, orient="horizontal")
        v_scroll = tk.Scrollbar(container, orient="vertical")
        self.canvas = tk.Canvas(container, bg="white", height=440, xscrollcommand=h_scroll.set, yscrollcommand=v_scroll.set)
        h_scroll.config(command=self.canvas.xview)
        v_scroll.config(command=self.canvas.yview)

        self.canvas.grid(row=0, column=0, sticky="nsew")
        v_scroll.grid(row=0, column=1, sticky="ns")
        h_scroll.grid(row=1, column=0, sticky="ew")

        self.canvas.bind("<MouseWheel>", lambda event: self.canvas.yview_scroll(int(-1 * (event.delta / 120)), "units"))
        self.canvas.bind("<Shift-MouseWheel>", lambda event: self.canvas.xview_scroll(int(-1 * (event.delta / 120)), "units"))

        info_frame = tk.Frame(paned)
        tk.Label(info_frame, text="Selected table details:").pack(anchor="w")
        info_scroll = tk.Scrollbar(info_frame, orient="vertical")
        self.info_text = tk.Text(info_frame, width=44, wrap="word", state="disabled", yscrollcommand=info_scroll.set)
        info_scroll.config(command=self.info_text.yview)
        self.info_text.pack(side="left", fill="both", expand=True)
        info_scroll.pack(side="right", fill="y")

        paned.add(container, stretch="always")
        paned.add(info_frame, stretch="never", width=320)

    def _build_text_editor(self) -> None:
        tk.Label(self, text="Raw YAML (read-only - use Open Containing Folder to edit in a text editor):").pack(anchor="w", padx=8)
        text_frame = tk.Frame(self)
        text_frame.pack(fill="both", expand=True, padx=8, pady=(0, 8))
        text_scroll = tk.Scrollbar(text_frame, orient="vertical")
        self.text_editor = tk.Text(text_frame, height=14, wrap="none", yscrollcommand=text_scroll.set)
        text_scroll.config(command=self.text_editor.yview)
        self.text_editor.pack(side="left", fill="both", expand=True)
        text_scroll.pack(side="right", fill="y")

    # --- data / rendering -------------------------------------------------

    def _load_and_render(self) -> None:
        try:
            raw_text = schema_parser.load_schema_raw_text(self.schema_path)
        except Exception as e:
            messagebox.showerror("Failed to load schema", str(e))
            return

        self.text_editor.config(state="normal")
        self.text_editor.delete("1.0", "end")
        self.text_editor.insert("1.0", raw_text)
        self.text_editor.config(state="disabled")
        self.status_var.set(f"Loaded {self.schema_path}")
        self._render_diagram()

    def _render_diagram(self) -> None:
        try:
            schema = schema_parser.load_schema(self.schema_path)
        except Exception as e:
            messagebox.showerror("Failed to parse schema for diagram", str(e))
            return

        tables = schema["tables"]
        relationships = schema["relationships"]
        self._tables = tables
        self._relationships = relationships
        self._selected_table = None
        self._update_info_panel(None)
        self._layout_tables(tables, relationships)
        self._draw_diagram(tables, relationships)

    def _layout_tables(self, tables: dict, relationships: list) -> None:
        # Combine depends_on and relationship "to" targets into one edge set, purely to get a sensible
        # top-to-bottom layout - relationship cardinality/direction is still drawn from the raw data.
        edges: dict[str, set] = {name: set(info["depends_on"]) for name, info in tables.items()}
        for rel in relationships:
            edges.setdefault(rel["from"], set()).add(rel["to"])
            edges.setdefault(rel["to"], set())

        levels: dict[str, int] = {}

        def level_of(node: str, visiting: set) -> int:
            if node in levels:
                return levels[node]
            if node in visiting or node not in edges:
                return 0
            visiting.add(node)
            dependencies = [dep for dep in edges.get(node, ()) if dep in edges]
            level = 0 if not dependencies else 1 + max(level_of(dep, visiting) for dep in dependencies)
            visiting.discard(node)
            levels[node] = level
            return level

        for node in edges:
            level_of(node, set())

        layers: dict[int, list] = {}
        for node, level in levels.items():
            layers.setdefault(level, []).append(node)
        for nodes in layers.values():
            nodes.sort()

        max_layer_size = max((len(nodes) for nodes in layers.values()), default=1)
        canvas_width = max(700, max_layer_size * (self.NODE_WIDTH + self.NODE_GAP_X))

        self._node_positions.clear()
        for level, nodes in layers.items():
            y = 40 + level * (self.NODE_HEIGHT + self.LAYER_GAP_Y)
            total_width = len(nodes) * (self.NODE_WIDTH + self.NODE_GAP_X) - self.NODE_GAP_X
            start_x = (canvas_width - total_width) / 2
            for i, node in enumerate(nodes):
                x = start_x + i * (self.NODE_WIDTH + self.NODE_GAP_X)
                self._node_positions[node] = (x + self.NODE_WIDTH / 2, y + self.NODE_HEIGHT / 2)

        self._canvas_width = canvas_width
        self._canvas_height = 40 + (max(layers, default=0) + 1) * (self.NODE_HEIGHT + self.LAYER_GAP_Y)

    def _draw_diagram(self, tables: dict, relationships: list) -> None:
        c = self.canvas
        c.delete("all")
        half_w, half_h = self.NODE_WIDTH / 2, self.NODE_HEIGHT / 2

        # Red depends_on arrows, offset sideways + dashed so they stay visible where they parallel a
        # relationship line between the same two tables. Drawn first so table boxes sit on top.
        if self.show_depends_on_var.get():
            for table_name, info in tables.items():
                if table_name not in self._node_positions:
                    continue
                x1, y1 = self._node_positions[table_name]
                for dep in info["depends_on"]:
                    if dep not in self._node_positions:
                        continue
                    x2, y2 = self._node_positions[dep]
                    p1 = _clip_point_to_box(x1, y1, half_w, half_h, x2, y2)
                    p2 = _clip_point_to_box(x2, y2, half_w, half_h, x1, y1)
                    p1, p2 = _offset_perpendicular(*p1, *p2, DEPENDS_ON_OFFSET)
                    tags = ("depends_on_item", f"dep_endpoint_{table_name}", f"dep_endpoint_{dep}")
                    c.create_line(*p1, *p2, fill=DEPENDS_ON_LINE_COLOR, width=2, dash=(6, 3), arrow=tk.FIRST, arrowshape=(8, 10, 4), tags=tags)

        # Black crow's-foot relationship lines.
        if self.show_relationships_var.get():
            for rel in relationships:
                from_table, to_table, rel_type = rel.get("from"), rel.get("to"), (rel.get("type") or "").lower()
                if from_table not in self._node_positions or to_table not in self._node_positions:
                    continue
                x1, y1 = self._node_positions[from_table]
                x2, y2 = self._node_positions[to_table]
                p1 = _clip_point_to_box(x1, y1, half_w, half_h, x2, y2)
                p2 = _clip_point_to_box(x2, y2, half_w, half_h, x1, y1)
                tags = ("relationship_item", f"rel_endpoint_{from_table}", f"rel_endpoint_{to_table}")
                c.create_line(*p1, *p2, fill=RELATIONSHIP_LINE_COLOR, width=2, tags=tags)

                dir1 = (p2[0] - p1[0], p2[1] - p1[1])
                dir2 = (p1[0] - p2[0], p1[1] - p2[1])
                if rel_type == "many-to-one":
                    _draw_crow_foot(c, *p1, *dir1, RELATIONSHIP_LINE_COLOR, tags=tags)
                    _draw_one_tick(c, *p2, *dir2, RELATIONSHIP_LINE_COLOR, tags=tags)
                elif rel_type == "one-to-one":
                    _draw_one_tick(c, *p1, *dir1, RELATIONSHIP_LINE_COLOR, tags=tags)
                    _draw_one_tick(c, *p2, *dir2, RELATIONSHIP_LINE_COLOR, tags=tags)

        # Table boxes: name + primary keys.
        for table_name, (cx, cy) in self._node_positions.items():
            x1, y1, x2, y2 = cx - half_w, cy - half_h, cx + half_w, cy + half_h
            box_tag = f"tablebox_{table_name}"
            c.create_rectangle(x1, y1, x2, y2, fill=TABLE_BOX_COLOR, outline=TABLE_OUTLINE_COLOR, width=2, tags=box_tag)
            c.create_line(x1, cy - 10, x2, cy - 10, fill=TABLE_OUTLINE_COLOR, tags=box_tag)
            c.create_text(cx, y1 + 12, text=table_name, font=("Segoe UI", 9, "bold"), tags=box_tag)
            primary_keys = tables.get(table_name, {}).get("primary_keys", [])
            pk_text = "PK: " + ", ".join(primary_keys) if primary_keys else "(no primary_keys)"
            c.create_text(cx, cy + (half_h - 10) / 2, text=pk_text, font=("Segoe UI", 7), width=self.NODE_WIDTH - 10, tags=box_tag)
            c.tag_bind(box_tag, "<Button-1>", lambda event, t=table_name: self._on_table_click(t))
            if tables.get(table_name, {}).get("independent_qualifiers"):
                _draw_iq_marker(c, x2, y1, tags=box_tag)

        c.configure(scrollregion=(0, 0, self._canvas_width, self._canvas_height))

    def _on_table_click(self, table_name: str) -> None:
        c = self.canvas
        c.itemconfigure("relationship_item", fill=RELATIONSHIP_LINE_COLOR)
        c.itemconfigure("depends_on_item", fill=DEPENDS_ON_LINE_COLOR)

        if self._selected_table == table_name:
            self._selected_table = None
            self._update_info_panel(None)
            return

        self._selected_table = table_name
        c.itemconfigure(f"rel_endpoint_{table_name}", fill=RELATIONSHIP_HIGHLIGHT_COLOR)
        c.itemconfigure(f"dep_endpoint_{table_name}", fill=DEPENDS_ON_HIGHLIGHT_COLOR)
        self._update_info_panel(table_name)

    def _relationships_between(self, table_a: str, table_b: str) -> list:
        return [rel for rel in self._relationships if {rel.get("from"), rel.get("to")} == {table_a, table_b}]

    @staticmethod
    def _describe_relationship(rel: dict) -> str:
        details = [f"type={rel.get('type', '?')}"]
        if rel.get("on_field"):
            details.append(f"on_field={rel['on_field']}")
        if rel.get("foreign_key_in_to"):
            details.append(f"foreign_key_in_to={rel['foreign_key_in_to']}")
        return f"{rel.get('from')} -> {rel.get('to')} ({', '.join(details)})"

    def _describe_related_table(self, table_name: str, other_table: str) -> list:
        lines = [f"  - {other_table}"]
        rels = self._relationships_between(table_name, other_table)
        if not rels:
            lines.append("      (no matching relationship entry)")
        for rel in rels:
            lines.append(f"      {self._describe_relationship(rel)}")
        return lines

    def _update_info_panel(self, table_name) -> None:
        self.info_text.config(state="normal")
        self.info_text.delete("1.0", "end")

        if table_name is not None:
            prerequisite_tables = sorted(self._tables.get(table_name, {}).get("depends_on", []))
            dependent_tables = sorted(
                other for other, info in self._tables.items() if table_name in info.get("depends_on", [])
            )

            lines = [f"Selected table: {table_name}", ""]
            lines.append(f"Prerequisite tables ({len(prerequisite_tables)}):")
            if not prerequisite_tables:
                lines.append("  (none)")
            for dep in prerequisite_tables:
                lines.extend(self._describe_related_table(table_name, dep))
            lines.append("")
            lines.append(f"Dependent tables ({len(dependent_tables)}):")
            if not dependent_tables:
                lines.append("  (none)")
            for dep in dependent_tables:
                lines.extend(self._describe_related_table(table_name, dep))

            self.info_text.insert("1.0", "\n".join(lines))

        self.info_text.config(state="disabled")
