"""字幕を確認し、保存する前に直すウィンドウ。

上に字幕の表、下に選んだ1件の編集欄（マスター/ディテール）。表は1行1件で、自分が直した行は黄色で示す。
「編集」以外のタブは、編集内容を反映した出力（.txt / .md / .srt）のプレビュー。
"""
from __future__ import annotations

import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

import customtkinter as ctk

import theme as T
import widgets as W
from subtitle_edit import CueEditor, format_for_path, render, save
from transcript import parse_srt

MAX_SPEAKERS = 6


def _hms(sec: float) -> str:
    sec = int(sec)
    return f"{sec // 3600:02d}:{sec % 3600 // 60:02d}:{sec % 60:02d}"


class SubtitleEditor(ctk.CTkToplevel):
    def __init__(self, app, cues=(), title: str = "", paths: dict | None = None):
        super().__init__(app)
        self.app = app
        self.t = app.t
        self.editor = CueEditor(cues)
        self.stem = title
        self.paths: dict[str, Path] = dict(paths or {})     # 上書き保存の宛先（形式 -> パス）
        self._sel: int | None = None
        self._loading = False
        self._status_after = None
        self.configure(fg_color=T.BENCH)
        self.geometry("980x720")
        self.minsize(820, 580)
        self.protocol("WM_DELETE_WINDOW", self._close)
        self._style_tree()
        self._build()
        self.bind("<Control-s>", lambda _e: self.save())
        self._refresh_all()
        self.after(50, self.lift)

    # ── 構築 ───────────────────────────────────────────────────────────────────────
    def _style_tree(self):
        st = ttk.Style(self)
        st.theme_use("clam")
        st.configure("Snip.Treeview", background=T.WELL, fieldbackground=T.WELL, foreground=T.CHALK,
                     bordercolor=T.WELL, lightcolor=T.WELL, darkcolor=T.WELL, rowheight=32, borderwidth=0,
                     font=T.font(ctk, "mono"))
        st.map("Snip.Treeview", background=[("selected", T.blend(T.PENCIL, T.WELL, 0.28))],
               foreground=[("selected", T.CHALK)])
        st.configure("Snip.Treeview.Heading", background=T.PANEL, foreground=T.DUST, relief="flat",
                     borderwidth=0, padding=(10, 8), font=T.font(ctk, "label"))
        st.map("Snip.Treeview.Heading", background=[("active", T.PANEL)])
        st.layout("Snip.Treeview", [("Treeview.treearea", {"sticky": "nswe"})])

    def _build(self):
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)

        # 上段: 表示の切り替えと件数
        bar = ctk.CTkFrame(self, fg_color="transparent")
        bar.grid(row=0, column=0, sticky="ew", padx=T.S4, pady=(T.S4, T.S2))
        bar.columnconfigure(1, weight=1)
        self.view = W.Choice(bar, self._view_options(), command=lambda _k: self._show_view())
        self.view.grid(row=0, column=0, sticky="w")
        self.count_lbl = W.caption(bar)
        self.count_lbl.grid(row=0, column=1, sticky="e", padx=(0, T.S4))
        self.dirty_lbl = W.label(bar, "", "label", T.PENCIL)
        self.dirty_lbl.grid(row=0, column=2, sticky="e")

        # 中段: 編集ビューとプレビュー（重ねて切り替える）
        self.body = ctk.CTkFrame(self, fg_color="transparent")
        self.body.grid(row=1, column=0, sticky="nsew", padx=T.S4)
        self.body.columnconfigure(0, weight=1)
        self.body.rowconfigure(0, weight=1)
        self._build_edit_view()
        self._build_preview_view()

        # 下段: 保存まわり
        foot = ctk.CTkFrame(self, fg_color="transparent")
        foot.grid(row=2, column=0, sticky="ew", padx=T.S4, pady=T.S4)
        foot.columnconfigure(1, weight=1)
        self.ts_var = tk.BooleanVar(value=True)
        self.ts_switch = W.switch(foot, self.t("ed_timestamps"), self.ts_var, command=self._show_view)
        self.ts_switch.grid(row=0, column=0, sticky="w")
        self.status = W.caption(foot)
        self.status.grid(row=0, column=1, sticky="w", padx=T.S4)
        self.btn_open = W.Btn(foot, self.t("ed_open"), self.open_srt)
        self.btn_open.grid(row=0, column=2, padx=(0, T.S2))
        self.btn_copy = W.Btn(foot, self.t("ed_copy"), self.copy)
        self.btn_copy.grid(row=0, column=3, padx=(0, T.S2))
        self.btn_save_as = W.Btn(foot, self.t("ed_save_as"), self.save_as)
        self.btn_save_as.grid(row=0, column=4, padx=(0, T.S2))
        self.btn_save = W.Btn(foot, self.t("ed_save"), self.save, kind="primary", width=120)
        self.btn_save.grid(row=0, column=5)

    def _view_options(self) -> dict:
        return {"edit": self.t("ed_view_edit"), "txt": ".txt", "md": ".md", "srt": ".srt"}

    def _build_edit_view(self):
        self.edit_view = ctk.CTkFrame(self.body, fg_color="transparent")
        self.edit_view.grid(row=0, column=0, sticky="nsew")
        self.edit_view.columnconfigure(0, weight=1)
        self.edit_view.rowconfigure(0, weight=1)

        # 表
        well = ctk.CTkFrame(self.edit_view, fg_color=T.WELL, corner_radius=T.R_PANEL)
        well.grid(row=0, column=0, sticky="nsew")
        well.columnconfigure(0, weight=1)
        well.rowconfigure(0, weight=1)
        self.tree = ttk.Treeview(well, columns=("time", "speaker", "text"), show="headings",
                                 style="Snip.Treeview", selectmode="browse")
        self.tree.grid(row=0, column=0, sticky="nsew", padx=(T.S2, 0), pady=T.S2)
        sb = ctk.CTkScrollbar(well, command=self.tree.yview, fg_color=T.WELL, button_color=T.EDGE,
                              button_hover_color=T.RAISED)
        sb.grid(row=0, column=1, sticky="ns", padx=(0, T.S1), pady=T.S2)
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.column("time", width=100, stretch=False, anchor="w")
        self.tree.column("speaker", width=96, stretch=False, anchor="w")
        self.tree.column("text", width=500, stretch=True, anchor="w")
        for i in range(len(T.SPEAKERS)):
            self.tree.tag_configure(f"s{i}", background=T.blend(T.SPEAKERS[i], T.WELL, 0.13))
        self.tree.tag_configure("changed", foreground=T.PENCIL)
        self.tree.bind("<<TreeviewSelect>>", lambda _e: self._on_select())

        # 空の状態（字幕が無いとき表の上に出す）
        self.empty = ctk.CTkFrame(well, fg_color=T.WELL, corner_radius=0)
        W.label(self.empty, self.t("ed_empty"), "body", T.DUST).pack(pady=(60, T.S3))
        W.Btn(self.empty, self.t("ed_open"), self.open_srt).pack()
        self._empty_label = self.empty.winfo_children()[0]
        self._empty_btn = self.empty.winfo_children()[1]

        # 選んだ1件の編集欄
        self.detail = ctk.CTkFrame(self.edit_view, fg_color=T.PANEL, corner_radius=T.R_PANEL)
        self.detail.grid(row=1, column=0, sticky="ew", pady=(T.S3, 0))
        self.detail.columnconfigure(0, weight=1)
        head = ctk.CTkFrame(self.detail, fg_color="transparent")
        head.grid(row=0, column=0, sticky="ew", padx=T.S4, pady=(T.S3, T.S1))
        head.columnconfigure(1, weight=1)
        self.detail_title = W.label(head, self.t("ed_detail"), "label")
        self.detail_title.grid(row=0, column=0, sticky="w")
        self.detail_time = W.label(head, "", "mono", T.DUST)
        self.detail_time.grid(row=0, column=1, sticky="w", padx=T.S4)
        self.time_note = W.caption(head, self.t("ed_time_note"))
        self.time_note.grid(row=0, column=2, sticky="e")
        self.text = ctk.CTkTextbox(self.detail, height=86, wrap="word", undo=True, corner_radius=T.R_CONTROL,
                                   fg_color=T.WELL, text_color=T.CHALK, border_width=1, border_color=T.EDGE,
                                   font=T.font(ctk, "body"))
        self.text.grid(row=1, column=0, sticky="ew", padx=T.S4, pady=(T.S1, T.S2))
        self.text._textbox.bind("<<Modified>>", self._on_text_modified)
        self.text._textbox.bind("<FocusIn>", lambda _e: self.text.configure(border_color=T.PENCIL))
        self.text._textbox.bind("<FocusOut>", lambda _e: self.text.configure(border_color=T.EDGE))
        tools = ctk.CTkFrame(self.detail, fg_color="transparent")
        tools.grid(row=2, column=0, sticky="ew", padx=T.S4, pady=(0, T.S3))
        self.speaker_lbl = W.caption(tools, self.t("ed_speaker"))
        self.speaker_lbl.pack(side="left", padx=(0, T.S2))
        self.speaker_var = tk.StringVar()
        self.speaker_menu = W.menu(tools, [""], command=self._on_speaker, width=120, variable=self.speaker_var)
        self.speaker_menu.pack(side="left", padx=(0, T.S4))
        self.btn_revert = W.Btn(tools, self.t("ed_revert"), self.revert)
        self.btn_split = W.Btn(tools, self.t("ed_split"), self.split)
        self.btn_merge = W.Btn(tools, self.t("ed_merge"), self.merge)
        self.btn_delete = W.Btn(tools, self.t("ed_delete"), self.delete, kind="danger", width=72)
        for b in (self.btn_revert, self.btn_split, self.btn_merge):
            b.pack(side="left", padx=(0, T.S2))
        self.btn_delete.pack(side="right")

    def _build_preview_view(self):
        self.preview_view = ctk.CTkFrame(self.body, fg_color="transparent")
        self.preview_view.grid(row=0, column=0, sticky="nsew")
        self.preview_view.columnconfigure(0, weight=1)
        self.preview_view.rowconfigure(1, weight=1)
        self.preview_note = W.caption(self.preview_view, self.t("ed_preview_note"))
        self.preview_note.grid(row=0, column=0, sticky="w", pady=(0, T.S2))
        self.preview = ctk.CTkTextbox(self.preview_view, wrap="word", corner_radius=T.R_PANEL, fg_color=T.WELL,
                                      text_color=T.CHALK, font=T.font(ctk, "mono"), border_width=0)
        self.preview.grid(row=1, column=0, sticky="nsew")

    # ── 表示 ───────────────────────────────────────────────────────────────────────
    def _refresh_all(self, select: int | None = None):
        self._fill_tree()
        self._update_chrome()
        n = len(self.editor)
        if n:
            self.empty.place_forget()
            idx = min(max(select if select is not None else 0, 0), n - 1)
            self.tree.selection_set(str(idx))
            self.tree.see(str(idx))
            self._on_select()
        else:
            self.empty.place(relx=0, rely=0, relwidth=1, relheight=1)
            self._sel = None
            self._load_detail()
        self._show_view()

    def _fill_tree(self):
        self.tree.delete(*self.tree.get_children())
        for i in range(len(self.editor)):
            self.tree.insert("", "end", iid=str(i), values=self._row(i), tags=self._tags(i))
        self.tree.heading("time", text=self.t("ed_col_time"), anchor="w")
        self.tree.heading("speaker", text=self.t("ed_col_speaker"), anchor="w")
        self.tree.heading("text", text=self.t("ed_col_text"), anchor="w")

    def _row(self, i: int):
        c = self.editor.cue(i)
        spk = self.t("ed_speaker_n", c.speaker + 1) if c.speaker is not None else ""
        return (_hms(c.start), spk, c.text.replace("\n", " "))

    def _tags(self, i: int):
        c = self.editor.cue(i)
        tags = []
        if c.speaker is not None:
            tags.append(f"s{c.speaker % len(T.SPEAKERS)}")
        if self.editor.is_changed(i):
            tags.append("changed")
        return tuple(tags)

    def _update_chrome(self):
        self.count_lbl.configure(text=self.t("ed_count", len(self.editor)))
        dirty = self.editor.dirty
        self.dirty_lbl.configure(text=self.t("ed_dirty") if dirty else "")
        name = f" — {self.stem}" if self.stem else ""
        self.title(f"{'● ' if dirty else ''}{self.t('ed_title')}{name}")
        self.btn_save.enable(bool(len(self.editor)))
        self.btn_save_as.enable(bool(len(self.editor)))
        self.btn_copy.enable(bool(len(self.editor)))

    def _show_view(self):
        key = self.view.get_key()
        editing = key == "edit"
        if editing:
            self.edit_view.tkraise()
            self.ts_switch.configure(state="disabled")
        else:
            self.preview_view.tkraise()
            self.ts_switch.configure(state="normal" if key in ("txt", "md") else "disabled")
            text = render(self.editor.cues, key, timestamps=self.ts_var.get(), line_chars=self.app.line_chars(),
                          ui_lang=self.app.lang, title=self.stem) if len(self.editor) else self.t("ed_empty")
            self.preview.configure(state="normal")
            self.preview.delete("1.0", "end")
            self.preview.insert("1.0", text)
            self.preview.configure(state="disabled")

    def flash(self, message: str):
        self.status.configure(text=message)
        if self._status_after:
            self.after_cancel(self._status_after)
        self._status_after = self.after(5000, lambda: self.status.configure(text=""))

    # ── 選択と編集 ──────────────────────────────────────────────────────────────────
    def _on_select(self):
        sel = self.tree.selection()
        self._sel = int(sel[0]) if sel else None
        self._load_detail()

    def _speaker_values(self) -> list[str]:
        top = max([MAX_SPEAKERS, *(s + 1 for s in self.editor.speakers())])
        return [self.t("ed_speaker_none")] + [self.t("ed_speaker_n", i + 1) for i in range(top)]

    def _load_detail(self):
        self._loading = True
        has = self._sel is not None
        self.text.configure(state="normal" if has else "disabled")
        self.text.delete("1.0", "end")
        if has:
            c = self.editor.cue(self._sel)
            self.text.insert("1.0", c.text)
            self.text._textbox.edit_reset()
            self.text._textbox.edit_modified(False)
            self.detail_time.configure(text=f"{_hms(c.start)} – {_hms(c.end)}")
            self.speaker_menu.configure(values=self._speaker_values())
            self.speaker_var.set(self.t("ed_speaker_n", c.speaker + 1) if c.speaker is not None
                                 else self.t("ed_speaker_none"))
        else:
            self.detail_time.configure(text=self.t("ed_detail_none"))
        for b in (self.btn_revert, self.btn_split, self.btn_merge, self.btn_delete):
            b.enable(has)
        self.speaker_menu.configure(state="normal" if has else "disabled")
        if has:
            self.btn_revert.enable(self.editor.is_changed(self._sel))
            self.btn_merge.enable(self._sel < len(self.editor) - 1)
        self._loading = False

    def _on_text_modified(self, _e=None):
        tb = self.text._textbox
        if not tb.edit_modified():
            return
        tb.edit_modified(False)
        if self._loading or self._sel is None:
            return
        if self.editor.set_text(self._sel, tb.get("1.0", "end-1c")):
            self._refresh_row(self._sel)
            self.btn_revert.enable(self.editor.is_changed(self._sel))
            self._update_chrome()

    def _refresh_row(self, i: int):
        self.tree.item(str(i), values=self._row(i), tags=self._tags(i))

    def _on_speaker(self, shown: str):
        if self._sel is None:
            return
        values = self._speaker_values()
        idx = values.index(shown) if shown in values else 0
        if self.editor.set_speaker(self._sel, None if idx == 0 else idx - 1):
            self._refresh_row(self._sel)
            self._update_chrome()

    def revert(self):
        if self._sel is not None and self.editor.revert(self._sel):
            self._refresh_row(self._sel)
            self._load_detail()
            self._update_chrome()

    def split(self):
        if self._sel is None:
            return
        offset = len(self.text._textbox.get("1.0", "insert"))
        if self.editor.split(self._sel, offset):
            self._refresh_all(select=self._sel)

    def merge(self):
        if self._sel is not None and self.editor.merge_next(self._sel):
            self._refresh_all(select=self._sel)

    def delete(self):
        if self._sel is not None:
            i = self._sel
            self.editor.delete(i)
            self._refresh_all(select=i)

    # ── 保存・コピー・読み込み ────────────────────────────────────────────────────────
    def _render_args(self) -> dict:
        return dict(timestamps=self.ts_var.get(), line_chars=self.app.line_chars(), ui_lang=self.app.lang)

    def save(self):
        """上書き保存。宛先が決まっていなければ「名前を付けて保存」。"""
        if not len(self.editor):
            return
        if not self.paths:
            return self.save_as()
        written = []
        try:
            for path in self.paths.values():
                save(self.editor.cues, path, **self._render_args())
                written.append(Path(path).name)
        except OSError as exc:
            messagebox.showerror(self.t("err_title"), str(exc), parent=self)
            return
        self.editor.mark_saved()
        self._update_chrome()
        names = ", ".join(written)
        self.flash(self.t("ed_saved", names))

    def save_as(self):
        if not len(self.editor):
            return
        current = self.view.get_key()
        ext = current if current in ("txt", "md", "srt") else "srt"
        types = [(f".{e}", f"*.{e}") for e in ([ext] + [x for x in ("srt", "txt", "md") if x != ext])]
        path = filedialog.asksaveasfilename(parent=self, defaultextension=f".{ext}", filetypes=types,
                                            initialfile=f"{self.stem or 'subtitles'}.{ext}")
        if not path:
            return
        try:
            save(self.editor.cues, path, **self._render_args())
        except OSError as exc:
            messagebox.showerror(self.t("err_title"), str(exc), parent=self)
            return
        self.paths = {format_for_path(path): Path(path)}
        self.stem = Path(path).stem
        self.editor.mark_saved()
        self._update_chrome()
        self.flash(self.t("ed_saved", Path(path).name))

    def copy(self):
        key = self.view.get_key()
        fmt = key if key in ("txt", "md", "srt") else "txt"
        self.clipboard_clear()
        self.clipboard_append(render(self.editor.cues, fmt, title=self.stem, **self._render_args()))
        self.flash(self.t("ed_copied"))

    def open_srt(self):
        if not self._confirm_discard():
            return
        path = filedialog.askopenfilename(parent=self, filetypes=[("SRT", "*.srt"), ("All files", "*.*")])
        if not path:
            return
        try:
            cues = parse_srt(Path(path).read_text(encoding="utf-8-sig"))
        except (OSError, UnicodeDecodeError) as exc:
            messagebox.showerror(self.t("err_title"), str(exc), parent=self)
            return
        self.load(cues, Path(path).stem, {"srt": Path(path)})

    def load(self, cues, title: str = "", paths: dict | None = None):
        self.editor = CueEditor(cues)
        self.stem = title
        self.paths = dict(paths or {})
        self._refresh_all()

    # ── 閉じる ─────────────────────────────────────────────────────────────────────
    def _confirm_discard(self) -> bool:
        """未保存の変更があれば確認する。続けてよければ True。"""
        if not self.editor.dirty:
            return True
        ans = messagebox.askyesnocancel(self.t("ed_close_title"), self.t("ed_close_ask"), parent=self)
        if ans is None:
            return False
        if ans:
            self.save()
            return not self.editor.dirty
        return True

    def _close(self):
        if self._confirm_discard():
            self.destroy()

    # ── 言語の切り替え ──────────────────────────────────────────────────────────────
    def relabel(self):
        self.view.relabel(self._view_options())
        self.ts_switch.configure(text=self.t("ed_timestamps"))
        for btn, key in ((self.btn_open, "ed_open"), (self.btn_copy, "ed_copy"), (self.btn_save_as, "ed_save_as"),
                         (self.btn_save, "ed_save"), (self.btn_revert, "ed_revert"), (self.btn_split, "ed_split"),
                         (self.btn_merge, "ed_merge"), (self.btn_delete, "ed_delete")):
            btn.configure(text=self.t(key))
        self.detail_title.configure(text=self.t("ed_detail"))
        self.time_note.configure(text=self.t("ed_time_note"))
        self.speaker_lbl.configure(text=self.t("ed_speaker"))
        self.preview_note.configure(text=self.t("ed_preview_note"))
        self._empty_label.configure(text=self.t("ed_empty"))
        self._empty_btn.configure(text=self.t("ed_open"))
        sel = self._sel
        self._refresh_all(select=sel)

