"""Reusable widgets. Styling decisions live in theme.py / DESIGN.md; nothing here picks a colour or size itself."""
from __future__ import annotations

import tkinter as tk

import customtkinter as ctk

import theme as T

# ── formatting ──────────────────────────────────────────────────────────────────────

def fmt_time(sec: float) -> str:
    sec = max(0, int(round(sec)))
    h, m, s = sec // 3600, sec % 3600 // 60, sec % 60
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def nice_step(duration: float, width_px: int, min_px: int = 96) -> int:
    """Seconds between time-axis ticks so labels are at least min_px apart."""
    per_px = duration / max(width_px, 1)
    for step in (1, 2, 5, 10, 15, 30, 60, 120, 300, 600, 900, 1800, 3600, 7200):
        if step / per_px >= min_px:
            return step
    return 7200


# ── text ────────────────────────────────────────────────────────────────────────────

def label(parent, text="", role="body", color=T.CHALK, **kw):
    return ctk.CTkLabel(parent, text=text, font=T.font(ctk, role), text_color=color, **kw)


class Caption(ctk.CTkLabel):
    """Secondary text that wraps. CTkLabel keeps a fixed height, so a wrapped line would be clipped;
    this resizes the label to the lines it actually needs whenever the text changes."""

    def __init__(self, parent, text="", wraplength=0, **kw):
        super().__init__(parent, text=text, font=T.font(ctk, "caption"), text_color=T.DUST,
                         wraplength=wraplength, justify="left", anchor="w", **kw)
        self._wrap = wraplength
        self._fit()

    def configure(self, require_redraw=False, **kw):
        super().configure(require_redraw=require_redraw, **kw)
        if "text" in kw or "wraplength" in kw:
            self._fit()

    def _fit(self):
        if not self._wrap:
            return
        try:
            self.update_idletasks()
            scale = ctk.ScalingTracker.get_widget_scaling(self)
            need = self._label.winfo_reqheight() / scale
            super().configure(height=max(int(need) + 2, 18))
        except Exception:
            pass


def caption(parent, text="", wraplength=0, **kw):
    return Caption(parent, text=text, wraplength=wraplength, **kw)


# ── controls ────────────────────────────────────────────────────────────────────────

class Btn(ctk.CTkButton):
    """Button with four roles. Yellow is reserved for the one primary action on a screen."""

    _STYLE = {
        # kind: (on: fg, hover, text, border) / (off: fg, text, border)
        "primary": (T.PENCIL, T.PENCIL_HOVER, T.PENCIL_INK, None, T.EDGE, T.DUST, None),
        "secondary": (T.EDGE, T.RAISED, T.CHALK, None, "transparent", T.DUST, T.EDGE),
        "danger": ("transparent", T.blend(T.CUT, T.PANEL, 0.18), T.CUT, T.CUT, "transparent", T.DUST, T.EDGE),
        "ghost": ("transparent", T.RAISED, T.DUST, None, "transparent", T.EDGE, None),
    }

    def __init__(self, parent, text, command=None, kind="secondary", width=0, height=34, **kw):
        self.kind = kind
        super().__init__(parent, text=text, command=command, width=width, height=height,
                         corner_radius=T.R_CONTROL, font=T.font(ctk, "label"), **kw)
        self.enable(True)

    def enable(self, on: bool = True) -> None:
        fg, hover, text, border, off_fg, off_text, off_border = self._STYLE[self.kind]
        if on:
            self.configure(state="normal", fg_color=fg, hover_color=hover, text_color=text,
                           border_width=1 if border else 0, border_color=border or T.EDGE)
        else:
            self.configure(state="disabled", fg_color=off_fg, hover_color=off_fg if off_fg != "transparent" else T.EDGE,
                           text_color=off_text,
                           text_color_disabled=off_text, border_width=1 if off_border else 0,
                           border_color=off_border or T.EDGE)


class Choice(ctk.CTkSegmentedButton):
    """Segmented choice that works with stable keys; labels can change with the language."""

    def __init__(self, parent, options: dict, command=None, height=32, **kw):
        self._choices = dict(options)
        self._on_pick = command
        super().__init__(parent, values=list(options.values()), command=self._clicked_key, height=height,
                         corner_radius=T.R_CONTROL, border_width=3, fg_color=T.WELL,
                         selected_color=T.PENCIL, selected_hover_color=T.PENCIL_HOVER,
                         unselected_color=T.WELL, unselected_hover_color=T.EDGE,
                         text_color=T.CHALK, text_color_disabled=T.DUST,
                         font=T.font(ctk, "label"), **kw)
        self.set(next(iter(options.values())))
        self._restyle()

    def _restyle(self) -> None:
        # One text colour per segment: the selected (yellow) segment needs dark ink, the others chalk.
        selected = self.get()
        for value, button in getattr(self, "_buttons_dict", {}).items():
            try:
                button.configure(text_color=T.PENCIL_INK if value == selected else T.CHALK)
            except Exception:
                pass

    def _clicked_key(self, display: str) -> None:
        self._restyle()
        if self._on_pick:
            self._on_pick(self.get_key())

    def get_key(self):
        shown = self.get()
        return next((k for k, v in self._choices.items() if v == shown), None)

    def set_key(self, key) -> None:
        if key in self._choices:
            self.set(self._choices[key])
            self._restyle()

    def relabel(self, options: dict) -> None:
        key = self.get_key()
        self._choices = dict(options)
        self.configure(values=list(options.values()))
        if key in options:
            self.set(options[key])
        self._restyle()

    def enable(self, on: bool = True) -> None:
        self.configure(state="normal" if on else "disabled")
        self._restyle()


def entry(parent, textvariable=None, width=0, placeholder="", mono=False, justify="left"):
    e = ctk.CTkEntry(parent, textvariable=textvariable, width=width, height=32, corner_radius=T.R_CONTROL,
                     fg_color=T.WELL, border_color=T.EDGE, border_width=1, text_color=T.CHALK,
                     placeholder_text=placeholder, placeholder_text_color=T.DUST,
                     font=T.font(ctk, "mono" if mono else "body"), justify=justify)
    e.bind("<FocusIn>", lambda _e: e.configure(border_color=T.PENCIL), add="+")
    e.bind("<FocusOut>", lambda _e: e.configure(border_color=T.EDGE), add="+")
    return e


def menu(parent, values, command=None, width=200, variable=None):
    return ctk.CTkOptionMenu(parent, values=list(values), command=command, variable=variable, width=width,
                             height=32, corner_radius=T.R_CONTROL, fg_color=T.WELL, button_color=T.EDGE,
                             button_hover_color=T.RAISED, text_color=T.CHALK, text_color_disabled=T.DUST,
                             dropdown_fg_color=T.PANEL, dropdown_hover_color=T.RAISED,
                             dropdown_text_color=T.CHALK, font=T.font(ctk, "body"),
                             dropdown_font=T.font(ctk, "body"), anchor="w")


def switch(parent, text, variable, command=None):
    return ctk.CTkSwitch(parent, text=text, variable=variable, command=command, font=T.font(ctk, "body"),
                         text_color=T.CHALK, text_color_disabled=T.DUST, fg_color=T.EDGE,
                         progress_color=T.PENCIL, button_color=T.CHALK, button_hover_color=T.PENCIL_HOVER,
                         switch_width=36, switch_height=18)


def slider(parent, from_, to, steps, variable, command=None, width=260):
    return ctk.CTkSlider(parent, from_=from_, to=to, number_of_steps=steps, variable=variable, command=command,
                         width=width, height=16, fg_color=T.WELL, progress_color=T.KEEP, button_color=T.CHALK,
                         button_hover_color=T.PENCIL)


# ── brand mark: a film strip with a cut ─────────────────────────────────────────────

class Logo(tk.Canvas):
    def __init__(self, parent, size=30, bg=T.BENCH):
        super().__init__(parent, width=size, height=size, bg=bg, highlightthickness=0, bd=0)
        s = size / 30
        def p(*pts):
            return [v * s for v in pts]
        self.create_polygon(p(3, 9, 15, 9, 11, 21, 3, 21), outline=T.CHALK, fill="", width=2)
        self.create_polygon(p(19, 9, 27, 9, 27, 21, 15, 21), outline=T.CHALK, fill="", width=2)
        self.create_line(p(18, 5, 9, 25), fill=T.PENCIL, width=3, capstyle="round")


# ── the monitor strip: what will be cut ─────────────────────────────────────────────

class CutMap(ctk.CTkFrame):
    """Waveform with the removed / sped-up spans marked. Also the drop target while no file is chosen."""

    HEIGHT = 132
    RULER = 8

    def __init__(self, parent, text_fn, on_click=None):
        super().__init__(parent, fg_color=T.WELL, corner_radius=T.R_STRIP)
        self._t = text_fn
        self._on_click = on_click
        self._state = "empty"
        self._error = ""
        self._peaks = None
        self._regions: list = []
        self._duration = 0.0
        self._stale = False
        self._hover_x: int | None = None
        self.canvas = tk.Canvas(self, height=self.HEIGHT, bg=T.WELL, highlightthickness=0, bd=0)
        self.canvas.pack(fill="x")
        self.canvas.bind("<Configure>", lambda _e: self.redraw())
        self.canvas.bind("<Motion>", self._motion)
        self.canvas.bind("<Leave>", lambda _e: self._set_hover(None))
        self.canvas.bind("<Button-1>", self._click)

    # state
    def set_empty(self):
        self._state, self._peaks, self._regions = "empty", None, []
        self.redraw()

    def set_busy(self):
        self._state = "busy"
        self.redraw()

    def set_error(self, msg: str):
        self._state, self._error = "error", msg
        self.redraw()

    def set_data(self, peaks, regions, duration: float):
        self._state, self._peaks, self._regions, self._duration, self._stale = "ready", peaks, regions, duration, False
        self.redraw()

    def set_stale(self, stale: bool):
        if self._state == "ready" and stale != self._stale:
            self._stale = stale
            self.redraw()

    @property
    def has_data(self) -> bool:
        return self._state == "ready"

    # input
    def _click(self, _e):
        if self._state == "empty" and self._on_click:
            self._on_click()

    def _kind_at(self, x: int):
        w = max(self.canvas.winfo_width(), 1)
        t = x / w * self._duration
        for s, e, kind in self._regions:
            if s <= t < e:
                return kind
        return None

    def _motion(self, e):
        if self._state == "ready":
            self._set_hover(e.x)
        elif self._state == "empty":
            self.canvas.configure(cursor="hand2")

    def _set_hover(self, x):
        if x != self._hover_x:
            self._hover_x = x
            self.redraw()

    # drawing
    def redraw(self):
        c = self.canvas
        c.delete("all")
        w, h = c.winfo_width(), c.winfo_height()
        if w < 60:
            return
        if self._state == "ready" and self._peaks is not None and self._duration > 0:
            self._draw_wave(w, h)
            if self._stale:
                self._draw_chip(w // 2, h // 2, self._t("map_stale"), T.PENCIL)
        elif self._state == "empty":
            c.create_rectangle(6, 6, w - 6, h - 6, outline=T.EDGE, dash=(5, 4), width=1)
            c.create_text(w // 2, h // 2 - 12, text=self._t("map_empty_1"), fill=T.CHALK, font=T.font(ctk, "title"))
            c.create_text(w // 2, h // 2 + 14, text=self._t("map_empty_2"), fill=T.DUST, font=T.font(ctk, "caption"))
        elif self._state == "busy":
            c.create_text(w // 2, h // 2, text=self._t("map_busy"), fill=T.CHALK, font=T.font(ctk, "body"))
        elif self._state == "error":
            c.create_text(w // 2, h // 2, text=self._t("map_error", self._error), fill=T.CUT,
                          font=T.font(ctk, "body"), width=w - 40)

    def _draw_chip(self, x, y, text, color):
        c = self.canvas
        item = c.create_text(x, y, text=text, fill=color, font=T.font(ctk, "label"))
        x0, y0, x1, y1 = c.bbox(item)
        r = c.create_rectangle(x0 - 10, y0 - 5, x1 + 10, y1 + 5, fill=T.PANEL, outline=T.EDGE)
        c.tag_raise(item, r)

    def _draw_wave(self, w, h):
        c = self.canvas
        top, bottom = self.RULER + 14, h - 24
        mid = (top + bottom) / 2
        dur = self._duration
        colors = {"keep": T.KEEP, "cut": T.CUT, "speed": T.SPEED}
        wave = {"keep": T.KEEP, "cut": T.blend(T.CUT, T.WELL, 0.7), "speed": T.SPEED}
        ruler = {"keep": T.blend(T.KEEP, T.WELL, 0.45), "cut": T.CUT, "speed": T.SPEED}
        kinds = ["keep"] * w
        for s, e, kind in self._regions:
            x0, x1 = int(s / dur * w), max(int(e / dur * w), int(s / dur * w) + 1)
            c.create_rectangle(x0, 0, x1, self.RULER, fill=ruler[kind], width=0)
            for x in range(max(0, x0), min(w, x1)):
                kinds[x] = kind
        n = len(self._peaks)
        top_peak = float(self._peaks.max()) or 1.0
        c.create_line(0, mid, w, mid, fill=T.EDGE)
        for x in range(w):
            p = float(self._peaks[min(n - 1, int(x / w * n))]) / top_peak
            half = max(1.0, p * (mid - top))
            c.create_line(x, mid - half, x, mid + half, fill=wave[kinds[x]])
        step = nice_step(dur, w)
        t = 0
        while t <= dur:
            x = int(t / dur * w)
            c.create_line(x, bottom + 6, x, bottom + 11, fill=T.DUST)
            if x < w - 36:
                c.create_text(x + 4, bottom + 16, text=fmt_time(t), fill=T.DUST, anchor="w", font=T.font(ctk, "mono_small"))
            t += step
        if self._hover_x is not None and 0 <= self._hover_x < w:
            x = self._hover_x
            c.create_line(x, 0, x, bottom + 6, fill=T.PENCIL, width=1)
            kind = self._kind_at(x)
            text = fmt_time(x / w * dur) + (f"  {self._t('hover_' + kind)}" if kind else "")
            tx = x + 8 if x < w - 140 else x - 8
            item = c.create_text(tx, top - 2, text=text, fill=colors.get(kind, T.CHALK), anchor="w" if x < w - 140 else "e",
                                 font=T.font(ctk, "mono_small"))
            x0, y0, x1, y1 = c.bbox(item)
            r = c.create_rectangle(x0 - 5, y0 - 2, x1 + 5, y1 + 2, fill=T.PANEL, outline=T.EDGE)
            c.tag_raise(item, r)


class Legend(ctk.CTkFrame):
    """Colour key for the cut map: kept / removed / sped up."""

    def __init__(self, parent, text_fn):
        super().__init__(parent, fg_color="transparent")
        self._t = text_fn
        self._labels = []
        for color, key in ((T.KEEP, "legend_keep"), (T.CUT, "legend_cut"), (T.SPEED, "legend_speed")):
            sw = ctk.CTkFrame(self, width=10, height=10, corner_radius=0, fg_color=color)
            sw.pack(side="left", padx=(0, T.S1), pady=T.S1)
            lb = caption(self, self._t(key))
            lb.pack(side="left", padx=(0, T.S3))
            self._labels.append((lb, key))

    def relabel(self):
        for lb, key in self._labels:
            lb.configure(text=self._t(key))
