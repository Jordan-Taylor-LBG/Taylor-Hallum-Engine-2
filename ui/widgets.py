"""Shared, reusable Tk widgets: the 24-hour run-window ClockWidget and the CalendarPopup date picker."""

import calendar
import math
import tkinter as tk
from datetime import date, time

CHECKPOINT_COLOR = "#2ca02c"
START_HAND_COLOR = "#1f77b4"
END_HAND_COLOR = "#d62728"
CURRENT_TIME_HAND_COLOR = "#9467bd"
RUN_PERIOD_SHADE_COLOR = "#fff2cc"


class ClockWidget(tk.Frame):
    """
    A single 24-hour analog clock face.
      - Drag the blue (start) or red (end) hand - whichever is nearer the click - to set the daily active
        run period, shown shaded.
      - Right-click adds a snapshot+delta checkpoint at the clicked time; right-clicking an existing
        checkpoint removes it instead.
      - When interactive=False (used by the step-through window), dragging/right-click are disabled and a
        third, purple hand can be set via set_current_time() to show the current simulated time.
    """

    RADIUS = 90
    CHECKPOINT_REMOVE_TOLERANCE_DEGREES = 6

    def __init__(self, master, start_time: time, end_time: time, checkpoint_times: list[time] = None, on_change=None, interactive: bool = True):
        super().__init__(master)
        self.on_change = on_change
        self.interactive = interactive
        self.start_time = start_time
        self.end_time = end_time
        self.checkpoint_times: list[time] = sorted(checkpoint_times or [])
        self.current_time: time | None = None
        self._dragging_hand: str | None = None

        tk.Label(self, text="Run window", font=("Segoe UI", 9, "bold")).pack()
        size = self.RADIUS * 2 + 24
        self.center = size / 2
        self.canvas = tk.Canvas(self, width=size, height=size, bg="white", highlightthickness=0)
        self.canvas.pack()
        self.time_label = tk.Label(self, text=self._format_times(), font=("Segoe UI", 10))
        self.time_label.pack()

        if self.interactive:
            tk.Label(
                self,
                text="Drag blue/red hands: daily start/end time\nRight-click: add/remove a snapshot+delta checkpoint",
                font=("Segoe UI", 7), fg="#666666", justify="center",
            ).pack()
            self.canvas.bind("<Button-1>", self._on_left_click)
            self.canvas.bind("<B1-Motion>", self._on_left_drag)
            self.canvas.bind("<Button-3>", self._on_right_click)

        self._draw()

    def _format_times(self) -> str:
        base = f"{self.start_time.strftime('%H:%M')} \u2192 {self.end_time.strftime('%H:%M')}  |  {len(self.checkpoint_times)} checkpoint(s)"
        if self.current_time is not None:
            base += f"  |  now: {self.current_time.strftime('%H:%M:%S')}"
        return base

    def _fraction_for_time(self, t: time) -> float:
        return (t.hour * 3600 + t.minute * 60) / 86400

    def _angle_for_time(self, t: time) -> float:
        """Degrees clockwise from 12 o'clock."""
        return self._fraction_for_time(t) * 360

    def _angular_distance_degrees(self, a: float, b: float) -> float:
        diff = abs(a - b) % 360
        return min(diff, 360 - diff)

    def _time_from_event(self, event) -> time:
        dx, dy = event.x - self.center, event.y - self.center
        angle_deg = (math.degrees(math.atan2(dy, dx)) + 90) % 360
        total_minutes = round((angle_deg / 360 * 24 * 60) / 5) * 5 % (24 * 60)
        hour, minute = divmod(total_minutes, 60)
        return time(hour=hour, minute=minute)

    def set_checkpoint_times(self, checkpoint_times: list[time]) -> None:
        self.checkpoint_times = sorted(checkpoint_times)
        self.time_label.config(text=self._format_times())
        self._draw()

    def set_run_period(self, start_time: time, end_time: time) -> None:
        self.start_time = start_time
        self.end_time = end_time
        self.time_label.config(text=self._format_times())
        self._draw()

    def set_current_time(self, current_time: time) -> None:
        self.current_time = current_time
        self.time_label.config(text=self._format_times())
        self._draw()

    def _draw(self) -> None:
        c = self.canvas
        c.delete("all")
        r = self.RADIUS
        cx = cy = self.center

        # Shaded arc showing the daily active run period, swept clockwise from start_time to end_time.
        start_fraction, end_fraction = self._fraction_for_time(self.start_time), self._fraction_for_time(self.end_time)
        tk_start_angle = 90 - start_fraction * 360
        tk_extent = -((end_fraction - start_fraction) % 1) * 360
        c.create_arc(cx - r, cy - r, cx + r, cy + r, start=tk_start_angle, extent=tk_extent, fill=RUN_PERIOD_SHADE_COLOR, outline="")

        c.create_oval(cx - r, cy - r, cx + r, cy + r, outline="black", width=2)

        for hour in range(0, 24, 2):
            angle = math.radians(hour / 24 * 360 - 90)
            x1, y1 = cx + (r - 8) * math.cos(angle), cy + (r - 8) * math.sin(angle)
            x2, y2 = cx + r * math.cos(angle), cy + r * math.sin(angle)
            c.create_line(x1, y1, x2, y2, width=2)
            lx, ly = cx + (r - 20) * math.cos(angle), cy + (r - 20) * math.sin(angle)
            c.create_text(lx, ly, text=str(hour), font=("Segoe UI", 7))

        for checkpoint_time in self.checkpoint_times:
            angle = math.radians(self._angle_for_time(checkpoint_time) - 90)
            mx, my = cx + (r - 4) * math.cos(angle), cy + (r - 4) * math.sin(angle)
            c.create_oval(mx - 4, my - 4, mx + 4, my + 4, fill=CHECKPOINT_COLOR, outline="black")

        for hand_time, color in ((self.start_time, START_HAND_COLOR), (self.end_time, END_HAND_COLOR)):
            angle = math.radians(self._angle_for_time(hand_time) - 90)
            hx, hy = cx + (r - 12) * math.cos(angle), cy + (r - 12) * math.sin(angle)
            c.create_line(cx, cy, hx, hy, width=3, fill=color)

        if self.current_time is not None:
            angle = math.radians(self._angle_for_time(self.current_time) - 90)
            hx, hy = cx + (r - 24) * math.cos(angle), cy + (r - 24) * math.sin(angle)
            c.create_line(cx, cy, hx, hy, width=2, fill=CURRENT_TIME_HAND_COLOR)
            c.create_oval(hx - 4, hy - 4, hx + 4, hy + 4, fill=CURRENT_TIME_HAND_COLOR, outline="")

        c.create_oval(cx - 3, cy - 3, cx + 3, cy + 3, fill="black")

    def _on_left_click(self, event) -> None:
        picked_angle = self._angle_for_time(self._time_from_event(event))
        start_angle, end_angle = self._angle_for_time(self.start_time), self._angle_for_time(self.end_time)
        distance_to_start = self._angular_distance_degrees(picked_angle, start_angle)
        distance_to_end = self._angular_distance_degrees(picked_angle, end_angle)
        self._dragging_hand = "start" if distance_to_start <= distance_to_end else "end"
        self._on_left_drag(event)

    def _on_left_drag(self, event) -> None:
        if self._dragging_hand is None:
            return
        picked_time = self._time_from_event(event)
        if self._dragging_hand == "start":
            self.start_time = picked_time
        else:
            self.end_time = picked_time
        self.time_label.config(text=self._format_times())
        self._draw()
        if self.on_change:
            self.on_change()

    def _on_right_click(self, event) -> None:
        picked_time = self._time_from_event(event)
        picked_angle = self._angle_for_time(picked_time)

        existing = next(
            (t for t in self.checkpoint_times if self._angular_distance_degrees(self._angle_for_time(t), picked_angle) <= self.CHECKPOINT_REMOVE_TOLERANCE_DEGREES),
            None,
        )
        if existing is not None:
            self.checkpoint_times.remove(existing)
        else:
            self.checkpoint_times = sorted(self.checkpoint_times + [picked_time])

        self.time_label.config(text=self._format_times())
        self._draw()
        if self.on_change:
            self.on_change()


class CalendarPopup(tk.Toplevel):
    """Simple month-grid date picker."""

    def __init__(self, master, initial_date: date, on_select):
        super().__init__(master)
        self.title("Select start date")
        self.resizable(False, False)
        self.on_select = on_select
        self.current_year = initial_date.year
        self.current_month = initial_date.month

        nav = tk.Frame(self)
        nav.pack(fill="x")
        tk.Button(nav, text="<", command=self._prev_month).pack(side="left")
        self.month_label = tk.Label(nav, width=16, anchor="center")
        self.month_label.pack(side="left", expand=True)
        tk.Button(nav, text=">", command=self._next_month).pack(side="right")

        self.days_frame = tk.Frame(self)
        self.days_frame.pack(padx=4, pady=4)

        self._render()

    def _prev_month(self) -> None:
        self.current_month -= 1
        if self.current_month < 1:
            self.current_month, self.current_year = 12, self.current_year - 1
        self._render()

    def _next_month(self) -> None:
        self.current_month += 1
        if self.current_month > 12:
            self.current_month, self.current_year = 1, self.current_year + 1
        self._render()

    def _render(self) -> None:
        for widget in self.days_frame.winfo_children():
            widget.destroy()

        self.month_label.config(text=f"{calendar.month_name[self.current_month]} {self.current_year}")

        for col, day_name in enumerate(["Mo", "Tu", "We", "Th", "Fr", "Sa", "Su"]):
            tk.Label(self.days_frame, text=day_name, width=3).grid(row=0, column=col)

        for row, week in enumerate(calendar.Calendar(firstweekday=0).monthdayscalendar(self.current_year, self.current_month), start=1):
            for col, day in enumerate(week):
                if day == 0:
                    tk.Label(self.days_frame, text="", width=3).grid(row=row, column=col)
                else:
                    tk.Button(self.days_frame, text=str(day), width=3, command=lambda d=day: self._select(d)).grid(row=row, column=col)

    def _select(self, day: int) -> None:
        self.on_select(date(self.current_year, self.current_month, day))
        self.destroy()
