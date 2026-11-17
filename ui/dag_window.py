"""Visualises a table-dependency DAG (DagWindow) - a Toplevel window used by App and StepThroughWindow."""

import tkinter as tk

from ui.badges import BADGE_X_OFFSET, draw_macro_badge, draw_update_badge


class DagWindow(tk.Toplevel):
    """
    Visualises a table-dependency DAG (as returned by Engine.get_table_dependency_dag()) in a scrollable
    canvas, laid out top-to-bottom by dependency depth. All tables start grey; once a table has been
    orchestrated (mark_orchestrated()) it turns permanently blue. Exposes highlight_nodes()/clear_highlights()
    and highlight_outlines()/clear_outlines() for temporary decoration (e.g. showing possible actions), so
    other windows (e.g. StepThroughWindow) can interact with it without any knowledge of the engine themselves
    - they only ever pass table names in.
    """

    NODE_WIDTH = 120
    NODE_HEIGHT = 34
    LAYER_GAP_Y = 70
    NODE_GAP_X = 20
    DEFAULT_NODE_COLOR = "#d9d9d9"
    HIGHLIGHT_COLOR = "#ff7f0e"
    ORCHESTRATED_COLOR = "#4a90d9"
    DEFAULT_OUTLINE_COLOR = "#333333"
    OUTLINE_HIGHLIGHT_COLOR = "#ff7f0e"
    IQ_BADGE_COLOR = "#e74c3c"
    IQ_BADGE_RADIUS = 9

    def __init__(self, master, dag: dict, independent_qualifier_tables=None):
        super().__init__(master)
        self.title("Table Dependency DAG")
        self.geometry("900x600")
        self.dag = dag
        self._iq_tables = set(independent_qualifier_tables or [])
        self._node_boxes: dict[str, int] = {}
        self._node_positions: dict[str, tuple[float, float]] = {}
        self._orchestrated_nodes: set = set()

        container = tk.Frame(self)
        container.pack(fill="both", expand=True)
        container.rowconfigure(0, weight=1)
        container.columnconfigure(0, weight=1)

        h_scroll = tk.Scrollbar(container, orient="horizontal")
        v_scroll = tk.Scrollbar(container, orient="vertical")
        self.canvas = tk.Canvas(container, bg="white", xscrollcommand=h_scroll.set, yscrollcommand=v_scroll.set)
        h_scroll.config(command=self.canvas.xview)
        v_scroll.config(command=self.canvas.yview)

        self.canvas.grid(row=0, column=0, sticky="nsew")
        v_scroll.grid(row=0, column=1, sticky="ns")
        h_scroll.grid(row=1, column=0, sticky="ew")

        self.canvas.bind("<MouseWheel>", lambda event: self.canvas.yview_scroll(int(-1 * (event.delta / 120)), "units"))
        self.canvas.bind("<Shift-MouseWheel>", lambda event: self.canvas.xview_scroll(int(-1 * (event.delta / 120)), "units"))

        self._layout_and_draw()

    def _compute_levels(self) -> dict:
        """Level(node) = 0 if it has no dependencies, else 1 + max(level(dependency))."""
        levels: dict[str, int] = {}

        def level_of(node: str, visiting: set) -> int:
            if node in levels:
                return levels[node]
            if node in visiting:
                return 0  # defensive: Engine already guarantees the DAG is acyclic

            visiting.add(node)
            dependencies = self.dag.get(node, [])
            level = 0 if not dependencies else 1 + max(level_of(dep, visiting) for dep in dependencies)
            visiting.discard(node)
            levels[node] = level
            return level

        for node in self.dag:
            level_of(node, set())
        return levels

    def _layout_and_draw(self) -> None:
        levels = self._compute_levels()

        layers: dict[int, list] = {}
        for node, level in levels.items():
            layers.setdefault(level, []).append(node)
        for nodes in layers.values():
            nodes.sort()

        max_layer_size = max((len(nodes) for nodes in layers.values()), default=1)
        canvas_width = max(600, max_layer_size * (self.NODE_WIDTH + self.NODE_GAP_X))

        for level, nodes in layers.items():
            y = 40 + level * (self.NODE_HEIGHT + self.LAYER_GAP_Y)
            total_width = len(nodes) * (self.NODE_WIDTH + self.NODE_GAP_X) - self.NODE_GAP_X
            start_x = (canvas_width - total_width) / 2
            for i, node in enumerate(nodes):
                x = start_x + i * (self.NODE_WIDTH + self.NODE_GAP_X)
                self._node_positions[node] = (x + self.NODE_WIDTH / 2, y + self.NODE_HEIGHT / 2)

        c = self.canvas
        c.delete("all")
        self._node_boxes.clear()

        # Edges first, so node boxes are drawn on top of them. Each edge runs from the dependent node's near
        # (top) edge to its dependency's near (bottom) edge, with the arrowhead landing on the dependency -
        # i.e. arrows point from a table's dependency down to the table that depends on it.
        for node, dependencies in self.dag.items():
            if node not in self._node_positions:
                continue
            x1, y1 = self._node_positions[node]
            for dependency in dependencies:
                if dependency not in self._node_positions:
                    continue
                x2, y2 = self._node_positions[dependency]
                c.create_line(x1, y1 - self.NODE_HEIGHT / 2, x2, y2 + self.NODE_HEIGHT / 2, arrow=tk.FIRST, arrowshape=(10, 12, 4), fill="#999999")

        for node, (cx, cy) in self._node_positions.items():
            x1, y1 = cx - self.NODE_WIDTH / 2, cy - self.NODE_HEIGHT / 2
            x2, y2 = cx + self.NODE_WIDTH / 2, cy + self.NODE_HEIGHT / 2
            box = c.create_rectangle(x1, y1, x2, y2, fill=self.DEFAULT_NODE_COLOR, outline=self.DEFAULT_OUTLINE_COLOR)
            c.create_text(cx, cy, text=node, font=("Segoe UI", 8))
            self._node_boxes[node] = box
            if node in self._iq_tables:
                r = self.IQ_BADGE_RADIUS
                c.create_oval(x2 - r, y1 - r, x2 + r, y1 + r, fill=self.IQ_BADGE_COLOR, outline="#7a1f13")
                c.create_text(x2, y1, text="IQ", font=("Segoe UI", 6, "bold"), fill="white")

        max_y = 40 + (max(layers, default=0) + 1) * (self.NODE_HEIGHT + self.LAYER_GAP_Y)
        c.configure(scrollregion=(0, 0, canvas_width, max_y))

    def highlight_nodes(self, node_names, color: str = HIGHLIGHT_COLOR) -> None:
        self.clear_highlights()
        for node in node_names:
            box = self._node_boxes.get(node)
            if box is not None:
                self.canvas.itemconfig(box, fill=color)

    def clear_highlights(self) -> None:
        # Orchestrated nodes keep their permanent blue - only temporary highlights are cleared.
        for node, box in self._node_boxes.items():
            if node not in self._orchestrated_nodes:
                self.canvas.itemconfig(box, fill=self.DEFAULT_NODE_COLOR)

    def highlight_outlines(self, node_names, color: str = OUTLINE_HIGHLIGHT_COLOR, width: int = 3) -> None:
        self.clear_outlines()
        for node in node_names:
            box = self._node_boxes.get(node)
            if box is not None:
                self.canvas.itemconfig(box, outline=color, width=width)

    def clear_outlines(self) -> None:
        for box in self._node_boxes.values():
            self.canvas.itemconfig(box, outline=self.DEFAULT_OUTLINE_COLOR, width=1)

    # Permanently marks node_names as orchestrated (blue); unlike highlight_nodes(), this is never reset by
    # clear_highlights().
    def mark_orchestrated(self, node_names) -> None:
        self._orchestrated_nodes.update(node_names)
        for node in node_names:
            box = self._node_boxes.get(node)
            if box is not None:
                self.canvas.itemconfig(box, fill=self.ORCHESTRATED_COLOR)

    # Outlined green 'update' icon - tables up for CRUD=update across all currently possible actions.
    def show_update_badges(self, node_names) -> None:
        self.clear_update_badges()
        for node in node_names:
            if node in self._node_positions:
                draw_update_badge(self.canvas, *self._node_positions[node], filled=False, tags=("update_badge",))

    # Filled green 'update' icon - tables up for CRUD=update in the one action that was actually selected.
    def fill_update_badges(self, node_names) -> None:
        self.clear_update_badges()
        for node in node_names:
            if node in self._node_positions:
                draw_update_badge(self.canvas, *self._node_positions[node], filled=True, tags=("update_badge",))

    def clear_update_badges(self) -> None:
        self.canvas.delete("update_badge")

    # Outlined grey gear 'macro' icon (to the right of the update badge) - tables up for CRUD=macro across
    # all currently possible actions.
    def show_macro_badges(self, node_names) -> None:
        self.clear_macro_badges()
        for node in node_names:
            if node in self._node_positions:
                cx, cy = self._node_positions[node]
                draw_macro_badge(self.canvas, cx + BADGE_X_OFFSET, cy, filled=False, tags=("macro_badge",))

    # Filled grey gear 'macro' icon - tables up for CRUD=macro in the one action that was actually selected.
    def fill_macro_badges(self, node_names) -> None:
        self.clear_macro_badges()
        for node in node_names:
            if node in self._node_positions:
                cx, cy = self._node_positions[node]
                draw_macro_badge(self.canvas, cx + BADGE_X_OFFSET, cy, filled=True, tags=("macro_badge",))

    def clear_macro_badges(self) -> None:
        self.canvas.delete("macro_badge")
