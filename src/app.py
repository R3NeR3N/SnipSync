"""
SnipSync - Silent Video Cutter & Subtitle Generator
Cuts silent portions from video/audio, exports XML for NLEs (or cut media), and generates
.srt subtitles (+ optional speaker labels, .txt/.md transcript).
"""
import dataclasses
import os
import re
import subprocess
import sys
import tempfile
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

from aebin import get_auto_editor_path
from autoeditor import (
    AUDIO_ONLY_TIMEBASE,
    MEDIA_EXTS,
    build_v1_export_cmd,
    is_audio_only,
    probe_fps,
)
from diarize import sherpa_available
from i18n import I18N
from pipeline import PipelineParams, run_pipeline
from presets import delete_preset, load_store, save_store, set_last_used, upsert_preset
from subtitles import (  # noqa: F401  (format_timestamp re-exported for tests)
    cuda_available,
    format_srt,
    format_timestamp,
)
from theme import (
    ACCENT,
    ACCENT_HOVER,
    BG_CARD,
    BG_CONSOLE,
    BG_DARK,
    ERROR_COL,
    SUCCESS,
    TEXT_MUTED,
    WARN_COL,
)
from transcript import cues_to_md, cues_to_txt, parse_srt
from version import APP_VERSION  # noqa: F401  (re-exported for tests)

EXPORT_MODES = {
    "DaVinci Resolve (.fcpxml)":    ("resolve",       ".fcpxml"),
    "Premiere Pro (.xml)":          ("premiere",      ".xml"),
    "Final Cut Pro (.fcpxml)":      ("final-cut-pro", ".fcpxml"),
    "Cut media / カット済みメディア": ("media",         ""),
}

SPEAKER_CHOICES = ["auto", "2", "3", "4", "5", "6"]

# ── Base class ─────────────────────────────────────────────────────────────────
if DND_AVAILABLE:
    class _Base(ctk.CTk, TkinterDnD.DnDWrapper):
        def __init__(self, *a, **kw):
            super().__init__(*a, **kw)
            self.TkdndVersion = TkinterDnD._require(self)
else:
    class _Base(ctk.CTk):
        pass


def _font(size=12, weight="normal", family="Segoe UI"):
    return ctk.CTkFont(family=family, size=size, weight=weight)


def _fmt_dur(sec: float) -> str:
    sec = int(round(sec))
    return f"{sec // 60}:{sec % 60:02d}" if sec < 3600 else f"{sec // 3600}:{sec % 3600 // 60:02d}:{sec % 60:02d}"


# ── 波形プレビュー ─────────────────────────────────────────────────────────────
class WaveformWindow(ctk.CTkToplevel):
    """どこが切られるか（auto-editor の v1 chunks そのもの）を波形に重ねて表示する。"""

    def __init__(self, app, file_path):
        super().__init__(app)
        self.app = app
        self.file_path = str(file_path)
        self.title(app.t("wave_title"))
        self.geometry("1000x340")
        self.minsize(640, 260)
        self.configure(fg_color=BG_DARK)
        self.peaks = None
        self.regions = []
        self.duration = 0.0
        self.samples = None          # 再計算のたびに読み直さない
        self.busy = False

        top = ctk.CTkFrame(self, fg_color="transparent")
        top.pack(fill="x", padx=14, pady=(12, 4))
        self.stats_lbl = ctk.CTkLabel(top, text=app.t("wave_calc"), font=_font(13, "bold"),
                                      text_color="white")
        self.stats_lbl.pack(side="left")
        self.recalc_btn = ctk.CTkButton(top, text=app.t("wave_recalc"), width=90, height=28,
                                        fg_color=ACCENT, hover_color=ACCENT_HOVER,
                                        command=self.compute)
        self.recalc_btn.pack(side="right")

        self.canvas = tk.Canvas(self, bg=BG_CONSOLE, highlightthickness=0, height=220)
        self.canvas.pack(fill="both", expand=True, padx=14, pady=4)
        self.canvas.bind("<Configure>", lambda e: self.draw())

        self.legend_lbl = ctk.CTkLabel(self, text=app.t("wave_legend"), font=_font(11),
                                       text_color=TEXT_MUTED)
        self.legend_lbl.pack(anchor="w", padx=16, pady=(0, 10))
        self.compute()

    def compute(self):
        if self.busy:
            return
        self.busy = True
        self.stats_lbl.configure(text=self.app.t("wave_calc"))
        cfg = self.app.snapshot_cut_settings()

        def work():
            try:
                ae_path = get_auto_editor_path()
                from vad import decode_mix, detect_speech, read_v1_chunks, speech_to_chunks
                from waveform import chunk_regions, compute_peaks, preview_stats
                audio_only = is_audio_only(self.file_path)
                fps = AUDIO_ONLY_TIMEBASE if audio_only else probe_fps(self.file_path)
                if not fps:
                    raise RuntimeError("fps")
                if self.samples is None:
                    self.samples = decode_mix(self.file_path, 16000)
                if cfg["cut_mode"] == "vad":
                    total = len(self.samples) / 16000
                    chunks = speech_to_chunks(detect_speech(self.samples), total, fps,
                                              margin=cfg["margin"], silent_speed=cfg["silent_speed"])
                else:
                    with tempfile.TemporaryDirectory() as tmp:
                        out_json = Path(tmp) / "v1.json"
                        cmd = build_v1_export_cmd(ae_path, self.file_path, cfg["margin"],
                                                  cfg["threshold"], out_json, fps,
                                                  silent_speed=cfg["silent_speed"])
                        subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                                       errors="replace",
                                       creationflags=0x08000000 if sys.platform == "win32" else 0)
                        chunks = read_v1_chunks(out_json)
                if not chunks:
                    raise RuntimeError("no chunks")
                peaks = compute_peaks(self.samples, 2400)
                regions = chunk_regions(chunks, fps)
                stats = preview_stats(chunks, fps)
                self.after(0, lambda: self._done(peaks, regions, stats))
            except Exception as exc:
                # lambda は except を抜けた後に実行される。exc は消えるので文字列を先に取り出す。
                msg = str(exc)
                self.after(0, lambda m=msg: self._fail(m))

        threading.Thread(target=work, daemon=True).start()

    def _done(self, peaks, regions, stats):
        self.busy = False
        self.peaks, self.regions = peaks, regions
        self.duration = stats["original"]
        self.stats_lbl.configure(text=self.app.t(
            "wave_stats", _fmt_dur(stats["original"]), _fmt_dur(stats["result"]),
            stats["saved_pct"], stats["cuts"]))
        self.draw()

    def _fail(self, msg):
        self.busy = False
        self.stats_lbl.configure(text=self.app.t("wave_error", msg))

    def draw(self):
        c = self.canvas
        c.delete("all")
        if self.peaks is None or len(self.peaks) == 0 or self.duration <= 0:
            return
        w, h = max(c.winfo_width(), 50), max(c.winfo_height(), 50)
        mid = h / 2
        for s, e, kind in self.regions:
            if kind == "keep":
                continue
            x0, x1 = s / self.duration * w, e / self.duration * w
            color = "#e5484d" if kind == "cut" else "#f5a524"
            c.create_rectangle(x0, 0, max(x1, x0 + 1), h, fill=color, outline="", stipple="gray50")
        n = len(self.peaks)
        top = float(self.peaks.max()) or 1.0
        for x in range(int(w)):
            p = float(self.peaks[min(n - 1, int(x / w * n))]) / top
            half = max(1.0, p * (mid - 6))
            c.create_line(x, mid - half, x, mid + half, fill=ACCENT)


# ── 字幕プレビュー ─────────────────────────────────────────────────────────────
class TextPreviewWindow(ctk.CTkToplevel):
    """字幕全体を .txt / .md / .srt の形で表示・コピー・保存する。"""

    VIEWS = ("txt", "md", "srt")

    def __init__(self, app):
        super().__init__(app)
        self.app = app
        self.title(app.t("text_title"))
        self.geometry("820x620")
        self.minsize(520, 360)
        self.configure(fg_color=BG_DARK)
        self.cues = list(app.last_cues)
        self.title_text = app.last_title
        self.view_var = ctk.StringVar(value="txt")
        self.stamp_var = ctk.BooleanVar(value=True)

        bar = ctk.CTkFrame(self, fg_color="transparent")
        bar.pack(fill="x", padx=14, pady=(12, 4))
        self.seg = ctk.CTkSegmentedButton(bar, values=[".txt", ".md", ".srt"], command=self._on_seg,
                                          selected_color=ACCENT, selected_hover_color=ACCENT_HOVER)
        self.seg.set(".txt")
        self.seg.pack(side="left")
        ctk.CTkCheckBox(bar, text=app.t("text_timestamps"), variable=self.stamp_var,
                        fg_color=ACCENT, hover_color=ACCENT_HOVER, font=_font(12),
                        command=self.render).pack(side="left", padx=16)
        ctk.CTkButton(bar, text=app.t("text_load_srt"), width=110, height=28, fg_color=BG_CARD,
                      hover_color=ACCENT, command=self._load_srt).pack(side="right")
        ctk.CTkButton(bar, text=app.t("text_save"), width=80, height=28, fg_color=ACCENT,
                      hover_color=ACCENT_HOVER, command=self._save).pack(side="right", padx=6)
        ctk.CTkButton(bar, text=app.t("text_copy"), width=80, height=28, fg_color=BG_CARD,
                      hover_color=ACCENT, command=self._copy).pack(side="right")

        self.box = ctk.CTkTextbox(self, font=_font(13, family="Consolas"), fg_color=BG_CONSOLE,
                                  text_color="#c9d1d9", wrap="word")
        self.box.pack(fill="both", expand=True, padx=14, pady=(4, 8))
        self.status = ctk.CTkLabel(self, text="", font=_font(11), text_color=TEXT_MUTED)
        self.status.pack(anchor="w", padx=16, pady=(0, 10))
        self.render()

    def _on_seg(self, value):
        self.view_var.set(value.lstrip("."))
        self.render()

    def _text(self) -> str:
        if not self.cues:
            return self.app.t("text_empty")
        speakers = any(c.speaker is not None for c in self.cues)
        stamps = self.stamp_var.get()
        view = self.view_var.get()
        if view == "md":
            return cues_to_md(self.cues, title=self.title_text, timestamps=stamps,
                              speakers=speakers, ui_lang=self.app.lang)
        if view == "srt":
            return format_srt(self.cues, speaker_labels=speakers, ui_lang=self.app.lang)
        return cues_to_txt(self.cues, timestamps=stamps, speakers=speakers, ui_lang=self.app.lang)

    def render(self):
        self.box.configure(state="normal")
        self.box.delete("1.0", "end")
        self.box.insert("1.0", self._text())
        self.box.configure(state="disabled")

    def _copy(self):
        self.clipboard_clear()
        self.clipboard_append(self._text())
        self.status.configure(text=self.app.t("text_copied"))

    def _save(self):
        view = self.view_var.get()
        path = filedialog.asksaveasfilename(
            parent=self, defaultextension=f".{view}", initialfile=f"{self.title_text or 'subtitles'}.{view}",
            filetypes=[(view.upper(), f"*.{view}"), ("All files", "*.*")])
        if not path:
            return
        Path(path).write_text(self._text(), encoding="utf-8")
        self.status.configure(text=self.app.t("text_saved", path))

    def _load_srt(self):
        path = filedialog.askopenfilename(parent=self, filetypes=[("SRT", "*.srt"), ("All files", "*.*")])
        if not path:
            return
        try:
            self.cues = parse_srt(Path(path).read_text(encoding="utf-8-sig"))
            self.title_text = Path(path).stem
        except Exception as e:
            self.status.configure(text=str(e))
            return
        self.render()


# ── Main App ───────────────────────────────────────────────────────────────────
class SnipSyncApp(_Base):
    def __init__(self):
        super().__init__()
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")

        self.lang = "ja"
        self.input_files: list[str] = []
        self.output_dir  = ""

        self.margin_var  = ctk.DoubleVar(value=0.2)
        self.threshold_var = ctk.DoubleVar(value=4.0)
        self.export_var  = ctk.StringVar(value=list(EXPORT_MODES.keys())[0])
        self.srt_var     = ctk.BooleanVar(value=True)
        self.gpu_var     = ctk.BooleanVar(value=False)
        self.snap_srt_var = ctk.BooleanVar(value=True)
        # Store the internal model key (tiny, base, small, medium, ...)
        self.model_key_var = ctk.StringVar(value="small")
        # Store the translated display string for OptionMenu
        self.model_display_var = ctk.StringVar()

        # 新機能の設定
        self.cut_mode_key_var = ctk.StringVar(value="threshold")
        self.cut_mode_display_var = ctk.StringVar()
        self.silence_key_var = ctk.StringVar(value="cut")
        self.silence_display_var = ctk.StringVar()
        self.speed_var = ctk.DoubleVar(value=8.0)
        self.hotwords_var = ctk.StringVar(value="")
        self.diarize_var = ctk.BooleanVar(value=False)
        self.speakers_var = ctk.StringVar(value="auto")
        self.speaker_labels_var = ctk.BooleanVar(value=True)
        self.markers_var = ctk.BooleanVar(value=False)
        self.line_chars_var = ctk.IntVar(value=20)
        self.txt_var = ctk.BooleanVar(value=False)
        self.md_var = ctk.BooleanVar(value=False)

        self.lang_var    = ctk.StringVar(value="日本語")

        self.process     = None
        self.running     = False
        self.stop_requested = False
        self.last_cues: list = []
        self.last_title = ""

        self.configure(fg_color=BG_DARK)
        self.minsize(820, 780)
        self.geometry("900x920")

        self._build_ui()
        self._update_margin_label()
        self._update_threshold_label()
        if not cuda_available():
            self.gpu_checkbox.configure(state="disabled")
            self._log(self.t("log_gpu_unavailable"), "muted")

        # Load preset store and apply last used settings
        store = load_store()
        if store.get("last_used"):
            self._apply_settings(store["last_used"])

        self._apply_lang()
        self._refresh_states()
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def t(self, key, *args):
        s = I18N[self.lang].get(key, key)
        return s.format(*args) if args else s

    def _build_ui(self):
        # Header
        hdr = ctk.CTkFrame(self, fg_color=BG_CARD, corner_radius=0, height=64)
        hdr.pack(fill="x", side="top")
        hdr.pack_propagate(False)

        self.title_lbl = ctk.CTkLabel(
            hdr, text="✂  SnipSync", font=_font(22, "bold"), text_color=ACCENT)
        self.title_lbl.pack(side="left", padx=24, pady=16)

        self.subtitle_lbl = ctk.CTkLabel(hdr, text="", font=_font(12), text_color=TEXT_MUTED)
        self.subtitle_lbl.pack(side="left", pady=16)

        # Language selector
        lang_frame = ctk.CTkFrame(hdr, fg_color="transparent")
        lang_frame.pack(side="right", padx=20)
        self.lang_lbl_hdr = ctk.CTkLabel(lang_frame, text="", font=_font(11), text_color=TEXT_MUTED)
        self.lang_lbl_hdr.pack(side="left", padx=(0, 6))
        self.lang_menu = ctk.CTkOptionMenu(
            lang_frame, values=["日本語", "English"], variable=self.lang_var, width=110,
            font=_font(12), fg_color=BG_DARK, button_color=ACCENT,
            button_hover_color=ACCENT_HOVER, dropdown_fg_color=BG_DARK, command=self._on_lang_change)
        self.lang_menu.pack(side="left")

        main = ctk.CTkFrame(self, fg_color="transparent")
        main.pack(fill="both", expand=True, padx=20, pady=(14, 12))
        main.columnconfigure(0, weight=1)
        main.rowconfigure(1, weight=3)     # 設定カード（スクロール可）
        main.rowconfigure(4, weight=1)     # コンソール

        self._build_drop_zone(main)
        self._build_settings(main)
        self._build_actions(main)
        self._build_console(main)

    def _build_drop_zone(self, parent):
        zone = ctk.CTkFrame(parent, fg_color=BG_CARD, corner_radius=16)
        zone.grid(row=0, column=0, sticky="ew", pady=(0, 10))

        self.drop_label = ctk.CTkLabel(
            zone, text="", font=_font(13), text_color=TEXT_MUTED, height=52, cursor="hand2")
        self.drop_label.pack(fill="x", padx=20, pady=12)
        self.drop_label.bind("<Button-1>", lambda e: self._browse_file())

        if DND_AVAILABLE:
            self.drop_label.drop_target_register(DND_FILES)
            self.drop_label.dnd_bind("<<Drop>>", self._on_drop)

    # ── settings card ──────────────────────────────────────────────────────────
    def _row_label(self, card, row):
        lbl = ctk.CTkLabel(card, text="", font=_font(12, "bold"), text_color="white")
        lbl.grid(row=row, column=0, sticky="w", padx=20, pady=5)
        return lbl

    def _menu(self, parent, var, command, width=170):
        return ctk.CTkOptionMenu(
            parent, values=[""], variable=var, font=_font(11), fg_color=BG_DARK,
            button_color=ACCENT, button_hover_color=ACCENT_HOVER, dropdown_fg_color=BG_DARK,
            width=width, command=command)

    def _check(self, parent, var, command=None):
        return ctk.CTkCheckBox(parent, text="", variable=var, font=_font(11), fg_color=ACCENT,
                               hover_color=ACCENT_HOVER, command=command)

    def _build_settings(self, parent):
        card = ctk.CTkScrollableFrame(parent, fg_color=BG_CARD, corner_radius=16)
        card.grid(row=1, column=0, sticky="nsew", pady=(0, 10))
        card.columnconfigure((1, 3), weight=1)

        # 0. Preset
        self.preset_lbl_w = self._row_label(card, 0)
        preset_frame = ctk.CTkFrame(card, fg_color="transparent")
        preset_frame.grid(row=0, column=1, columnspan=3, sticky="w", padx=(0, 20), pady=5)

        self.preset_menu_var = ctk.StringVar()
        self.preset_menu = ctk.CTkOptionMenu(
            preset_frame, values=[], variable=self.preset_menu_var, font=_font(12), fg_color=BG_DARK,
            button_color=ACCENT, button_hover_color=ACCENT_HOVER, dropdown_fg_color=BG_DARK, width=200,
            command=self._on_preset_select)
        self.preset_menu.pack(side="left")
        self.preset_save_btn = ctk.CTkButton(
            preset_frame, text="", width=60, font=_font(11), fg_color=BG_DARK, hover_color=ACCENT,
            command=self._on_preset_save)
        self.preset_save_btn.pack(side="left", padx=(10, 0))
        self.preset_delete_btn = ctk.CTkButton(
            preset_frame, text="", width=60, font=_font(11), fg_color=BG_DARK, hover_color=ERROR_COL,
            command=self._on_preset_delete)
        self.preset_delete_btn.pack(side="left", padx=(10, 0))

        # 1. Margin
        self.margin_lbl_w = self._row_label(card, 1)
        sf1 = ctk.CTkFrame(card, fg_color="transparent")
        sf1.grid(row=1, column=1, sticky="ew", padx=(0, 10), pady=5)
        sf1.columnconfigure(0, weight=1)
        self.slider_margin = ctk.CTkSlider(
            sf1, from_=0.0, to=2.0, number_of_steps=40, variable=self.margin_var,
            command=self._on_slider_margin, button_color=ACCENT, button_hover_color=ACCENT_HOVER,
            progress_color=ACCENT)
        self.slider_margin.grid(row=0, column=0, sticky="ew")
        self.margin_val_lbl = ctk.CTkLabel(card, text="", font=_font(13, "bold", "Consolas"),
                                           text_color=ACCENT, width=60)
        self.margin_val_lbl.grid(row=1, column=2, padx=(0, 6), pady=5)
        self.margin_entry = ctk.CTkEntry(card, width=70, textvariable=self.margin_var,
                                         font=_font(12, family="Consolas"), justify="center")
        self.margin_entry.grid(row=1, column=3, sticky="w", padx=(0, 20), pady=5)
        self.margin_entry.bind("<Return>", self._on_entry_margin_commit)
        self.margin_entry.bind("<FocusOut>", self._on_entry_margin_commit)

        # 2. Threshold
        self.threshold_lbl_w = self._row_label(card, 2)
        sf2 = ctk.CTkFrame(card, fg_color="transparent")
        sf2.grid(row=2, column=1, sticky="ew", padx=(0, 10), pady=5)
        sf2.columnconfigure(0, weight=1)
        self.slider_threshold = ctk.CTkSlider(
            sf2, from_=0.0, to=50.0, number_of_steps=100, variable=self.threshold_var,
            command=self._on_slider_threshold, button_color=ACCENT, button_hover_color=ACCENT_HOVER,
            progress_color=ACCENT)
        self.slider_threshold.grid(row=0, column=0, sticky="ew")
        self.threshold_val_lbl = ctk.CTkLabel(card, text="", font=_font(13, "bold", "Consolas"),
                                              text_color=ACCENT, width=60)
        self.threshold_val_lbl.grid(row=2, column=2, padx=(0, 6), pady=5)
        self.threshold_entry = ctk.CTkEntry(card, width=70, textvariable=self.threshold_var,
                                            font=_font(12, family="Consolas"), justify="center")
        self.threshold_entry.grid(row=2, column=3, sticky="w", padx=(0, 20), pady=5)
        self.threshold_entry.bind("<Return>", self._on_entry_threshold_commit)
        self.threshold_entry.bind("<FocusOut>", self._on_entry_threshold_commit)

        # 3. Cut method + silence handling
        self.cut_mode_lbl_w = self._row_label(card, 3)
        cm = ctk.CTkFrame(card, fg_color="transparent")
        cm.grid(row=3, column=1, columnspan=3, sticky="w", padx=(0, 20), pady=5)
        self.cut_mode_menu = self._menu(cm, self.cut_mode_display_var, self._on_cut_mode_select, 190)
        self.cut_mode_menu.pack(side="left")
        self.silence_lbl_w = ctk.CTkLabel(cm, text="", font=_font(11), text_color=TEXT_MUTED)
        self.silence_lbl_w.pack(side="left", padx=(20, 8))
        self.silence_menu = self._menu(cm, self.silence_display_var, self._on_silence_select, 130)
        self.silence_menu.pack(side="left")
        self.speed_lbl_w = ctk.CTkLabel(cm, text="", font=_font(11), text_color=TEXT_MUTED)
        self.speed_lbl_w.pack(side="left", padx=(14, 6))
        self.speed_entry = ctk.CTkEntry(cm, width=56, textvariable=self.speed_var,
                                        font=_font(12, family="Consolas"), justify="center")
        self.speed_entry.pack(side="left")
        self.speed_entry.bind("<Return>", self._on_entry_speed_commit)
        self.speed_entry.bind("<FocusOut>", self._on_entry_speed_commit)

        # 4. Export format
        self.export_lbl_w = self._row_label(card, 4)
        self.export_menu = ctk.CTkOptionMenu(
            card, values=list(EXPORT_MODES.keys()), variable=self.export_var, font=_font(12),
            fg_color=BG_DARK, button_color=ACCENT, button_hover_color=ACCENT_HOVER,
            dropdown_fg_color=BG_DARK, width=300, command=self._on_export_change)
        self.export_menu.grid(row=4, column=1, columnspan=3, sticky="w", padx=(0, 20), pady=5)

        # 5. Subtitles: enable
        self.srt_lbl_w = self._row_label(card, 5)
        self.srt_checkbox = self._check(card, self.srt_var, self._on_srt_toggle)
        self.srt_checkbox.grid(row=5, column=1, columnspan=3, sticky="w", padx=(0, 20), pady=5)

        # 6. AI model + GPU
        self.model_lbl_w = self._row_label(card, 6)
        mr = ctk.CTkFrame(card, fg_color="transparent")
        mr.grid(row=6, column=1, columnspan=3, sticky="w", padx=(0, 20), pady=5)
        self.model_menu = self._menu(mr, self.model_display_var, self._on_model_select, 330)
        self.model_menu.pack(side="left")
        self.gpu_checkbox = self._check(mr, self.gpu_var)
        self.gpu_checkbox.pack(side="left", padx=(16, 0))

        # 7. Subtitle options: cut-align + line width
        self.sub_opt_lbl_w = self._row_label(card, 7)
        so = ctk.CTkFrame(card, fg_color="transparent")
        so.grid(row=7, column=1, columnspan=3, sticky="w", padx=(0, 20), pady=5)
        self.snap_srt_checkbox = self._check(so, self.snap_srt_var)
        self.snap_srt_checkbox.pack(side="left")
        self.line_chars_lbl_w = ctk.CTkLabel(so, text="", font=_font(11), text_color=TEXT_MUTED)
        self.line_chars_lbl_w.pack(side="left", padx=(18, 6))
        self.line_chars_entry = ctk.CTkEntry(so, width=50, textvariable=self.line_chars_var,
                                             font=_font(12, family="Consolas"), justify="center")
        self.line_chars_entry.pack(side="left")

        # 8. Speakers
        self.speaker_row_lbl_w = self._row_label(card, 8)
        sp = ctk.CTkFrame(card, fg_color="transparent")
        sp.grid(row=8, column=1, columnspan=3, sticky="w", padx=(0, 20), pady=5)
        self.diarize_checkbox = self._check(sp, self.diarize_var, self._refresh_states)
        self.diarize_checkbox.pack(side="left")
        self.speakers_lbl_w = ctk.CTkLabel(sp, text="", font=_font(11), text_color=TEXT_MUTED)
        self.speakers_lbl_w.pack(side="left", padx=(14, 6))
        self.speakers_menu = ctk.CTkOptionMenu(
            sp, values=SPEAKER_CHOICES, font=_font(11), fg_color=BG_DARK, button_color=ACCENT,
            button_hover_color=ACCENT_HOVER, dropdown_fg_color=BG_DARK, width=80,
            command=self._on_speakers_select)
        self.speakers_menu.pack(side="left")
        self.speaker_labels_checkbox = self._check(sp, self.speaker_labels_var)
        self.speaker_labels_checkbox.pack(side="left", padx=(16, 0))

        # 9. Transcript files
        self.out_opt_lbl_w = self._row_label(card, 9)
        oo = ctk.CTkFrame(card, fg_color="transparent")
        oo.grid(row=9, column=1, columnspan=3, sticky="w", padx=(0, 20), pady=5)
        self.txt_checkbox = self._check(oo, self.txt_var)
        self.txt_checkbox.pack(side="left")
        self.md_checkbox = self._check(oo, self.md_var)
        self.md_checkbox.pack(side="left", padx=(16, 0))

        # 10. Markers
        self.markers_lbl_w = self._row_label(card, 10)
        self.markers_checkbox = self._check(card, self.markers_var)
        self.markers_checkbox.grid(row=10, column=1, columnspan=3, sticky="w", padx=(0, 20), pady=5)

        # 11. Glossary (hotwords)
        self.hotwords_lbl_w = self._row_label(card, 11)
        self.hotwords_entry = ctk.CTkEntry(card, textvariable=self.hotwords_var, font=_font(12))
        self.hotwords_entry.grid(row=11, column=1, columnspan=3, sticky="ew", padx=(0, 20), pady=5)

        # 12. Output dir
        self.outdir_lbl_w = self._row_label(card, 12)
        of = ctk.CTkFrame(card, fg_color="transparent")
        of.grid(row=12, column=1, columnspan=3, sticky="ew", padx=(0, 20), pady=5)
        of.columnconfigure(0, weight=1)
        self.outdir_val_lbl = ctk.CTkLabel(of, text="", anchor="w", font=_font(11), text_color=TEXT_MUTED)
        self.outdir_val_lbl.grid(row=0, column=0, sticky="ew")
        self.outdir_btn = ctk.CTkButton(
            of, text="", width=60, font=_font(11), fg_color=BG_DARK, hover_color=ACCENT,
            command=self._browse_outdir)
        self.outdir_btn.grid(row=0, column=1, padx=(8, 0))

        if not WHISPER_AVAILABLE:
            self.srt_var.set(False)
            self.srt_checkbox.configure(state="disabled")

    def _build_actions(self, parent):
        act = ctk.CTkFrame(parent, fg_color="transparent")
        act.grid(row=2, column=0, sticky="ew", pady=(0, 10))
        act.columnconfigure(0, weight=1)

        self.run_btn = ctk.CTkButton(
            act, text="", font=_font(14, "bold"), height=46, corner_radius=12, fg_color=ACCENT,
            hover_color=ACCENT_HOVER, command=self._start_process)
        self.run_btn.grid(row=0, column=0, sticky="ew")

        self.wave_btn = ctk.CTkButton(
            act, text="", font=_font(12), height=46, corner_radius=12, fg_color=BG_CARD,
            hover_color=ACCENT, command=self._open_waveform)
        self.wave_btn.grid(row=0, column=1, padx=(10, 0), sticky="e")

        self.text_btn = ctk.CTkButton(
            act, text="", font=_font(12), height=46, corner_radius=12, fg_color=BG_CARD,
            hover_color=ACCENT, command=self._open_text_preview)
        self.text_btn.grid(row=0, column=2, padx=(10, 0), sticky="e")

        self.stop_btn = ctk.CTkButton(
            act, text="", font=_font(13), height=46, corner_radius=12, fg_color="#3a3a4a",
            hover_color=ERROR_COL, command=self._stop_process, state="disabled")
        self.stop_btn.grid(row=0, column=3, padx=(10, 0), sticky="e")

        self.progress = ctk.CTkProgressBar(act, mode="indeterminate", progress_color=ACCENT, height=6,
                                           corner_radius=3)
        self.progress.grid(row=1, column=0, columnspan=4, sticky="ew", pady=(8, 0))
        self.progress.set(0)

    def _build_console(self, parent):
        hdr_f = ctk.CTkFrame(parent, fg_color="transparent")
        hdr_f.grid(row=3, column=0, sticky="ew")

        self.log_hdr_lbl = ctk.CTkLabel(hdr_f, text="", font=_font(11, "bold"), text_color=TEXT_MUTED)
        self.log_hdr_lbl.pack(side="left")

        self.clear_btn = ctk.CTkButton(
            hdr_f, text="", width=52, height=22, font=_font(10), fg_color="transparent", border_width=1,
            text_color=TEXT_MUTED, hover_color=BG_CARD, command=self._clear_log)
        self.clear_btn.pack(side="right")

        card = ctk.CTkFrame(parent, fg_color=BG_CONSOLE, corner_radius=12)
        card.grid(row=4, column=0, sticky="nsew", pady=(4, 0))

        self.console = ctk.CTkTextbox(
            card, font=_font(11, family="Consolas"), fg_color=BG_CONSOLE, text_color="#c9d1d9",
            wrap="word", state="disabled", scrollbar_button_color=ACCENT, height=96)
        self.console.pack(fill="both", expand=True, padx=2, pady=2)

        self.console._textbox.tag_config("info",    foreground="#58a6ff")
        self.console._textbox.tag_config("success", foreground=SUCCESS)
        self.console._textbox.tag_config("error",   foreground=ERROR_COL)
        self.console._textbox.tag_config("warn",    foreground=WARN_COL)
        self.console._textbox.tag_config("muted",   foreground=TEXT_MUTED)

    # ── Language & UI Updates ──────────────────────────────────────────────────
    def _on_lang_change(self, choice):
        self.lang = "ja" if choice == "日本語" else "en"
        self._apply_lang()

    def _apply_lang(self):
        self.title(self.t("title"))
        self.subtitle_lbl.configure(text=self.t("subtitle"))
        self.lang_lbl_hdr.configure(text=self.t("lang_label"))
        self._refresh_drop_label()

        # Update preset labels & buttons
        self.preset_lbl_w.configure(text=self.t("preset_label"))
        self.preset_save_btn.configure(text=self.t("preset_save"))
        self.preset_delete_btn.configure(text=self.t("preset_delete"))

        # Update preset OptionMenu values dynamically based on language
        old_val = self.preset_menu_var.get()
        none_ja = I18N["ja"]["preset_none"]
        none_en = I18N["en"]["preset_none"]

        store = load_store()
        presets = store.get("presets", {})
        none_text = self.t("preset_none")
        values = [none_text] + list(presets.keys())
        self.preset_menu.configure(values=values)

        if old_val in (none_ja, none_en) or old_val not in presets:
            self.preset_menu_var.set(none_text)
        else:
            self.preset_menu_var.set(old_val)

        self.margin_lbl_w.configure(text=self.t("margin_label"))
        self.threshold_lbl_w.configure(text=self.t("threshold_label"))
        self.export_lbl_w.configure(text=self.t("export_label"))
        self.srt_lbl_w.configure(text=self.t("srt_label"))
        self.srt_checkbox.configure(text=self.t("srt_check"))
        self.gpu_checkbox.configure(text=self.t("gpu_label"))
        self.snap_srt_checkbox.configure(text=self.t("snap_srt_label"))
        self.model_lbl_w.configure(text=self.t("model_label"))

        self.cut_mode_lbl_w.configure(text=self.t("cut_mode_label"))
        self.silence_lbl_w.configure(text=self.t("silence_label"))
        self.speed_lbl_w.configure(text=self.t("speed_label"))
        self._sync_option_menu(self.cut_mode_menu, "cut_mode_options", self.cut_mode_key_var,
                               self.cut_mode_display_var)
        self._sync_option_menu(self.silence_menu, "silence_options", self.silence_key_var,
                               self.silence_display_var)
        self._sync_option_menu(self.model_menu, "model_options", self.model_key_var,
                               self.model_display_var)

        self.sub_opt_lbl_w.configure(text=self.t("sub_opt_label"))
        self.out_opt_lbl_w.configure(text=self.t("out_opt_label"))
        self.speaker_row_lbl_w.configure(text=self.t("speaker_row_label"))
        self.diarize_checkbox.configure(text=self.t("diarize_label"))
        self.speakers_lbl_w.configure(text=self.t("speakers_label"))
        self.speaker_labels_checkbox.configure(text=self.t("speaker_labels_label"))
        self.line_chars_lbl_w.configure(text=self.t("line_chars_label"))
        self.txt_checkbox.configure(text=self.t("txt_label"))
        self.md_checkbox.configure(text=self.t("md_label"))
        self.markers_lbl_w.configure(text=self.t("markers_row_label"))
        self.markers_checkbox.configure(text=self.t("markers_label"))
        self.hotwords_lbl_w.configure(text=self.t("hotwords_label"))
        self.hotwords_entry.configure(placeholder_text=self.t("hotwords_hint"))
        self.speakers_menu.configure(values=[self.t("speakers_auto") if v == "auto" else v
                                             for v in SPEAKER_CHOICES])
        self._sync_speakers_display()

        self.outdir_lbl_w.configure(text=self.t("outdir_label"))
        self.outdir_val_lbl.configure(
            text=self.output_dir if self.output_dir else self.t("outdir_default"))
        self.outdir_btn.configure(text=self.t("outdir_change"))
        self.run_btn.configure(text=self.t("run_btn"))
        self.stop_btn.configure(text=self.t("stop_btn"))
        self.wave_btn.configure(text=self.t("wave_btn"))
        self.text_btn.configure(text=self.t("text_btn"))
        self.log_hdr_lbl.configure(text=self.t("log_header"))
        self.clear_btn.configure(text=self.t("log_clear"))

        self._update_margin_label()
        self._update_threshold_label()

    def _sync_option_menu(self, menu, i18n_key, key_var, display_var):
        opts = self.t(i18n_key)
        menu.configure(values=list(opts.values()))
        cur = key_var.get()
        if cur in opts:
            display_var.set(opts[cur])

    def _sync_speakers_display(self):
        v = self.speakers_var.get()
        self.speakers_menu.set(self.t("speakers_auto") if v == "auto" else v)

    def _on_speakers_select(self, display_val):
        # 内部値は "auto" または人数。表示（「自動」）と混ぜない。
        self.speakers_var.set("auto" if display_val == self.t("speakers_auto") else display_val)

    def _refresh_drop_label(self):
        n = len(self.input_files)
        if n == 0:
            self.drop_label.configure(text=self.t("drop_hint"), text_color=TEXT_MUTED)
        elif n == 1:
            self.drop_label.configure(text=f"🎬  {Path(self.input_files[0]).name}", text_color="white")
        else:
            self.drop_label.configure(
                text=self.t("files_selected", Path(self.input_files[0]).name, n - 1), text_color="white")

    def _refresh_states(self, *_):
        """設定の組み合わせに応じて、使えない項目を無効化する。"""
        srt_on = self.srt_var.get() and WHISPER_AVAILABLE
        normal, disabled = "normal", "disabled"

        def st(widget, on):
            widget.configure(state=normal if on else disabled)

        st(self.model_menu, srt_on)
        st(self.gpu_checkbox, srt_on and cuda_available())
        st(self.snap_srt_checkbox, srt_on)
        st(self.diarize_checkbox, srt_on and sherpa_available())
        diar_on = srt_on and self.diarize_var.get() and sherpa_available()
        st(self.speakers_menu, diar_on)
        st(self.speaker_labels_checkbox, diar_on)
        st(self.line_chars_entry, srt_on)
        st(self.txt_checkbox, srt_on)
        st(self.md_checkbox, srt_on)
        st(self.hotwords_entry, srt_on)

        media = EXPORT_MODES.get(self.export_var.get(), ("", ""))[0] == "media"
        st(self.markers_checkbox, not media)
        vad = self.cut_mode_key_var.get() == "vad"
        st(self.slider_threshold, not vad)
        st(self.threshold_entry, not vad)
        st(self.speed_entry, self.silence_key_var.get() == "speed")

    def _collect_settings(self) -> dict:
        export_disp = self.export_var.get()
        export_val = "resolve"
        for name, (key, ext) in EXPORT_MODES.items():
            if name == export_disp:
                export_val = key
                break
        return {
            "margin": self.margin_var.get(),
            "threshold": self.threshold_var.get(),
            "export": export_val,
            "srt": self.srt_var.get(),
            "model": self.model_key_var.get(),
            "output_dir": self.output_dir,
            "gpu": self.gpu_var.get(),
            "snap_srt": self.snap_srt_var.get(),
            "cut_mode": self.cut_mode_key_var.get(),
            "silence": self.silence_key_var.get(),
            "speed": self.speed_var.get(),
            "hotwords": self.hotwords_var.get(),
            "diarize": self.diarize_var.get(),
            "speakers": self.speakers_var.get(),
            "speaker_labels": self.speaker_labels_var.get(),
            "markers": self.markers_var.get(),
            "line_chars": self._line_chars(),
            "txt": self.txt_var.get(),
            "md": self.md_var.get(),
        }

    def _apply_settings(self, s: dict):
        if "margin" in s:
            self.margin_var.set(s["margin"])
        if "threshold" in s:
            self.threshold_var.set(s["threshold"])
        if "export" in s:
            export_val = s["export"]
            for name, (key, ext) in EXPORT_MODES.items():
                if key == export_val:
                    self.export_var.set(name)
                    break
        if "srt" in s:
            self.srt_var.set(s["srt"])
        if "model" in s:
            opts_dict = self.t("model_options")
            if s["model"] in opts_dict:      # 古いプリセットの未対応モデル名は無視（既定のまま）
                self.model_key_var.set(s["model"])
                self.model_display_var.set(opts_dict[s["model"]])
        if "output_dir" in s:
            self.output_dir = s["output_dir"]
            if self.output_dir:
                self.outdir_val_lbl.configure(text=self.output_dir, text_color="white")
            else:
                self.outdir_val_lbl.configure(text=self.t("outdir_default"), text_color=TEXT_MUTED)
        if "gpu" in s:
            if cuda_available():
                self.gpu_var.set(s["gpu"])
            else:
                self.gpu_var.set(False)
        if "snap_srt" in s:
            self.snap_srt_var.set(s["snap_srt"])
        if s.get("cut_mode") in self.t("cut_mode_options"):
            self.cut_mode_key_var.set(s["cut_mode"])
            self.cut_mode_display_var.set(self.t("cut_mode_options")[s["cut_mode"]])
        if s.get("silence") in self.t("silence_options"):
            self.silence_key_var.set(s["silence"])
            self.silence_display_var.set(self.t("silence_options")[s["silence"]])
        if "speed" in s:
            self.speed_var.set(s["speed"])
        if "hotwords" in s:
            self.hotwords_var.set(s["hotwords"])
        if "diarize" in s:
            self.diarize_var.set(bool(s["diarize"]) and sherpa_available())
        if s.get("speakers") in SPEAKER_CHOICES:
            self.speakers_var.set(s["speakers"])
            self._sync_speakers_display()
        if "speaker_labels" in s:
            self.speaker_labels_var.set(s["speaker_labels"])
        if "markers" in s:
            self.markers_var.set(s["markers"])
        if "line_chars" in s:
            self.line_chars_var.set(int(s["line_chars"]))
        if "txt" in s:
            self.txt_var.set(s["txt"])
        if "md" in s:
            self.md_var.set(s["md"])

        self._update_margin_label()
        self._update_threshold_label()
        self._refresh_states()

    def _update_preset_menu(self):
        store = load_store()
        presets = store.get("presets", {})
        none_text = self.t("preset_none")
        values = [none_text] + list(presets.keys())
        self.preset_menu.configure(values=values)

        current = self.preset_menu_var.get()
        if current not in presets:
            self.preset_menu_var.set(none_text)

    def _on_preset_select(self, choice):
        none_text = self.t("preset_none")
        if choice == none_text:
            return
        store = load_store()
        presets = store.get("presets", {})
        if choice in presets:
            self._apply_settings(presets[choice])

    def _on_preset_save(self):
        dialog = ctk.CTkInputDialog(
            text=self.t("preset_name_prompt"),
            title=self.t("preset_save")
        )
        name = dialog.get_input()
        if not name:
            return
        name = name.strip()
        if not name:
            return

        settings = self._collect_settings()
        store = load_store()
        upsert_preset(store, name, settings)
        save_store(store)

        self._log(self.t("log_preset_saved", name), "success")
        self.preset_menu_var.set(name)
        self._update_preset_menu()

    def _on_preset_delete(self):
        choice = self.preset_menu_var.get()
        none_text = self.t("preset_none")
        if choice == none_text:
            return

        store = load_store()
        presets = store.get("presets", {})
        if choice in presets:
            delete_preset(store, choice)
            save_store(store)
            self._log(self.t("log_preset_deleted", choice), "info")

        self.preset_menu_var.set(none_text)
        self._update_preset_menu()

    def _on_close(self):
        try:
            store = load_store()
            set_last_used(store, self._collect_settings())
            save_store(store)
        except Exception as e:
            print(f"Error saving presets on close: {e}", file=sys.stderr)
        self.destroy()

    def _reverse_lookup(self, i18n_key, display_val, key_var):
        for k, v in self.t(i18n_key).items():
            if v == display_val:
                key_var.set(k)
                break

    def _on_model_select(self, display_val):
        self._reverse_lookup("model_options", display_val, self.model_key_var)

    def _on_cut_mode_select(self, display_val):
        self._reverse_lookup("cut_mode_options", display_val, self.cut_mode_key_var)
        self._refresh_states()

    def _on_silence_select(self, display_val):
        self._reverse_lookup("silence_options", display_val, self.silence_key_var)
        self._refresh_states()

    def _on_srt_toggle(self):
        self._refresh_states()

    def _on_export_change(self, choice):
        self._refresh_states()

    def _on_drop(self, event):
        raw = event.data.strip()
        found = re.findall(r'\{([^}]+)\}|(\S+)', raw)
        self._set_files([f[0] or f[1] for f in found])

    def _browse_file(self):
        exts = " ".join(f"*{e}" for e in sorted(MEDIA_EXTS))
        paths = filedialog.askopenfilenames(
            title=self.t("file_dialog"),
            filetypes=[("Media files", exts), ("All files", "*.*")])
        if paths:
            self._set_files(list(paths))

    def _set_files(self, paths):
        """ファイル/フォルダのリストを受け取り、対応する拡張子のファイルだけ入力に設定する。"""
        files: list[str] = []
        for p in paths:
            path = Path(p)
            if path.is_dir():
                files += [str(f) for f in sorted(path.iterdir())
                          if f.is_file() and f.suffix.lower() in MEDIA_EXTS]
            elif path.suffix.lower() in MEDIA_EXTS or path.exists():
                files.append(str(path))
        if not files:
            return
        self.input_files = files
        self._refresh_drop_label()
        if not self.output_dir:
            self.outdir_val_lbl.configure(text=self.t("outdir_default"), text_color=TEXT_MUTED)
        if len(files) == 1:
            self._log(self.t("log_file", files[0]), "info")
        else:
            self._log(self.t("log_files", len(files)), "info")

    def _browse_outdir(self):
        path = filedialog.askdirectory(title=self.t("dir_dialog"))
        if path:
            self.output_dir = path
            self.outdir_val_lbl.configure(text=path, text_color="white")
            self._log(self.t("log_outdir", path), "info")

    def _on_slider_margin(self, _): self._update_margin_label()
    def _on_entry_margin_commit(self, _=None):
        try:
            self.margin_var.set(max(0.0, min(2.0, float(self.margin_entry.get()))))
        except ValueError: pass
        self._update_margin_label()
    def _update_margin_label(self):
        self.margin_val_lbl.configure(text=f"{self.margin_var.get():.2f} {self.t('margin_unit')}")

    def _on_slider_threshold(self, _): self._update_threshold_label()
    def _on_entry_threshold_commit(self, _=None):
        try:
            self.threshold_var.set(max(0.0, min(100.0, float(self.threshold_entry.get()))))
        except ValueError: pass
        self._update_threshold_label()
    def _update_threshold_label(self):
        self.threshold_val_lbl.configure(text=f"{self.threshold_var.get():.1f} {self.t('threshold_unit')}")

    def _on_entry_speed_commit(self, _=None):
        try:
            self.speed_var.set(max(1.1, min(100.0, float(self.speed_entry.get()))))
        except (ValueError, tk.TclError):
            self.speed_var.set(8.0)

    def _line_chars(self) -> int:
        try:
            return max(0, min(60, int(self.line_chars_var.get())))
        except (ValueError, tk.TclError):
            return 20

    def snapshot_cut_settings(self) -> dict:
        """波形プレビュー用に、現在のカット設定を数値で取り出す。"""
        try:
            speed = float(self.speed_var.get())
        except (ValueError, tk.TclError):
            speed = 8.0
        return {
            "margin": self.margin_var.get(),
            "threshold": self.threshold_var.get(),
            "cut_mode": self.cut_mode_key_var.get(),
            "silent_speed": speed if self.silence_key_var.get() == "speed" else None,
        }

    def _clear_log(self):
        self.console.configure(state="normal")
        self.console.delete("1.0", "end")
        self.console.configure(state="disabled")

    def _log(self, msg, tag=""):
        def _ins():
            self.console.configure(state="normal")
            if tag: self.console._textbox.insert("end", msg + "\n", tag)
            else: self.console.insert("end", msg + "\n")
            self.console.configure(state="disabled")
            self.console.see("end")
        self.after(0, _ins)

    # ── Previews ───────────────────────────────────────────────────────────────
    def _open_waveform(self):
        if not self.input_files:
            messagebox.showwarning(self.t("warn_title"), self.t("wave_no_file"))
            return
        WaveformWindow(self, self.input_files[0])

    def _open_text_preview(self):
        TextPreviewWindow(self)

    # ── Processing ─────────────────────────────────────────────────────────────
    def _build_params(self) -> PipelineParams:
        label = self.export_var.get()
        ae_key, _ext = EXPORT_MODES[label]
        speakers = self.speakers_var.get()
        try:
            speed = float(self.speed_var.get())
        except (ValueError, tk.TclError):
            speed = 8.0
        return PipelineParams(
            margin=self.margin_var.get(),
            threshold=self.threshold_var.get(),
            export_key=ae_key,
            do_srt=self.srt_var.get(),
            model_size=self.model_key_var.get(),
            use_gpu=self.gpu_var.get(),
            snap_srt=self.snap_srt_var.get(),
            cut_mode=self.cut_mode_key_var.get(),
            silent_speed=speed if self.silence_key_var.get() == "speed" else None,
            hotwords=self.hotwords_var.get(),
            diarize=self.diarize_var.get() and sherpa_available(),
            num_speakers=-1 if speakers == "auto" else int(speakers),
            speaker_labels=self.speaker_labels_var.get(),
            markers=self.markers_var.get() and ae_key != "media",
            line_chars=self._line_chars(),
            txt=self.txt_var.get(),
            md=self.md_var.get(),
            ui_lang=self.lang,
        )

    def _start_process(self):
        if not self.input_files:
            messagebox.showwarning(self.t("warn_title"), self.t("warn_no_file"))
            return
        missing = [f for f in self.input_files if not Path(f).exists()]
        if missing:
            messagebox.showerror(self.t("err_title"), self.t("err_not_found"))
            return
        if self.running:
            return

        params = self._build_params()
        label = self.export_var.get()
        files = [Path(f).resolve() for f in self.input_files]

        sep = "─" * 50
        self._log(sep, "muted")
        self._log(self.t("log_start"), "info")
        self._log(f"{self.t('log_margin')}: {params.margin:.2f} {self.t('margin_unit')}", "muted")
        if params.cut_mode == "vad":
            self._log(f"{self.t('cut_mode_label')}: {self.t('cut_mode_options')['vad']}", "muted")
        else:
            self._log(f"{self.t('log_threshold')}: {params.threshold:.1f} {self.t('threshold_unit')}", "muted")
        self._log(f"{self.t('log_format')}: {label}", "muted")
        if params.do_srt:
            self._log(self.t("log_srt_enabled", params.model_size), "muted")
        self._log(sep, "muted")

        self.running = True
        self.stop_requested = False
        self.run_btn.configure(state="disabled")
        self.stop_btn.configure(state="normal")
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
            # 出力先を共有していて同名の入力が複数あるときだけ、連番で出力名を分ける
            stem = f"{inp.stem}_{idx}" if (shared_out and stems.count(inp.stem) > 1) else None
            if total > 1:
                self._log(self.t("log_batch_item", idx, total, inp.name), "info")
            self._log(f"{self.t('log_input')}: {inp.name}", "muted")
            result = run_pipeline(
                ae_path, inp, out_dir, dataclasses.replace(params, out_stem=stem),
                on_log=self._log,
                should_stop=lambda: self.stop_requested,
                tr=self.t,
                model_cache=model_cache,
            )
            if result.ok and not result.stopped:
                finished += 1
                last_out, last_result = out_dir, result
        model_cache.clear()
        self.running = False
        if last_result is not None:
            self.last_cues = list(last_result.cues)
            self.last_title = Path(last_result.timeline_path).stem if last_result.timeline_path else ""
        if total > 1 and finished:
            self._log(self.t("log_batch_done", finished), "success")
        if finished and not self.stop_requested:
            self.after(0, lambda: self._popup_done(out_dir=last_out))
        self.after(0, self._reset_ui)

    def _popup_done(self, out_dir):
        def _show():
            if messagebox.askyesno(self.t("done_title"), self.t("done_msg")):
                os.startfile(str(out_dir))
        self.after(0, _show)

    def _stop_process(self):
        self.stop_requested = True
        self._log(self.t("log_stop_requested"), "warn")

    def _reset_ui(self):
        self.running = False
        self.run_btn.configure(state="normal")
        self.stop_btn.configure(state="disabled")
        self.progress.stop()
        self.progress.set(0)

def main():
    app = SnipSyncApp()
    if not WHISPER_AVAILABLE:
        app._log(app.t("log_whisper_unavailable"), "warn")
    app._log(app.t("log_welcome"), "muted")
    app.mainloop()

if __name__ == "__main__":
    main()
