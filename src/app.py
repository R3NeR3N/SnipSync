"""
SnipSync - Silent Video Cutter & Subtitle Generator
Cuts silent portions from video, exports XML for NLEs, and generates .srt subtitles.
"""
import os
import re
import sys
import threading
from pathlib import Path
from tkinter import filedialog, messagebox

import customtkinter as ctk

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

from i18n import I18N
from pipeline import PipelineParams, run_pipeline
from presets import delete_preset, load_store, save_store, set_last_used, upsert_preset
from subtitles import (  # noqa: F401  (format_timestamp re-exported for tests)
    cuda_available,
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
from version import APP_VERSION  # noqa: F401  (re-exported for tests)


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

EXPORT_MODES = {
    "DaVinci Resolve (.fcpxml)":    ("resolve",       ".fcpxml"),
    "Premiere Pro (.xml)":          ("premiere",      ".xml"),
    "Final Cut Pro (.fcpxml)":      ("final-cut-pro", ".fcpxml"),
}

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
        self.gpu_var     = ctk.BooleanVar(value=False)
        self.snap_srt_var = ctk.BooleanVar(value=True)
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
        if not cuda_available():
            self.gpu_checkbox.configure(state="disabled")
            self._log(self.t("log_gpu_unavailable"), "muted")

        # Load preset store and apply last used settings
        store = load_store()
        if store.get("last_used"):
            self._apply_settings(store["last_used"])

        self._apply_lang()
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

        # 0. Preset
        self.preset_lbl_w = ctk.CTkLabel(
            card, text="", font=ctk.CTkFont(family="Segoe UI", size=12, weight="bold"), text_color="white")
        self.preset_lbl_w.grid(row=0, column=0, sticky="w", **pad)

        preset_frame = ctk.CTkFrame(card, fg_color="transparent")
        preset_frame.grid(row=0, column=1, columnspan=3, sticky="w", padx=(0, 20), pady=8)

        self.preset_menu_var = ctk.StringVar()
        self.preset_menu = ctk.CTkOptionMenu(
            preset_frame, values=[], variable=self.preset_menu_var,
            font=ctk.CTkFont(family="Segoe UI", size=12), fg_color=BG_DARK, button_color=ACCENT,
            button_hover_color=ACCENT_HOVER, dropdown_fg_color=BG_DARK, width=200,
            command=self._on_preset_select)
        self.preset_menu.pack(side="left")

        self.preset_save_btn = ctk.CTkButton(
            preset_frame, text="", width=60, font=ctk.CTkFont(family="Segoe UI", size=11),
            fg_color=BG_DARK, hover_color=ACCENT, command=self._on_preset_save)
        self.preset_save_btn.pack(side="left", padx=(10, 0))

        self.preset_delete_btn = ctk.CTkButton(
            preset_frame, text="", width=60, font=ctk.CTkFont(family="Segoe UI", size=11),
            fg_color=BG_DARK, hover_color=ERROR_COL, command=self._on_preset_delete)
        self.preset_delete_btn.pack(side="left", padx=(10, 0))

        # 1. Margin
        self.margin_lbl_w = ctk.CTkLabel(
            card, text="", font=ctk.CTkFont(family="Segoe UI", size=12, weight="bold"), text_color="white")
        self.margin_lbl_w.grid(row=1, column=0, sticky="w", **pad)

        sf1 = ctk.CTkFrame(card, fg_color="transparent")
        sf1.grid(row=1, column=1, sticky="ew", padx=(0, 10), pady=8)
        sf1.columnconfigure(0, weight=1)
        self.slider_margin = ctk.CTkSlider(
            sf1, from_=0.0, to=2.0, number_of_steps=40, variable=self.margin_var, command=self._on_slider_margin,
            button_color=ACCENT, button_hover_color=ACCENT_HOVER, progress_color=ACCENT)
        self.slider_margin.grid(row=0, column=0, sticky="ew")

        self.margin_val_lbl = ctk.CTkLabel(
            card, text="", font=ctk.CTkFont(family="Consolas", size=13, weight="bold"), text_color=ACCENT, width=60)
        self.margin_val_lbl.grid(row=1, column=2, padx=(0, 6), pady=8)

        self.margin_entry = ctk.CTkEntry(
            card, width=70, textvariable=self.margin_var, font=ctk.CTkFont(family="Consolas", size=12), justify="center")
        self.margin_entry.grid(row=1, column=3, sticky="w", padx=(0, 20), pady=8)
        self.margin_entry.bind("<Return>", self._on_entry_margin_commit)
        self.margin_entry.bind("<FocusOut>", self._on_entry_margin_commit)

        # 2. Threshold
        self.threshold_lbl_w = ctk.CTkLabel(
            card, text="", font=ctk.CTkFont(family="Segoe UI", size=12, weight="bold"), text_color="white")
        self.threshold_lbl_w.grid(row=2, column=0, sticky="w", **pad)

        sf2 = ctk.CTkFrame(card, fg_color="transparent")
        sf2.grid(row=2, column=1, sticky="ew", padx=(0, 10), pady=8)
        sf2.columnconfigure(0, weight=1)
        self.slider_threshold = ctk.CTkSlider(
            sf2, from_=0.0, to=50.0, number_of_steps=100, variable=self.threshold_var, command=self._on_slider_threshold,
            button_color=ACCENT, button_hover_color=ACCENT_HOVER, progress_color=ACCENT)
        self.slider_threshold.grid(row=0, column=0, sticky="ew")

        self.threshold_val_lbl = ctk.CTkLabel(
            card, text="", font=ctk.CTkFont(family="Consolas", size=13, weight="bold"), text_color=ACCENT, width=60)
        self.threshold_val_lbl.grid(row=2, column=2, padx=(0, 6), pady=8)

        self.threshold_entry = ctk.CTkEntry(
            card, width=70, textvariable=self.threshold_var, font=ctk.CTkFont(family="Consolas", size=12), justify="center")
        self.threshold_entry.grid(row=2, column=3, sticky="w", padx=(0, 20), pady=8)
        self.threshold_entry.bind("<Return>", self._on_entry_threshold_commit)
        self.threshold_entry.bind("<FocusOut>", self._on_entry_threshold_commit)

        # 3. Export format
        self.export_lbl_w = ctk.CTkLabel(
            card, text="", font=ctk.CTkFont(family="Segoe UI", size=12, weight="bold"), text_color="white")
        self.export_lbl_w.grid(row=3, column=0, sticky="w", **pad)

        self.export_menu = ctk.CTkOptionMenu(
            card, values=list(EXPORT_MODES.keys()), variable=self.export_var,
            font=ctk.CTkFont(family="Segoe UI", size=12), fg_color=BG_DARK, button_color=ACCENT,
            button_hover_color=ACCENT_HOVER, dropdown_fg_color=BG_DARK, width=240,
            command=self._on_export_change)
        self.export_menu.grid(row=3, column=1, columnspan=3, sticky="w", padx=(0, 20), pady=8)

        # 4. SRT Generation settings
        self.srt_lbl_w = ctk.CTkLabel(
            card, text="", font=ctk.CTkFont(family="Segoe UI", size=12, weight="bold"), text_color="white")
        self.srt_lbl_w.grid(row=4, column=0, sticky="w", **pad)

        srt_frame = ctk.CTkFrame(card, fg_color="transparent")
        srt_frame.grid(row=4, column=1, columnspan=3, sticky="w", padx=(0, 20), pady=8)

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

        self.gpu_checkbox = ctk.CTkCheckBox(
            srt_frame, text="", variable=self.gpu_var, font=ctk.CTkFont(family="Segoe UI", size=11),
            fg_color=ACCENT, hover_color=ACCENT_HOVER)
        self.gpu_checkbox.pack(side="left", padx=(20, 0))

        self.snap_srt_checkbox = ctk.CTkCheckBox(
            srt_frame, text="", variable=self.snap_srt_var, font=ctk.CTkFont(family="Segoe UI", size=11),
            fg_color=ACCENT, hover_color=ACCENT_HOVER)
        self.snap_srt_checkbox.pack(side="left", padx=(20, 0))

        if not WHISPER_AVAILABLE:
            self.srt_var.set(False)
            self.srt_checkbox.configure(state="disabled")
            self.model_menu.configure(state="disabled")
            self.gpu_checkbox.configure(state="disabled")
            self.snap_srt_checkbox.configure(state="disabled")

        # 5. Output dir
        self.outdir_lbl_w = ctk.CTkLabel(
            card, text="", font=ctk.CTkFont(family="Segoe UI", size=12, weight="bold"), text_color="white")
        self.outdir_lbl_w.grid(row=5, column=0, sticky="w", **pad)

        of = ctk.CTkFrame(card, fg_color="transparent")
        of.grid(row=5, column=1, columnspan=3, sticky="ew", padx=(0, 20), pady=8)
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
            "snap_srt": self.snap_srt_var.get()
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
            if s["model"] in opts_dict:
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

        self._update_margin_label()
        self._update_threshold_label()
        self._on_srt_toggle()

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

    def _on_model_select(self, display_val):
        opts_dict = self.t("model_options")
        # Reverse lookup to find internal key
        for k, v in opts_dict.items():
            if v == display_val:
                self.model_key_var.set(k)
                break

    def _on_srt_toggle(self):
        is_srt = self.srt_var.get()
        export_disp = self.export_var.get()
        ae_key = EXPORT_MODES.get(export_disp, ("resolve", ""))[0]
        is_fcpxml = ae_key in ("resolve", "final-cut-pro")

        if is_srt:
            self.model_menu.configure(state="normal")
            if cuda_available():
                self.gpu_checkbox.configure(state="normal")
            else:
                self.gpu_checkbox.configure(state="disabled")

            if is_fcpxml:
                self.snap_srt_checkbox.configure(state="normal")
            else:
                self.snap_srt_checkbox.configure(state="disabled")
        else:
            self.model_menu.configure(state="disabled")
            self.gpu_checkbox.configure(state="disabled")
            self.snap_srt_checkbox.configure(state="disabled")

    def _on_export_change(self, choice):
        self._on_srt_toggle()

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

        do_srt = self.srt_var.get()
        model_size = self.model_key_var.get()

        ae_path = get_auto_editor_path()

        sep = "─" * 50
        self._log(sep, "muted")
        self._log(self.t("log_start"), "info")
        self._log(f"{self.t('log_input')}: {inp.name}", "muted")
        self._log(f"{self.t('log_margin')}: {margin:.2f} {self.t('margin_unit')}", "muted")
        self._log(f"{self.t('log_threshold')}: {threshold:.1f} {self.t('threshold_unit')}", "muted")
        self._log(f"{self.t('log_format')}: {label}", "muted")
        if do_srt:
            self._log(self.t("log_srt_enabled", model_size), "muted")
        self._log(f"{self.t('log_output')}: {out_dir}", "muted")
        self._log(sep, "muted")

        self.running = True
        self.stop_requested = False
        self.run_btn.configure(state="disabled")
        self.stop_btn.configure(state="normal")
        self.progress.start()

        params = PipelineParams(
            margin=margin,
            threshold=threshold,
            export_key=ae_key,
            do_srt=do_srt,
            model_size=model_size,
            use_gpu=self.gpu_var.get(),
            snap_srt=self.snap_srt_var.get(),
        )

        threading.Thread(
            target=self._worker, args=(ae_path, inp, out_dir, params), daemon=True).start()

    def _worker(self, ae_path, inp, out_dir, params):
        result = run_pipeline(
            ae_path, inp, out_dir, params,
            on_log=self._log,
            should_stop=lambda: self.stop_requested,
            tr=self.t,
        )
        self.running = False
        if not result.stopped and result.ok:
            self.after(0, lambda: self._popup_done(out_dir=out_dir))
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
