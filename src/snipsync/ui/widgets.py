"""Reusable widgets. Styling decisions live in theme.py / DESIGN.md; nothing here picks a colour or size itself."""
from __future__ import annotations

import tkinter as tk

import customtkinter as ctk

from snipsync.ui import theme as T

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


def nice_step_fine(span: float, width_px: int, min_px: int = 96) -> float:
    """拡大しているときの、時間軸の目盛りの間隔（秒）。0.05 秒まで細かくできる。"""
    per_px = span / max(width_px, 1)
    for step in (0.05, 0.1, 0.2, 0.5, 1, 2, 5, 10, 15, 30, 60, 120, 300, 600, 900, 1800, 3600, 7200):
        if step / per_px >= min_px:
            return step
    return 7200


def fmt_time_step(sec: float, step: float) -> str:
    """目盛りの間隔に合わせた時刻。1 秒より細かいときは、小数も出す。"""
    if step >= 1:
        return fmt_time(sec)
    digits = 2 if step < 0.1 else 1
    sec = max(0.0, sec)
    m, s = int(sec // 60), sec % 60
    h, m = m // 60, m % 60
    body = f"{s:0{3 + digits}.{digits}f}"
    return f"{h}:{m:02d}:{body}" if h else f"{m}:{body}"


# ── text ────────────────────────────────────────────────────────────────────────────

def fit_window(win, default, floor, slack_h=0, first=False):
    """ウィンドウの大きさを、中身が切れない大きさに合わせる（画面に収まる範囲で）。
    最小サイズは、中身が要る大きさ（言語を変えると、文字の幅が変わる）。slack_h は、縮めてよい高さ（一覧やログ）。
    first=True のときだけ、最初の大きさも決める。大きさの単位は、画面の拡大率をかける前（CustomTkinter の geometry と同じ）。"""
    win.update_idletasks()
    scale = win._get_window_scaling() if hasattr(win, "_get_window_scaling") else 1.0
    need_w, need_h = win.winfo_reqwidth() / scale, win.winfo_reqheight() / scale
    max_w, max_h = max(win.winfo_screenwidth() / scale - 40, 640), max(win.winfo_screenheight() / scale - 90, 560)
    min_w = int(min(max(need_w, floor[0]), max_w))
    min_h = int(min(max(need_h - slack_h, floor[1]), max_h))
    win.minsize(min_w, min_h)
    if first:
        win.geometry(f"{int(min(max(need_w, default[0]), max_w))}x{int(min(max(need_h, default[1]), max_h))}")
    elif win.winfo_width() / scale < min_w - 1 or win.winfo_height() / scale < min_h - 1:
        win.geometry(f"{max(min_w, int(win.winfo_width() / scale))}x{max(min_h, int(win.winfo_height() / scale))}")


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
        # アプリアイコン（scripts/make_icon.py）と同じ図形。2つのクリップを、黄色の線で切る。
        self.create_polygon(p(3, 9, 15, 9, 11, 21, 3, 21), outline="", fill=T.CHALK)
        self.create_polygon(p(19, 9, 27, 9, 27, 21, 15, 21), outline="", fill=T.CHALK)
        self.create_line(p(18, 5, 9, 25), fill=bg, width=5.6 * s, capstyle="round")      # 切れ目の隙間
        self.create_line(p(18, 5, 9, 25), fill=T.PENCIL, width=3 * s, capstyle="round")


# ── the monitor strip: what will be cut ─────────────────────────────────────────────

class CutMap(ctk.CTkFrame):
    """Waveform with the removed / sped-up spans marked. Also the drop target while no file is chosen.

    時間の方向（拡大・縮小・移動）と、波形の大きさの方向に、拡縮できる。
    マウス: ホイール = 時間の拡大・縮小（カーソルの位置が動かない）、Shift + ホイール = 左右へ移動、Ctrl + ホイール = 波形の大きさ。
    """

    HEIGHT = 132
    RULER = 8
    DRAG_PX = 6          # これ以上ドラッグしたら、位置の指定ではなく、区間の選択とみなす
    MIN_VIEW = 0.5       # 最大まで拡大したときの、表示する長さ（秒）
    GAINS = (0.5, 0.75, 1.0, 1.5, 2.0, 3.0, 4.0, 6.0, 8.0, 12.0, 16.0)

    def __init__(self, parent, text_fn, on_click=None, on_seek=None, on_select=None, detail_fn=None, on_view=None):
        super().__init__(parent, fg_color=T.WELL, corner_radius=T.R_STRIP)
        self._t = text_fn
        self._on_select = on_select      # 波形をドラッグして区間を選んだとき: (開始秒, 終了秒)
        self._detail_fn = detail_fn      # 拡大したときの細かい波形: (開始秒, 終了秒, 本数) -> 長さ「本数」の配列、または None
        self.on_view = on_view           # 表示する範囲・波形の大きさが変わったとき
        self._selection: tuple | None = None
        self._press_x: int | None = None
        self._dragging = False
        self._on_click = on_click        # 何も選ばれていないとき（ドロップ領域）のクリック
        self._on_seek = on_seek          # 結果が出ているときのクリック: 元の時刻（秒）を渡す
        self._playhead: float | None = None
        self._state = "empty"
        self._error = ""
        self._peaks = None
        self._top = 1.0                  # 全体でいちばん大きな音（波形の大きさの基準）
        self._regions: list = []
        self._duration = 0.0
        self._vs = 0.0                   # 表示している範囲の開始（秒）
        self._vl: float | None = None    # 表示している範囲の長さ（None = 全体）
        self._gain_i = self.GAINS.index(1.0)
        self._stale = False
        self._hover_x: int | None = None
        self.canvas = tk.Canvas(self, height=self.HEIGHT, bg=T.WELL, highlightthickness=0, bd=0)
        self.canvas.pack(fill="x")
        self.canvas.bind("<Configure>", lambda _e: self.redraw())
        self.canvas.bind("<Motion>", self._motion)
        self.canvas.bind("<Leave>", lambda _e: self._set_hover(None))
        self.canvas.bind("<Button-1>", self._press)
        self.canvas.bind("<B1-Motion>", self._drag)
        self.canvas.bind("<ButtonRelease-1>", self._release)
        self.canvas.bind("<MouseWheel>", self._wheel)

    # state
    def set_empty(self):
        self._state, self._peaks, self._regions = "empty", None, []
        self._reset_view()
        self.redraw()

    def set_busy(self):
        self._state = "busy"
        self.redraw()

    def set_error(self, msg: str):
        self._state, self._error = "error", msg
        self.redraw()

    def set_data(self, peaks, regions, duration: float):
        same = self._state == "ready" and abs(duration - self._duration) < 0.5       # 同じ動画の再計算では、拡大を保つ
        self._state, self._peaks, self._regions, self._duration, self._stale = "ready", peaks, regions, duration, False
        self._top = float(peaks.max()) or 1.0 if peaks is not None and len(peaks) else 1.0
        if not same:
            self._reset_view()
        self.redraw()
        self._notify()

    # view（拡大・縮小・移動）
    def _reset_view(self):
        self._vs, self._vl = 0.0, None

    def _notify(self):
        if self.on_view:
            self.on_view()

    def view(self) -> tuple[float, float]:
        """いま表示している範囲（開始秒, 終了秒）。"""
        dur = self._duration
        if self._vl is None or dur <= 0 or self._vl >= dur:
            return 0.0, dur
        vs = min(max(0.0, self._vs), dur - self._vl)
        return vs, vs + self._vl

    @property
    def duration(self) -> float:
        return self._duration

    @property
    def zoomed(self) -> bool:
        return self._vl is not None and self._vl < self._duration

    @property
    def gain(self) -> float:
        return self.GAINS[self._gain_i]

    def view_fraction(self) -> tuple[float, float]:
        """スクロールバー用: 表示している範囲の、全体に対する位置（0〜1）。"""
        if self._duration <= 0:
            return 0.0, 1.0
        a, b = self.view()
        return a / self._duration, b / self._duration

    def zoom_time(self, factor: float, anchor: float | None = None):
        """表示する長さを factor 倍にする（0.5 = 2 倍に拡大）。anchor（秒）の画面上の位置は、動かさない。"""
        if self._state != "ready" or self._duration <= 0:
            return
        a, b = self.view()
        length = b - a
        new = min(self._duration, max(min(self.MIN_VIEW, self._duration), length * factor))
        if new >= self._duration - 1e-6:
            self._reset_view()
        else:
            anchor = (a + b) / 2 if anchor is None else min(max(anchor, a), b)
            rel = (anchor - a) / length if length > 0 else 0.5
            self._vl = new
            self._vs = min(max(0.0, anchor - rel * new), self._duration - new)
        self._changed()

    def zoom_all(self):
        self._reset_view()
        self._changed()

    def pan(self, seconds: float):
        if self.zoomed:
            self._vs = min(max(0.0, self.view()[0] + seconds), self._duration - self._vl)
            self._changed()

    def center_on(self, seconds: float):
        """拡大しているとき、seconds が真ん中に来るように動かす。"""
        if self.zoomed:
            self._vs = min(max(0.0, seconds - self._vl / 2), self._duration - self._vl)
            self._changed()

    def zoom_gain(self, step: int):
        i = min(max(self._gain_i + step, 0), len(self.GAINS) - 1)
        if i != self._gain_i:
            self._gain_i = i
            self._changed()

    def reset_gain(self):
        self._gain_i = self.GAINS.index(1.0)
        self._changed()

    def xview(self, *args):
        """スクロールバーの command（Tk の規約: moveto f / scroll n units|pages）。"""
        if not self.zoomed:
            return
        a, b = self.view()
        length = b - a
        if args and args[0] == "moveto":
            self._vs = min(max(0.0, float(args[1]) * self._duration), self._duration - length)
        elif args and args[0] == "scroll":
            unit = length * (0.9 if args[2] == "pages" else 0.1)
            self._vs = min(max(0.0, a + int(args[1]) * unit), self._duration - length)
        self._changed()

    def _changed(self):
        self.redraw()
        self._notify()

    def _x_of(self, t: float, w: int) -> int:
        a, b = self.view()
        return int((t - a) / (b - a) * w) if b > a else 0

    def _time_at(self, x: float) -> float:
        a, b = self.view()
        w = max(self.canvas.winfo_width(), 1)
        return min(b, max(a, a + x / w * (b - a)))

    def set_playhead(self, source_sec: float | None):
        """再生位置の線。再生中に何度も呼ばれるので、全体を描き直さず線だけ動かす。"""
        self._playhead = source_sec
        if self._state != "ready" or self._duration <= 0:
            return
        w = self.canvas.winfo_width()
        if source_sec is None or not self._playhead_visible():
            self.canvas.delete("playhead")
        elif self.canvas.find_withtag("playhead"):
            x = self._playhead_x(w)
            self.canvas.coords("playhead", x, 0, x, self._wave_bottom() + 6)
        else:
            self._draw_playhead(w)

    def _playhead_visible(self) -> bool:
        a, b = self.view()
        return self._playhead is not None and a <= self._playhead <= b

    def _playhead_x(self, w: int) -> int:
        return min(w - 1, max(0, self._x_of(self._playhead, w)))

    def _wave_bottom(self) -> int:
        return self.canvas.winfo_height() - 24

    def _draw_playhead(self, w: int):
        if self._playhead is None or not self._playhead_visible():
            return
        x = self._playhead_x(w)
        self.canvas.create_line(x, 0, x, self._wave_bottom() + 6, fill=T.CHALK, width=2, tags="playhead")

    def set_stale(self, stale: bool):
        if self._state == "ready" and stale != self._stale:
            self._stale = stale
            self.redraw()

    @property
    def has_data(self) -> bool:
        return self._state == "ready"

    @property
    def is_stale(self) -> bool:
        return self._stale

    # input
    def _press(self, e):
        self._press_x, self._dragging = e.x, False
        if self._state == "empty" and self._on_click:
            self._on_click()

    def _drag(self, e):
        if self._state != "ready" or not self._on_select or self._press_x is None or self._duration <= 0:
            return
        if not self._dragging and abs(e.x - self._press_x) < self.DRAG_PX:
            return
        self._dragging = True
        a, b = sorted((self._time_at(self._press_x), self._time_at(e.x)))
        self.set_selection((a, b))

    def _release(self, e):
        if self._state != "ready" or self._press_x is None:
            return
        if self._dragging and self._selection and self._on_select:
            self._on_select(*self._selection)
        elif self._on_seek and self._duration > 0:
            self._on_seek(self._time_at(e.x))
        self._press_x, self._dragging = None, False

    def _wheel(self, e):
        if self._state != "ready" or self._duration <= 0:
            return
        up = e.delta > 0
        if e.state & 0x4:                                    # Ctrl: 波形の大きさ
            self.zoom_gain(1 if up else -1)
        elif e.state & 0x1:                                  # Shift: 左右へ
            a, b = self.view()
            self.pan((b - a) * 0.15 * (-1 if up else 1))
        else:                                                # ホイール: 時間の拡大・縮小（カーソルの位置が動かない）
            self.zoom_time(0.8 if up else 1.25, self._time_at(e.x))

    @property
    def selection(self):
        return self._selection

    def set_selection(self, sel) -> None:
        """選んでいる区間（開始秒, 終了秒）。None で外す。"""
        self._selection = sel
        self._draw_selection()

    def _draw_selection(self):
        c = self.canvas
        c.delete("selection")
        if self._selection is None or self._state != "ready" or self._duration <= 0:
            return
        a, b = self.view()
        if self._selection[1] < a or self._selection[0] > b:
            return
        w = max(c.winfo_width(), 1)
        x0 = max(0, self._x_of(self._selection[0], w))
        x1 = min(w, max(self._x_of(self._selection[1], w), x0 + 1))
        c.create_rectangle(x0, 0, x1, self._wave_bottom() + 6, fill=T.PENCIL, stipple="gray25", outline=T.PENCIL,
                           tags="selection")
        c.tag_lower("selection")
        self.canvas.tag_raise("playhead")

    def _kind_at(self, x: int):
        t = self._time_at(x)
        for s, e, kind in self._regions:
            if s <= t < e:
                return kind
        return None

    def _motion(self, e):
        if self._state == "ready":
            self._set_hover(e.x)
            self.canvas.configure(cursor="hand2" if self._on_seek else "")
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

    def _visible_peaks(self, a: float, b: float, w: int):
        """表示範囲の、横 1 ピクセルごとの波形の大きさ（0..1 を、全体の最大で割ったもの）。"""
        import numpy as np
        if self.zoomed and self._detail_fn is not None:
            fine = self._detail_fn(a, b, w)
            if fine is not None and len(fine) == w:
                return np.asarray(fine, dtype=np.float32) / self._top
        n = len(self._peaks)
        i0 = a / self._duration * n
        i1 = b / self._duration * n
        idx = np.minimum(n - 1, (i0 + (np.arange(w) + 0.5) / w * (i1 - i0)).astype(int))
        return np.asarray(self._peaks, dtype=np.float32)[idx] / self._top

    def _draw_wave(self, w, h):
        c = self.canvas
        top, bottom = self.RULER + 14, h - 24
        mid = (top + bottom) / 2
        va, vb = self.view()
        span = vb - va
        colors = {"keep": T.KEEP, "cut": T.CUT, "speed": T.SPEED}
        wave = {"keep": T.KEEP, "cut": T.blend(T.CUT, T.WELL, 0.7), "speed": T.SPEED}
        ruler = {"keep": T.blend(T.KEEP, T.WELL, 0.45), "cut": T.CUT, "speed": T.SPEED}
        kinds = ["keep"] * w
        for s, e, kind in self._regions:
            if e < va or s > vb:
                continue
            x0 = max(0, self._x_of(s, w))
            x1 = min(w, max(self._x_of(e, w), x0 + 1))
            c.create_rectangle(x0, 0, x1, self.RULER, fill=ruler[kind], width=0)
            for x in range(x0, x1):
                kinds[x] = kind
        peaks = self._visible_peaks(va, vb, w)
        gain, room = self.gain, mid - top
        c.create_line(0, mid, w, mid, fill=T.EDGE)
        for x in range(w):
            half = min(room, max(1.0, float(peaks[x]) * gain * room))
            c.create_line(x, mid - half, x, mid + half, fill=wave[kinds[x]])
        step = nice_step_fine(span, w)
        t = (va // step) * step
        if t < va:
            t += step
        while t <= vb:
            x = self._x_of(t, w)
            c.create_line(x, bottom + 6, x, bottom + 11, fill=T.DUST)
            if x < w - 36:
                c.create_text(x + 4, bottom + 16, text=fmt_time_step(t, step), fill=T.DUST, anchor="w",
                              font=T.font(ctk, "mono_small"))
            t += step
        self._draw_playhead(w)
        self._draw_selection()
        if self._hover_x is not None and 0 <= self._hover_x < w:
            x = self._hover_x
            c.create_line(x, 0, x, bottom + 6, fill=T.PENCIL, width=1)
            kind = self._kind_at(x)
            text = fmt_time_step(self._time_at(x), 0.1 if span < 60 else 1) + (f"  {self._t('hover_' + kind)}" if kind else "")
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


# ── hover help ──────────────────────────────────────────────────────────────────────

_NO_LINE_START = set("、。，．）」』】〕！？!?,.)]}：:；;ー")     # 行の先頭に来てはいけない文字


def wrap_text(text: str, measure, max_px: int) -> str:
    """幅 max_px に収まるよう改行する。日本語は文字の間で、英単語は途中で切らず、句読点・閉じ括弧は行頭に置かない。

    measure(文字列) -> 幅(px)。Tk のラベル任せの折り返しは、空白でしか切れないため、日本語の文に
    英単語（GPU など）が混じると、行が極端に短くなる。
    """
    import re
    tokens = re.findall(r"[A-Za-z0-9_+./\-]+|\s+|.", text)
    lines, cur = [], ""
    for tok in tokens:
        if tok == "\n":
            lines.append(cur)
            cur = ""
            continue
        if cur and measure(cur + tok) > max_px and tok[0] not in _NO_LINE_START and not tok.isspace():
            lines.append(cur.rstrip())
            cur = ""
        if not cur and tok.isspace():
            continue
        cur += tok
    if cur:
        lines.append(cur.rstrip())
    return "\n".join(lines)


class Tooltip:
    """マウスを重ねて少し待つと出る簡易ヘルプ。

    text は文字列か、呼ぶたびに今の言語の文字列を返す関数（言語を切り替えても追従する）。
    部品とその中身すべて（ラベル・ボタンの内側など）にまとめて効く。マウスが部品の外へ出る、または
    クリック・キー入力で消える。
    """

    DELAY_MS = 450
    WRAP = 340
    _active = None            # いま出ているもの。同時に 2 つは出さない（あとから出る = 内側の部品のヘルプが勝つ）

    def __init__(self, widget, text, delay: int | None = None):
        self.widget = widget
        self._text = text
        self._delay = self.DELAY_MS if delay is None else delay
        self._job = None
        self._tip = None
        self._bind_tree(widget)

    def _bind_tree(self, w):
        for ev, fn in (("<Enter>", self._enter), ("<Leave>", self._leave), ("<ButtonPress>", self._hide),
                       ("<KeyPress>", self._hide)):
            try:
                tk.Misc.bind(w, ev, fn, add="+")
            except tk.TclError:
                pass
        for child in w.winfo_children():
            self._bind_tree(child)

    @property
    def text(self) -> str:
        return self._text() if callable(self._text) else str(self._text)

    def _inside(self) -> bool:
        w = self.widget
        try:
            x, y = w.winfo_pointerxy()
            return (w.winfo_rootx() <= x < w.winfo_rootx() + w.winfo_width()
                    and w.winfo_rooty() <= y < w.winfo_rooty() + w.winfo_height())
        except tk.TclError:
            return False

    def _enter(self, _e=None):
        if self._tip is None and self._job is None:
            self._job = self.widget.after(self._delay, self._show)

    def _leave(self, _e=None):
        if not self._inside():          # 部品の中の別の部分へ移っただけなら、そのまま
            self._hide()

    def _hide(self, _e=None):
        if self._job is not None:
            try:
                self.widget.after_cancel(self._job)
            except tk.TclError:
                pass
            self._job = None
        if self._tip is not None:
            try:
                self._tip.destroy()
            except tk.TclError:
                pass
            self._tip = None
            if Tooltip._active is self:
                Tooltip._active = None

    def _show(self):
        self._job = None
        text = self.text
        if self._tip is not None or not text or not self._inside():
            return
        if Tooltip._active is not None and Tooltip._active is not self:
            Tooltip._active._hide()
        tip = tk.Toplevel(self.widget)
        tip.wm_overrideredirect(True)
        tip.attributes("-topmost", True)          # 他の窓の裏に隠れない
        tip.configure(bg=T.EDGE)
        font = T.font(ctk, "caption")
        tk.Label(tip, text=wrap_text(text, font.measure, self.WRAP), justify="left", bg=T.PANEL, fg=T.CHALK,
                 font=font, padx=T.S3, pady=T.S2, bd=0).pack(padx=1, pady=1)
        tip.update_idletasks()
        x, y = self.widget.winfo_pointerxy()
        x, y = x + 14, y + 20
        sw, sh = tip.winfo_screenwidth(), tip.winfo_screenheight()
        x = max(0, min(x, sw - tip.winfo_reqwidth() - 8))
        if y + tip.winfo_reqheight() > sh - 8:               # 下にはみ出すなら、ポインターの上に出す
            y = max(0, y - tip.winfo_reqheight() - 34)
        tip.wm_geometry(f"+{x}+{y}")
        self._tip = tip
        Tooltip._active = self


def tip(widget, text):
    """widget に簡易ヘルプを付ける。widget はそのまま返す。"""
    Tooltip(widget, text)
    return widget
