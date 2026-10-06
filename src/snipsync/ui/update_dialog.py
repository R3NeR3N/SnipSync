"""更新の確認画面: SnipSync 本体と、取得済みの AI モデルに新しい版があるかを知らせ、許可されたものだけ更新する。"""
import re
import threading
import time
import tkinter as tk
import webbrowser
from dataclasses import dataclass, field

import customtkinter as ctk

from snipsync.core import models, updater
from snipsync.ui import theme as T
from snipsync.ui import widgets as W

NOTES_LIMIT = 1800


@dataclass
class Findings:
    """確認の結果。release / model_updates は、利用者に知らせるもの（通知しないと決めた版を除く）。"""
    release: updater.Release | None = None
    latest: str = ""                                  # 見つかった最新版（新しくなくても入る。確認できなければ空）
    app_error: str = ""
    model_updates: list = field(default_factory=list)
    models_checked: int = 0
    models_failed: int = 0

    @property
    def has_news(self) -> bool:
        return self.release is not None or bool(self.model_updates)


def collect(state: dict, *, manual: bool, fetch=updater.fetch_latest, check_models=models.find_model_updates) -> Findings:
    """本体とモデルの更新を確認する（通信する。画面のスレッドでは呼ばない）。
    manual=False のときは、「通知しない」と決めた版を除く。"""
    out = Findings()
    try:
        latest = fetch()
        out.latest = latest.version
        if updater.is_newer(latest.version) and (manual or state["skip_version"] != latest.version):
            out.release = latest
    except updater.UpdateError as exc:
        out.app_error = str(exc)
    check = check_models()
    out.models_checked, out.models_failed = check.checked, check.failed
    out.model_updates = [m for m in check.updates if manual or state["skip_models"].get(m.key) != m.remote]
    return out


def notes_for(text: str, lang: str) -> str:
    """リリースの説明文を、画面に出せる形にする。「## 日本語」「## English」の 2 部構成なら、いまの言語の側だけを取り、
    Markdown の記号（見出し・強調・コード・リンク）を外す。"""
    head, sep, tail = text.partition("## English")
    if sep:
        text = tail if lang == "en" else head.replace("## 日本語", "")
    text = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", text)        # [名前](URL) を、名前だけにする
    text = re.sub(r"^#{1,6}\s*", "", text, flags=re.M)            # 見出しの #
    text = re.sub(r"(\*\*|`)", "", text)                         # 強調・コード
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def mb(n: float) -> str:
    return f"{n / 1_000_000:,.0f}"


class UpdateDialog(ctk.CTkToplevel):
    def __init__(self, app, findings: Findings | None = None):
        """findings を渡すと、その結果を見せる。渡さなければ、開いてすぐ確認する。"""
        super().__init__(app)
        self.app = app
        self.t = app.t
        self.prefs = updater.load_state()
        self.findings = findings
        self.busy = False
        self.stop = False
        self.configure(fg_color=T.BENCH)
        T.apply_icon(self)
        self.title(self.t("upd_title"))
        self.geometry("660x600")
        self.minsize(560, 480)
        self.transient(app)
        self.protocol("WM_DELETE_WINDOW", self._close)
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)
        self.body = ctk.CTkScrollableFrame(self, fg_color="transparent")
        self.body.grid(row=0, column=0, sticky="nsew", padx=T.S4, pady=(T.S4, 0))
        self.body.columnconfigure(0, weight=1)
        self._build_footer()
        self.after(50, self.lift)
        if findings is None:
            self.check_now()
        else:
            self._render()

    # ── 構築 ───────────────────────────────────────────────────────────────────────
    def _build_footer(self):
        foot = ctk.CTkFrame(self, fg_color="transparent")
        foot.grid(row=1, column=0, sticky="ew", padx=T.S4, pady=T.S4)
        foot.columnconfigure(0, weight=1)
        self.status = W.caption(foot, wraplength=600)
        self.status.grid(row=0, column=0, columnspan=4, sticky="w")
        self.bar = ctk.CTkProgressBar(foot, mode="determinate", height=8, corner_radius=4, fg_color=T.EDGE,
                                      progress_color=T.PENCIL)
        self.bar.grid(row=1, column=0, columnspan=4, sticky="ew", pady=(T.S2, T.S3))
        self.bar.grid_remove()
        self.auto_var = tk.BooleanVar(value=bool(self.prefs["check_enabled"]))
        self.auto_switch = W.switch(foot, self.t("upd_auto"), self.auto_var, command=self._on_auto)
        self.auto_switch.grid(row=2, column=0, sticky="w")
        W.tip(self.auto_switch, lambda: self.t("tip_upd_auto"))
        self.btn_stop = W.Btn(foot, self.t("upd_stop"), self._on_stop, kind="danger", width=72)
        self.btn_stop.grid(row=2, column=1, padx=(0, T.S2))
        self.btn_stop.grid_remove()
        self.btn_check = W.Btn(foot, self.t("upd_check_now"), self.check_now)
        self.btn_check.grid(row=2, column=2, padx=(0, T.S2))
        self.btn_close = W.Btn(foot, self.t("upd_close"), self._close)
        self.btn_close.grid(row=2, column=3)

    def _clear_body(self):
        for w in self.body.winfo_children():
            w.destroy()

    def _section(self, row: int, title: str) -> ctk.CTkFrame:
        box = ctk.CTkFrame(self.body, fg_color=T.PANEL, corner_radius=T.R_PANEL)
        box.grid(row=row, column=0, sticky="ew", pady=(0, T.S3))
        box.columnconfigure(0, weight=1)
        W.label(box, title, "label").grid(row=0, column=0, sticky="w", padx=T.S4, pady=(T.S3, T.S1))
        return box

    def _render(self):
        self._clear_body()
        f = self.findings
        if f is None:
            return
        self._render_app(self._section(0, self.t("upd_app_head")), f)
        self._render_models(self._section(1, self.t("upd_models_head")), f)
        self._set_busy(self.busy)

    def _render_app(self, box, f: Findings):
        if f.release is None:
            key = ("upd_app_error", f.app_error) if f.app_error else ("upd_uptodate", updater.APP_VERSION)
            W.caption(box, self.t(*key), wraplength=560).grid(row=1, column=0, sticky="w", padx=T.S4, pady=(0, T.S3))
            return
        r = f.release
        head = (self.t("upd_available_sized", r.version, updater.APP_VERSION, mb(r.size)) if r.size
                else self.t("upd_available", r.version, updater.APP_VERSION))
        W.label(box, head, "body").grid(row=1, column=0, sticky="w", padx=T.S4)
        notes = ctk.CTkTextbox(box, height=150, wrap="word", corner_radius=T.R_CONTROL, fg_color=T.WELL,
                               text_color=T.CHALK, font=T.font(ctk, "body"), border_width=0)
        text = notes_for(r.notes, self.app.lang)
        notes.insert("1.0", (text[:NOTES_LIMIT] + "…") if len(text) > NOTES_LIMIT else text or r.tag)
        notes.configure(state="disabled")
        notes.grid(row=2, column=0, sticky="ew", padx=T.S4, pady=(T.S2, T.S2))
        row = ctk.CTkFrame(box, fg_color="transparent")
        row.grid(row=3, column=0, sticky="ew", padx=T.S4, pady=(0, T.S3))
        if updater.can_install(r):
            self.btn_install = W.Btn(row, self.t("upd_install"), self._install, kind="primary")
            self.btn_install.pack(side="left", padx=(0, T.S2))
        else:
            self.btn_install = None
            W.Btn(row, self.t("upd_open_page"), lambda: webbrowser.open(r.page_url), kind="primary").pack(
                side="left", padx=(0, T.S2))
            W.caption(box, self.t("upd_manual_note"), wraplength=560).grid(
                row=4, column=0, sticky="w", padx=T.S4, pady=(0, T.S3))
        self.btn_skip_app = W.Btn(row, self.t("upd_skip"), self._skip_app, kind="ghost")
        self.btn_skip_app.pack(side="left")

    def _render_models(self, box, f: Findings):
        self._model_buttons = []
        if not f.model_updates:
            if f.models_failed:
                text = self.t("upd_models_partial")
            elif f.models_checked:
                text = self.t("upd_models_latest")
            else:
                text = self.t("upd_models_none")
            W.caption(box, text, wraplength=560).grid(row=1, column=0, sticky="w", padx=T.S4, pady=(0, T.S3))
            return
        for i, m in enumerate(f.model_updates, start=1):
            row = ctk.CTkFrame(box, fg_color="transparent")
            row.grid(row=i, column=0, sticky="ew", padx=T.S4, pady=(0, T.S2))
            row.columnconfigure(0, weight=1)
            detail = self.t("upd_model_size", mb(m.size)) if m.size else ""
            W.label(row, f"{m.key}  {detail}".strip(), "body").grid(row=0, column=0, sticky="w")
            b1 = W.Btn(row, self.t("upd_model_update"), lambda m=m: self._update_model(m), height=30)
            b1.grid(row=0, column=1, padx=(T.S2, T.S2))
            b2 = W.Btn(row, self.t("upd_skip_short"), lambda m=m: self._skip_model(m), kind="ghost", height=30)
            b2.grid(row=0, column=2)
            self._model_buttons += [b1, b2]
        W.caption(box, self.t("upd_model_note"), wraplength=560).grid(
            row=len(f.model_updates) + 1, column=0, sticky="w", padx=T.S4, pady=(0, T.S3))

    # ── 状態 ───────────────────────────────────────────────────────────────────────
    def _alive(self) -> bool:
        try:
            return bool(self.winfo_exists())
        except tk.TclError:
            return False

    def _post(self, fn):
        """作業スレッドから画面を触るときは、必ずここを通す（画面が閉じられていたら何もしない）。"""
        try:
            self.after(0, lambda: fn() if self._alive() else None)
        except (tk.TclError, RuntimeError):
            pass

    def _set_status(self, text: str):
        self.status.configure(text=text)

    def _set_busy(self, busy: bool):
        self.busy = busy
        self.btn_check.enable(not busy)
        self.auto_switch.configure(state="disabled" if busy else "normal")
        for b in (getattr(self, "btn_install", None), getattr(self, "btn_skip_app", None),
                  *getattr(self, "_model_buttons", [])):
            if b is not None and b.winfo_exists():
                b.enable(not busy)
        if busy and self.btn_stop.winfo_manager() == "":
            self.btn_stop.grid()
        elif not busy:
            self.btn_stop.grid_remove()
            self.bar.grid_remove()

    def _progress(self, done, total):
        def show():
            if done is None:
                self.bar.grid_remove()
                return
            self.bar.grid()
            self.bar.set(min(1.0, done / total) if total else 0)
            self._set_status(self.t("upd_downloading", mb(done), mb(total) if total else "?"))
        self._post(show)

    def _on_stop(self):
        self.stop = True
        self.btn_stop.enable(False)

    def _on_auto(self):
        self.prefs["check_enabled"] = bool(self.auto_var.get())
        updater.save_state(self.prefs)

    def _close(self):
        if self.busy:                    # 取得の途中で閉じない（止めるなら「停止」）
            return
        self.destroy()

    # ── 確認 ───────────────────────────────────────────────────────────────────────
    def check_now(self):
        if self.busy:
            return
        self._set_busy(True)
        self.btn_stop.grid_remove()
        self._set_status(self.t("upd_checking"))

        def work():
            found = collect(self.prefs, manual=True)
            self._post(lambda: self._checked(found))

        threading.Thread(target=work, daemon=True).start()

    def _checked(self, found: Findings):
        self.findings = found
        self.prefs["last_check"] = time.time()
        updater.save_state(self.prefs)
        self._set_busy(False)
        self._set_status("")
        self._render()

    # ── 本体の更新 ─────────────────────────────────────────────────────────────────
    def _skip_app(self):
        self.prefs["skip_version"] = self.findings.release.version
        updater.save_state(self.prefs)
        self.destroy()

    def _install(self):
        if self.app.running:
            self._set_status(self.t("upd_busy_running"))
            return
        release = self.findings.release
        dest = updater.new_exe_path()
        self.stop = False
        self._set_busy(True)
        self.btn_stop.enable(True)
        self._set_status(self.t("upd_downloading", "0", mb(release.size)))

        def work():
            try:
                updater.download(release, dest, on_progress=self._progress, should_stop=lambda: self.stop)
            except updater.UpdateCancelled:
                self._post(lambda: self._failed(self.t("upd_stopped")))
            except updater.UpdateError as exc:
                self._post(lambda e=str(exc): self._failed(self.t("upd_failed", e)))
            else:
                self._post(lambda: self._installed(dest))

        threading.Thread(target=work, daemon=True).start()

    def _failed(self, message: str):
        self._set_busy(False)
        self._set_status(message)
        updater.new_exe_path().unlink(missing_ok=True)

    def _installed(self, new_exe):
        """取得と照合が済んだ。未保存の字幕の確認を済ませてから入れ替え、再起動する。"""
        if not self.app.confirm_close_editors():
            self._failed(self.t("upd_stopped"))
            return
        self._set_status(self.t("upd_installing"))
        try:
            updater.swap_and_relaunch(new_exe)
        except updater.UpdateError as exc:
            self._failed(self.t("upd_failed", str(exc)))
            return
        self.app.exit_now()

    # ── モデルの更新 ───────────────────────────────────────────────────────────────
    def _skip_model(self, m: models.ModelUpdate):
        self.prefs["skip_models"][m.key] = m.remote
        updater.save_state(self.prefs)
        self.findings.model_updates = [x for x in self.findings.model_updates if x.key != m.key]
        self._render()

    def _update_model(self, m: models.ModelUpdate):
        if self.app.running:
            self._set_status(self.t("upd_busy_running"))
            return
        self.stop = False
        self._set_busy(True)
        self.btn_stop.enable(True)
        self._set_status(self.t("upd_downloading", "0", mb(m.size) if m.size else "?"))

        def work():
            try:
                models.download_model(m.key, on_progress=self._progress, should_stop=lambda: self.stop)
            except models.DownloadCancelled:
                self._post(lambda: self._model_failed(self.t("upd_stopped")))
            except models.DownloadFailed as exc:
                self._post(lambda e=str(exc): self._model_failed(self.t("upd_failed", e)))
            else:
                self._post(lambda: self._model_done(m))

        threading.Thread(target=work, daemon=True).start()

    def _model_failed(self, message: str):
        self._set_busy(False)
        self._set_status(message)

    def _model_done(self, m: models.ModelUpdate):
        self.findings.model_updates = [x for x in self.findings.model_updates if x.key != m.key]
        self.findings.models_checked = max(1, self.findings.models_checked)
        self._set_busy(False)
        self._render()
        self._set_status(self.t("upd_model_done", m.key))
