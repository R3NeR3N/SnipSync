"""文字起こしの清書の画面: PC 上の LLM で直す／貼り付け用のファイルを作る。"""
import os
import threading
import tkinter as tk
import webbrowser
from pathlib import Path
from tkinter import filedialog, messagebox

import customtkinter as ctk

from snipsync.core import polish
from snipsync.core.subtitles import speaker_label
from snipsync.core.transcript import cues_to_md, cues_to_txt, reading_turns
from snipsync.ui import theme as T
from snipsync.ui import widgets as W


class PolishDialog(ctk.CTkToplevel):
    def __init__(self, editor):
        """editor: 開いている字幕編集ウィンドウ。いまの字幕（編集後）と、話者名を使う。"""
        super().__init__(editor)
        self.editor = editor
        self.app = editor.app
        self.t = editor.t
        self.prefs = polish.load_settings()
        self.busy = False
        self.stop = False
        self.out_dir: Path | None = None
        self.configure(fg_color=T.BENCH)
        T.apply_icon(self)
        self.title(self.t("pl_title"))
        self.geometry("640x470")
        self.minsize(560, 420)
        self.transient(editor)
        self.protocol("WM_DELETE_WINDOW", self._close)
        self.columnconfigure(0, weight=1)
        self._build()
        self._show_mode()
        self.after(50, self.lift)

    # ── 構築 ───────────────────────────────────────────────────────────────────────
    def _build(self):
        pad = dict(padx=T.S4)
        W.caption(self, self.t("pl_note"), wraplength=580).grid(row=0, column=0, sticky="w", pady=(T.S4, T.S3), **pad)
        self.mode = W.Choice(self, {"local": self.t("pl_mode_local"), "paste": self.t("pl_mode_paste")},
                             command=self._on_mode)
        self.mode.grid(row=1, column=0, sticky="w", pady=(0, T.S3), **pad)
        self.mode.set_key(self.prefs["mode"])

        # PC 上の LLM
        self.local_box = ctk.CTkFrame(self, fg_color=T.PANEL, corner_radius=T.R_PANEL)
        self.local_box.columnconfigure(1, weight=1)
        W.caption(self.local_box, self.t("pl_endpoint")).grid(row=0, column=0, sticky="w", padx=T.S4, pady=(T.S3, T.S1))
        self.endpoint_var = tk.StringVar(value=self.prefs["endpoint"])
        W.entry(self.local_box, self.endpoint_var).grid(row=0, column=1, sticky="ew", padx=(0, T.S4), pady=(T.S3, T.S1))
        W.caption(self.local_box, self.t("pl_model")).grid(row=1, column=0, sticky="w", padx=T.S4, pady=T.S1)
        self.model_var = tk.StringVar(value=self.prefs["model"])
        W.entry(self.local_box, self.model_var, placeholder=self.t("pl_model_hint")).grid(
            row=1, column=1, sticky="ew", padx=(0, T.S4), pady=T.S1)
        self.btn_check = W.Btn(self.local_box, self.t("pl_check"), self._check)
        self.btn_check.grid(row=2, column=1, sticky="w", pady=(T.S1, T.S3))
        W.caption(self.local_box, self.t("pl_local_note"), wraplength=560).grid(
            row=3, column=0, columnspan=2, sticky="w", padx=T.S4, pady=(0, T.S2))
        guide = ctk.CTkFrame(self.local_box, fg_color="transparent")
        guide.grid(row=4, column=0, columnspan=2, sticky="w", padx=T.S4, pady=(0, T.S3))
        W.caption(guide, self.t("pl_guide")).pack(side="left", padx=(0, T.S2))
        self.btn_guides = {}
        for key, label in (("browser", "pl_guide_web"), ("claude", "pl_guide_claude"), ("chatgpt", "pl_guide_chatgpt")):
            b = W.Btn(guide, self.t(label), lambda k=key: self._open_guide(k), kind="ghost", height=28)
            b.pack(side="left", padx=(0, T.S1))
            self.btn_guides[key] = b

        # 貼り付け用
        self.paste_box = ctk.CTkFrame(self, fg_color=T.PANEL, corner_radius=T.R_PANEL)
        self.paste_box.columnconfigure(1, weight=1)
        W.caption(self.paste_box, self.t("pl_chunk")).grid(row=0, column=0, sticky="w", padx=T.S4, pady=(T.S3, T.S1))
        self.chunk_var = tk.StringVar(value=str(polish.PASTE_CHUNK_CHARS))
        W.entry(self.paste_box, self.chunk_var, width=90, justify="right").grid(row=0, column=1, sticky="w", pady=(T.S3, T.S1))
        W.caption(self.paste_box, self.t("pl_paste_note"), wraplength=560).grid(
            row=1, column=0, columnspan=2, sticky="w", padx=T.S4, pady=(T.S1, T.S3))

        self.status = W.caption(self, wraplength=580)
        self.status.grid(row=4, column=0, sticky="w", pady=(T.S3, T.S1), **pad)
        self.bar = ctk.CTkProgressBar(self, mode="determinate", height=8, corner_radius=4, fg_color=T.EDGE,
                                      progress_color=T.PENCIL)
        self.bar.grid(row=5, column=0, sticky="ew", pady=(0, T.S3), **pad)
        self.bar.set(0)
        foot = ctk.CTkFrame(self, fg_color="transparent")
        foot.grid(row=6, column=0, sticky="ew", pady=(0, T.S4), **pad)
        foot.columnconfigure(0, weight=1)
        self.btn_open = W.Btn(foot, self.t("pl_open_folder"), self._open_folder)
        self.btn_open.grid(row=0, column=1, padx=(0, T.S2))
        self.btn_open.enable(False)
        self.btn_stop = W.Btn(foot, self.t("upd_stop"), self._on_stop, kind="danger", width=72)
        self.btn_stop.grid(row=0, column=2, padx=(0, T.S2))
        self.btn_stop.enable(False)
        self.btn_run = W.Btn(foot, self.t("pl_run"), self._run, kind="primary", width=120)
        self.btn_run.grid(row=0, column=3, padx=(0, T.S2))
        self.btn_close = W.Btn(foot, self.t("upd_close"), self._close)
        self.btn_close.grid(row=0, column=4)

    def _open_guide(self, which: str):
        """初めて設定する人のために、手順を、ブラウザの検索や、AI への質問（質問文は入力済み）で調べる。"""
        url = polish.guide_links(self.app.lang)[which]
        webbrowser.open(url)
        self.status.configure(text=self.t("pl_guide_opened"))

    def _show_mode(self):
        key = self.mode.get_key()
        if key == "local":
            self.paste_box.grid_remove()
            self.local_box.grid(row=2, column=0, sticky="ew", padx=T.S4)
        else:
            self.local_box.grid_remove()
            self.paste_box.grid(row=2, column=0, sticky="ew", padx=T.S4)
        self.btn_run.configure(text=self.t("pl_run" if key == "local" else "pl_make"))

    def _on_mode(self, _key):
        self._show_mode()

    # ── 状態 ───────────────────────────────────────────────────────────────────────
    def _alive(self) -> bool:
        try:
            return bool(self.winfo_exists())
        except tk.TclError:
            return False

    def _post(self, fn):
        try:
            self.after(0, lambda: fn() if self._alive() else None)
        except (tk.TclError, RuntimeError):
            pass

    def _set_busy(self, busy: bool):
        self.busy = busy
        for b in (self.btn_run, self.btn_check):
            b.enable(not busy)
        self.btn_stop.enable(busy and self.mode.get_key() == "local")

    def _close(self):
        if not self.busy:
            self._save_prefs()
            self.destroy()

    def _on_stop(self):
        self.stop = True
        self.btn_stop.enable(False)

    def _save_prefs(self):
        self.prefs.update(mode=self.mode.get_key(), endpoint=self.endpoint_var.get().strip(),
                          model=self.model_var.get().strip())
        try:
            polish.save_settings(self.prefs)
        except OSError:
            pass

    # ── 元の文章 ───────────────────────────────────────────────────────────────────
    def _material(self):
        """いまの字幕から、読みやすく整えた段落と、行を作る。"""
        ed = self.editor.editor
        lang = self.app.lang
        passages = reading_turns(ed.cues, names=ed.names, ui_lang=lang)
        lines = polish.lines_from_passages(
            passages, lambda s: ed.speaker_name(s, speaker_label(s, lang)))
        return passages, lines

    def _target_dir(self) -> Path | None:
        base = self.editor.paths.get("srt") or next(iter(self.editor.paths.values()), None)
        if base is None:
            chosen = filedialog.askdirectory(parent=self, title=self.t("pl_pick_dir"))
            return Path(chosen) if chosen else None
        return Path(base).parent

    def _stem(self) -> str:
        base = self.editor.paths.get("srt") or next(iter(self.editor.paths.values()), None)
        return Path(base).stem if base else (self.editor.stem or "transcript")

    def _open_folder(self):
        if self.out_dir:
            os.startfile(str(self.out_dir))

    # ── 実行 ───────────────────────────────────────────────────────────────────────
    def _run(self):
        if self.busy:
            return
        passages, lines = self._material()
        if not lines:
            self.status.configure(text=self.t("pl_empty"))
            return
        folder = self._target_dir()
        if folder is None:
            return
        self._save_prefs()
        if self.mode.get_key() == "paste":
            self._make_paste_set(lines, folder)
        else:
            self._run_local(passages, lines, folder)

    def _make_paste_set(self, lines, folder: Path):
        try:
            chars = int(self.chunk_var.get().strip())
            if chars < 500:
                raise ValueError
        except ValueError:
            chars = polish.PASTE_CHUNK_CHARS
        try:
            written = polish.write_paste_set(lines, folder / f"{self._stem()}_polish", lang=self.app.lang, max_chars=chars)
        except OSError as exc:
            self.status.configure(text=self.t("pl_failed", exc))
            return
        self.out_dir = written[0].parent
        self.btn_open.enable(True)
        self.bar.set(1)
        self.status.configure(text=self.t("pl_paste_done", len(written) - 1, self.out_dir.name))

    def _run_local(self, passages, lines, folder: Path):
        model = self.model_var.get().strip()
        if not model:
            self.status.configure(text=self.t("pl_need_model"))
            return
        try:
            client = polish.LocalLLM(self.endpoint_var.get(), model)
        except polish.PolishError:
            self.status.configure(text=self.t("pl_not_local"))
            return
        n = len(polish.split_chunks(lines, polish.CHUNK_CHARS))
        if not messagebox.askyesno(self.t("pl_confirm_title"), self.t("pl_confirm", len(lines), n), parent=self):
            return
        self.stop = False
        self._set_busy(True)
        self.bar.set(0)
        self.status.configure(text=self.t("pl_progress", 0, n))
        lang = self.app.lang

        def progress(done, total):
            self._post(lambda: (self.bar.set(done / total), self.status.configure(text=self.t("pl_progress", done, total))))

        def work():
            try:
                result = polish.polish_local(lines, client, lang=lang, on_progress=progress, should_stop=lambda: self.stop)
            except polish.PolishCancelled:
                self._post(lambda: self._finished(self.t("pl_stopped")))
            except polish.PolishError as exc:
                self._post(lambda e=str(exc): self._finished(self.t("pl_failed", e)))
            else:
                self._post(lambda: self._local_done(passages, lines, result, folder))

        threading.Thread(target=work, daemon=True).start()

    def _finished(self, message: str):
        self._set_busy(False)
        self.status.configure(text=message)

    def _local_done(self, passages, lines, result, folder: Path):
        fixed = polish.apply_to_passages(passages, lines, result.texts)
        ed = self.editor.editor
        cues, lang, stem = ed.cues, self.app.lang, self._stem()
        speakers = any(c.speaker is not None for c in cues)
        try:
            (folder / f"{stem}_polished.txt").write_text(
                cues_to_txt(cues, speakers=speakers, ui_lang=lang, names=ed.names, passages=fixed), encoding="utf-8")
            (folder / f"{stem}_polished.md").write_text(
                cues_to_md(cues, title=f"{stem}_polished", speakers=speakers, ui_lang=lang, names=ed.names,
                           passages=fixed), encoding="utf-8")
        except OSError as exc:
            self._finished(self.t("pl_failed", exc))
            return
        self.out_dir = folder
        self.btn_open.enable(True)
        self._finished(self.t("pl_local_done", len(result.texts), len(lines), result.fallbacks, f"{stem}_polished"))

    def _check(self):
        try:
            client = polish.LocalLLM(self.endpoint_var.get(), self.model_var.get())
        except polish.PolishError:
            self.status.configure(text=self.t("pl_not_local"))
            return
        self._set_busy(True)
        self.status.configure(text=self.t("upd_checking"))

        def work():
            try:
                names = client.models()
            except polish.PolishError as exc:
                self._post(lambda e=str(exc): self._finished(self.t("pl_check_failed", e)))
            else:
                self._post(lambda: self._checked(names))

        threading.Thread(target=work, daemon=True).start()

    def _checked(self, names):
        if names and not self.model_var.get().strip():
            self.model_var.set(names[0])
        shown = ", ".join(names[:5])
        self._finished(self.t("pl_check_ok", len(names), shown) if names else self.t("pl_check_none"))
