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

## 2026-10-04 — 字幕の最後の「今から」が、音声の位置と合わない（Whisper の開始時刻が前の字幕に張り付く＋カット点で字幕が切れる）
- やったこと/疑い: `.fcpxml` と `.srt` を Resolve のタイムライン先頭に合わせて読み込むと、最後の字幕だけ声とずれた。字幕全体のずれ（開始位置の違い）を疑ったが、SRT の境界は、`.fcpxml` のクリップ境界と一致し、タイムラインの長さ（41.95 秒）も一致していた。
- 原因: (1) Whisper の語の開始時刻は、間に無音があると直前の字幕の終わりに張り付く（声は 40.4 秒ごろからなのに、字幕は 39.72 秒から）。(2) 字幕をカット点で区切るため、カット点（40.883 秒）をこえて続く「から」（41.05〜41.95 秒）が、字幕なしになった。
- 回避策 / 正しい手順: VAD で、字幕の開始・終了を声の区間に合わせる（`subtitles.refine_cue_times`）。試した最初の版は、無音をこえて声を次々につなげて延ばしたため、字幕が文字にしていない声まで取り込んだ（最初の字幕が 1.1 秒から 3.3 秒に）。つなぐ無音は短く（0.25 秒）。また、VAD の区間が、直前の字幕の声の端（約 0.3 秒）を含むと、開始が動かなかったので、字幕の頭に食い込んだ短い端は数えない。評価は、字幕の時刻とは別の物差し（音量）で行う（声のうち字幕に覆われた割合 83.7% → 91.3%、取りこぼした声 3.72 秒 → 1.98 秒、声のない場所の字幕 12.2 秒 → 13.9 秒）。
- 未解決: 1 本の録画でしか確かめていない。Whisper が文字にしなかった声（取りこぼし 1.98 秒）は、字幕にならない。
- 関連: `src/subtitles.py`（`refine_cue_times`）、`src/pipeline.py`（`refine_timing`）

## 2026-10-04 — DaVinci Resolve で .fcpxml を読み込むと「3 クリップのうち 3 クリップが見つかりません」になる（ファイル名のスペース・日本語で、音声の参照を書き換えられていなかった）
- やったこと/疑い: 複数トラック音声の録画（`2026-06-20 11-04-28.mp4`）を処理し、出力した `.fcpxml` を Resolve で「XML をロード」した。音声の WAV 3 本が、すべて見つからなかった。映像（元の mp4）は見つかった。
- 原因 1（SnipSync の不具合）: 処理は、`<名前>_tracks`（取り出した音声）を、出力先へ移し、`.fcpxml` の中の参照を書き換える。auto-editor は参照を **URL**（スペースは `%20`、日本語は `%XX`）で書くが、書き換えは**生のパス文字列**で置換していたため、名前にスペースや日本語があると一致せず、**何も書き換えないまま成功扱い**になった（ログには「参照を更新しました」と出ていた）。結果、`.fcpxml` は、元の録画のフォルダ（そこには `_tracks` が無い）を指したままだった。OBS の録画は、名前にスペースを含むことが多い。既存のテストは、スペースの無い名前の生のパスだけで確かめていたため、見逃した。
- 原因 2（運用）: 出力フォルダを、あとから別の場所へ移すと、絶対パスの参照が、また切れる。
- 回避策 / 正しい手順: (1) URL（%エンコード）形式を先に試し、生の形式・バックスラッシュ形式も試す。置換後も、一致した形式に合わせて %エンコードで書く（`pipeline._rewrite_fcpxml_track_paths`）。(2) 書き換えに失敗したら、`_tracks` を移さず元の場所に残し、警告を出す（移すと、必ず音声を見失うため）。(3) すでに切れた `.fcpxml` は、Resolve の「他のフォルダを選択して検索しますか?」で **はい** を選び、`.fcpxml` の隣の `_tracks` フォルダを指定すると、ファイル名で見つけて復旧できる。
- 関連: `src/pipeline.py`、`tests/test_pipeline.py`（スペース・日本語の名前のテストを追加）

## 2026-10-04 — 「動画・音声」の書き出しが「Could not write packet: Invalid argument (pts … dts …)」で失敗する（auto-editor 31.7.2 の既定の映像設定）
- やったこと/疑い: 実機で、プリセットを選び、新しいファイルをドロップし、出力形式を「動画・音声」に切り替えて処理を開始した。auto-editor が終了コード 1 で失敗した。
- 再現: 失敗した録画（OBS 系の H.264・60fps・音声 4 トラック・約 1 分）で、**カットする設定**（声で判定・音量で判定のどちらでも）だと、ログのエラー（`stream 0, pts 21248, dts 20736, duration 256, timebase 1/15360`）まで同じものが出た。無音を倍速にする設定では出なかったため、倍速の設定の人は気づかなかった。出力先には、再生できない書きかけの `.mp4`（約 260KB）が残っていた。
- 原因: auto-editor 31.7.2 は、映像のプロファイルを指定しないと、B フレームのある H.264 で、書き出しの途中にパケットの時刻（pts/dts）が合わなくなることがある。24 通りの設定（しきい値 4・余白 2・指定 3）で比べると、指定なしは 8 通り中 5 通りで失敗、`-vprofile high` と `main` を指定した 16 通りはすべて成功した。`-c:v libx264` の明示や `--no-seek`、`-g`、`--no-faststart` では直らなかった。`--smooth 0` は直るが、カットの結果が変わるので採らない。
- 回避策 / 正しい手順: 「動画・音声」の書き出し（H.264 の入れ物 `.mp4` `.mov` `.mkv` `.m4v`）では、`-vprofile high` を付ける（`autoeditor._media_video_args`）。`.webm`（VP9）と音声のみには付けない。失敗した（または止めた）書き出しの書きかけのファイルは消す。
- 注意: 試験用に作った B フレーム入りの動画（PyAV で生成）では再現しなかった。実際の録画でしか再現しないため、コマンドの組み立てだけをテストで固定している（`tests/test_autoeditor.py`）。
- 関連: `src/autoeditor.py`、`src/pipeline.py`、`tests/test_autoeditor.py`

## 2026-10-04 — GPU を選んでも CPU に切り替わる（EXE に cuBLAS・cuDNN が入っていない）／文字起こし中は「停止」が効かず、進み具合も見えなかった
- やったこと/疑い: 実機（RTX 5070）で「GPU を使う」を入れて処理した。ログに「GPU を使えなかったため、CPU に切り替えました」。large-v3 を選ぶと、数分間ログが止まり、「停止」を押しても終わらなかった。
- 実測: GPU 自体は使える。`ctranslate2.get_cuda_device_count()` は 1。失敗の理由は `Library cublas64_12.dll is not found or cannot be loaded`（cuBLAS が無い）。配布する EXE には、1GB 以上ある NVIDIA の DLL を入れていない（意図した設計）が、画面は「GPU がある」だけを見て、使えるかのように見せていた。cuBLAS・cuDNN を入れると、RTX 5070 でも動いた（large-v3-turbo・38 秒の音声で GPU 0.6 秒、CPU 8.7 秒）。kotoba に限らず、どのモデルでも同じ。
- 「進まない」の正体: 取得は終わっていて（Hugging Face のキャッシュに 3.09GB がそろっていた）、そのあとの CPU での文字起こしが長く、しかも (1) 文字起こしの間はログも進捗も出ない、(2) `list(seg_iter)` で最後まで取り出していたため、終わるまで「停止」の判定に到達しない、の 2 つで、止まっているように見えた。
- 回避策 / 正しい手順: (1) GPU 用の部品を、利用者の許可を得て初回だけ取得する（`src/cudalibs.py`。版・SHA-256 固定、公式の PyPI から、`%APPDATA%\SnipSync\cuda\bin` へ）。「GPU を使えるか」は、デバイスの有無ではなく DLL を読み込めるかで確かめる（`subtitles.cuda_libs_ready`）。(2) セグメントを 1 つずつ取り出し、そのつど `should_stop` を見て、秒単位の進み具合を画面に出す。(3) GPU が失敗したときのログに理由を付ける。
- 関連: `src/cudalibs.py`、`src/subtitles.py`、`src/pipeline.py`（`_decode`）、`tests/test_cudalibs.py`

## 2026-10-04 — kotoba-whisper が 30 分経っても取得されず、「停止」も効かなかった（Xet 転送の停止＋取得が止められない作り）
- やったこと/疑い: 実機で kotoba-whisper を選んで処理を開始した。ログは「ダウンロードします」で止まり、30 分以上そのまま。「停止」を押しても終わらなかった。
- 実測: 保存先フォルダには `.cache/huggingface/trees/*.json`（ファイル一覧）だけがあり、本体（model.bin 1.5GB）は 0 バイト。同じ回線で `snapshot_download` を再現すると、6/7 ファイルで止まって進まない。環境変数 `HF_HUB_DISABLE_XET=1`（通常の HTTP 転送）にすると約 8MB/s で完走した。Xet 方式（huggingface_hub 1.x の既定）の転送が、この回線で固まる。
- 原因: (1) Xet 転送が進捗 0 のまま止まる。(2) 取得を `snapshot_download` の同期呼び出しで行っていたため、固まるとワーカースレッドごと戻らず、「停止」の判定（`should_stop`）に到達しない。(3) 画面に取得の進捗が無く、固まっているのか遅いのか区別できなかった。
- 回避策 / 正しい手順: `HF_HUB_DISABLE_XET=1` を、huggingface_hub を最初に import するより前（`app.py` の先頭と `models.py`）に設定する。取得は別スレッドで行い、本体は 0.2 秒ごとに `should_stop` と無進捗時間（120 秒）を見る。停止は固まった転送を放置して即座に戻り、進捗クラスの更新で打ち切る。進捗は tqdm_class で受ける。
- 関連: `src/models.py` `download_model`、`src/pipeline.py`（取得はデコード試行の前に 1 回だけ行う。取得の停止を「GPU の失敗」と取り違えて取得をやり直さないため）、`tests/test_model_download.py`

## 2026-10-03 — `.gitignore` の `build/` が PyInstaller の設定（app.spec・フック）まで除外していた
- やったこと/疑い: 動作確認を終えてコミットする前に、`git ls-files build` で追跡対象を確認した。
- 何が起きたか: 結果が**空**。`build/app.spec` と `build/build_hooks/hook-tkinterdnd2.py` が一度も git に入っておらず、リリース用ワークフロー（`pyinstaller build/app.spec`）は GitHub 上でビルドに必要なファイルを持たない状態だった。手元ではファイルがあるため気付けない。
- 原因: `.gitignore` の `build/`（生成物の置き場）が、同じフォルダにある設定ファイルまで巻き込んでいた。
- 回避策 / 正しい手順: `build/*` で生成物を除外し、`!build/app.spec` と `!build/build_hooks/` で設定を追跡する。**「手元で動く」ことと「リポジトリに入っている」ことは別**。コミット前に、動作に必要なファイルが `git ls-files` に出るかを確認する。
- 関連: `.gitignore`, `build/app.spec`, `.github/workflows/release.yml`

## 2026-10-03 — 31.x を鍵なしで使うと、レンダリングが 3200x1800 に縮小される（NLE 用タイムライン出力は無制限）
- やったこと/疑い: auto-editor を 31.x へ移行する際、30.0.0 のリリースノートにある「一部のリリースはライセンスキーが必要になる（FOSSIL モデル）」が、無料アプリの SnipSync の主機能を止めないかを確認した。
- 実測（31.7.2・キー無し）: 4K(3840x2160) の **FCPXML 出力は制限なく成功**。4K の**レンダリング（メディア書き出し）は失敗せず、警告を出して 0.75 倍（2880x1620）に自動縮小**する。公式ノート 31.4.0: 単一入力のレンダリングは 3200x1800 まで、複数入力の結合は要キー（タイムライン出力も）。リポジトリは Unlicense。
- 影響: 無料版の主機能（NLE 用タイムライン出力）は無制限。影響するのは「カット済みメディア」の 4K 超のみ。
- 回避策 / 運用: メディア書き出しの開始前に解像度を調べて警告する（`pipeline` の `log_media_downscale`）。フル解像度が要るときはタイムライン出力を案内。**版は固定してハッシュを照合**する（今後の版でキーの要件が増える可能性があるため、`AE_VERSION` を勝手に上げない）。
- 関連: `src/autoeditor.py`(`UNLICENSED_RENDER_MAX`), `src/pipeline.py`, `src/aebin.py`

## 2026-10-03 — 31.x は同じ設定でもカット結果が変わる（`--smooth` が既定で効く）
- やったこと: 29.3.1 と 31.7.2 を同じ素材・同じ `--margin` / `--edit audio:threshold` で比べた。
- 何が起きたか: カット区間が 27 → 19 に減る（短すぎるカット・クリップが除かれる）。29.97fps 素材でも同様。
- 原因: 31.x は `--smooth MINCUT,MINCLIP`（既定 0.2s,0.1s）が既定で適用される。29.3.1 には無かった。
- 対応: 仕様変更として受け入れる（短すぎるカットが減るのは編集上は好ましい）。CHANGELOG と README に明記。前の挙動に戻したいときは `--smooth 0`（UI には出していない）。
- 関連: `docs/handoff/verification-2026-10.md`

## 2026-10-03 — 同梱の auto-editor 31.7.2 は mp3 / m4a / aac を書き出せない（`Could not open encoder`）
- やったこと: 音声のみ入力のメディア書き出しで、拡張子ごとに書き出せるかを実測した。
- 何が起きたか: wav / flac / ogg / opus は成功。**mp3 / m4a / aac は `Error! Could not open encoder`**。wma は成功扱いだが PCM の巨大ファイルになる。
- 回避策: 書き出せない形式の入力は WAV で出力する（`autoeditor.AUDIO_RENDER_EXTS`、`pipeline._output_ext`）。
- 関連: `src/autoeditor.py`, `src/pipeline.py`

## 2026-10-03 — DaVinci Resolve が無料版だと、外部スクリプトで取り込み検証を自動化できない
- やったこと: この PC の Resolve 21.1 に、スクリプト API（`DaVinciResolveScript`）で FCPXML を自動取り込みして検証しようとした。
- 何が起きたか: Resolve を起動しても `scriptapp("Resolve")` が `None`。公式の README どおり、外部スクリプトの接続設定は **Resolve Studio のみ**（無料版は Workspace → Scripts からの内部実行だけ）。
- 代替: 出力ファイルの内部整合性を機械的に検査する（参照切れ・クリップの連続性・範囲外・トラック長の不一致・マーカーの範囲外・`linkclipref`）。実 NLE への取り込みは人間が行う（`docs/handoff/verification-2026-10.md`）。
- 関連: `docs/handoff/verification-2026-10.md`

## 2026-10-03 — 倍速モードの境界は、版ごとにクリップ位置の丸め規則が違う（累積して丸めれば最大1フレーム）
- やったこと: 倍速化した無音区間の長さを `(end-start)/speed`（小数）で累積して、字幕のカット境界とマーカー位置を計算した。
- 何が起きたか: 実際の FCPXML のクリップ位置と合わない。1フレーム未満の極小の倍速区間は XML に出力されず、残る区間数も v1 の27に対し XML は23（29.3.1）。
- 原因（実測）: **29.3.1**: クリップごとに「元のフレーム数 ÷ 倍速」を四捨五入した整数フレームにし、0 の区間は出力しない（この規則で23クリップの位置が完全に再現できた）。**31.7.2**: 同じ規則では再現できず（9.625→9、6.625→6 だが 3.625→4）、全体の長さに誤差を配分しているように見える。単純な per-chunk 丸め・累積の floor/ceil/round のどれも一致しない。
- 回避策 / 正しい手順: 長さは**小数のまま累積し、境界ごとに四捨五入（.5 は切り上げ）でフレームへ丸める**（`subtitles.chunks_to_boundaries`、`audiocut.render_cut_audio`）。31.7.2 の XML のクリップ位置と最大1フレーム以内で一致（誤差が溜まらない）。マーカーは境界の1フレーム手前に入ったらクリップ先頭へ寄せる（`markers`）。**等速のみの場合は完全に一致**。字幕が実際のカット境界をまたがないことは実 XML で確認済み。
- 関連: `src/subtitles.py`, `src/audiocut.py`, `src/markers.py`, `tests/test_subtitles_v2.py`

## 2026-10-03 — マーカーの時刻は先にフレーム格子へ丸める（丸め済みの秒数だと直前のクリップに入る）
- やったこと: カット境界（秒・小数6桁に丸め済み）を、そのまま FCPXML のクリップ範囲 `[offset, offset+duration)` に当てはめてマーカーを付けた。
- 何が起きたか: クリップの境目ぴったりの境界（523/30 秒）が 17.433333 秒になり、直前のクリップの**末尾（範囲外）**に付いた。1つのクリップに「カット 8」「カット 9」が重なる。lint では見つからず、実データの XML を数えて発覚。
- 原因: 丸め済みの秒数が、クリップ境界よりわずかに小さい。
- 回避策 / 正しい手順: 時刻を先にフレーム格子へ丸めてから（`round(t/fd)*fd`）所属クリップを決める。検証は「全マーカーがクリップ範囲内・フレーム格子上・1クリップに複数のカット点マーカーが無い」を XML から機械的に確認する。カット点マーカーはタイムライン先頭と終端を含めない。
- 関連: `src/markers.py`, `tests/test_transcript_markers_models.py`

## 2026-10-03 — auto-editor 29.3.1 は「モノラル音声」のカット書き出しで音を壊す（字幕が誤認識された真因・31.x で修正済み）
- やったこと: 合成した日本語2話者音声（モノラル）から、字幕用の WAV を `auto-editor -vn --mix-audio-streams` で書き出して Whisper に渡した。
- 何が起きたか: 「こんにちは」が「ボンニティは」に。mp4 由来の WAV は言語判定すら失敗（en 0.25・字幕0件）。tiny/turbo どちらでも同じ。
- 原因（波形の相関とエネルギーで確定）: 29.3.1 はモノラルを書き出すと、**カットなし**でも元と無相関（相関 0.003）・エネルギー半減になる。ステレオ（左右同一）は相関 1.000 で正常。`-layout stereo` は mp4 では形が戻るが左チャンネルのみ、WAV では直らない。`--margin` / `-tb` / `-ar` / `-c:a` を変えても直らない。`_tracks/*.wav` の書き出しと NLE 用タイムライン出力は影響なし。
- **解決**: 31.7.2 で修正済み（モノラル WAV 相関 1.000、モノラル mp4 は 6 秒以降 1.000・エネルギー比 0.993〜0.998）。SnipSync は 31.7.2 へ移行した。
- やりがちな失敗: 認識結果だけを見て「モデルが小さい」「TTS が不自然」と判断し、モデルを大きくする。まず元音声と出力音声の**相関・エネルギー**を直接比べる。
- 運用: 字幕用のカット後音声は、版に依存せず・音声の再レンダリングが不要になるため、**v1 chunks から自前で組み立てる方式を維持**（`audiocut.render_cut_audio`）。メディア書き出しは 31.x でモノラルも正しいので auto-editor に任せる（29.x 用に作った音声合成の回避策は削除した）。
- 関連: `src/audiocut.py`, `src/pipeline.py`(2a), MEMORY 2026-10-03

## 2026-10-03 — kotoba-whisper-v2.0-faster で単語時刻を有効にするとプロセスごと落ちる（セグメンテーション違反）
- やったこと: 日本語特化の `kotoba-tech/kotoba-whisper-v2.0-faster` を faster-whisper で `word_timestamps=True` にして実行（カット整合字幕は単語時刻が必須）。
- 何が起きたか: Python の例外ではなく**プロセスが異常終了**（終了コード 139）。`word_timestamps=False` なら正常。tiny で同条件にすると正常（対照実験）。
- 原因: 配布 config の `alignment_heads` が large-v3（デコーダ32層）の番号（7〜25層目）のままだが、kotoba は2層に蒸留してあり存在しない層を指す。CTranslate2 が範囲外参照で落ちる。
- 回避策 / 正しい手順: 蒸留元と同型の distil-large-v3 と同じ `[[1, 0..19]]` に config を補正する（`models.patch_alignment_heads`）。専用フォルダへ取得して補正（`prepare_model`）。補正後は単語時刻つきで動くが、単語時刻が粗く短い字幕に細かく割れるため「実験的」扱い。カット整合字幕には large-v3-turbo を推奨。
- 関連: `src/models.py`, `tests/test_transcript_markers_models.py`

## 2026-10-03 — PyAV 19 系だと faster-whisper 1.2.1 の `decode_audio` が落ちる
- やったこと: 新規環境で `pip install faster-whisper` → PyAV の最新（19.0.1）が入った。
- 何が起きたか: `TypeError: open() got an unexpected keyword argument 'metadata_errors'`（`decode_audio`）。
- 原因: faster-whisper 1.2.1 は `av` の上限を指定しておらず、新しい PyAV で引数が無くなっている。`requirements.txt`（フリーズ）は `av==17.0.1` で、`pyproject.toml` に指定が無かったため新規導入で再現する。
- 回避策 / 正しい手順: `pyproject.toml` に `av>=17,<18` を明記（17.0.1 で動作確認）。
- 関連: `pyproject.toml`

## 2026-10-03 — v1 export の `-tb` を整数に丸めると 29.97fps で NLE の格子とずれる
- やったこと: `probe_fps` の値（29.97）を `str(int(round(tb)))` で `-tb 30` にして v1 JSON を作り、字幕のカット境界を計算していた（カット整合字幕の初期実装）。
- 何が起きたか: 実測で `-tb 30` と `-tb 30000/1001` ではカット位置のフレームが変わる（例: 31 と 32）。NLE のタイムラインは 30000/1001 なので、境界が最大1フレームずつずれ、カットが多いほど累積する。
- 原因: タイムベースの丸め。`-tb` は有理数（`30000/1001`）を受け付ける。
- 回避策 / 正しい手順: `autoeditor.format_timebase` で有理数のまま渡す（`Fraction(...).limit_denominator(1001)`）。
- 関連: `src/autoeditor.py`, `tests/test_autoeditor.py`

## 2026-10-03 — auto-editor 公式サイトのフラグ名は 29.3.1 に存在しない（版を手元で確認せよ）
- やったこと: 公式サイト（auto-editor.com）の `--when-inactive` / `--cut` を使って倍速化と区間指定を実装しようとした。
- 何が起きたか: `Error! Unknown option: --when-inactive`。
- 原因: 公式サイトは新しい版（GitHub は 31.x）の記述。PyPI の `auto-editor` は 29.3.1 で止まっており、`--help` の実フラグは `--when-silent` / `--cut-out`。Windows 版バイナリの資産名も `auto-editor-windows-amd64.exe`（29.x）から `auto-editor-windows-x86_64.exe`（30 以降）に変わっている。
- 回避策 / 正しい手順: 固定している版の `--help` と実バイナリで必ず確認する。フラグ名は `autoeditor.py` の冒頭に注記した。移行時はここを直す。**→ 2026-10-03 に 31.7.2 へ移行し、`--when-inactive` を使う**（`--when-silent` も別名として残っているが正式名を使う）。
- 関連: `src/autoeditor.py`

## 2026-10-03 — `--cut-out` は1回に1区間しか取れない → v1 JSON を入力にする
- やったこと: VAD で得た多数の無音区間を `--cut-out 2sec,4sec 10sec,12sec` のように渡そうとした。
- 何が起きたか: `Input file must have an extension: 10sec,12sec`（空白区切りは入力ファイル扱い）。1区間を超えるカンマ連結は `--cut-out has too many arguments`。繰り返し指定も期待どおりにならない。
- 原因: 29.x の引数仕様。
- 回避策 / 正しい手順: auto-editor は v1 JSON を**入力**として受け取れる。直接実行と同じ出力になる（29.3.1 は Premiere XML が1バイトも違わず、FCPXML は複数トラックで名前だけ差があった。**31.7.2 は Premiere / Resolve / Final Cut Pro の全形式・複数トラック・29.97fps で完全一致**を実測）。区間を v1 JSON に書いて渡す（`vad.write_v1` → `build_cut_cmd_from_chunks`）。31.x の `--cut` は引数仕様が変わったが、この経路は変わらない。
- 関連: `src/vad.py`, `src/autoeditor.py`, `src/pipeline.py`

## 2026-10-03 — 「呼び出し回数 N 回目で停止」型のテストは、呼び出し順を変えると壊れる
- やったこと: 字幕用音声の組み立て方を変え、auto-editor の呼び出し順が変わった。
- 何が起きたか: `test_pipeline_should_stop` が失敗。`should_stop()` を数えて「8回目で停止」としていたため、停止が意図より早く発火した。
- 原因: テストが実装の呼び出し回数に結合していた。
- 回避策 / 正しい手順: 意図（文字起こしが済んだ後、2つ目の字幕を書く前に停止）を状態で表す。呼び出し回数でタイミングを指定しない。
- 関連: `tests/test_pipeline.py`

## 2026-06-20 — 「字幕切替えがカットに乗らない」をリグレッションと決めつけて追うな（margin由来の恒常仕様）
- やったこと/疑い: ユーザーが「映像カットと字幕切替えが一致しない。v1.0.0では揃っていた」と報告→ 直近の fcpxml reorder/relocate 改修を疑い、コード変更起点のリグレッションとして調査を開始しがち。
- 何が起きたか/真相: 実測で**コード由来のリグレッションは無かった**。v1.0.0 と現行は字幕SRT時刻もカットoffset集合もバイト等価（差はwhisper実行ゆらぎ≤40ms）。ズレの正体は **auto-editor が発話前後に margin(0.2s) を残してカット**するため、whisper がカット音声の**発話部分**を字幕化すると字幕境界がクリップ境界から**margin分内側**に入る恒常現象。実測差 +0.20s = margin そのもの。v1.0.0 でも同じだけズレていた。
- やりがちな失敗: (1)「最近の改修が原因」と決め打ちして reorder コードを弄る。(2) `--mix-audio-streams` がカットを変えると推測（実測では mix有/無でカット完全一致＝無関係）。(3) `language=None`化を疑う（small では分割が変わるが、実使用 medium では ja≡None で無影響）。(4) VFR を疑う（実ファイルは真の60fps CFR）。すべて実測で棄却される推測。
- 正しい手順: 「v1.0.0で揃ってた」系のリグレッション主張は、**実 v1.0.0 を同一入力・同条件で走らせて出力をバイト比較**して確定/否定する（`git show v1.0.0:src/app.py > scratch.py` で当時のモノリスを抽出し現行 `.venv` で起動できる＝旧exe不要）。本件はそれで非リグレッションを確定。字幕切替えをカットに乗せたいなら whisper 任せでは原理的に無理＝**既知カット境界(fcpxml offset)へSRT境界をスナップする後処理**が必要（別機能・MINOR）。
- 関連: `src/autoeditor.py`, `src/pipeline.py`(2a/2b), MEMORY 2026-06-20 03:15, CONTEXT §1

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
