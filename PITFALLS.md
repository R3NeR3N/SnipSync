# PITFALLS.md — 失敗・ハマりどころ記録

> 開発中に**試して失敗した手順**を残し、同じ轍を二度踏まないためのログ。
> MEMORY.md が「採用した決定」なら、こちらは「うまくいかなかった試み」。
> 着手前に必ず一読すること。新しいものを上に追記。

書式:
```
## YYYY-MM-DD — 症状の一言
- やったこと:
- 何が起きたか（エラー/症状）:
- 原因:
- 回避策 / 正しい手順:
- 関連: ファイル/関数
```

---

## 2026-06-20 — Resolve は fcpxml の音声 clip を「文書の逆順」でトラック割当する（推測でなく実測せよ）
- やったこと: 多トラック fcpxml のトラック順ズレを、spine の clip 文書順を変えて直そうと**4回**試行（lane ネスト / 映像先頭+wav昇順 / clip改名 / wav降順+映像最後）。毎回「次はこの順では」と**推測**で当て、実機で確認するまで規則を知らなかった。3回以上失敗＝アーキ疑え（systematic-debugging Phase 4.5）の典型。
- 何が起きたか: どの順序でも実機で期待トラック順にならず、テストは実装の吐く順序をそのまま assert するだけで**本バグを検出不能（偽の緑）**。
- 原因（実測で確定）: **Resolve の fcpxml インポータは spine の音声 asset-clip を「文書の逆順」でオーディオトラックへ割り当てる**。文書の**最後**の clip→**A1（最上段）**、**最初**→最下段。検証: 区別名 NAME01→02→03→04 の順で積層→インポート→ **A1=NAME04 … A4=NAME01**。
- 併せて判明: **fcpxml インポート時 Resolve はメディアを実プローブしない**（宣言 `audioChannels` と clip 構造をそのまま使う）。よって「多ストリーム mp4 を単一 clip 参照に畳む」案は**1トラックに潰れて不可**。N トラック出すには音声 clip が N 個必要（auto-editor の wav 分割は必然）。
- 回避策 / 正しい手順: 希望のトラック順（A1=T1/映像音声, A2=_1, A3=_2 …）を得るには文書順を**逆**に並べる＝ wav を**降順**（_N…_1）に置き、映像ブロックを**最後**に append（現 `_reorder_fcpxml_tracks` の `sorted(wavs, reverse=True)`＋映像 last）。実機(DaVinci Resolve 21)で A1=mp4(T1)/A2=_1/A3=_2/A4=_3・全セグメント保持・V1 ありを確認済み。**順序仮説は必ず実機 import で検証**（合成4トラックmp4＋実 auto-editor＋Resolve）。テストは「逆順規則に基づく期待順」を固定値で assert する形にし、実装追従の自己満足 assert にしない。
- 関連: `src/pipeline.py` `_reorder_fcpxml_tracks`, `tests/test_pipeline.py`, MEMORY 2026-06-20 01:50

## 2026-06-20 — FCPXML で lane ネストによる connected clip を作ると映像消失・音声分裂する
- やったこと: DaVinci Resolve で音声トラック順が狂う問題を解消するため、`asset-clip` の下に `lane="-1"` 等で他の WAV `asset-clip` をネストする connected clip 構造を作成した。
- 何が起きたか: 実機 DaVinci Resolve でインポートした際、映像（V1トラック）が完全に消失し、音声トラックが過剰（A1〜A15等）に細切れに分裂して配置されてしまうバグが発生した。
- 原因: DaVinci Resolve の FCPXML インポーターが複雑なネスト構造を正しく処理できないバグ（仕様制限）によるもの。
- 回避策 / 正しい手順: `lane` 属性やネスト構造を使用せず、auto-editor 本来の「spine 直下にすべてのクリップをフラットに並べる」構造を完全に維持する。その上で、同じ offset を持つ各セグメント内の物理的な出現順序（映像アセットを先頭、続いて各 WAV アセットをストリーム順）のみを元のストリーム順に整列する。これにより、構造を破壊せずに Resolve へのトラック割当を正しく整列させることができる。
- 関連: `src/pipeline.py` `_reorder_fcpxml_tracks`, `tests/test_pipeline.py`, MEMORY 2026-06-20

## 2026-06-19 — fcpxml の音声トラック並べ替えで spine の全カットセグメントを潰した
- やったこと: 多トラック fcpxml のトラック順を直すため `_reorder_fcpxml_tracks` を試作。`spine.findall("asset-clip")` で得たクリップの **`clips[0]` だけをテンプレ化→全 remove→1個だけ再生成**し lane ネストを付けた。
- 何が起きたか: 実機 DaVinci でタイムラインが **2.2秒・1クリップ**に崩壊。31セグメント中30消滅。wav と mp4 が別オフセットにズレて表示。
- 原因: spine 構造の誤解。素の auto-editor resolve fcpxml の spine は **「N_seg × N_track 個の asset-clip をフラット列挙」**（実測 31×4=124、lane 無し、各 `(offset,duration)` グループに各トラック1ref）。「4 asset-clip = 1トラックずつ」と仮定したため、セグメント次元(31)を丸ごと無視して 1 に潰した。さらに asset id は名前順でない（順序は asset `name` suffix で判定要）。
- 回避策 / 正しい手順: top-level `asset-clip` を `(offset,duration)` で**全グループ化**し、**セグメント数を必ず維持**。各セグメントごとに primary=映像asset(lane0)＋wavを元ストリーム順で lane-1,-2,-3 ネスト。primary の `start` をネストへ流用しない（各クリップ自身の値）。検証は素の auto-editor 出力の spine クリップ数(=セグ数×トラック数)を実測し、reorder 後にセグメント数==入力セグメント数を assert。設計: `docs/handoff/P3-fcpxml-track-reorder.md`。退避: `git stash@{0}`。
- 関連: `src/pipeline.py` `_reorder_fcpxml_tracks`, `docs/handoff/P3-fcpxml-track-reorder.md`, MEMORY 2026-06-19 23:20

## 2026-06-19 — fcpxml(resolve) の `_tracks/*.wav` を掃除するとDaVinciで多トラックが「メディア未検出」
- やったこと: 多トラック音声(OBS 4トラック収録)の動画を resolve 出力→ DaVinci 取込。事前に「auto-editor の `_tracks` はゴミ」と判断し処理後 `rmtree`（2026-06-19 初版実装）。
- 何が起きたか: DaVinci でトラック1(全音声ミックス=元mp4由来)だけ残り、他3トラックが「見つからない」。
- 原因: 当初の仮説「auto-editor は fcpxml に音声1本しか宣言しない」は**誤り**（実測で否定）。fcpxml は4トラックを正しく宣言するが、各分解トラックを**入力隣 `{stem}_tracks/*.wav` の絶対パス file:// 参照**で持つ。元mp4参照(=映像+T1)だけは残り、`_tracks` を消した3本が参照切れ→未検出。掃除が必須アセットを削除していた自爆。なお premiere(.xml) は元mp4直参照(`<sourcetrack> trackindex`)なので `_tracks` は本当に不要だが、DaVinti はmp4内の分離4ストリームを trackindex 通りに展開できず 8トラック化&6無音(別問題)。
- 回避策 / 正しい手順: fcpxml(resolve/final-cut-pro) では `_tracks` を**削除せず出力先へ移動し fcpxml 内の参照パスを書き換える**（B案）。premiere(.xml) のみ従来どおり掃除。実装は `pipeline._rewrite_fcpxml_track_paths` ＋ relocate ブロック（字幕用WAV抽出が再生成し得るので 2a の前に移動）。検証は実 auto-editor + 合成4トラックmp4でE2E（入力dirクリーン/出力dirに `_tracks` 移動/fcpxml書換）。
- 関連: `src/pipeline.py`(relocate/_rewrite_fcpxml_track_paths), `src/i18n.py`(log_tracks_relocated), `tests/test_pipeline.py`, MEMORY 2026-06-19

## 2026-06-19 — faster-whisper GPU: nvidia-* wheel 導入だけ／add_dll_directory だけでは cuBLAS を読めない
- やったこと: GPU を使うため `.venv` に `nvidia-cublas-cu12`/`nvidia-cudnn-cu12` を入れ、cuda で `WhisperModel` を構築。
- 何が起きたか: `RuntimeError: Library cublas64_12.dll is not found or cannot be loaded`。(1) wheel 導入だけ → DLL 未発見。(2) `os.add_dll_directory(.../nvidia/cublas/bin)` を足すだけでも依然「cannot be loaded」。(3) `nvidia-cuda-runtime-cu12`(cudart) 欠落も一因。
- 原因: ctranslate2 は `site-packages/nvidia/*/bin` を自動探索しない。さらに Windows の LoadLibrary 探索順の都合で `add_dll_directory` 単独では不足。`cublas64_12.dll` は `cudart64_12.dll` に依存。
- 正しい手順: cublas + cudnn + **cuda-runtime** を入れ、**インポート/モデル構築前に各 `bin` を `os.add_dll_directory` ＋ `PATH` 前置**する（PATH 前置が決め手）。SnipSync は `subtitles.add_cuda_dll_dirs()` で自動化し `pipeline._decode` の cuda 構築直前で呼ぶ。CUDA ライブラリは `.venv` 内に閉じ込めホスト非汚染。
- 関連: `src/subtitles.py`, `src/pipeline.py`, `pyproject.toml [gpu]`, MEMORY 2026-06-19

## 2026-06-19 — auto-editor の `--temp-dir` は `{stem}_tracks`（多トラック分解）を移動しない
- やったこと: 多トラック音声の動画で、元動画の隣に出る `{stem}_tracks` フォルダ（`_1.wav`/`_2.wav`...）を消そうとして auto-editor に `--temp-dir <空dir>` を渡した。
- 何が起きたか: `_tracks` は**依然として入力ファイルの隣に生成**され、指定した temp-dir は空のままだった。`--help` を見てもトラック分解の出力先変更/抑制フラグは無い。
- 原因: `--temp-dir` が制御するのは auto-editor の内部一時ファイルであって、多トラック入力を分解した音声フォルダ（`_tracks`）の置き場所ではない。`_tracks` は入力パス基準で作られる。
- 回避策 / 正しい手順: auto-editor 側では抑止できない。**呼び出し側（SnipSync）が処理後に掃除する**。`run_pipeline` 開始前に `{stem}_tracks` の存在を記録し、`finally` で「本実行中に出現した場合のみ」`shutil.rmtree`（既存フォルダは温存）。単トラック動画では `_tracks` は出ない（再現には多トラック入力が必要）。
- 関連: `src/pipeline.py` run_pipeline(tracks掃除), `tests/test_pipeline.py`, MEMORY 2026-06-19

## 2026-06-18 — GitHub Actions の job-level `environment:` は `steps.*` 出力を読めない
- やったこと: release.yml で 1ジョブ内の step でチャネル（staging/prod）を判定し、同ジョブの `environment: ${{ steps.channel.outputs.env }}` に渡そうとした。
- 何が起きるか: `environment` はジョブ開始時（step実行前）に評価されるため `steps.*` は空。環境が解決されず無効。
- 正しい手順: 判定を別ジョブ（classify）に切り出し outputs に出す → build ジョブで `needs: classify` + `environment: ${{ needs.classify.outputs.env }}`。job-level environment は `needs`/`github`/`vars`/`inputs` は読めるが `steps` は不可。
- 関連: `.github/workflows/release.yml`

## 2026-06-18 — ruff の F401 自動修正が「再エクスポート / 可用性プローブ import」を消す
- やりがちなこと: `ruff check --fix` を丸ごと走らせ F401（未使用 import）を一括削除。
- 何が起きるか: app.py の `APP_VERSION`/`format_timestamp` は test_p0 が `from app import ...` する**再エクスポート**、`from faster_whisper import WhisperModel` は try 内の**可用性判定専用**で本体未使用。一括削除すると test破壊・WHISPER_AVAILABLE 判定破壊。
- 正しい手順: 自動修正は安全規則のみに限定（`--select W293,I001,E401 --fix`）。再エクスポート/プローブ import は `# noqa: F401` で残す（または `__all__`）。真の不要 import だけ手で削除。
- 関連: `src/app.py`, `tests/test_p0.py`, `pyproject.toml [tool.ruff]`

## 2026-06-17 — faster-whisper transcribe() は遅延ジェネレータ。例外はデコード（反復）時に出る
- やりがちなこと: `model.transcribe()` 呼び出しを try で囲み「これで GPU 失敗を捕捉できる」と考える。
- 何が起きるか: `transcribe()` は (segments_generator, info) を即返すだけで**実デコードは segments を反復したとき**に走る。CUDA OOM 等の実行時エラーは反復ループ（SRT書込）で送出され、transcribe() を囲んだ try/except を**素通り**する → GPUフォールバックが効かない。DIモックが即時例外で落ちる設計だとテストでも露見しない。
- 正しい手順: フォールバック判定をしたい範囲内で `list(seg_iter)` 等により**デコードを完走させてから**SRT書込へ進む。フォールバック時は device と compute_type を同時に CPU 用へ切り替える。
- 関連: `src/pipeline.py` 2bブロック, `docs/handoff/P3-review-fixes.md`, `tests/test_pipeline.py`

## 2026-06-17 — テスト内で subprocess.Popen をモックすると taskkill 等の subprocess.run も巻き込まれる
- やったこと: `tests/test_pipeline.py` で `subprocess.Popen` をモックした。また、`_kill_tree` の Windows 用処理で `subprocess.run(["taskkill", ...])` を呼び出した。
- 何が起きたか: `subprocess.run` は内部で `Popen` を呼び出すため、モックされた `Popen` が返された。モッククラスがコンテキストマネージャプロトコル (`__enter__`/`__exit__`) や `communicate` / `args` などの属性を実装していなかったため、`TypeError` や `AttributeError` が発生した。
- 原因: グローバルな `subprocess.Popen` のモックが、テストフレームワークや `subprocess.run` の内部呼び出しに影響を与えたため。
- 回避策 / 正しい手順: モック用の `Popen` に `__enter__`, `__exit__`, `communicate() -> ("", "")`, `args` を持たせる。また、コマンドが `"taskkill"` のときはダミーの MockPopen を返すようにモック関数内で条件分岐させる。
- 関連: `tests/test_pipeline.py`, `src/pipeline.py` `_kill_tree`

## （初期エントリ）プロジェクト固有の既知の落とし穴

実コードと環境から判明している、繰り返しやすい失敗を先に登録しておく。

### P-1: UI に文字列を直接書くと言語切替で消える
- やりがちなこと: `CTkLabel(text="処理開始")` のように文字列を直書きする。
- 何が起きるか: 言語切替 (`_apply_lang`) で上書きされない／英語側に出ない。
- 正しい手順: 必ず `I18N` にキーを足し、`self.t("key")` 経由で設定する。`ja` と `en` 両方追加。
- 関連: `src/app.py` `I18N`, `_apply_lang`

### P-2: auto-editor の margin/threshold をメインと字幕用で食い違わせる
- やりがちなこと: メインカット (`cmd`) と字幕用 WAV 抽出 (`temp_cmd`) で別パラメータを使う。
- 何が起きるか: カット位置がズレて **字幕タイムコードがタイムラインと同期しなくなる**（本プロダクトの核心価値が壊れる）。
- 正しい手順: 両者で `--margin` と `--edit audio:threshold=` を必ず一致させる。
- 関連: `src/app.py` `_worker`（①と②）, CONTEXT.md §1

### P-3: 相対パスで auto-editor を呼ぶと出力先が迷子になる
- やりがちなこと: 入力/出力をそのままの相対パスで渡す。
- 何が起きるか: 作業ディレクトリ依存で出力ファイルが想定外の場所に出る。
- 正しい手順: `Path(...).resolve()` で絶対パス化してから渡す（既存方針）。
- 関連: `src/app.py` `_start_process`

### P-4: FFmpeg 不在で無言に失敗する
- やりがちなこと: FFmpeg を PATH に通さず実行。
- 何が起きるか: auto-editor が内部で FFmpeg を呼べず処理が失敗する。
- 正しい手順: 開発環境で FFmpeg を PATH に通す。READMEの前提条件参照。
- 関連: CONTEXT.md §7

### P-5: Whisper モデルを git にコミットしてしまう
- やりがちなこと: キャッシュされた `*.bin` / `*.pt`（数 GB）をうっかり追加。
- 何が起きるか: リポジトリが肥大化。
- 正しい手順: `.gitignore` 済み（`*.bin` `*.pt` `huggingface/`）。コミット前に `git status` で確認。
- 関連: `.gitignore`

### P-6: subprocess の文字化け
- やりがちなこと: `subprocess.run` を encoding 指定なしで呼ぶ。
- 何が起きるか: 日本語ログ/パスが文字化け・デコード例外。
- 正しい手順: `text=True, encoding="utf-8", errors="replace"` を踏襲。
- 関連: `src/app.py` `_worker`

### P-7: 生成物ディレクトリでの作業
- やりがちなこと: `build/` `dist/` の中のファイルを直接編集して挙動を変えようとする。
- 何が起きるか: 再ビルドで消える。ソースは `src/`、ビルド設定は `build/app.spec`。
- 正しい手順: ソースを直し `pyinstaller build/app.spec` で再生成。
- 関連: `build/app.spec`, `dist/`
