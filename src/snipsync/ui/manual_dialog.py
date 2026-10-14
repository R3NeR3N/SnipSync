"""手動のカット・倍速の一覧: 指定した区間を確かめ、1 件ずつ外す。"""
import tkinter as tk

import customtkinter as ctk

from snipsync.core import manualcuts as mc
from snipsync.ui import theme as T
from snipsync.ui import widgets as W


class ManualListDialog(ctk.CTkToplevel):
    def __init__(self, app):
        super().__init__(app)
        self.app = app
        self.t = app.t
        self.configure(fg_color=T.BENCH)
        T.apply_icon(self)
        self.title(self.t("man_title"))
        self.geometry("560x420")
        self.minsize(460, 300)
        self.transient(app)
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)
        W.caption(self, self.t("man_note"), wraplength=520).grid(row=0, column=0, sticky="w", padx=T.S4, pady=(T.S4, T.S2))
        self.body = ctk.CTkScrollableFrame(self, fg_color=T.PANEL, corner_radius=T.R_PANEL)
        self.body.grid(row=1, column=0, sticky="nsew", padx=T.S4)
        self.body.columnconfigure(0, weight=1)
        foot = ctk.CTkFrame(self, fg_color="transparent")
        foot.grid(row=2, column=0, sticky="ew", padx=T.S4, pady=T.S4)
        foot.columnconfigure(0, weight=1)
        self.btn_all = W.Btn(foot, self.t("man_clear_all"), self._clear_all, kind="danger")
        self.btn_all.grid(row=0, column=1, padx=(0, T.S2))
        W.Btn(foot, self.t("upd_close"), self.destroy).grid(row=0, column=2)
        self.refresh()
        self.after(50, self.lift)

    def describe(self, e: mc.ManualEdit) -> str:
        span = f"{W.fmt_time(e.start)} – {W.fmt_time(e.end)}"
        length = f"{e.length:.1f}"
        if e.action == mc.CUT:
            return self.t("man_row_cut", span, length)
        return self.t("man_row_speed", f"{e.speed:g}", span, length)

    def refresh(self):
        for w in self.body.winfo_children():
            w.destroy()
        edits = list(self.app.manual_edits)
        if not edits:
            W.caption(self.body, self.t("man_none")).grid(row=0, column=0, sticky="w", padx=T.S3, pady=T.S3)
        for i, e in enumerate(edits):
            row = ctk.CTkFrame(self.body, fg_color="transparent")
            row.grid(row=i, column=0, sticky="ew", padx=T.S2, pady=2)
            row.columnconfigure(0, weight=1)
            W.label(row, self.describe(e), "mono", T.CHALK).grid(row=0, column=0, sticky="w")
            W.Btn(row, self.t("man_play"), lambda e=e: self.app.play_source(e.start), kind="ghost", height=28).grid(
                row=0, column=1, padx=(T.S2, T.S1))
            W.Btn(row, self.t("man_remove"), lambda e=e: self._remove(e), height=28).grid(row=0, column=2)
        self.btn_all.enable(bool(edits))

    def _remove(self, edit: mc.ManualEdit):
        self.app.remove_manual(edit)
        self.refresh()

    def _clear_all(self):
        self.app.clear_manual()
        self.refresh()

    def alive(self) -> bool:
        try:
            return bool(self.winfo_exists())
        except tk.TclError:
            return False
