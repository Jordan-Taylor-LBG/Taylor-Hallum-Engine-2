"""Small canvas-drawing helpers for the 'update'/'macro' CRUD badges shown on DagWindow nodes."""

import math
import tkinter as tk

UPDATE_BADGE_COLOR = "#2e8b57"
UPDATE_BADGE_OUTLINE = "#1b5e20"
MACRO_BADGE_COLOR = "#757575"
MACRO_BADGE_OUTLINE = "#3d3d3d"
BADGE_X_OFFSET = 20


def draw_update_badge(canvas: tk.Canvas, cx: float, cy: float, filled: bool, tags: tuple = ()) -> None:
    """Draws a small circular-arrows 'update' icon centered at (cx, cy) - outlined green when a table is
    up for update in a possible action, filled green once that action has actually been selected."""
    radius = 9
    if filled:
        canvas.create_oval(cx - radius, cy - radius, cx + radius, cy + radius, fill=UPDATE_BADGE_COLOR, outline=UPDATE_BADGE_OUTLINE, width=1, tags=tags)
        stroke_color = "white"
    else:
        canvas.create_oval(cx - radius, cy - radius, cx + radius, cy + radius, fill="white", outline=UPDATE_BADGE_COLOR, width=2, tags=tags)
        stroke_color = UPDATE_BADGE_COLOR

    arc_radius = radius - 3
    for start_angle in (15, 195):
        canvas.create_arc(
            cx - arc_radius, cy - arc_radius, cx + arc_radius, cy + arc_radius,
            start=start_angle, extent=150, style="arc", outline=stroke_color, width=2, tags=tags,
        )
        tip_angle = math.radians(start_angle + 150)
        tip_x, tip_y = cx + arc_radius * math.cos(tip_angle), cy - arc_radius * math.sin(tip_angle)
        tangent = tip_angle + math.radians(90)
        p1 = (tip_x + 3 * math.cos(tangent + 2.6), tip_y - 3 * math.sin(tangent + 2.6))
        p2 = (tip_x + 3 * math.cos(tangent - 2.6), tip_y - 3 * math.sin(tangent - 2.6))
        canvas.create_polygon(tip_x, tip_y, *p1, *p2, fill=stroke_color, outline=stroke_color, tags=tags)


def draw_macro_badge(canvas: tk.Canvas, cx: float, cy: float, filled: bool, tags: tuple = ()) -> None:
    """Draws a small grey gear 'macro' icon centered at (cx, cy) - outlined when a table is up for a macro
    in a possible action, filled once that action has actually been selected."""
    radius = 9
    if filled:
        canvas.create_oval(cx - radius, cy - radius, cx + radius, cy + radius, fill=MACRO_BADGE_COLOR, outline=MACRO_BADGE_OUTLINE, width=1, tags=tags)
        stroke_color = "white"
    else:
        canvas.create_oval(cx - radius, cy - radius, cx + radius, cy + radius, fill="white", outline=MACRO_BADGE_COLOR, width=2, tags=tags)
        stroke_color = MACRO_BADGE_COLOR

    body_radius = radius - 4
    tooth_span = 2
    for i in range(8):
        angle = math.radians(i * 45)
        x1, y1 = cx + body_radius * math.cos(angle), cy - body_radius * math.sin(angle)
        x2, y2 = cx + (body_radius + tooth_span) * math.cos(angle), cy - (body_radius + tooth_span) * math.sin(angle)
        canvas.create_line(x1, y1, x2, y2, fill=stroke_color, width=2, tags=tags)

    canvas.create_oval(cx - body_radius, cy - body_radius, cx + body_radius, cy + body_radius, outline=stroke_color, width=1.5, tags=tags)
    hole_radius = 2
    canvas.create_oval(cx - hole_radius, cy - hole_radius, cx + hole_radius, cy + hole_radius, fill=stroke_color, outline=stroke_color, tags=tags)
