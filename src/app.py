"""
SnipSync - Silent Video Cutter & Subtitle Generator
Cuts silent portions from video, exports XML for NLEs, and generates .srt subtitles.
"""
import os, sys, re, subprocess, threading, time, traceback
from pathlib import Path
import customtkinter as ctk
from tkinter import filedialog, messagebox

try:
    from tkinterdnd2 import DND_FILES, TkinterDnD
    DND_AVAILABLE = True
except ImportError:
    DND_AVAILABLE = False

try:
    from faster_whisper import WhisperModel
    WHISPER_AVAILABLE = True
except ImportError:
    WHISPER_AVAILABLE = False

APP_VERSION = "1.0.0"

# ── PyInstaller resource path ──────────────────────────────────────────────────
def resource_path(rel):
    try:
        base = Path(sys._MEIPASS)
    except AttributeError:
        base = Path(__file__).parent
    return base / rel

def get_auto_editor_path():
    bundled = resource_path("auto-editor.exe")
    if bundled.exists():
        return bundled
    try:
        from auto_editor.__main__ import download_binary
        return download_binary()
    except ImportError:
        return "auto-editor" # fallback to PATH if not bundled properly

# ── i18n Dictionaries ──────────────────────────────────────────────────────────
I18N = {
    "ja": {
        "title":          f"SnipSync  v{APP_VERSION}",
        "subtitle":       "無音自動カット ＆ 字幕生成",
        "lang_label":     "言語",
        "drop_hint":      "🎬  ここに動画ファイルをドラッグ＆ドロップ\n（または クリックして選択）",
        "margin_label":   "無音マージン（秒）",
        "threshold_label":"音量閾値（%）",
        "export_label":   "出力形式",
        "srt_label":      "字幕自動生成",
        "srt_check":      ".srt ファイルも同時に生成する",
        "model_label":    "AIモデル精度",
        "outdir_label":   "出力先フォルダ",
        "outdir_default": "（入力ファイルと同じフォルダ）",
        "outdir_change":  "変更",
        "run_btn":        "▶  処理を開始する",
        "stop_btn":       "⬛  停止",
        "log_header":     "ログ",
        "log_clear":      "クリア",
        "warn_no_file":   "動画ファイルを選択してください。",
        "warn_title":     "ファイル未選択",
        "err_not_found":  "選択されたファイルが見つかりません。",
        "err_title":      "エラー",
        "log_welcome":    "SnipSync へようこそ！動画ファイルを選択してください。",
        "log_start":      "▶ 処理開始",
        "log_input":      "  入力",
        "log_margin":     "  マージン",
        "log_threshold":  "  音量閾値",
        "log_format":     "  出力形式",
        "log_output":     "  出力先",
        "log_cmd":        "  コマンド",
        "log_done_ae":    "✅ カット処理完了！ 出力ファイル:",
        "log_srt_temp_start": "⏳ カット済み音声の一時ファイルを作成中...",
        "log_srt_analyze": "⏳ 一時ファイルから音声を解析中... (モデル: {})",
        "log_srt_start":  "⏳ 音声認識を開始します (モデル: {}) ... ※初回はダウンロードが発生します",
        "log_srt_done":   "✅ 字幕生成が完了しました！ 出力ファイル:",
        "log_error":      "❌ エラーが発生しました（終了コード: {}）\n詳細:\n{}",
        "log_wav_missing":"❌ WAVファイルの生成に失敗しました。処理を中断します。",
        "log_ae_missing": "❌ auto-editor が見つかりません: {}",
        "log_unexpected": "❌ 予期しないエラー:\n{}",
        "log_stopped":    "⬛ 処理を停止しました。",
        "done_title":     "処理完了",
        "done_msg":       "処理がすべて完了しました！\n\n出力フォルダを開きますか？",
        "file_dialog":    "動画ファイルを選択",
        "dir_dialog":     "出力先フォルダを選択",
        "log_file":       "ファイル選択: {}",
        "log_outdir":     "出力先変更: {}",
        "margin_unit":    "秒",
        "threshold_unit": "%",
        "model_options":  {
            "tiny":   "tiny (最速/低精度)",
            "base":   "base (高速)",
            "small":  "small (標準)",
            "medium": "medium (高精度/遅い)"
        }
    },
    "en": {
        "title":          f"SnipSync  v{APP_VERSION}",
        "subtitle":       "Silent Auto-Cutter & Subtitles",
        "lang_label":     "Language",
        "drop_hint":      "🎬  Drag & Drop a video file here\n(or click to browse)",
        "margin_label":   "Silence Margin (sec)",
        "threshold_label":"Volume Threshold (%)",
        "export_label":   "Export Format",
        "srt_label":      "Subtitles",
        "srt_check":      "Generate .srt file simultaneously",
        "model_label":    "AI Model Size",
        "outdir_label":   "Output Folder",
        "outdir_default": "(Same folder as input file)",
        "outdir_change":  "Change",
        "run_btn":        "▶  Start Processing",
        "stop_btn":       "⬛  Stop",
        "log_header":     "Log",
        "log_clear":      "Clear",
        "warn_no_file":   "Please select a video file.",
        "warn_title":     "No File Selected",
        "err_not_found":  "The selected file was not found.",
        "err_title":      "Error",
        "log_welcome":    "Welcome to SnipSync! Please select a video file.",
        "log_start":      "▶ Processing started",
        "log_input":      "  Input",
        "log_margin":     "  Margin",
        "log_threshold":  "  Threshold",
        "log_format":     "  Export format",
        "log_output":     "  Output",
        "log_cmd":        "  Command",
        "log_done_ae":    "✅ Cutting done! Output file:",
        "log_srt_temp_start": "⏳ Creating temporary cut audio file...",
        "log_srt_analyze": "⏳ Analyzing temporary audio file... (Model: {})",
        "log_srt_start":  "⏳ Starting transcription (Model: {}) ... *May download on first run",
        "log_srt_done":   "✅ Subtitles generated! Output file:",
        "log_error":      "❌ Error occurred (exit code: {})\nDetails:\n{}",
        "log_wav_missing":"❌ Failed to generate the temporary WAV file. Aborting.",
        "log_ae_missing": "❌ auto-editor not found: {}",
        "log_unexpected": "❌ Unexpected error:\n{}",
        "log_stopped":    "⬛ Processing stopped.",
        "done_title":     "Processing Complete",
        "done_msg":       "All processing is complete!\n\nOpen output folder?",
        "file_dialog":    "Select Video File",
        "dir_dialog":     "Select Output Folder",
        "log_file":       "File selected: {}",
        "log_outdir":     "Output folder changed: {}",
        "margin_unit":    "sec",
        "threshold_unit": "%",
        "model_options":  {
            "tiny":   "tiny (Fastest/Low Acc)",
            "base":   "base (Fast)",
            "small":  "small (Standard)",
            "medium": "medium (Accurate/Slow)"
        }
    },
}

EXPORT_MODES = {
    "DaVinci Resolve (.fcpxml)":    ("resolve",       ".fcpxml"),
    "Premiere Pro (.xml)":          ("premiere",      ".xml"),
    "Final Cut Pro (.fcpxml)":      ("final-cut-pro", ".fcpxml"),
}

# ── Colors ─────────────────────────────────────────────────────────────────────
ACCENT       = "#6C63FF"
ACCENT_HOVER = "#5a52e0"
SUCCESS      = "#2ECC71"
ERROR_COL    = "#E74C3C"
WARN_COL     = "#F39C12"
BG_DARK      = "#1a1a2e"
BG_CARD      = "#16213e"
BG_CONSOLE   = "#0d1117"
TEXT_MUTED   = "#8892a4"

# ── SRT Formatting Helper ──────────────────────────────────────────────────────
def format_timestamp(seconds: float) -> str:
    total_ms = int(round(seconds * 1000))
    hrs = total_ms // 3600000
    mins = (total_ms % 3600000) // 60000
    secs = (total_ms % 60000) // 1000
    ms = total_ms % 1000
    return f"{hrs:02d}:{mins:02d}:{secs:02d},{ms:03d}"

# ── Base class ─────────────────────────────────────────────────────────────────
if DND_AVAILABLE:
    class _Base(ctk.CTk, TkinterDnD.DnDWrapper):
        def __init__(self, *a, **kw):
            super().__init__(*a, **kw)
            self.TkdndVersion = TkinterDnD._require(self)
else:
    class _Base(ctk.CTk):
        pass

# ── Main App ───────────────────────────────────────────────────────────────────
class SnipSyncApp(_Base):
    def __init__(self):
        super().__init__()
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")

        self.lang = "ja"
        self.input_file  = ""
        self.output_dir  = ""
        
        self.margin_var  = ctk.DoubleVar(value=0.2)
        self.threshold_var = ctk.DoubleVar(value=4.0)
        self.export_var  = ctk.StringVar(value=list(EXPORT_MODES.keys())[0])
        self.srt_var     = ctk.BooleanVar(value=True)
        # Store the internal model key (tiny, base, small, medium)
        self.model_key_var = ctk.StringVar(value="small")
        # Store the translated display string for OptionMenu
        self.model_display_var = ctk.StringVar()
        
        self.lang_var    = ctk.StringVar(value="日本語")
        
        self.process     = None
        self.running     = False
        self.stop_requested = False

        self.configure(fg_color=BG_DARK)
        self.minsize(740, 720)
        self.geometry("860x780")
        
        self._build_ui()
        self._update_margin_label()
        self._update_threshold_label()
        self._apply_lang()

    def t(self, key, *args):
        s = I18N[self.lang].get(key, key)
        return s.format(*args) if args else s

    def _build_ui(self):
        # Header
        hdr = ctk.CTkFrame(self, fg_color=BG_CARD, corner_radius=0, height=64)
        hdr.pack(fill="x", side="top")
        hdr.pack_propagate(False)

        self.title_lbl = ctk.CTkLabel(
            hdr, text="✂  SnipSync",
            font=ctk.CTkFont(family="Segoe UI", size=22, weight="bold"),
            text_color=ACCENT)
        self.title_lbl.pack(side="left", padx=24, pady=16)

        self.subtitle_lbl = ctk.CTkLabel(
            hdr, text="", font=ctk.CTkFont(family="Segoe UI", size=12), text_color=TEXT_MUTED)
        self.subtitle_lbl.pack(side="left", pady=16)

        # Language selector
        lang_frame = ctk.CTkFrame(hdr, fg_color="transparent")
        lang_frame.pack(side="right", padx=20)
        self.lang_lbl_hdr = ctk.CTkLabel(
            lang_frame, text="", font=ctk.CTkFont(family="Segoe UI", size=11), text_color=TEXT_MUTED)
        self.lang_lbl_hdr.pack(side="left", padx=(0, 6))
        self.lang_menu = ctk.CTkOptionMenu(
            lang_frame, values=["日本語", "English"], variable=self.lang_var, width=110,
            font=ctk.CTkFont(family="Segoe UI", size=12), fg_color=BG_DARK, button_color=ACCENT,
            button_hover_color=ACCENT_HOVER, dropdown_fg_color=BG_DARK, command=self._on_lang_change)
        self.lang_menu.pack(side="left")

        main = ctk.CTkFrame(self, fg_color="transparent")
        main.pack(fill="both", expand=True, padx=20, pady=16)
        main.columnconfigure(0, weight=1)
        main.rowconfigure(5, weight=1)

        self._build_drop_zone(main)
        self._build_settings(main)
        self._build_actions(main)
        self._build_console(main)

    def _build_drop_zone(self, parent):
        zone = ctk.CTkFrame(parent, fg_color=BG_CARD, corner_radius=16)
        zone.grid(row=0, column=0, sticky="ew", pady=(0, 12))

        self.drop_label = ctk.CTkLabel(
            zone, text="", font=ctk.CTkFont(family="Segoe UI", size=13),
            text_color=TEXT_MUTED, height=90, cursor="hand2")
        self.drop_label.pack(fill="x", padx=20, pady=16)
        self.drop_label.bind("<Button-1>", lambda e: self._browse_file())

        if DND_AVAILABLE:
            self.drop_label.drop_target_register(DND_FILES)
            self.drop_label.dnd_bind("<<Drop>>", self._on_drop)

    def _build_settings(self, parent):
        card = ctk.CTkFrame(parent, fg_color=BG_CARD, corner_radius=16)
        card.grid(row=1, column=0, sticky="ew", pady=(0, 12))
        card.columnconfigure((1, 3), weight=1)
        pad = {"padx": 20, "pady": 8}

        # 1. Margin
        self.margin_lbl_w = ctk.CTkLabel(
            card, text="", font=ctk.CTkFont(family="Segoe UI", size=12, weight="bold"), text_color="white")
        self.margin_lbl_w.grid(row=0, column=0, sticky="w", **pad)

        sf1 = ctk.CTkFrame(card, fg_color="transparent")
        sf1.grid(row=0, column=1, sticky="ew", padx=(0, 10), pady=8)
        sf1.columnconfigure(0, weight=1)
        self.slider_margin = ctk.CTkSlider(
            sf1, from_=0.0, to=2.0, number_of_steps=40, variable=self.margin_var, command=self._on_slider_margin,
            button_color=ACCENT, button_hover_color=ACCENT_HOVER, progress_color=ACCENT)
        self.slider_margin.grid(row=0, column=0, sticky="ew")

        self.margin_val_lbl = ctk.CTkLabel(
            card, text="", font=ctk.CTkFont(family="Consolas", size=13, weight="bold"), text_color=ACCENT, width=60)
        self.margin_val_lbl.grid(row=0, column=2, padx=(0, 6), pady=8)

        self.margin_entry = ctk.CTkEntry(
            card, width=70, textvariable=self.margin_var, font=ctk.CTkFont(family="Consolas", size=12), justify="center")
        self.margin_entry.grid(row=0, column=3, sticky="w", padx=(0, 20), pady=8)
        self.margin_entry.bind("<Return>", self._on_entry_margin_commit)
        self.margin_entry.bind("<FocusOut>", self._on_entry_margin_commit)

        # 2. Threshold
        self.threshold_lbl_w = ctk.CTkLabel(
            card, text="", font=ctk.CTkFont(family="Segoe UI", size=12, weight="bold"), text_color="white")
        self.threshold_lbl_w.grid(row=1, column=0, sticky="w", **pad)

        sf2 = ctk.CTkFrame(card, fg_color="transparent")
        sf2.grid(row=1, column=1, sticky="ew", padx=(0, 10), pady=8)
        sf2.columnconfigure(0, weight=1)
        self.slider_threshold = ctk.CTkSlider(
            sf2, from_=0.0, to=50.0, number_of_steps=100, variable=self.threshold_var, command=self._on_slider_threshold,
            button_color=ACCENT, button_hover_color=ACCENT_HOVER, progress_color=ACCENT)
        self.slider_threshold.grid(row=0, column=0, sticky="ew")

        self.threshold_val_lbl = ctk.CTkLabel(
            card, text="", font=ctk.CTkFont(family="Consolas", size=13, weight="bold"), text_color=ACCENT, width=60)
        self.threshold_val_lbl.grid(row=1, column=2, padx=(0, 6), pady=8)

        self.threshold_entry = ctk.CTkEntry(
            card, width=70, textvariable=self.threshold_var, font=ctk.CTkFont(family="Consolas", size=12), justify="center")
        self.threshold_entry.grid(row=1, column=3, sticky="w", padx=(0, 20), pady=8)
        self.threshold_entry.bind("<Return>", self._on_entry_threshold_commit)
        self.threshold_entry.bind("<FocusOut>", self._on_entry_threshold_commit)

        # 3. Export format
        self.export_lbl_w = ctk.CTkLabel(
            card, text="", font=ctk.CTkFont(family="Segoe UI", size=12, weight="bold"), text_color="white")
        self.export_lbl_w.grid(row=2, column=0, sticky="w", **pad)

        self.export_menu = ctk.CTkOptionMenu(
            card, values=list(EXPORT_MODES.keys()), variable=self.export_var,
            font=ctk.CTkFont(family="Segoe UI", size=12), fg_color=BG_DARK, button_color=ACCENT,
            button_hover_color=ACCENT_HOVER, dropdown_fg_color=BG_DARK, width=240)
        self.export_menu.grid(row=2, column=1, columnspan=3, sticky="w", padx=(0, 20), pady=8)

        # 4. SRT Generation settings
        self.srt_lbl_w = ctk.CTkLabel(
            card, text="", font=ctk.CTkFont(family="Segoe UI", size=12, weight="bold"), text_color="white")
        self.srt_lbl_w.grid(row=3, column=0, sticky="w", **pad)

        srt_frame = ctk.CTkFrame(card, fg_color="transparent")
        srt_frame.grid(row=3, column=1, columnspan=3, sticky="w", padx=(0, 20), pady=8)
        
        self.srt_checkbox = ctk.CTkCheckBox(
            srt_frame, text="", variable=self.srt_var, font=ctk.CTkFont(family="Segoe UI", size=12),
            fg_color=ACCENT, hover_color=ACCENT_HOVER, command=self._on_srt_toggle)
        self.srt_checkbox.pack(side="left")

        self.model_lbl_w = ctk.CTkLabel(
            srt_frame, text="", font=ctk.CTkFont(family="Segoe UI", size=11), text_color=TEXT_MUTED)
        self.model_lbl_w.pack(side="left", padx=(20, 8))

        self.model_menu = ctk.CTkOptionMenu(
            srt_frame, values=["small"], variable=self.model_display_var,
            font=ctk.CTkFont(family="Segoe UI", size=11), fg_color=BG_DARK, button_color=ACCENT,
            button_hover_color=ACCENT_HOVER, dropdown_fg_color=BG_DARK, width=160,
            command=self._on_model_select)
        self.model_menu.pack(side="left")
        if not WHISPER_AVAILABLE:
            self.srt_var.set(False)
            self.srt_checkbox.configure(state="disabled")
            self.model_menu.configure(state="disabled")

        # 5. Output dir
        self.outdir_lbl_w = ctk.CTkLabel(
            card, text="", font=ctk.CTkFont(family="Segoe UI", size=12, weight="bold"), text_color="white")
        self.outdir_lbl_w.grid(row=4, column=0, sticky="w", **pad)

        of = ctk.CTkFrame(card, fg_color="transparent")
        of.grid(row=4, column=1, columnspan=3, sticky="ew", padx=(0, 20), pady=8)
        of.columnconfigure(0, weight=1)

        self.outdir_val_lbl = ctk.CTkLabel(
            of, text="", anchor="w", font=ctk.CTkFont(family="Segoe UI", size=11), text_color=TEXT_MUTED)
        self.outdir_val_lbl.grid(row=0, column=0, sticky="ew")

        self.outdir_btn = ctk.CTkButton(
            of, text="", width=60, font=ctk.CTkFont(family="Segoe UI", size=11),
            fg_color=BG_DARK, hover_color=ACCENT, command=self._browse_outdir)
        self.outdir_btn.grid(row=0, column=1, padx=(8, 0))

    def _build_actions(self, parent):
        act = ctk.CTkFrame(parent, fg_color="transparent")
        act.grid(row=3, column=0, sticky="ew", pady=(0, 12))
        act.columnconfigure(0, weight=1)

        self.run_btn = ctk.CTkButton(
            act, text="", font=ctk.CTkFont(family="Segoe UI", size=14, weight="bold"),
            height=50, corner_radius=12, fg_color=ACCENT, hover_color=ACCENT_HOVER,
            command=self._start_process)
        self.run_btn.grid(row=0, column=0, sticky="ew")

        self.stop_btn = ctk.CTkButton(
            act, text="", font=ctk.CTkFont(family="Segoe UI", size=13),
            height=50, corner_radius=12, fg_color="#3a3a4a", hover_color=ERROR_COL,
            command=self._stop_process, state="disabled")
        self.stop_btn.grid(row=0, column=1, padx=(10, 0), sticky="e")

        self.progress = ctk.CTkProgressBar(act, mode="indeterminate", progress_color=ACCENT, height=6, corner_radius=3)
        self.progress.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(8, 0))
        self.progress.set(0)

    def _build_console(self, parent):
        hdr_f = ctk.CTkFrame(parent, fg_color="transparent")
        hdr_f.grid(row=4, column=0, sticky="ew")

        self.log_hdr_lbl = ctk.CTkLabel(
            hdr_f, text="", font=ctk.CTkFont(family="Segoe UI", size=11, weight="bold"), text_color=TEXT_MUTED)
        self.log_hdr_lbl.pack(side="left")

        self.clear_btn = ctk.CTkButton(
            hdr_f, text="", width=52, height=22, font=ctk.CTkFont(family="Segoe UI", size=10),
            fg_color="transparent", border_width=1, text_color=TEXT_MUTED, hover_color=BG_CARD,
            command=self._clear_log)
        self.clear_btn.pack(side="right")

        card = ctk.CTkFrame(parent, fg_color=BG_CONSOLE, corner_radius=12)
        card.grid(row=5, column=0, sticky="nsew", pady=(4, 0))

        self.console = ctk.CTkTextbox(
            card, font=ctk.CTkFont(family="Consolas", size=11),
            fg_color=BG_CONSOLE, text_color="#c9d1d9", wrap="word", state="disabled", scrollbar_button_color=ACCENT)
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
        self.drop_label.configure(
            text=self.t("drop_hint") if not self.input_file else self.drop_label.cget("text"))
        self.margin_lbl_w.configure(text=self.t("margin_label"))
        self.threshold_lbl_w.configure(text=self.t("threshold_label"))
        self.export_lbl_w.configure(text=self.t("export_label"))
        self.srt_lbl_w.configure(text=self.t("srt_label"))
        self.srt_checkbox.configure(text=self.t("srt_check"))
        self.model_lbl_w.configure(text=self.t("model_label"))
        
        # Update Model OptionMenu
        opts_dict = self.t("model_options")
        model_values = list(opts_dict.values())
        self.model_menu.configure(values=model_values)
        # Preserve selected model
        cur_key = self.model_key_var.get()
        if cur_key in opts_dict:
            self.model_display_var.set(opts_dict[cur_key])

        self.outdir_lbl_w.configure(text=self.t("outdir_label"))
        self.outdir_val_lbl.configure(
            text=self.output_dir if self.output_dir else self.t("outdir_default"))
        self.outdir_btn.configure(text=self.t("outdir_change"))
        self.run_btn.configure(text=self.t("run_btn"))
        self.stop_btn.configure(text=self.t("stop_btn"))
        self.log_hdr_lbl.configure(text=self.t("log_header"))
        self.clear_btn.configure(text=self.t("log_clear"))
        
        self._update_margin_label()
        self._update_threshold_label()

    def _on_model_select(self, display_val):
        opts_dict = self.t("model_options")
        # Reverse lookup to find internal key
        for k, v in opts_dict.items():
            if v == display_val:
                self.model_key_var.set(k)
                break

    def _on_srt_toggle(self):
        if self.srt_var.get():
            self.model_menu.configure(state="normal")
        else:
            self.model_menu.configure(state="disabled")

    def _on_drop(self, event):
        raw = event.data.strip()
        files = re.findall(r'\{([^}]+)\}|(\S+)', raw)
        path = next((f[0] or f[1] for f in files), "")
        if path:
            self._set_file(path)

    def _browse_file(self):
        path = filedialog.askopenfilename(
            title=self.t("file_dialog"),
            filetypes=[("Video files", "*.mp4 *.mov *.avi *.mkv *.wmv *.flv *.webm *.m4v"), ("All files", "*.*")])
        if path:
            self._set_file(path)

    def _set_file(self, path):
        self.input_file = path
        self.drop_label.configure(text=f"🎬  {Path(path).name}", text_color="white")
        if not self.output_dir:
            self.outdir_val_lbl.configure(text=self.t("outdir_default"), text_color=TEXT_MUTED)
        self._log(self.t("log_file", path), "info")

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

    # ── Processing ─────────────────────────────────────────────────────────────
    def _start_process(self):
        if not self.input_file:
            messagebox.showwarning(self.t("warn_title"), self.t("warn_no_file"))
            return
        if not Path(self.input_file).exists():
            messagebox.showerror(self.t("err_title"), self.t("err_not_found"))
            return
        if self.running:
            return

        margin      = self.margin_var.get()
        threshold   = self.threshold_var.get()
        label       = self.export_var.get()
        ae_key, ext = EXPORT_MODES[label]
        
        # USE ABSOLUTE PATHS TO PREVENT PATH ERRORS
        inp         = Path(self.input_file).resolve()
        out_dir     = Path(self.output_dir).resolve() if self.output_dir else inp.parent
        output_ae   = out_dir / f"{inp.stem}_snipsynced{ext}"
        output_srt  = out_dir / f"{inp.stem}.srt"
        
        do_srt = self.srt_var.get()
        model_size = self.model_key_var.get()

        ae_path = get_auto_editor_path()
        cmd = [
            str(ae_path), str(inp),
            "--margin", f"{margin:.3f}s",
            "--edit", f"audio:threshold={threshold:.1f}%",
            "--export", ae_key,
            "--output", str(output_ae),
            "--no-open",
        ]

        sep = "─" * 50
        self._log(sep, "muted")
        self._log(self.t("log_start"), "info")
        self._log(f"{self.t('log_input')}: {inp.name}", "muted")
        self._log(f"{self.t('log_margin')}: {margin:.2f} {self.t('margin_unit')}", "muted")
        self._log(f"{self.t('log_threshold')}: {threshold:.1f} {self.t('threshold_unit')}", "muted")
        self._log(f"{self.t('log_format')}: {label}", "muted")
        if do_srt:
            self._log(f"  SRT生成: 有効 (モデル: {model_size})", "muted")
        self._log(f"{self.t('log_output')}: {out_dir}", "muted")
        self._log(sep, "muted")

        self.running = True
        self.stop_requested = False
        self.run_btn.configure(state="disabled")
        self.stop_btn.configure(state="normal")
        self.progress.start()

        threading.Thread(
            target=self._worker, args=(cmd, output_ae, inp, output_srt, do_srt, model_size, ae_path, margin, threshold), daemon=True).start()

    def _worker(self, cmd, output_ae, inp, output_srt, do_srt, model_size, ae_path, margin, threshold):
        try:
            success = False
            # 1. Auto-Editor Processing
            try:
                # Use subprocess.run as requested for capture_output=True
                res = subprocess.run(
                    cmd, capture_output=True, text=True, encoding="utf-8", errors="replace"
                )
                
                # Log stdout
                if res.stdout:
                    for line in res.stdout.splitlines():
                        line = line.rstrip()
                        if not line: continue
                        if any(k in line.lower() for k in ("error", "failed", "exception")):
                            self._log(line, "error")
                        elif any(k in line.lower() for k in ("warning", "warn")):
                            self._log(line, "warn")
                        else:
                            self._log(line)
                            
                rc = res.returncode
                if rc == 0 and not self.stop_requested:
                    self._log(self.t("log_done_ae"), "success")
                    self._log(f"   {output_ae.name}", "success")
                    success = True
                elif self.stop_requested:
                    self._log(self.t("log_stopped"), "warn")
                else:
                    self._log(self.t("log_error", rc, res.stderr), "error")
            except FileNotFoundError as e:
                self._log(self.t("log_ae_missing", e), "error")
            except Exception as e:
                self._log(self.t("log_unexpected", traceback.format_exc()), "error")

            # 2. Faster-Whisper Processing via Temp WAV
            if success and do_srt and not self.stop_requested:
                temp_wav = output_ae.parent / f"{inp.stem}_temp_audio.wav"
                temp_success = False

                # 2a. Generate Temp WAV
                self._log(self.t("log_srt_temp_start"), "info")
                temp_cmd = [
                    str(ae_path), str(inp),
                    "--margin", f"{margin:.3f}s",
                    "--edit", f"audio:threshold={threshold:.1f}%",
                    "-vn", "-sn", "-dn",
                    "--mix-audio-streams",
                    "--output", str(temp_wav),
                    "--no-open"
                ]
                try:
                    res_temp = subprocess.run(
                        temp_cmd, capture_output=True, text=True, encoding="utf-8", errors="replace"
                    )
                    
                    if res_temp.returncode == 0 and not self.stop_requested:
                        # Ensure the file actually exists
                        if temp_wav.exists():
                            temp_success = True
                        else:
                            self._log(self.t("log_wav_missing"), "error")
                    else:
                        if not self.stop_requested:
                            self._log(self.t("log_error", res_temp.returncode, res_temp.stderr), "error")
                except Exception as e:
                    self._log(self.t("log_unexpected", traceback.format_exc()), "error")

                # 2b. Transcribe Temp WAV
                if temp_success and not self.stop_requested:
                    self._log(self.t("log_srt_analyze", model_size), "info")
                    try:
                        # Load model (CPU + int8 for compatibility and speed without huge GPU binary bundles)
                        model = WhisperModel(model_size, device="cpu", compute_type="int8")
                        
                        # Transcribe
                        segments, info = model.transcribe(str(temp_wav), beam_size=5, language=None)
                        
                        self._log(f"  音声検出: {info.language} (確率: {info.language_probability:.2f})", "muted")
                        
                        # Generate SRT
                        with open(output_srt, "w", encoding="utf-8") as srt_file:
                            for i, segment in enumerate(segments, start=1):
                                if self.stop_requested:
                                    break
                                start = format_timestamp(segment.start)
                                end = format_timestamp(segment.end)
                                text = segment.text.strip()
                                srt_file.write(f"{i}\n{start} --> {end}\n{text}\n\n")
                                # Log partial progress
                                self._log(f"  [{start} -> {end}] {text}", "muted")

                        if not self.stop_requested:
                            self._log(self.t("log_srt_done"), "success")
                            self._log(f"   {output_srt.name}", "success")
                        else:
                            self._log(self.t("log_stopped"), "warn")
                            
                    except Exception as e:
                        self._log(self.t("log_unexpected", traceback.format_exc()), "error")

                # 2c. Cleanup Temp WAV
                try:
                    if temp_wav.exists():
                        temp_wav.unlink()
                except Exception as e:
                    self._log(f"Temp file cleanup failed: {e}", "warn")

        except Exception as e:
            # Catch any unexpected top-level worker thread crashes
            self._log(self.t("log_unexpected", traceback.format_exc()), "error")
        finally:
            self.running = False
            if not self.stop_requested and success:
                self.after(0, lambda: self._popup_done(out_dir=output_ae.parent))
            self.after(0, self._reset_ui)

    def _popup_done(self, out_dir):
        def _show():
            if messagebox.askyesno(self.t("done_title"), self.t("done_msg")):
                os.startfile(str(out_dir))
        self.after(0, _show)

    def _stop_process(self):
        # When using subprocess.run, immediate process termination from outside is harder.
        # We set the flag so the next stages skip.
        self.stop_requested = True
        self._log("⬛ 停止リクエストを受け付けました。現在の処理が完了すると停止します...", "warn")

    def _reset_ui(self):
        self.running = False
        self.run_btn.configure(state="normal")
        self.stop_btn.configure(state="disabled")
        self.progress.stop()
        self.progress.set(0)

def main():
    app = SnipSyncApp()
    if not WHISPER_AVAILABLE:
        app._log("⚠ faster-whisper がインストールされていないため、字幕機能は利用できません。", "warn")
    app._log(app.t("log_welcome"), "muted")
    app.mainloop()

if __name__ == "__main__":
    main()
