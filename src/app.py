"""
SnipSync - cuts silence from video/audio, exports a timeline for your editor (or the cut media), and
makes subtitles. Layout and styling: DESIGN.md.
"""
import dataclasses
import os
import re
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox

import customtkinter as ctk

os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")   # モデル取得時の利用統計を送らない（faster_whisper より前）

try:
    from tkinterdnd2 import DND_FILES, TkinterDnD
    DND_AVAILABLE = True
except ImportError:
    DND_AVAILABLE = False

try:
    from faster_whisper import WhisperModel  # noqa: F401  (imported only to probe availability)
    WHISPER_AVAILABLE = True
except ImportError:
    WHISPER_AVAILABLE = False

import theme as T
import widgets as W
from aebin import get_auto_editor_path
from autoeditor import MEDIA_EXTS
from diarize import sherpa_available
from i18n import I18N
from pipeline import PipelineParams, run_pipeline
from player import PLAY_SR, RATES, EditedAudio, Player, PlayerError, sounddevice_available
from presets import delete_preset, load_store, save_store, set_last_used, upsert_preset
from preview import CutSettings, compute_preview
from subtitle_editor import SubtitleEditor
from subtitles import (  # noqa: F401  (format_timestamp re-exported for tests)
    cuda_available,
    format_timestamp,
)
from vad import decode_mix
from version import APP_VERSION  # noqa: F401  (re-exported for tests)

EXPORT_KEYS = ("resolve", "premiere", "final-cut-pro", "media")
SPEAKER_COUNTS = ("auto", "2", "3", "4", "5", "6")
LANGS = {"ja": "日本語", "en": "English"}

if DND_AVAILABLE:
    class _Base(ctk.CTk, TkinterDnD.DnDWrapper):
        def __init__(self, *a, **kw):
            super().__init__(*a, **kw)
            self.TkdndVersion = TkinterDnD._require(self)
else:
    class _Base(ctk.CTk):
        pass


class SnipSyncApp(_Base):
    def __init__(self):
        super().__init__()
        ctk.set_appearance_mode("dark")
        T.load_fonts(ctk, self)
        T.apply_icon(self)
        self.configure(fg_color=T.BENCH)
        self.geometry("1020x990")
        self.minsize(940, 860)

        self.lang = "ja"
        self.input_files: list[str] = []
        self.output_dir = ""
        self.last_cues: list = []
        self.last_title = ""
        self.last_paths: dict = {}
        self.last_out_dir: Path | None = None
        self.editor_win = None
        self.review_win = None               # 処理中に開く、保存前の確認ウィンドウ
        self.running = False
        self.stop_requested = False
        self._reg: list = []                 # (widget, i18n key): 言語切り替えで文言を差し替える
        self._preview_gen = 0
        self._preview_busy = False
        self._preview_again = False
        self._preview_timer = None
        self._preview_cache: dict = {}
        self._preview_result = None          # 最新の確認結果（再生が使う区間を持つ）
        self.player = Player() if sounddevice_available() else None
        self.play_rate = 1.0
        self._play_cache: dict = {}          # 再生用に読み込んだ元の音（ファイルごと）
        self._audio_loading = False
        self._tick_job = None

        # 設定（プリセットに保存される）
        self.margin_var = tk.DoubleVar(value=0.2)
        self.threshold_var = tk.DoubleVar(value=4.0)
        self.speed_var = tk.DoubleVar(value=8.0)
        self.cut_mode = "threshold"
        self.silence = "cut"
        self.export_key = "resolve"
        self.srt_var = tk.BooleanVar(value=True)
        self.model_key = "small"
        self.gpu_var = tk.BooleanVar(value=False)
        self.snap_var = tk.BooleanVar(value=True)
        self.chars_var = tk.IntVar(value=20)
        self.diarize_var = tk.BooleanVar(value=False)
        self.speakers = "auto"
        self.glossary_var = tk.StringVar(value="")
        self.txt_var = tk.BooleanVar(value=False)
        self.md_var = tk.BooleanVar(value=False)
        self.review_var = tk.BooleanVar(value=True)      # 字幕を保存する前に確認・編集する（無人の一括処理ではオフ）
        self.markers_var = tk.BooleanVar(value=False)
        self.speaker_labels = True           # 画面には出さない（既定どおり話者名を付ける）。プリセットには残す

        self._build()
        for var in (self.margin_var, self.threshold_var, self.speed_var):
            var.trace_add("write", lambda *_: self._mark_stale())

        store = load_store()
        if store.get("last_used"):
            self._apply_settings(store["last_used"])
        self._apply_lang()
        self._refresh_states()
        self._on_files_changed()
        if not cuda_available():
            self._log(self.t("log_gpu_unavailable"), "muted")
        self._log(self.t("log_welcome"), "muted")

        if DND_AVAILABLE:
            for w in (self, self.monitor, self.cutmap.canvas):
                w.drop_target_register(DND_FILES)
                w.dnd_bind("<<Drop>>", self._on_drop)
        self.bind("<Control-o>", lambda _e: self._browse_file())
        self.bind("<Control-Return>", lambda _e: self._start_process())
        self.bind("<Escape>", lambda _e: self._stop_process() if self.running else None)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # ── 文言 ────────────────────────────────────────────────────────────────────────
    def t(self, key, *args):
        s = I18N[self.lang].get(key, key)
        return s.format(*args) if args else s

    def reg(self, widget, key):
        """文言を持つ部品を登録して、いまの言語で文言を設定する。"""
        self._reg.append((widget, key))
        widget.configure(text=self.t(key))
        return widget

    # ── 画面の構築 ───────────────────────────────────────────────────────────────────
    def _build(self):
        self.columnconfigure(0, weight=1)
        self.rowconfigure(5, weight=1)
        self._build_header()
        self._build_monitor()
        self._build_settings()
        self._build_actions()
        self._build_log()

    def _build_header(self):
        bar = ctk.CTkFrame(self, fg_color="transparent")
        bar.grid(row=0, column=0, sticky="ew", padx=T.S6, pady=(T.S4, T.S3))
        bar.columnconfigure(2, weight=1)
        W.Logo(bar).grid(row=0, column=0, padx=(0, T.S2))
        W.label(bar, "SnipSync", "wordmark").grid(row=0, column=1, sticky="w")
        W.caption(bar, f"v{APP_VERSION}").grid(row=0, column=2, sticky="w", padx=(T.S3, 0), pady=(T.S2, 0))
        self.lang_choice = W.Choice(bar, LANGS, command=self._on_lang_change, height=30)
        self.lang_choice.grid(row=0, column=3, sticky="e")
        self.lang_choice.set_key(self.lang)

    def _build_monitor(self):
        self.monitor = ctk.CTkFrame(self, fg_color=T.WELL, corner_radius=T.R_PANEL)
        self.monitor.grid(row=1, column=0, sticky="ew", padx=T.S6)
        self.monitor.columnconfigure(0, weight=1)

        top = ctk.CTkFrame(self.monitor, fg_color="transparent")
        top.grid(row=0, column=0, sticky="ew", padx=T.S4, pady=(T.S3, T.S2))
        top.columnconfigure(0, weight=1)
        names = ctk.CTkFrame(top, fg_color="transparent")
        names.grid(row=0, column=0, sticky="w")
        self.file_name = W.label(names, "", "label")
        self.file_name.pack(side="left")
        self.file_more = W.caption(names)
        self.file_more.pack(side="left", padx=(T.S2, 0))
        self.btn_pick = self.reg(W.Btn(top, "", self._browse_file, height=30), "btn_pick")
        self.btn_pick.grid(row=0, column=1, padx=(T.S2, 0))
        self.btn_clear = self.reg(W.Btn(top, "", self._clear_files, kind="ghost", height=30, width=56), "btn_clear")
        self.btn_clear.grid(row=0, column=2, padx=(T.S1, 0))

        self.cutmap = W.CutMap(self.monitor, self.t, on_click=self._browse_file, on_seek=self._seek_source)
        self.cutmap.grid(row=1, column=0, sticky="ew", padx=T.S4)
        self._build_transport(self.monitor)

        stats = ctk.CTkFrame(self.monitor, fg_color="transparent")
        stats.grid(row=3, column=0, sticky="ew", padx=T.S4, pady=(T.S2, T.S3))
        stats.columnconfigure(1, weight=1)
        self.stats_time = W.label(stats, "", "mono_large")
        self.stats_time.grid(row=0, column=0, sticky="w")
        self.stats_text = W.caption(stats)
        self.stats_text.grid(row=0, column=1, sticky="w", padx=(T.S3, 0), pady=(T.S2, 0))
        self.legend = W.Legend(stats, self.t)
        self.legend.grid(row=0, column=2, padx=(T.S3, T.S3))
        self.legend.grid_remove()
        self.btn_preview = W.Btn(stats, "", self._run_preview, height=32)
        self.btn_preview.grid(row=0, column=3)
        self.btn_preview.enable(False)       # ファイルを選ぶまでは押せない

    def _build_transport(self, parent):
        """編集後の音を聞く操作。カットマップの真下に置き、波形を見ながら押せるようにする。"""
        self.transport = ctk.CTkFrame(parent, fg_color="transparent")
        self.transport.grid(row=2, column=0, sticky="ew", padx=T.S4, pady=(T.S2, 0))
        self.transport.columnconfigure(4, weight=1)
        if self.player is None:
            self.transport_note = W.caption(self.transport)
            self.transport_note.grid(row=0, column=0, sticky="w")
            return
        self.btn_prev = self.reg(W.Btn(self.transport, "", self._play_prev, height=32), "tr_prev")
        self.btn_prev.grid(row=0, column=0)
        self.btn_play = W.Btn(self.transport, "", self._play_toggle, height=32, width=104)
        self.btn_play.grid(row=0, column=1, padx=(T.S2, T.S2))
        self.btn_next = self.reg(W.Btn(self.transport, "", self._play_next, height=32), "tr_next")
        self.btn_next.grid(row=0, column=2)
        self.play_time = W.label(self.transport, "", "mono", T.CHALK, anchor="w", width=130)
        self.play_time.grid(row=0, column=3, padx=(T.S4, 0))
        self.rate_lbl = self.reg(W.caption(self.transport), "tr_speed")
        self.rate_lbl.grid(row=0, column=5, padx=(0, T.S2))
        self.rate_choice = W.Choice(self.transport, {f"{r:g}": f"{r:g}×" for r in RATES},
                                    command=self._on_rate, height=30)
        self.rate_choice.grid(row=0, column=6)
        self.rate_choice.set_key("1")

    def _build_settings(self):
        self.panel = ctk.CTkFrame(self, fg_color=T.PANEL, corner_radius=T.R_PANEL)
        self.panel.grid(row=2, column=0, sticky="ew", padx=T.S6, pady=(T.S3, 0))
        self.panel.columnconfigure(0, weight=1)

        bar = ctk.CTkFrame(self.panel, fg_color="transparent")
        bar.grid(row=0, column=0, sticky="ew", padx=T.S4, pady=(T.S3, T.S1))
        bar.columnconfigure(1, weight=1)
        self.tabs = W.Choice(bar, self._tab_options(), command=self._show_tab, height=32)
        self.tabs.grid(row=0, column=0, sticky="w")
        presets = ctk.CTkFrame(bar, fg_color="transparent")
        presets.grid(row=0, column=2, sticky="e")
        self.preset_lbl = W.caption(presets)
        self.preset_lbl.pack(side="left", padx=(0, T.S2))
        self.preset_var = tk.StringVar()
        self.preset_menu = W.menu(presets, [""], command=self._on_preset_select, width=170, variable=self.preset_var)
        self.preset_menu.pack(side="left")
        self.btn_preset_save = self.reg(W.Btn(presets, "", self._on_preset_save, height=32, width=64), "preset_save")
        self.btn_preset_save.pack(side="left", padx=(T.S2, 0))
        self.btn_preset_delete = self.reg(W.Btn(presets, "", self._on_preset_delete, kind="ghost", height=32, width=64),
                                          "preset_delete")
        self.btn_preset_delete.pack(side="left", padx=(T.S1, 0))

        self.tab_frames = {}
        holder = ctk.CTkFrame(self.panel, fg_color="transparent")
        holder.grid(row=1, column=0, sticky="ew", padx=T.S4, pady=(T.S2, T.S4))
        holder.columnconfigure(0, weight=1)
        for key, build in (("cut", self._tab_cut), ("subs", self._tab_subs), ("export", self._tab_export)):
            f = ctk.CTkFrame(holder, fg_color="transparent")
            f.grid(row=0, column=0, sticky="nsew")
            f.columnconfigure((0, 1), weight=1, uniform="col")
            build(f)
            self.tab_frames[key] = f
        self.tab_frames["cut"].tkraise()

    def _tab_options(self) -> dict:
        return {"cut": self.t("tab_cut"), "subs": self.t("tab_subs"), "export": self.t("tab_export")}

    def _show_tab(self, key):
        self.tab_frames[key].tkraise()

    # 設定の1項目: 見出し、操作部品、補足の3段
    def _field(self, parent, title, build, cap=None, wrap=460):
        f = ctk.CTkFrame(parent, fg_color="transparent")
        f.columnconfigure(0, weight=1)
        r = 0
        if title:
            self.reg(W.label(f, "", "label"), title).grid(row=r, column=0, sticky="w")
            r += 1
        build(f).grid(row=r, column=0, sticky="w", pady=(T.S1, 0))
        r += 1
        if cap:
            self.reg(W.caption(f, wraplength=wrap), cap).grid(row=r, column=0, sticky="w", pady=(T.S1, 0))
        return f

    def _column(self, parent, col):
        c = ctk.CTkFrame(parent, fg_color="transparent")
        c.grid(row=0, column=col, sticky="nsew", padx=(0 if col == 0 else T.S3, T.S3 if col == 0 else 0))
        return c

    def _slider_row(self, parent, var, from_, to, steps, fmt, command=None):
        row = ctk.CTkFrame(parent, fg_color="transparent")
        value = W.label(row, "", "mono", T.CHALK, width=84, anchor="w")
        def changed(_v=None):
            value.configure(text=fmt(var.get()))
            if command:
                command()
        s = W.slider(row, from_, to, steps, var, changed, width=250)
        s.pack(side="left")
        value.pack(side="left", padx=(T.S3, 0))
        row.slider, row.value, row.update_label = s, value, changed
        changed()
        return row

    def _tab_cut(self, f):
        left, right = self._column(f, 0), self._column(f, 1)
        def method(p):
            self.method_choice = W.Choice(p, self.t("method_options"), command=self._on_method)
            return self.method_choice
        self._field(left, "f_method", method, "cap_method").pack(anchor="w", fill="x")
        def silence(p):
            row = ctk.CTkFrame(p, fg_color="transparent")
            self.silence_choice = W.Choice(row, self.t("silence_options"), command=self._on_silence)
            self.silence_choice.pack(side="left")
            self.speed_prefix = self.reg(W.caption(row), "speed_prefix")
            self.speed_prefix.pack(side="left", padx=(T.S3, T.S1))
            self.speed_entry = W.entry(row, self.speed_var, width=56, mono=True, justify="center")
            self.speed_entry.pack(side="left")
            self.speed_entry.bind("<FocusOut>", self._commit_speed, add="+")
            self.speed_entry.bind("<Return>", self._commit_speed, add="+")
            return row
        self._field(left, "f_silence", silence, "cap_silence").pack(anchor="w", fill="x", pady=(T.S4, 0))
        def threshold(p):
            self.threshold_row = self._slider_row(p, self.threshold_var, 0.0, 50.0, 100,
                                                  lambda v: f"{v:.1f} {self.t('unit_pct')}")
            return self.threshold_row
        self._field(right, "f_threshold", threshold, "cap_threshold").pack(anchor="w", fill="x")
        def margin(p):
            self.margin_row = self._slider_row(p, self.margin_var, 0.0, 2.0, 40,
                                               lambda v: f"{v:.2f} {self.t('unit_sec')}")
            return self.margin_row
        self._field(right, "f_margin", margin, "cap_margin").pack(anchor="w", fill="x", pady=(T.S4, 0))

    def _tab_subs(self, f):
        left, right = self._column(f, 0), self._column(f, 1)
        def srt(p):
            self.srt_switch = self.reg(W.switch(p, "", self.srt_var, self._refresh_states), "f_srt")
            return self.srt_switch
        self._field(left, None, srt).pack(anchor="w", fill="x")
        def model(p):
            self.model_menu = W.menu(p, [""], command=self._on_model, width=380)
            return self.model_menu
        self._field(left, "f_model", model, "cap_model").pack(anchor="w", fill="x", pady=(T.S3, 0))
        def gpu(p):
            self.gpu_switch = self.reg(W.switch(p, "", self.gpu_var), "f_gpu")
            return self.gpu_switch
        self._field(left, None, gpu, "cap_gpu").pack(anchor="w", fill="x", pady=(T.S3, 0))
        def glossary(p):
            self.glossary_entry = W.entry(p, self.glossary_var, width=380)
            return self.glossary_entry
        self._field(left, "f_glossary", glossary).pack(anchor="w", fill="x", pady=(T.S3, 0))
        def review(p):
            self.review_switch = self.reg(W.switch(p, "", self.review_var), "f_review")
            return self.review_switch
        self._field(left, None, review, "cap_review").pack(anchor="w", fill="x", pady=(T.S3, 0))

        def snap(p):
            self.snap_switch = self.reg(W.switch(p, "", self.snap_var), "f_snap")
            return self.snap_switch
        self._field(right, None, snap, "cap_snap").pack(anchor="w", fill="x")
        def chars(p):
            self.chars_row = self._slider_row(p, self.chars_var, 0, 40, 40,
                                              lambda v: self.t("chars_off") if int(v) == 0 else f"{int(v)} {self.t('unit_chars')}")
            return self.chars_row
        self._field(right, "f_chars", chars, "cap_chars").pack(anchor="w", fill="x", pady=(T.S3, 0))
        def speakers(p):
            row = ctk.CTkFrame(p, fg_color="transparent")
            self.diarize_switch = self.reg(W.switch(row, "", self.diarize_var, self._refresh_states), "f_speakers")
            self.diarize_switch.pack(side="left")
            self.speakers_lbl = self.reg(W.caption(row), "speakers_count")
            self.speakers_lbl.pack(side="left", padx=(T.S4, T.S1))
            self.speakers_menu = W.menu(row, [""], command=self._on_speakers, width=96)
            self.speakers_menu.pack(side="left")
            return row
        self._field(right, None, speakers, "cap_speakers").pack(anchor="w", fill="x", pady=(T.S3, 0))

    def _tab_export(self, f):
        left, right = self._column(f, 0), self._column(f, 1)
        def output(p):
            self.export_choice = W.Choice(p, self.t("export_options"), command=self._on_export)
            return self.export_choice
        box = self._field(left, "f_export", output, None)
        box.pack(anchor="w", fill="x")
        self.export_cap = W.caption(box, wraplength=430)
        self.export_cap.grid(row=2, column=0, sticky="w", pady=(T.S1, 0))
        def folder(p):
            row = ctk.CTkFrame(p, fg_color="transparent")
            self.folder_lbl = W.label(row, "", "mono_small", T.DUST, anchor="w", width=300)
            self.folder_lbl.pack(side="left")
            self.btn_change = self.reg(W.Btn(row, "", self._browse_outdir, height=30), "btn_change")
            self.btn_change.pack(side="left", padx=(T.S2, 0))
            return row
        self._field(left, "f_folder", folder).pack(anchor="w", fill="x", pady=(T.S4, 0))

        def extra(p):
            col = ctk.CTkFrame(p, fg_color="transparent")
            self.txt_switch = self.reg(W.switch(col, "", self.txt_var), "extra_txt")
            self.md_switch = self.reg(W.switch(col, "", self.md_var), "extra_md")
            self.markers_switch = self.reg(W.switch(col, "", self.markers_var), "extra_markers")
            for s in (self.txt_switch, self.md_switch, self.markers_switch):
                s.pack(anchor="w", pady=(0, T.S2))
            return col
        self._field(right, "f_extra", extra).pack(anchor="w", fill="x")

    def _build_actions(self):
        row = ctk.CTkFrame(self, fg_color="transparent")
        row.grid(row=3, column=0, sticky="ew", padx=T.S6, pady=(T.S4, T.S2))
        row.columnconfigure(2, weight=1)
        self.btn_start = self.reg(W.Btn(row, "", self._start_process, kind="primary", height=44, width=200), "btn_start")
        self.btn_start.grid(row=0, column=0)
        self.btn_stop = self.reg(W.Btn(row, "", self._stop_process, kind="danger", height=44, width=96), "btn_stop")
        self.btn_stop.grid(row=0, column=1, padx=(T.S2, 0))
        self.btn_stop.enable(False)
        self.btn_open_out = self.reg(W.Btn(row, "", self._open_output, height=44), "btn_open_out")
        self.btn_open_out.grid(row=0, column=3, padx=(0, T.S2))
        self.btn_open_out.enable(False)
        self.btn_review = self.reg(W.Btn(row, "", self._open_editor, height=44), "btn_review")
        self.btn_review.grid(row=0, column=4)
        self.btn_review.enable(False)        # 字幕ができるまで押せない（空の編集画面を開かせない）
        self.progress = ctk.CTkProgressBar(self, mode="determinate", height=3, corner_radius=0, fg_color=T.EDGE,
                                           progress_color=T.PENCIL)
        self.progress.grid(row=4, column=0, sticky="ew", padx=T.S6)
        self.progress.set(0)

    def _build_log(self):
        box = ctk.CTkFrame(self, fg_color="transparent")
        box.grid(row=5, column=0, sticky="nsew", padx=T.S6, pady=(T.S3, T.S4))
        box.columnconfigure(0, weight=1)
        box.rowconfigure(1, weight=1)
        head = ctk.CTkFrame(box, fg_color="transparent")
        head.grid(row=0, column=0, sticky="ew")
        head.columnconfigure(0, weight=1)
        self.log_title = self.reg(W.label(head, "", "label", T.DUST), "log_header")
        self.log_title.grid(row=0, column=0, sticky="w")
        self.btn_log_clear = self.reg(W.Btn(head, "", self._clear_log, kind="ghost", height=26), "btn_log_clear")
        self.btn_log_clear.grid(row=0, column=1)
        self.console = ctk.CTkTextbox(box, height=120, corner_radius=T.R_PANEL, fg_color=T.WELL, text_color=T.CHALK,
                                      font=T.font(ctk, "mono_small"), wrap="word", state="disabled", border_width=0,
                                      scrollbar_button_color=T.EDGE, scrollbar_button_hover_color=T.RAISED)
        self.console.grid(row=1, column=0, sticky="nsew", pady=(T.S1, 0))
        tb = self.console._textbox
        for tag, color in (("info", T.SPEED), ("success", T.OK), ("error", T.CUT), ("warn", T.WARN), ("muted", T.DUST)):
            tb.tag_config(tag, foreground=color)

    # ── 言語 ────────────────────────────────────────────────────────────────────────
    def _on_lang_change(self, key):
        self.lang = key
        self._apply_lang()

    def _apply_lang(self):
        self.title(self.t("title"))
        for widget, key in self._reg:
            widget.configure(text=self.t(key))
        self.tabs.relabel(self._tab_options())
        self.method_choice.relabel(self.t("method_options"))
        self.silence_choice.relabel(self.t("silence_options"))
        self.export_choice.relabel(self.t("export_options"))
        self.preset_lbl.configure(text=self.t("preset_label"))
        self.model_menu.configure(values=list(self.t("model_options").values()))
        self.model_menu.set(self.t("model_options")[self.model_key])
        self.speakers_menu.configure(values=[self.t("speakers_auto")] + list(SPEAKER_COUNTS[1:]))
        self._sync_speakers_menu()
        self.glossary_entry.configure(placeholder_text=self.t("glossary_hint"))
        for row in (self.threshold_row, self.margin_row, self.chars_row):
            row.update_label()
        self._update_preset_menu()
        self._update_export_caption()
        self._update_folder_label()
        self._update_file_header()
        self._update_stats()
        self.legend.relabel()
        self.cutmap.redraw()
        for win in self._open_editors():
            win.relabel()

    # ── 設定の収集・反映 ──────────────────────────────────────────────────────────────
    def line_chars(self) -> int:
        try:
            return max(0, min(60, int(self.chars_var.get())))
        except (ValueError, tk.TclError):
            return 20

    def _speed(self) -> float:
        try:
            return max(1.1, min(100.0, float(self.speed_var.get())))
        except (ValueError, tk.TclError):
            return 8.0

    def _collect_settings(self) -> dict:
        return {
            "margin": self.margin_var.get(), "threshold": self.threshold_var.get(), "export": self.export_key,
            "srt": self.srt_var.get(), "model": self.model_key, "output_dir": self.output_dir,
            "gpu": self.gpu_var.get(), "snap_srt": self.snap_var.get(), "cut_mode": self.cut_mode,
            "silence": self.silence, "speed": self._speed(), "hotwords": self.glossary_var.get(),
            "diarize": self.diarize_var.get(), "speakers": self.speakers, "speaker_labels": self.speaker_labels,
            "markers": self.markers_var.get(), "line_chars": self.line_chars(), "txt": self.txt_var.get(),
            "md": self.md_var.get(), "review": self.review_var.get(),
        }

    def _apply_settings(self, s: dict):
        if "margin" in s:
            self.margin_var.set(s["margin"])
        if "threshold" in s:
            self.threshold_var.set(s["threshold"])
        if s.get("export") in EXPORT_KEYS:
            self.export_key = s["export"]
            self.export_choice.set_key(self.export_key)
        if "srt" in s:
            self.srt_var.set(bool(s["srt"]) and WHISPER_AVAILABLE)
        if s.get("model") in self.t("model_options"):    # 古いプリセットの未対応モデル名は無視する
            self.model_key = s["model"]
            self.model_menu.set(self.t("model_options")[self.model_key])
        if "output_dir" in s:
            self.output_dir = s["output_dir"]
            self._update_folder_label()
        if "gpu" in s:
            self.gpu_var.set(bool(s["gpu"]) and cuda_available())
        if "snap_srt" in s:
            self.snap_var.set(s["snap_srt"])
        if s.get("cut_mode") in self.t("method_options"):
            self.cut_mode = s["cut_mode"]
            self.method_choice.set_key(self.cut_mode)
        if s.get("silence") in self.t("silence_options"):
            self.silence = s["silence"]
            self.silence_choice.set_key(self.silence)
        if "speed" in s:
            self.speed_var.set(s["speed"])
        if "hotwords" in s:
            self.glossary_var.set(s["hotwords"])
        if "diarize" in s:
            self.diarize_var.set(bool(s["diarize"]) and sherpa_available())
        if s.get("speakers") in SPEAKER_COUNTS:
            self.speakers = s["speakers"]
            self._sync_speakers_menu()
        if "speaker_labels" in s:
            self.speaker_labels = bool(s["speaker_labels"])
        if "markers" in s:
            self.markers_var.set(s["markers"])
        if "line_chars" in s:
            self.chars_var.set(int(s["line_chars"]))
        if "txt" in s:
            self.txt_var.set(s["txt"])
        if "md" in s:
            self.md_var.set(s["md"])
        if "review" in s:
            self.review_var.set(bool(s["review"]))
        for row in (self.threshold_row, self.margin_row, self.chars_row):
            row.update_label()
        self._update_export_caption()
        self._refresh_states()
        self._mark_stale()

    def _build_params(self) -> PipelineParams:
        return PipelineParams(
            margin=self.margin_var.get(), threshold=self.threshold_var.get(), export_key=self.export_key,
            do_srt=self.srt_var.get(), model_size=self.model_key, use_gpu=self.gpu_var.get(),
            snap_srt=self.snap_var.get(), cut_mode=self.cut_mode,
            silent_speed=self._speed() if self.silence == "speed" else None,
            hotwords=self.glossary_var.get(), diarize=self.diarize_var.get() and sherpa_available(),
            num_speakers=-1 if self.speakers == "auto" else int(self.speakers),
            speaker_labels=self.speaker_labels, markers=self.markers_var.get() and self.export_key != "media",
            line_chars=self.line_chars(), txt=self.txt_var.get(), md=self.md_var.get(), ui_lang=self.lang,
            hold_subtitles=self.review_var.get() and self.srt_var.get(),
        )

    # ── 部品の状態 ───────────────────────────────────────────────────────────────────
    def _refresh_states(self, *_):
        """設定の組み合わせに応じて、使えない項目を無効にする。"""
        srt_on = self.srt_var.get() and WHISPER_AVAILABLE
        def sw(widget, on):
            widget.configure(state="normal" if on else "disabled")
        sw(self.srt_switch, WHISPER_AVAILABLE)
        sw(self.model_menu, srt_on)
        sw(self.gpu_switch, srt_on and cuda_available())
        sw(self.snap_switch, srt_on)
        sw(self.glossary_entry, srt_on)
        sw(self.chars_row.slider, srt_on)
        sw(self.diarize_switch, srt_on and sherpa_available())
        diar = srt_on and self.diarize_var.get() and sherpa_available()
        sw(self.speakers_menu, diar)
        sw(self.txt_switch, srt_on)
        sw(self.md_switch, srt_on)
        sw(self.review_switch, srt_on)
        sw(self.markers_switch, self.export_key != "media")
        vad = self.cut_mode == "vad"
        sw(self.threshold_row.slider, not vad)
        self.threshold_row.value.configure(text_color=T.DUST if vad else T.CHALK)
        sw(self.speed_entry, self.silence == "speed")
        self.speed_prefix.configure(text_color=T.DUST if self.silence == "cut" else T.CHALK)

    def _on_method(self, key):
        self.cut_mode = key
        self._refresh_states()
        self._mark_stale()

    def _on_silence(self, key):
        self.silence = key
        self._refresh_states()
        self._mark_stale()

    def _on_export(self, key):
        self.export_key = key
        self._update_export_caption()
        self._refresh_states()

    def _on_model(self, shown):
        for k, v in self.t("model_options").items():
            if v == shown:
                self.model_key = k

    def _on_speakers(self, shown):
        self.speakers = "auto" if shown == self.t("speakers_auto") else shown

    def _sync_speakers_menu(self):
        self.speakers_menu.set(self.t("speakers_auto") if self.speakers == "auto" else self.speakers)

    def _commit_speed(self, _e=None):
        self.speed_var.set(self._speed())

    def _update_export_caption(self):
        self.export_cap.configure(text=self.t(f"cap_export_{self.export_key}"))

    def _update_folder_label(self):
        self.folder_lbl.configure(text=self.output_dir or self.t("folder_default"),
                                  text_color=T.CHALK if self.output_dir else T.DUST)

    # ── 素材 ────────────────────────────────────────────────────────────────────────
    def _on_drop(self, event):
        found = re.findall(r"\{([^}]+)\}|(\S+)", event.data.strip())
        self._set_files([f[0] or f[1] for f in found])

    def _browse_file(self):
        exts = " ".join(f"*{e}" for e in sorted(MEDIA_EXTS))
        paths = filedialog.askopenfilenames(title=self.t("file_dialog"),
                                            filetypes=[("Media files", exts), ("All files", "*.*")])
        if paths:
            self._set_files(list(paths))

    def _set_files(self, paths):
        """ファイル/フォルダを受け取り、対応する拡張子のファイルだけを入力にする。"""
        files: list[str] = []
        for p in paths:
            path = Path(p)
            if path.is_dir():
                files += [str(f) for f in sorted(path.iterdir()) if f.is_file() and f.suffix.lower() in MEDIA_EXTS]
            elif path.suffix.lower() in MEDIA_EXTS or path.exists():
                files.append(str(path))
        if not files:
            return
        self.input_files = files
        self._on_files_changed()
        self._run_preview()
        self._log(self.t("log_file", Path(files[0]).name) if len(files) == 1 else self.t("log_files", len(files)), "muted")

    def _clear_files(self):
        self.input_files = []
        self._on_files_changed()

    def _on_files_changed(self):
        self._preview_gen += 1                 # 計算中の確認は破棄する
        self._preview_cache.clear()
        self._play_cache.clear()
        self._preview_result = None
        self._reset_player()
        self._update_file_header()
        has = bool(self.input_files)
        if not has:
            self.cutmap.set_empty()
        self._stats = None
        self.btn_preview.enable(has)
        self.btn_clear.enable(has)
        self._update_stats()

    def _update_file_header(self):
        if not self.input_files:
            self.file_name.configure(text=self.t("file_none"), text_color=T.DUST)
            self.file_more.configure(text="")
            return
        self.file_name.configure(text=Path(self.input_files[0]).name, text_color=T.CHALK)
        n = len(self.input_files) - 1
        self.file_more.configure(text=self.t("file_more", n) if n else "")

    def _browse_outdir(self):
        path = filedialog.askdirectory(title=self.t("dir_dialog"))
        if path:
            self.output_dir = path
            self._update_folder_label()
            self._log(self.t("log_outdir", path), "muted")

    # ── 切れる場所の確認 ──────────────────────────────────────────────────────────────
    def _mark_stale(self):
        """設定が変わった。結果が出ているなら、少し待って自動で更新する。"""
        self.cutmap.set_stale(True)
        if self.player is not None and self.player.playing:
            self.player.pause()                # 設定が変わった: 古い設定の音を流し続けない
        self._update_transport()
        if getattr(self, "_preview_timer", None):
            self.after_cancel(self._preview_timer)
            self._preview_timer = None
        if self.input_files and self.cutmap.has_data:
            self._preview_timer = self.after(700, self._run_preview)

    def _update_stats(self):
        self.btn_preview.configure(text=self.t("btn_preview_again" if self.cutmap.has_data else "btn_preview"))
        (self.legend.grid if self.cutmap.has_data else self.legend.grid_remove)()
        s = getattr(self, "_stats", None)
        if self.cutmap.has_data and s:
            self.stats_time.configure(text=f"{W.fmt_time(s['original'])} → {W.fmt_time(s['result'])}")
            self.stats_text.configure(text=self.t("stats_line", s["saved_pct"], s["cuts"]))
        else:
            self.stats_time.configure(text="")
            self.stats_text.configure(text="")
        self._update_transport()

    def _run_preview(self):
        self._preview_timer = None
        if not self.input_files or not Path(self.input_files[0]).exists():
            return
        if self._preview_busy:
            self._preview_again = True       # 実行中なら、終わってから最新の設定でやり直す
            return
        self._preview_busy, self._preview_again = True, False
        gen = self._preview_gen
        cfg = CutSettings(self.margin_var.get(), self.threshold_var.get(), self.cut_mode,
                          self._speed() if self.silence == "speed" else None)
        path = self.input_files[0]
        if not self.cutmap.has_data:
            self.cutmap.set_busy()
        self.btn_preview.enable(False)

        def work():
            try:
                ae = get_auto_editor_path(self._log) if cfg.cut_mode == "threshold" else None
                result = compute_preview(path, cfg, ae, self._preview_cache)
                self.after(0, lambda: self._preview_done(gen, result, None))
            except Exception as exc:
                msg = str(exc)
                self.after(0, lambda m=msg: self._preview_done(gen, None, m))

        threading.Thread(target=work, daemon=True).start()

    def _preview_done(self, gen, result, error):
        self._preview_busy = False
        current = gen == self._preview_gen
        if current:
            self._reset_player()               # 新しい結果の区間で、次の再生時に組み立て直す
            if error is not None:
                self.cutmap.set_error(error)
                self._stats = None
                self._preview_result = None
            else:
                self._stats = result.stats
                self._preview_result = result
                self.cutmap.set_data(result.peaks, result.regions, result.duration)
        self.btn_preview.enable(bool(self.input_files))
        self._update_stats()
        if (self._preview_again or not current) and self.input_files:
            self._run_preview()

    # ── 編集後の音を聞く ─────────────────────────────────────────────────────────────
    def _transport_ready(self) -> bool:
        return (self.player is not None and self._preview_result is not None and self.cutmap.has_data
                and not self.cutmap.is_stale and bool(self.input_files))

    def _update_transport(self):
        if self.player is None:
            self.transport_note.configure(text=self.t("tr_unavailable"))
            return
        ready = self._transport_ready() and not self._audio_loading
        for b in (self.btn_prev, self.btn_play, self.btn_next):
            b.enable(ready)
        self.rate_choice.enable(ready)
        if self._audio_loading:
            label = self.t("tr_busy")
        else:
            label = self.t("tr_pause" if self.player.playing else "tr_play")
        self.btn_play.configure(text=label)
        self._update_clock()

    def _update_clock(self):
        if self.player is None:
            return
        if not self._transport_ready() or not self._stats:
            self.play_time.configure(text="")
            return
        pos = self.player.position if self.player.loaded else 0.0
        self.play_time.configure(text=f"{W.fmt_time(pos)} / {W.fmt_time(self._stats['result'])}")

    def _reset_player(self):
        if self.player is not None:
            self.player.unload()
        self.cutmap.set_playhead(None)
        if self._tick_job is not None:
            self.after_cancel(self._tick_job)
            self._tick_job = None
        if hasattr(self, "play_time"):
            self._update_transport()

    def _with_player(self, action):
        """音の準備ができていれば action を実行する。まだなら、元の音を読み込み、編集後の音を組み立ててから実行する。"""
        if not self._transport_ready() or self._audio_loading:
            return
        if self.player.loaded:
            self._run_player(action)
            return
        self._audio_loading = True
        self._update_transport()
        result, path, gen = self._preview_result, self.input_files[0], self._preview_gen

        def work():
            try:
                if self._play_cache.get("path") != path:
                    self._play_cache.clear()
                    self._play_cache["samples"] = decode_mix(path, PLAY_SR)
                    self._play_cache["path"] = path
                audio = EditedAudio.build(self._play_cache["samples"], result.chunks, result.fps, PLAY_SR)
                self.after(0, lambda: self._audio_ready(gen, result, audio, action, None))
            except Exception as exc:
                self.after(0, lambda m=str(exc): self._audio_ready(gen, result, None, action, m))

        threading.Thread(target=work, daemon=True).start()

    def _audio_ready(self, gen, result, audio, action, error):
        self._audio_loading = False
        if error is not None:
            self._log(self.t("log_play_failed", error), "error")
        elif gen == self._preview_gen and result is self._preview_result:     # 準備中に設定が変わっていなければ
            self.player.load(audio, self.play_rate)
            self._run_player(action)
            return
        self._update_transport()

    def _run_player(self, action):
        try:
            action()
        except PlayerError as exc:
            self._log(self.t("log_play_failed", exc), "error")
        self._update_transport()
        self._sync_playhead()
        if self.player.playing:
            self._start_tick()

    def _sync_playhead(self):
        self.cutmap.set_playhead(self.player.source_position if self.player.loaded else None)

    def _start_tick(self):
        if self._tick_job is None:
            self._tick_job = self.after(40, self._tick)

    def _tick(self):
        self._tick_job = None
        self._sync_playhead()
        if self.player.playing:
            self._update_clock()
            self._start_tick()
        else:
            self._update_transport()       # 末尾まで再生した: ボタンを「再生」に戻す

    def _play_toggle(self):
        self._with_player(self.player.toggle)

    def _play_next(self):
        self._with_player(self.player.next_cut)

    def _play_prev(self):
        self._with_player(self.player.prev_cut)

    def _seek_source(self, source_sec: float):
        self._with_player(lambda: self.player.seek_source(source_sec))

    def _on_rate(self, key):
        self.play_rate = float(key)
        if self.player is None or not self.player.loaded:
            return
        self._audio_loading = True            # 変換中は操作を止める（長い音声では数秒かかる）
        self._update_transport()

        def work():
            try:
                self.player.set_rate(self.play_rate)
            finally:
                self.after(0, self._rate_done)

        threading.Thread(target=work, daemon=True).start()

    def _rate_done(self):
        self._audio_loading = False
        self._update_transport()
        self._sync_playhead()

    # ── ログ ────────────────────────────────────────────────────────────────────────
    def _clear_log(self):
        self.console.configure(state="normal")
        self.console.delete("1.0", "end")
        self.console.configure(state="disabled")

    def _log(self, msg, tag=""):
        def _ins():
            self.console.configure(state="normal")
            self.console._textbox.insert("end", msg + "\n", tag) if tag else self.console.insert("end", msg + "\n")
            self.console.configure(state="disabled")
            self.console.see("end")
        self.after(0, _ins)

    # ── プリセット ───────────────────────────────────────────────────────────────────
    def _update_preset_menu(self):
        presets = load_store().get("presets", {})
        none = self.t("preset_none")
        self.preset_menu.configure(values=[none] + list(presets))
        if self.preset_var.get() not in presets:
            self.preset_var.set(none)

    def _on_preset_select(self, choice):
        presets = load_store().get("presets", {})
        if choice in presets:
            self._apply_settings(presets[choice])

    def _on_preset_save(self):
        dialog = ctk.CTkInputDialog(text=self.t("preset_name_prompt"), title=self.t("preset_save"),
                                    fg_color=T.PANEL, text_color=T.CHALK, button_fg_color=T.PENCIL,
                                    button_hover_color=T.PENCIL_HOVER, button_text_color=T.PENCIL_INK,
                                    entry_fg_color=T.WELL, entry_border_color=T.EDGE, entry_text_color=T.CHALK,
                                    font=T.font(ctk, "body"))
        name = (dialog.get_input() or "").strip()
        if not name:
            return
        store = load_store()
        upsert_preset(store, name, self._collect_settings())
        save_store(store)
        self._log(self.t("log_preset_saved", name), "success")
        self.preset_var.set(name)
        self._update_preset_menu()

    def _on_preset_delete(self):
        choice = self.preset_var.get()
        store = load_store()
        if choice in store.get("presets", {}):
            delete_preset(store, choice)
            save_store(store)
            self._log(self.t("log_preset_deleted", choice), "muted")
        self.preset_var.set(self.t("preset_none"))
        self._update_preset_menu()

    def _on_close(self):
        if self.player is not None:
            self.player.close()
        for win in self._open_editors():
            if not win._confirm_discard():
                return
        try:
            store = load_store()
            set_last_used(store, self._collect_settings())
            save_store(store)
        except Exception as e:
            print(f"Error saving presets on close: {e}", file=sys.stderr)
        self.destroy()

    # ── 処理 ────────────────────────────────────────────────────────────────────────
    def _start_process(self):
        if self.running:
            return
        if not self.input_files:
            messagebox.showwarning(self.t("warn_title"), self.t("warn_no_file"))
            return
        if any(not Path(f).exists() for f in self.input_files):
            messagebox.showerror(self.t("err_title"), self.t("err_not_found"))
            return
        params = self._build_params()
        files = [Path(f).resolve() for f in self.input_files]
        self._log("", "")
        self._log(self.t("log_start"), "info")
        self.running = True
        self.stop_requested = False
        self.btn_start.enable(False)
        self.btn_stop.enable(True)
        self.progress.configure(mode="indeterminate")
        self.progress.start()
        threading.Thread(target=self._worker, args=(files, params), daemon=True).start()

    def _worker(self, files, params):
        try:
            ae_path = get_auto_editor_path(self._log)    # 初回のみ公式リリースから取得（SHA-256 検証）
        except Exception as exc:
            self._log(self.t("log_ae_download_failed", exc), "error")
            self.running = False
            self.after(0, self._reset_ui)
            return
        shared_out = Path(self.output_dir).resolve() if self.output_dir else None
        stems = [f.stem for f in files]
        model_cache: dict = {}           # バッチ中は Whisper モデルを読み込み直さない
        finished, last_out, last_result = 0, None, None
        total = len(files)
        for idx, inp in enumerate(files, start=1):
            if self.stop_requested:
                break
            out_dir = shared_out or inp.parent
            stem = f"{inp.stem}_{idx}" if (shared_out and stems.count(inp.stem) > 1) else None
            self._log(self.t("log_batch_item", idx, total, inp.name) if total > 1 else self.t("log_input", inp.name),
                      "info")
            result = run_pipeline(ae_path, inp, out_dir, dataclasses.replace(params, out_stem=stem),
                                  on_log=self._log, should_stop=lambda: self.stop_requested, tr=self.t,
                                  model_cache=model_cache)
            if result.pending_paths and not result.stopped:
                self._review_and_wait(result, inp.stem if stem is None else stem)
            if result.ok and not result.stopped:
                finished += 1
                last_out, last_result = out_dir, result
        model_cache.clear()
        self.running = False
        if last_result is not None:
            self.last_cues = list(last_result.cues)
            self.last_title = Path(last_result.timeline_path).stem if last_result.timeline_path else ""
            self.last_out_dir = last_out
            paths = {}
            if last_result.srt_path:
                paths["srt"] = last_result.srt_path
            for p in last_result.extra_paths:
                paths[p.suffix.lstrip(".")] = p
            self.last_paths = paths
        if finished and not self.stop_requested:
            self._log(self.t("log_batch_done", finished) if total > 1 else self.t("log_done_all"), "success")
        self.after(0, self._reset_ui)

    def _review_and_wait(self, result, title: str):
        """字幕を保存する前に確認・編集ウィンドウを開き、閉じるまで処理を止める（ワーカースレッドで呼ぶ）。

        保存した宛先だけを result に反映する。保存しなかった字幕はファイルにならない。
        """
        done = threading.Event()
        outcome: dict = {}

        def finished(cues, saved, paths):
            outcome.update(cues=cues, saved=saved, paths=paths)
            done.set()

        self._log(self.t("log_review_wait"), "info")
        self.after(0, lambda: self._open_review(result, title, finished))
        while not done.wait(0.2):
            if self.stop_requested:       # 停止しても窓は残り、保存はできる
                return
        result.cues = outcome["cues"]
        written = outcome["paths"] if outcome["saved"] else {}
        result.srt_path = written.get("srt")
        result.extra_paths = [p for k, p in written.items() if k != "srt"]
        if outcome["saved"]:
            self._log(self.t("log_review_saved", ", ".join(p.name for p in written.values())), "success")
        else:
            self._log(self.t("log_review_discarded"), "warn")

    def _open_review(self, result, title: str, on_closed):
        self.review_win = SubtitleEditor(self, result.cues, title, result.pending_paths, pending=True,
                                         on_closed=on_closed)
        self.review_win.focus()

    def _stop_process(self):
        self.stop_requested = True
        self._log(self.t("log_stop_requested"), "warn")

    def _reset_ui(self):
        self.running = False
        self.btn_start.enable(True)
        self.btn_stop.enable(False)
        self.btn_open_out.enable(self.last_out_dir is not None)
        self.btn_review.enable(bool(self.last_cues))
        self.progress.stop()
        self.progress.configure(mode="determinate")
        self.progress.set(0)

    def _open_output(self):
        if self.last_out_dir:
            os.startfile(str(self.last_out_dir))

    # ── 字幕の確認・編集 ──────────────────────────────────────────────────────────────
    def _editor_alive(self) -> bool:
        return self.editor_win in self._open_editors()

    def _open_editors(self) -> list:
        """開いている字幕ウィンドウ（処理後に開いたものと、保存前の確認用）。"""
        alive = []
        for win in (self.editor_win, self.review_win):
            try:
                if win is not None and win.winfo_exists():
                    alive.append(win)
            except tk.TclError:
                pass
        return alive

    def _open_editor(self):
        if self._editor_alive():
            self.editor_win.lift()
            self.editor_win.focus()
            return
        self.editor_win = SubtitleEditor(self, self.last_cues, self.last_title, self.last_paths)


def main():
    if sys.platform == "win32":
        try:    # Python から起動しても、タスクバーに python.exe ではなく SnipSync のアイコンを出す
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("R3NeR3N.SnipSync")
        except Exception:
            pass
    app = SnipSyncApp()
    if not WHISPER_AVAILABLE:
        app._log(app.t("log_whisper_unavailable"), "warn")
    app.mainloop()


if __name__ == "__main__":
    main()
