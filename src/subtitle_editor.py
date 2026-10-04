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
    def __init__(self, app, cues=(), title: str = "", paths: dict | None = None, *, pending: bool = False,
                 on_closed=None):
        """pending=True: 字幕ファイルはまだ無い（処理は保存前で止まっている）。最初の保存で paths へ書く。
        on_closed(cues, saved, paths, info): 閉じたときに、編集後の字幕・保存したか・保存先を受け取る。
        info["saved_cues"] / info["names"] は、最後に保存した時点の字幕と話者名（保存していなければ None / {}）。"""
        super().__init__(app)
        self.app = app
        self.t = app.t
        self.editor = CueEditor(cues)
        self.stem = title
        self.paths: dict[str, Path] = dict(paths or {})     # 保存先（形式 -> パス）
        self.pending = pending
        self.saved = False
        self.saved_cues = None                              # 最後に保存した時点の字幕（ファイルの中身と同じ）
        self.saved_names: dict = {}
        self._on_closed = on_closed
        self._sel: int | None = None          # 1件だけ選んでいるときの番号
        self._sels: list[int] = []            # 選んでいる件（複数のことがある）
        self._loading = False
        self._status_after = None
        self.configure(fg_color=T.BENCH)
        T.apply_icon(self)
        self.geometry("980x720")
        self.minsize(820, 580)
        self.protocol("WM_DELETE_WINDOW", self._close)
        self._style_tree()
        self._build()
        self._help = None
        self._bind_keys()
        self._attach_tips()
        self._refresh_all()
        if self.pending and self.paths:
            self.status.configure(text=self.t("ed_dest", ", ".join(p.name for p in self.paths.values())))
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
        self.dirty_lbl.grid(row=0, column=2, sticky="e", padx=(0, T.S4))
        self.btn_undo = W.Btn(bar, self.t("ed_undo"), self.undo, height=30)
        self.btn_undo.grid(row=0, column=3, padx=(0, T.S2))
        self.btn_redo = W.Btn(bar, self.t("ed_redo"), self.redo, height=30)
        self.btn_redo.grid(row=0, column=4, padx=(0, T.S2))
        self.btn_keys = W.Btn(bar, self.t("ed_keys"), self.toggle_help, kind="ghost", height=30)
        self.btn_keys.grid(row=0, column=5)

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
        opts = ctk.CTkFrame(foot, fg_color="transparent")
        opts.grid(row=0, column=0, sticky="w")
        self.ts_var = tk.BooleanVar(value=True)
        self.ts_switch = W.switch(opts, self.t("ed_timestamps"), self.ts_var, command=self._show_view)
        self.ts_switch.grid(row=0, column=0, sticky="w")
        self.sp_var = tk.BooleanVar(value=bool(getattr(self.app, "speaker_labels", True)))   # 既定は、処理の設定どおり
        self.sp_switch = W.switch(opts, self.t("ed_speaker_names"), self.sp_var, command=self._show_view)
        self.sp_switch.grid(row=0, column=1, sticky="w", padx=(T.S4, 0))
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
        self.close_note = None
        if self._on_closed is not None:         # 処理が、この画面を閉じるのを待っている
            self.close_note = W.caption(foot, self.t("ed_close_note"), wraplength=900)
            self.close_note.grid(row=1, column=0, columnspan=6, sticky="w", pady=(T.S2, 0))

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
                                 style="Snip.Treeview", selectmode="extended")
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
        self.text = ctk.CTkTextbox(self.detail, height=86, wrap="word", undo=False, corner_radius=T.R_CONTROL,
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
        self.speaker_menu.pack(side="left", padx=(0, T.S2))
        self.name_lbl = W.caption(tools, self.t("ed_name"))
        self.name_lbl.pack(side="left", padx=(0, T.S2))
        self.name_var = tk.StringVar()
        self.name_entry = W.entry(tools, self.name_var, width=110, placeholder=self.t("ed_name_placeholder"))
        self.name_entry.pack(side="left", padx=(0, T.S4))
        self.name_entry.bind("<Return>", lambda _e: self._on_rename())
        self.name_entry.bind("<FocusOut>", lambda _e: self._on_rename())
        self.btn_revert = W.Btn(tools, self.t("ed_revert"), self.revert)
        self.btn_split = W.Btn(tools, self.t("ed_split"), self.split)
        self.btn_merge = W.Btn(tools, self.t("ed_merge"), self.merge)
        self.btn_delete = W.Btn(tools, self.t("ed_delete"), self.delete, kind="danger", width=72)
        for b in (self.btn_revert, self.btn_split, self.btn_merge):
            b.pack(side="left", padx=(0, T.S2))
        self.btn_delete.pack(side="right")
        self.split_hint = W.caption(self.detail, self.t("ed_split_hint"))
        self.split_hint.grid(row=3, column=0, sticky="w", padx=T.S4, pady=(0, T.S3))

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
            self._on_select(force=True)
        else:
            self.empty.place(relx=0, rely=0, relwidth=1, relheight=1)
            self._sel, self._sels = None, []
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
        return (_hms(c.start), self._speaker_name(c.speaker), c.text.replace("\n", " "))

    def _speaker_name(self, speaker) -> str:
        if speaker is None:
            return ""
        return self.editor.speaker_name(speaker, self.t("ed_speaker_n", speaker + 1))

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
        unsaved = dirty or self.pending
        self.dirty_lbl.configure(text=self.t("ed_pending") if self.pending else (self.t("ed_dirty") if dirty else ""))
        name = f" — {self.stem}" if self.stem else ""
        self.title(f"{'● ' if unsaved else ''}{self.t('ed_title')}{name}")
        self.btn_undo.enable(self.editor.can_undo)
        self.btn_redo.enable(self.editor.can_redo)
        self.btn_save.enable(bool(len(self.editor)))
        self.btn_save_as.enable(bool(len(self.editor)))
        self.btn_copy.enable(bool(len(self.editor)))
        self.sp_switch.configure(state="normal" if self.editor.speakers() else "disabled")   # 話者が無ければ、効くものが無い

    def _show_view(self):
        key = self.view.get_key()
        editing = key == "edit"
        if editing:
            self.edit_view.tkraise()
            self.ts_switch.configure(state="disabled")
        else:
            self.preview_view.tkraise()
            self.ts_switch.configure(state="normal" if key in ("txt", "md") else "disabled")
            text = render(self.editor.cues, key, title=self.stem,
                          **self._render_args()) if len(self.editor) else self.t("ed_empty")
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
    def _on_select(self, force=False):
        sels = sorted(int(i) for i in self.tree.selection())
        if sels == self._sels and not force:
            return          # 同じ選択の通知（プログラムで選んだあとに遅れて届く分）で、編集欄を読み直さない（カーソルが飛ぶ）
        self.editor.end_typing()                       # 別の字幕へ移ったら、文字入力のまとまりはここで区切る
        self._sels = sels
        self._sel = self._sels[0] if len(self._sels) == 1 else None
        self._load_detail()

    def _speaker_values(self) -> list[str]:
        top = max([MAX_SPEAKERS, *(sp + 1 for sp in self.editor.speakers())])
        return [self.t("ed_speaker_none")] + [self._speaker_name(i) for i in range(top)]

    def _shared_speaker(self):
        """選んでいる字幕の話者が全部同じならその番号。違う・話者なしなら None。"""
        found = {self.editor.cue(i).speaker for i in self._sels}
        return found.pop() if len(found) == 1 else None

    def _load_detail(self):
        self._loading = True
        n = len(self._sels)
        single = self._sel is not None
        self.text.configure(state="normal" if single else "disabled")
        self.text.delete("1.0", "end")
        if single:
            c = self.editor.cue(self._sel)
            self.text.insert("1.0", c.text)
            self.text._textbox.edit_reset()
            self.text._textbox.edit_modified(False)
            self.detail_title.configure(text=self.t("ed_detail"))
            self.detail_time.configure(text=f"{_hms(c.start)} – {_hms(c.end)}")
        elif n > 1:
            self.detail_title.configure(text=self.t("ed_detail_multi", n))
            self.detail_time.configure(text=self.t("ed_multi_note"))
        else:
            self.detail_title.configure(text=self.t("ed_detail"))
            self.detail_time.configure(text=self.t("ed_detail_none"))
        values = self._speaker_values()
        self.speaker_menu.configure(values=values, state="normal" if n else "disabled")
        shared = self._shared_speaker() if n else None
        if n and len({self.editor.cue(i).speaker for i in self._sels}) > 1:
            self.speaker_var.set(self.t("ed_speaker_mixed"))
        elif n:
            self.speaker_var.set(values[0 if shared is None else shared + 1])
        self._load_name()
        for b in (self.btn_split, self.btn_merge):
            b.enable(single)
        self.btn_delete.enable(single)
        self.btn_revert.enable(single and self.editor.is_changed(self._sel))
        if single:
            self.btn_merge.enable(self._sel < len(self.editor) - 1)
        self._loading = False

    def _load_name(self):
        """話者名の欄: 選んだ字幕の話者が1人なら、その人の名前（未設定なら空で「話者N」を薄く出す）。"""
        spk = self._shared_speaker() if self._sels else None
        usable = spk is not None
        self.name_entry.configure(state="normal" if usable else "disabled",
                                  placeholder_text=self._speaker_name(spk) if usable else self.t("ed_name_placeholder"))
        self.name_var.set(self.editor.names.get(spk, "") if usable else "")
        try:                                   # 入力欄が空のとき、薄い「話者N」を出し直す（CTkEntry は設定だけでは描き直さない）
            self.name_entry._deactivate_placeholder()
            self.name_entry._activate_placeholder()
        except Exception:
            pass

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

    def _refresh_rows(self):
        for i in range(len(self.editor)):
            self._refresh_row(i)

    def _on_speaker(self, shown: str):
        if not self._sels:
            return
        values = self._speaker_values()
        idx = values.index(shown) if shown in values else 0
        if self.editor.set_speakers(self._sels, None if idx == 0 else idx - 1):
            self._refresh_rows()
            self._load_detail()
            self._update_chrome()

    def _on_rename(self):
        """話者名の欄の確定。その話者のすべての字幕の表示と、書き出しの名前が変わる。"""
        if self._loading or not self._sels:
            return
        spk = self._shared_speaker()
        if spk is None:
            return
        if self.editor.rename_speaker(spk, self.name_var.get()):
            self._refresh_rows()
            self._load_detail()
            self._update_chrome()
            self._show_view()

    def revert(self):
        """この字幕を取り込んだときの状態へ。結合・分割したものは、元の字幕に戻る（件数が変わる）。"""
        if self._sel is not None and self.editor.revert(self._sel):
            self._refresh_all(select=self._sel)

    def undo(self):
        if self.editor.undo():
            self._after_history()

    def redo(self):
        if self.editor.redo():
            self._after_history()

    def _after_history(self):
        keep = self._sels[0] if self._sels else None
        self._refresh_all(select=keep)

    def split(self):
        """カーソル位置で2件に分け、あとの方を選ぶ（続けて、その先で分けられる）。"""
        if self._sel is None:
            return
        offset = len(self.text._textbox.get("1.0", "insert"))
        if self.editor.split(self._sel, offset):
            self._refresh_all(select=self._sel + 1)
            self._focus_text("start")

    def merge(self):
        """次の字幕と結合し、つなぎ目にカーソルを置く（続けて、さらに次と結合できる）。"""
        if self._sel is not None:
            joint = len(self.editor.cue(self._sel).text)
            if self.editor.merge_next(self._sel):
                self._refresh_all(select=self._sel)
                self._focus_text(joint)

    def delete(self):
        if self._sel is not None:
            i = self._sel
            self.editor.delete(i)
            self._refresh_all(select=i)
            self._focus_text("start")

    def _focus_text(self, at="end"):
        """本文の欄にフォーカスを置き、カーソルを位置 at（"start" / "end" / 文字数）に置く。"""
        if self._sel is None:
            return
        tb = self.text._textbox
        tb.focus_set()
        tb.mark_set("insert", "1.0" if at == "start" else ("end-1c" if at == "end" else f"1.0+{at}c"))
        tb.see("insert")

    # ── キー操作 ───────────────────────────────────────────────────────────────────
    def _move_row(self, delta: int):
        n = len(self.editor)
        if not n:
            return
        base = self._sels[0] if self._sels else -1
        idx = min(max(base + delta, 0), n - 1)
        self.tree.selection_set(str(idx))
        self.tree.see(str(idx))
        self._on_select()
        self._focus_text("end")

    def _set_speaker_key(self, number: int):
        """Ctrl+1〜9 で話者 N に、Ctrl+0 でなしにする（選んでいる字幕すべて）。"""
        if self._sels and self.editor.set_speakers(self._sels, None if number == 0 else number - 1):
            self._refresh_rows()
            self._load_detail()
            self._update_chrome()

    def _select_all_rows(self):
        self.tree.selection_set(*self.tree.get_children())
        self._on_select()

    def _bind_keys(self):
        keys = {
            "<Control-Return>": self.split, "<Control-j>": self.merge, "<Control-J>": self.merge,
            "<Control-d>": self.delete, "<Control-D>": self.delete, "<Control-r>": self.revert,
            "<Control-R>": self.revert, "<Alt-Up>": lambda: self._move_row(-1),
            "<Alt-Down>": lambda: self._move_row(1), "<Control-s>": self.save, "<Control-z>": self.undo,
            "<Control-Z>": self.redo, "<Control-y>": self.redo, "<Control-Y>": self.redo,
            "<F1>": self.toggle_help, "<Escape>": self.close_help,
        }
        for n in range(10):
            keys[f"<Control-Key-{n}>"] = (lambda n=n: self._set_speaker_key(n))

        def handler(fn):
            def run(_e=None):
                fn()
                return "break"             # 入力欄の標準の動き（Ctrl+D で1文字消える等）より、こちらを優先する
            return run

        targets = [self, self.text._textbox, self.name_entry, self.tree]
        for seq, fn in keys.items():
            for w in targets:
                tk.Misc.bind(w, seq, handler(fn))
        tk.Misc.bind(self.tree, "<Control-a>", handler(self._select_all_rows))
        tk.Misc.bind(self.tree, "<Control-A>", handler(self._select_all_rows))

    def toggle_help(self):
        self.close_help() if self._help is not None else self._open_help()

    def close_help(self):
        if self._help is not None:
            self._help.destroy()
            self._help = None

    def _open_help(self):
        """ショートカットの一覧を、窓の上に重ねて出す（普段は隠れている）。"""
        rows = [("Ctrl+Enter", "sc_split"), ("Ctrl+J", "sc_merge"), ("Ctrl+D", "sc_delete"),
                ("Ctrl+R", "sc_revert"), ("Alt+\u2191", "sc_prev"), ("Alt+\u2193", "sc_next"),
                ("Ctrl+1 \u2013 9", "sc_speaker"), ("Ctrl+0", "sc_speaker_none"), ("Ctrl+Z", "sc_undo"),
                ("Ctrl+Y", "sc_redo"), ("Ctrl+S", "sc_save"), ("Ctrl+A", "sc_select_all"), ("F1", "sc_help")]
        box = ctk.CTkFrame(self, fg_color=T.PANEL, corner_radius=T.R_PANEL, border_width=1, border_color=T.EDGE)
        W.label(box, self.t("sc_title"), "title").grid(row=0, column=0, columnspan=2, sticky="w",
                                                      padx=T.S6, pady=(T.S4, T.S3))
        for i, (key, text_key) in enumerate(rows, start=1):
            chip = ctk.CTkLabel(box, text=key, font=T.font(ctk, "mono"), text_color=T.CHALK, fg_color=T.WELL,
                                corner_radius=T.R_CONTROL, width=128, height=26)
            chip.grid(row=i, column=0, sticky="w", padx=(T.S6, T.S3), pady=2)
            W.label(box, self.t(text_key), "body").grid(row=i, column=1, sticky="w", padx=(0, T.S6), pady=2)
        W.caption(box, self.t("sc_hint")).grid(row=len(rows) + 1, column=0, columnspan=2, sticky="w",
                                              padx=T.S6, pady=(T.S3, T.S4))
        box.place(relx=0.5, rely=0.5, anchor="center")
        box.lift()
        for w in (box, *box.winfo_children()):
            tk.Misc.bind(w, "<Button-1>", lambda _e: self.close_help())
        self._help = box

    def _attach_tips(self):
        pairs = [
            (self.view, "tip_ed_view"), (self.btn_undo, "tip_ed_undo"), (self.btn_redo, "tip_ed_redo"),
            (self.btn_keys, "tip_ed_keys"), (self.text, "tip_ed_text"), (self.speaker_menu, "tip_ed_speaker"),
            (self.name_entry, "tip_ed_name"), (self.name_lbl, "tip_ed_name"), (self.btn_revert, "tip_ed_revert"),
            (self.btn_split, "tip_ed_split"), (self.btn_merge, "tip_ed_merge"), (self.btn_delete, "tip_ed_delete"),
            (self.ts_switch, "tip_ed_timestamps"), (self.sp_switch, "tip_ed_speaker_names"), (self.btn_open, "tip_ed_open"), (self.btn_copy, "tip_ed_copy"),
            (self.btn_save_as, "tip_ed_save_as"), (self.btn_save, "tip_ed_save"),
        ]
        for widget, key in pairs:
            W.tip(widget, (lambda k=key: self.t(k)))

    # ── 保存・コピー・読み込み ────────────────────────────────────────────────────────
    def _render_args(self) -> dict:
        return dict(timestamps=self.ts_var.get(), line_chars=self.app.line_chars(), ui_lang=self.app.lang,
                    names=self.editor.names, show_speakers=self.sp_var.get())

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
        self._mark_saved()
        names = ", ".join(written)
        self.flash(self.t("ed_saved", names))

    def _mark_saved(self):
        self.editor.mark_saved()
        self.saved_cues, self.saved_names = self.editor.cues, dict(self.editor.names)
        self.pending = False
        self.saved = True
        self._update_chrome()

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
        self._mark_saved()
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
        self.pending = False             # 別の字幕を読み込んだので、保存待ちだった字幕は破棄された
        self._refresh_all()

    # ── 閉じる ─────────────────────────────────────────────────────────────────────
    def _confirm_discard(self) -> bool:
        """未保存の変更があれば確認する。続けてよければ True。"""
        waiting = self.pending and len(self.editor) > 0       # まだ一度も保存しておらず、書くものがある
        if not self.editor.dirty and not waiting:
            return True
        if waiting:
            ans = messagebox.askyesnocancel(self.t("ed_pending_title"), self.t("ed_pending_ask"), parent=self)
        else:
            ans = messagebox.askyesnocancel(self.t("ed_close_title"), self.t("ed_close_ask"), parent=self)
        if ans is None:
            return False
        if ans:
            self.save()
            return not (self.editor.dirty or (self.pending and len(self.editor) > 0))
        return True

    def _close(self):
        if self._confirm_discard():
            callback, self._on_closed = self._on_closed, None
            if callback:
                callback(self.editor.cues, self.saved, dict(self.paths),
                         {"saved_cues": self.saved_cues, "names": dict(self.saved_names)})
            self.destroy()

    # ── 言語の切り替え ──────────────────────────────────────────────────────────────
    def relabel(self):
        self.view.relabel(self._view_options())
        self.ts_switch.configure(text=self.t("ed_timestamps"))
        self.sp_switch.configure(text=self.t("ed_speaker_names"))
        for btn, key in ((self.btn_open, "ed_open"), (self.btn_copy, "ed_copy"), (self.btn_save_as, "ed_save_as"),
                         (self.btn_save, "ed_save"), (self.btn_revert, "ed_revert"), (self.btn_split, "ed_split"),
                         (self.btn_merge, "ed_merge"), (self.btn_delete, "ed_delete"), (self.btn_undo, "ed_undo"),
                         (self.btn_redo, "ed_redo")):
            btn.configure(text=self.t(key))
        self.detail_title.configure(text=self.t("ed_detail"))
        self.time_note.configure(text=self.t("ed_time_note"))
        self.speaker_lbl.configure(text=self.t("ed_speaker"))
        self.split_hint.configure(text=self.t("ed_split_hint"))
        self.name_lbl.configure(text=self.t("ed_name"))
        self.btn_keys.configure(text=self.t("ed_keys"))
        if self.close_note is not None:
            self.close_note.configure(text=self.t("ed_close_note"))
        if self._help is not None:                   # 開いている一覧は、閉じて開き直す
            self.close_help()
            self._open_help()
        self.preview_note.configure(text=self.t("ed_preview_note"))
        self._empty_label.configure(text=self.t("ed_empty"))
        self._empty_btn.configure(text=self.t("ed_open"))
        sel = self._sel
        self._refresh_all(select=sel)

