# 設計書 — P2 課題C: 即時停止対応（Popen + プロセスツリー kill + ログストリーミング）

> 区分: 🧠頭脳(Opus 4.8) 設計 → 🔧作業(Gemini) 実装
> 対象: ROADMAP P2「即時停止対応」/ MEMORY 課題C
> 前提ブランチ: `feat/p1-refactor`（P1 完了・`pipeline.py` 抽出済み）

非開発者向け要約: いまの「停止」ボタンは、**実行中の外部処理が終わるのを待ってから**次の段を
スキップするだけ（途中で本当には止まらない）。これを、停止を押したら**実行中のプロセスを即座に
終了**するよう変える。auto-editor は内部で ffmpeg を呼ぶため、親だけ殺すと ffmpeg が残る。Windows
では**プロセスツリーごと**終了させる必要がある。あわせて、処理ログを**1行ずつ流して表示**（ストリー
ミング）し、長い処理でも「動いている」が見えるようにする。**字幕同期などの既存の挙動・出力は変えない。**

---

## 1. 目的

`pipeline.run_pipeline` の auto-editor 呼び出しを `subprocess.run`（完了までブロック）から
`subprocess.Popen`（ストリーミング）へ変更し、停止要求時に**実行中プロセスを即時終了**する。
これにより MEMORY 課題C（「停止が即時でない」）を解消する。

## 2. 背景 — 現状の停止セマンティクス（変更前）

`pipeline.py` は各 auto-editor 段で `subprocess.run(capture_output=True, ...)` を使う。停止は
`should_stop()` フラグで**次ステージをスキップ**するのみ。実行中の auto-editor / ffmpeg は完走を待つ。
（PITFALLS P-2 の margin/threshold 一致、P-6 の encoding は現状どおり維持する。）

### 現状コードの結合点（変更対象）
| 箇所 | 現状 | 変更後 |
|---|---|---|
| `pipeline.py` ①メインカット | `subprocess.run` 後に `res.stdout.splitlines()` でまとめ出力 | `_run_streaming()` で1行ずつ `on_log` |
| `pipeline.py` ②a 一時WAV抽出 | 同上 | 同上 |
| `app.py` `_stop_process` | フラグ立て + ログのみ | フラグ立て（プロセス kill は pipeline 側が担当）|

## 3. 設計方針

- **kill は pipeline 内に閉じる**: `pipeline` が `Popen` ハンドルを所有し、ストリーミング読取ループ内で
  `should_stop()` を監視→真なら**プロセスツリーを kill**。UI 側 `_stop_process` は従来どおり
  **フラグを立てるだけ**（`Popen` ハンドルを UI へ渡さない＝UI 非依存を維持）。
- **Windows プロセスツリー kill が肝**: auto-editor は ffmpeg を子プロセスとして起動する。
  `proc.terminate()`（= TerminateProcess）は**親のみ**終了し ffmpeg が孤児化しうる。
  → `subprocess.Popen(..., creationflags=CREATE_NEW_PROCESS_GROUP)` で新プロセスグループを作り、
    停止時は `taskkill /F /T /PID <pid>`（`/T`=ツリー, `/F`=強制）でツリーごと終了する。
    **psutil 等の新規依存は足さない**（配布 EXE を太らせない方針／要承認）。
- **挙動不変の範囲**: ステージ順・margin/threshold 一致（P-2）・字幕タイムコード同期・出力ファイル名は不変。
  変わるのは「停止の即時性」と「ログが逐次表示になる」点のみ。
- **ログ分類は維持**: 1行ごとに現行のキーワード判定（`error`/`failed`/`exception`→error,
  `warning`/`warn`→warn, それ以外→info）を踏襲。stderr は stdout にマージ（`stderr=STDOUT`）。
- **encoding**: `text=True, encoding="utf-8", errors="replace"`（PITFALLS P-6 踏襲）。

## 4. 公開API 変更（最小）

`run_pipeline` のシグネチャは**変更しない**（`on_log` / `should_stop` / `tr` / `transcribe` のまま）。
内部に**プライベートヘルパ**を追加する:

```python
# pipeline.py（内部ヘルパ。外部公開しない）
import subprocess, sys

CREATE_NEW_PROCESS_GROUP = 0x00000200  # Windows 専用フラグ（sys.platform != "win32" では 0）

def _run_streaming(cmd, *, on_log, should_stop) -> tuple[int, bool]:
    """auto-editor を Popen で起動し stdout を1行ずつ on_log。
    should_stop() が真になったらプロセスツリーを kill して打ち切る。
    戻り値: (returncode, stopped)。stopped=True のとき returncode は不定(kill)。
    """
```

### 契約
- 戻り値 `(rc, stopped)`。`stopped=True` なら呼び出し側は `result.stopped=True` にして以降を skip。
- `stopped=False & rc==0` → 成功。`stopped=False & rc!=0` → `tr("log_error", rc, "")` を出す
  （stderr は既にストリームで出力済みのため、まとめ stderr は空文字でよい）。
- 例外は内部で握り、`on_log(tr("log_unexpected", ...), "error")` 後に `(rc=-1, stopped=False)` を返す。

### kill の実装指針（Windows）
```python
def _kill_tree(proc):
    if proc.poll() is not None:
        return
    if sys.platform == "win32":
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                       capture_output=True)
    else:
        proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
```

### ストリーミング読取ループ（即時性とブロッキングの両立）
- `proc = Popen(cmd, stdout=PIPE, stderr=STDOUT, text=True, encoding="utf-8",
  errors="replace", creationflags=(CREATE_NEW_PROCESS_GROUP if win32 else 0))`。
- `for line in proc.stdout:` で1行ずつ読む。各行の**前**に `if should_stop(): _kill_tree(proc); return (-1, True)`。
- ループ終了後 `proc.wait()` で `returncode` 確定。
- **既知の制約（要記載）**: `for line in proc.stdout` は次の行が来るまでブロックするため、
  auto-editor が**無出力で固まった場合**は停止判定が次行まで遅延する。auto-editor は進捗を頻繁に
  出すため実用上は即時に近い。完全な即時性が要件化したら別スレッドで `stdout` をポンプし、
  メインで一定間隔ポーリングして kill する方式へ拡張（本設計では非対象）。

## 5. ②b 文字起こし段（in-process）の停止

`faster_whisper` の `transcribe` は外部プロセスではなく**同一プロセス内**のイテレータ。現状どおり
SRT 書込ループ各回先頭で `should_stop()` を見て `break` する方式を維持（kill 不要）。**変更なし。**

## 6. UI 側（app.py）の変更

- `_stop_process` は**フラグ立てのみ**に統一し、ハードコード日本語をやめ i18n キー化:
  ```python
  def _stop_process(self):
      self.stop_requested = True
      self._log(self.t("log_stop_requested"), "warn")
  ```
- それ以外（`_worker` / `_start_process`）は**変更なし**。`should_stop=lambda: self.stop_requested` のまま。

## 7. 付随クリーンアップ（本タスクで一緒に直す i18n 違反）

着手中に発見した**ハードコード文字列**（AGENTS §4.1 違反）を、触る範囲なので同時修正する:

| 箇所 | 現状（ハードコード） | 対応 |
|---|---|---|
| `app.py:458` | `"  SRT生成: 有効 (モデル: {model_size})"` | i18n キー `log_srt_enabled` を新設し ja/en 追加 |
| `app.py:501` | `"⬛ 停止リクエストを受け付けました。..."` | §6 の `log_stop_requested` へ置換 |
| `pipeline.py:138` | `f"  音声検出: {info.language} (確率: {...})"` | i18n キー `log_lang_detected` を新設、`tr("log_lang_detected", info.language, info.language_probability)` |

### 追加する i18n キー（`i18n.py` ja/en 両方・必須）
| key | ja | en |
|---|---|---|
| `log_stop_requested` | `⬛ 停止リクエストを受け付けました。プロセスを終了します...` | `⬛ Stop requested. Terminating process...` |
| `log_srt_enabled` | `  字幕生成: 有効 (モデル: {})` | `  Subtitles: enabled (model: {})` |
| `log_lang_detected` | `  音声検出: {} (確率: {:.2f})` | `  Detected language: {} (probability: {:.2f})` |

> 注: `log_lang_detected` のフォーマットは `tr` 側で `{:.2f}` を扱う。`tr=self.t` が `str.format(*args)`
> 互換なら `"{} (確率: {:.2f})".format(lang, prob)` が成立する。`t()` の実装が `%`/`format` どちらか
> 着手時に確認し、合わせること（既存 `log_srt_analyze` が `{}` を使うため `format` 互換のはず）。

## 8. テスト計画（`tests/test_pipeline.py` 追補・subprocess モック）

`subprocess.run` 前提の既存テストを `Popen` 用に調整 + 即時停止ケースを追加:

1. **ストリーミング出力**: `Popen` をモックし `stdout` に複数行を流す→各行が `on_log` される。
2. **即時停止**: 読取ループ途中で `should_stop()` が True → `_kill_tree`（= `taskkill`/`terminate` の
   モック）が**呼ばれる**、戻り `stopped=True`、`result.stopped=True`、②以降未実行。
3. **rc!=0**: `stopped=False, rc!=0` → `result.ok=False`、②未実行（既存ケース踏襲）。
4. **正常 do_srt=True**: 既存どおり SRT 生成（②b は変更なしのため既存テスト流用）。
5. **kill ヘルパ**: `proc.poll()` が None のとき kill 呼出、既に終了済みなら no-op。
- `_kill_tree` 内の `subprocess.run(["taskkill",...])` はモックして OS 非依存にする
  （CI/非 Windows でも green にするため `sys.platform` を monkeypatch 可能に）。

## 9. 受け入れ基準（Definition of Done）

1. `python src/app.py` 起動 → 長い動画でカット中に**停止 → 即座にプロセスが消える**（タスクマネージャで
   auto-editor/ffmpeg が残らないことを**人手目視**）。字幕同期・出力は従来どおり。
2. ログがリアルタイムで1行ずつ流れる。
3. `tests/`（test_p0 / test_unit / test_pipeline）が全 green。
4. i18n は §7 の3キーが ja/en 両方そろう。ハードコード3箇所が消えている。
5. MEMORY.md に決定追記（課題C を「解消」へ更新）。新たな失敗があれば PITFALLS.md。
   バージョン整合（AGENTS §5）不変・生成物未コミット。

## 10. 非対象（やらない）

- 別スレッド stdout ポンプによる「完全即時」停止（§4 の制約参照。無出力ハング時のみ差が出る）。
- `subprocess.Popen` 化を②b（whisper, in-process）へ広げること（不要）。
- 新規依存（psutil 等）の追加。プロセスツリー kill は OS 標準 `taskkill` で行う。

## 11. 変更ファイル

| ファイル | 操作 |
|---|---|
| `src/pipeline.py` | `_run_streaming` / `_kill_tree` 追加、①②a を流用呼出に置換、`log_lang_detected` 化 |
| `src/app.py` | `_stop_process` を i18n キー化、`log_srt_enabled` 化（:458） |
| `src/i18n.py` | 3キー追加（ja/en） |
| `tests/test_pipeline.py` | ストリーミング/即時停止/kill のテスト追補 |
| `ROADMAP.md` | P2「即時停止対応」を進行/完了へ |
| `MEMORY.md` | 決定追記・課題C 更新 |
| `PITFALLS.md` | （必要時）Windows プロセスツリー kill の落とし穴を追記 |

## 12. 実装者（Gemini）への注意 — PITFALLS 先読み

- **P-2**: ①と②a の margin/threshold 一致は崩さない（ヘルパ化しても cmd 組立は `autoeditor.py` のまま）。
- **P-6**: `Popen` でも `encoding="utf-8", errors="replace"` 必須。`text=True`。
- **新規候補**: `taskkill` は Windows 専用。`sys.platform` 分岐を必ず入れ、非 Windows は `terminate()`。
  孤児 ffmpeg を残さないため `/T`（ツリー）必須。これを忘れると「停止したのに CPU が回り続ける」事故。
