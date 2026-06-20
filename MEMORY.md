# MEMORY.md — 意思決定ログ

> 「なぜそうしたか」を時系列で残す。実装を変えたら追記する。新しいものを上に。
> 失敗した手順そのものは PITFALLS.md、ここには**採用した決定とその理由**を書く。
> 見出しには**日付＋時刻**（`YYYY-MM-DD HH:MM`）を記載する。

書式:
```
## YYYY-MM-DD HH:MM — タイトル
- 決定:
- 理由:
- 影響/トレードオフ:
- 関連: ファイル/関数
```

---

## 2026-06-20 14:45 — SRT-snap 実装のレビュー検証＋lint緑化（レビュー: Opus 4.8）
- 経緯: Gemini 実装完了報告(commit d583a5d)を受け、設計書 `docs/handoff/P3-srt-snap.md` 突合でレビュー検証。
- 検証結果（設計準拠を確認）: ①純ロジック4関数は `src/subtitles.py`・UI非依存。②pipeline 統合は新ステップ2d=2c掃除後/`finally`(_tracks掃除)前・`is_fcpxml && srt_path && timeline.exists && !stopped` ゲート付き。③UI=チェックボックス既定ON・`is_fcpxml`(premiere除外)/字幕OFF で disabled・i18n ja/en 両添付・presets `SETTING_KEYS` に `snap_srt`・`_collect/_apply_settings` 往復。④全45テスト緑。⑤GUI construct スモーク（checkbox生成・既定True・destroy）OK。
- 検出＋対応: ruff 12件（W293 ブランク行空白＋I001 import整列）が未解消で **CI を落とす状態**だった。いずれも SRT 文字列リテラル内の真の空行(89/93/102/106)ではなく**コード字下げ空行**と確認のうえ自動修正。ロジック無変更（45テスト緑維持・全lintパス）。`style:` で Opus コミット(b4734b2、§6.1 編集者＝コミット者)。
- 残 DoD: **実機 DaVinci 目視（検証素材 `2026-06-20 10-56-29.mp4`・15.36/25.28/45.60 がカットへ乗り・20.64 は不動）はユーザー側で1回**（合成テストで機構は証明済み）。
- 関連: `src/subtitles.py`, `src/pipeline.py`, `src/app.py`, `tests/`, [[subtitle-cut-margin-inset]], [[role-boundary-opus-design-only]]

## 2026-06-20 14:30 — 字幕境界をカット境界へスナップする後処理(SRT-snap)の実装完了（作業: Gemini）
- 決定: 設計書 `docs/handoff/P3-srt-snap.md` に基づき、字幕境界スナップロジック（`parse_timestamp`, `parse_fcpxml_cut_boundaries`, `_fcpxml_time_to_seconds`, `snap_srt_to_boundaries`）を `src/subtitles.py` に、パイプライン統合（ステップ 2d）を `src/pipeline.py` に、UI制御（チェックボックス・字幕OFF/Premiere時の連動無効化・プリセット復元）を `src/app.py` / `src/presets.py` に実装完了。
- 理由: 承認された実装計画に沿って正確かつ堅牢に実装し、映像カットと字幕の切り替えの同期を実現するため。
- 影響/トレードオフ: スナップ処理は純後処理であり、処理負荷は極めて軽微。かつ「distinct時刻モデル」および各種ガード（同一字幕反転ガード・隣接逆転ガード）により、字幕順序の整合性と contiguous が完全に保証される。単体テストを `tests/test_subtitles.py` に 9 ケース、統合テストを `tests/test_pipeline.py` に 1 ケース追加し、全 45 テストのパスを確認。
- 関連: `src/subtitles.py`, `src/pipeline.py`, `src/app.py`, `src/presets.py`, `src/i18n.py`, `tests/test_subtitles.py`, `tests/test_pipeline.py`

## 2026-06-20 12:30 — 字幕境界をカット境界へスナップする後処理(SRT-snap)を設計＝MINOR新機能（設計: Opus 4.8）
- 経緯: ユーザーが本番素材 `2026-06-20 10-56-29.mp4`(4トラック)を 最新版/v1.0.0 双方で実機検証→「前セッションと変わらず」＝**非リグレッション(03:15)を実機再確認**。残る「字幕切替えがカットに乗らない」を直す後処理機能を作る選択（AskUserQuestionでユーザーがSRT-snap実装を選択）。
- 決定: 字幕(.srt)生成後に、生成済み fcpxml の既知カット境界(映像asset-clipの`offset`)へ字幕境界を **tolerance 内なら吸着**する純後処理を新設。設計書 `docs/handoff/P3-srt-snap.md`(Opus作成)→ 実装は Gemini。
- 実データ検証（本素材・44カット/45境界/45.533s）で設計を裏付け:
  - srt遷移 15.360→cut15.300(-0.060) / 25.280→25.133(-0.147) / 45.600→45.533(-0.067・超過解消) は**カット隣接→snap**。
  - srt遷移 20.640→最寄りcut21.117(**+0.477**) は**カット無し（発話中のwhisper文区切り）→動かさない**。
  - **真のカット隣接差≤0.147 / 偽の差0.477 で分離帯域が広い** → `tolerance = margin + 0.15 ≈ 0.35` で隣接のみ吸着し偽を除外。全字幕遷移がカットに対応するわけではない＝tolerance ゲートが肝（遠いカットへ寄せると逆に音とズレる）。
- 設計の肝: ①純ロジックは `src/subtitles.py`(`parse_fcpxml_cut_boundaries`/`_fcpxml_time_to_seconds`/`snap_srt_to_boundaries`/`parse_timestamp`)。②pipeline 新ステップ2d（2b後・finallyの`_tracks`掃除前・`is_fcpxml`ガード）。③`PipelineParams.snap_srt=True`(末尾・後方互換)＋UIチェックボックス「字幕をカット境界に合わせる」既定ON（字幕OFF/premiereで disabled）＋presets `SETTING_KEYS`に`snap_srt`。④distinct時刻モデルで start/end を統一remap＝contiguous維持・反転/衝突ガード。⑤fcpxml の `offset`(タイムライン位置)を使う＝`start`(ソースin点)ではない。
- 対象外: premiere(.xml)は境界構造が違い対象外。`_reorder_fcpxml_tracks`/relocate/`_tracks`掃除は不変。margin/threshold同期(P-2)不変。
- 区分: **MINOR機能（バグ修正ではない）**。CHANGELOG `[Unreleased]` Added へ。
- 関連: `docs/handoff/P3-srt-snap.md`, `src/subtitles.py`, `src/pipeline.py`, `src/app.py`, `src/i18n.py`, `src/presets.py`, [[subtitle-cut-margin-inset]], [[role-boundary-opus-design-only]], PITFALLS 2026-06-20(margin-inset)

## 2026-06-20 03:15 — 「字幕切替えが映像カットに乗らない」は非リグレッション＝margin由来の構造的インセット（診断: Opus 4.8 / systematic-debugging）
- 症状報告: ユーザーが実録画(`2026-06-19 22-55-03.mp4`, OBS 4トラック)を DaVinci 取込→「映像カットと字幕切替えが一致しない。v1.0.0では揃っていた」=リグレッション疑い。
- 棄却した仮説（すべて実測で否定）:
  - P-2(mix説): `build_cut_cmd`(timeline)と`build_extract_wav_cmd`(`--mix-audio-streams`付)で無音検出基準が違う説→ 実 auto-editor で同一素材を mix有/無で `--export resolve` 比較→ **カット完全一致(38セグ・offset/duration同一・40.583s)**。mix は無音検出を変えない。
  - VFR説: fcpxml が `FFVideoFormatRateUndefined`+60fps仮定→ ffprobe で `r=avg=60/1, nb_frames=5273, 87.88s` ＝**真の60fps CFR**。タイムベース正常。
  - language=None リグレッション説: P0で`language="ja"`→`None`化が唯一の字幕コード差分。small では ja=3セグ/None=7セグと**変わる**が、ユーザー実使用の **medium では ja≡None（境界17.60/36.60/40.60で完全一致）**→ 無影響。
- 決定的検証（ユーザー実施）: v1.0.0 のモノリス app.py を `git show v1.0.0:src/app.py` で抽出し現行 `.venv` で起動、**同一mp4を同条件で処理**→ DaVinci 目視。結果:
  - **カット位置(offset,duration)集合 = 現行と完全一致(38)**
  - **SRT時刻 = 現行と一致(差≤40ms＝whisper実行ゆらぎのみ)**: v1.0.0=17.60/36.60/40.60, 現行=17.56/36.56/40.56
  - **DaVinci目視も同一**＝v1.0.0でも字幕切替えはカットに乗っていない
  - ⇒ **コード由来のリグレッションは無い**。v1.0.0と現行は字幕・カットの出力時刻がバイト等価。
- 真因（恒常・設計由来）: auto-editor は発話の**前後にmargin(0.2s)を残して**カット→各クリップは発話端より0.2s外側に境界。whisperはカット音声の**発話部分**を字幕化するので、字幕境界は各クリップ境界から**margin分(0.2s)内側**に必ず入る。実測差 **+0.20s = margin そのもの**（17.60 vs カット17.40）。whisper任せで字幕切替えをカットに乗せるのは原理的に不可能。「v1.0.0で揃ってた」記憶は本素材で再現せず（別素材/当時非認知の可能性）。
- 残方針（未着手・ユーザー判断待ち→次セッション）: 本当に「切替えをカットに乗せる」なら **step2: 既知カット境界(fcpxml offset)へSRT境界をスナップする後処理**を新規実装（margin分シフト・model/言語非依存）。これは**機能追加(MINOR)であってバグ修正ではない**。設計=Opus→実装=Gemini。
- 検証アセット温存（次セッションの別録画再検証用）: `F:/20_Media_Production/21_Recordings/Games/仮フォルダ/` 配下に `_v100_app.py`(v1.0.0実行用), `_v100_out/`(v1.0.0出力), `_compare_current_v1.1/`(現行出力バックアップ)。不要になれば削除可。
- 関連: `src/autoeditor.py`(build_cut_cmd/build_extract_wav_cmd), `src/pipeline.py`(2a/2b), CONTEXT §1, PITFALLS 2026-06-20(margin-inset), [[snipsync-shared-design-docs]]

## 2026-06-20 02:30 — fcpxml トラック順: 本番録画素材で実機検証パス＝P3 クローズ（報告: ユーザー / 記録: Opus 4.8）
- 決定: Gemini 実装 #4（`sorted(wavs, reverse=True)`＋映像ブロック最後 / commit `c35bb01`）を本番の実録画データで実機検証し、**出力トラックの並びが元データと一致**することをユーザーが確認。P3「fcpxml 音声トラック順 reorder」を**クローズ**。
- 意味: MEMORY 01:50 の残 DoD「実機の本番素材（OBS/VRChat 等の実多トラック動画）での最終目視＝ユーザー側で1回」を充足。合成 E2E（証拠E）＋本番素材の二重確認で機構と実運用の両方が証明された。
- 補足: 設計書 `docs/handoff/P3-fcpxml-track-reorder.md`（Opus 作成）を docs としてコミット（§6.1 作者一致＝docs は Opus）。
- 関連: `src/pipeline.py` (_reorder_fcpxml_tracks), `tests/test_pipeline.py`, [[resolve-fcpxml-reverse-track-order]], PITFALLS 2026-06-20（逆順規則）

## 2026-06-20 01:50 — fcpxml 音声トラック順の真因＝Resolve は「文書の逆順」で割当（実測確定・診断: Opus 4.8）
- 経緯: Gemini が #4（wav降順→映像最後・未コミット）を実装後も「解消しない」とユーザー報告。systematic-debugging で Phase 4.5（4回失敗＝アーキ疑え）と判断し、推測を止めて**実機で割当規則を直接実測**した。
- 採取した証拠（合成4トラックmp4 + ホスト .venv の実 auto-editor + 実機 DaVinci Resolve 21）:
  - **証拠A（素の auto-editor resolve fcpxml）**: spine に asset-clip をフラット積層（lane 無し・同 offset）。文書順は「映像/ミックス先頭→_1,_2,_3 昇順」。asset-clip の `name` は全クリップ共通でプロジェクト名（順序判定に使えない＝asset `name` suffix で判定要は正しい）。
  - **証拠B（mp4 を直ドラッグ→Resolve が fcpxml 書き出し）**: 単一 asset-clip(ref=mp4)。ただし**インポートし直すと音声1トラックに潰れる**。
  - **重要発見**: fcpxml **インポート時、Resolve はメディアファイルを実プローブしない**。宣言 `audioChannels` と clip 構造をそのまま使う。→ 単一 mp4 参照に畳む案（C）は**1トラックにしかならず棄却**。4トラック出すには音声 clip が4つ必要＝auto-editor の wav 分割は必然。
  - **証拠D（割当規則の直接測定）**: 区別名の音声4本を文書順 NAME01→02→03→04 で積層→インポート。結果 **A1=NAME04, A2=NAME03, A3=NAME02, A4=NAME01**。⇒ **Resolve は spine の音声 clip を「文書の逆順」でトラック割当する（最後の clip→A1/最上段）**。これが全並べ替え失敗の真因。
  - **証拠E（現コード #4 の実出力を実機検証）**: 実 mp4+wav 混合・2セグメントで #4 出力をインポート→ **A1=cut.mp4(T1), A2=cut_1, A3=cut_2, A4=cut_3 / 各2クリップ / V1 あり**＝**正順展開を確認**。
- 決定: **未コミットの #4（`sorted(wavs, reverse=True)` で wav 降順→映像ブロックを最後に append）は実機上正しい。これを採用・コミットする（実装者 Gemini がコミット＝§6.1）**。コード変更は不要。コメントの「Resoveの逆順展開を考慮」は本実測で裏付け済み。
- 「解消しない」の真因: ユーザーが**コミット済み旧版 #3（昇順, cdbd933）で検証**していた。#3 は昇順→逆順割当で順序反転→狂う。#4（降順）未コミット分が未検証だった。
- 残 DoD: 合成での E2E は確定。**実機の本番素材（OBS/VRChat 等の実多トラック動画）での最終目視はユーザー側で1回実施**を推奨（機構は証明済み）。
- 関連: `src/pipeline.py` (_reorder_fcpxml_tracks), `tests/test_pipeline.py`, PITFALLS 2026-06-20（逆順規則）, [[role-boundary-opus-design-only]]

## 2026-06-20 00:30 — Resolveインポート時の音声トラック減少バグ対応（決定: 作業/Gemini）
- 決定: `_reorder_fcpxml_tracks` において、`asset-clip` の `name` 属性を書き換える処理（`_A1`, `_A2` などのサフィックス付与）を廃止し、元の stem 名を維持するように変更。
- 理由: 実機検証で音声トラックが4トラックから3トラックに減少したため。クリップ名を書き換えた結果、Resolve インポーターがそれらを同一のマルチトラックグループと関連付けられなくなり、トラック自動展開時に競合が起きて最後のトラック（A4）がスキップされていたことが原因。名前を変更せず、物理的なブロック出現順（ソート順）による整列だけを行えば、Resolve 側で正常に4トラックとして展開される。
- 影響/トレードオフ: タイムライン上のクリップ名はすべて元の stem 名で統一される（auto-editor 本来の挙動と一致）。
- 関連: `src/pipeline.py` (_reorder_fcpxml_tracks), `tests/test_pipeline.py` (test_reorder_fcpxml_tracks_comprehensive)

## 2026-06-20 00:10 — FCPXML 音声トラック順並べ替えをフラット構造維持に変更（決定: 作業/Gemini）
- 決定: `_reorder_fcpxml_tracks` において、`lane` ネストによる connected clip を廃止し、spine 直下にすべてのクリップをフラットに並べる元の構造を完全に維持したまま、出現順（物理的な並び順）のみを元のストリーム順に整列する方針に変更。
- 理由: 実機検証において、`lane` ネスト構造を DaVinci Resolve にインポートした際、映像クリップ（V1）が消失し、音声トラックが細切れに分裂（A1〜A15等）する重大なバグが発生したため。Resolve の XML インポーターのバグ（制限）を回避しつつトラックの順序を正常化するには、元のフラット構造を崩さずにセグメント内の出現順を統一するのが安全かつ確実と判断。
- 影響/トレードオフ: 各クリップ自身の `offset` や `start` などの属性値は完全に維持されるため、互換性が非常に高い。`lane` 属性を使用しない。
- 関連: `src/pipeline.py` (_reorder_fcpxml_tracks), `tests/test_pipeline.py` (test_reorder_fcpxml_tracks_comprehensive)

## 2026-06-19 23:50 — FCPXML 音声トラック順並べ替えの正規化（決定: 作業/Gemini）
- 決定: FCPXML タイムラインの音声トラック順を元のストリーム順に整列する正しい並び替えロジックを実装。
- 理由: auto-editor が spine 直下に asset-clip をフラット列挙するため NLE (DaVinci Resolve等) でトラック順が狂うバグを解消するため。以前の試作 (stash) で発生した「全セグメントが1つに潰れる（31セグメント中30個が消滅する）」というバグを完全に回避し、`(offset, duration)` でグループ化（セグメント化）して元のセグメント数を厳密に維持したまま、映像付きアセットを primary (lane 0)、wav アセットを lane=-1, -2, -3... のネスト構造に再構成する。
- 影響/トレードオフ: 各クリップ自身の start/duration を維持して lane 内にネストさせるため、トラックごとにイン点（start）が異なる場合でもズレが発生しない（堅牢性を向上）。異常な XML（映像アセットがない、または重複があるなど）の場合は、安全のために並べ替えをせず False を返して native を全保持する。
- 関連: `src/pipeline.py` (_reorder_fcpxml_tracks, run_pipeline), `src/i18n.py`, `tests/test_pipeline.py` (test_reorder_fcpxml_tracks_comprehensive ほか)

## 2026-06-19 23:20 — fcpxml トラック順 reorder 試作は破壊的→退避し設計書化（決定A 初適用）（診断: Opus 4.8）
- 経緯: 実機(DaVinci)検証で「元/出力のトラック順不一致」を確認するためアプリ起動。ユーザーが出力 fcpxml 自体のバグを指摘。
- 診断（実測）: 出力 fcpxml の spine は asset-clip **1個(2.2秒)** のみ＝タイムライン崩壊。素の auto-editor 出力を別途生成し XML 実検査→ spine は **124 asset-clip = 31セグメント×4トラック**をフラット列挙（lane 無し・各セグメントに4ref）。asset id は名前順でない（r2=_1, r4=_3, r6=_2, r8=mp4/hasVideo=1）。順序判定は asset `name` suffix で行う必要。
- 真因: 未コミットの試作 `_reorder_fcpxml_tracks` が構造を誤解。「4 asset-clip=1トラックずつ」と仮定し **clips[0] だけテンプレ化→全削除→1個再生成**。31セグ中30消滅。lane 無し offset 重複（=Resolve のトラック割当推測）が元々の順序ズレ真因で、それを直そうとして自爆。
- 決定（ユーザー選択: まず破損コードを退避）: 試作 reorder 一式(pipeline/i18n/tests)を `git stash@{0}` へ退避し working tree を **native+relocate（動く版・commit 5908ae4）** へ復帰。MEMORY 22:10 決定エントリ(staged)は退避対象外で維持。アプリ再起動済。
- 次手: 決定A（22:10）初適用として **設計書 `docs/handoff/P3-fcpxml-track-reorder.md` を Opus が作成→実装は Gemini**。正しい設計＝124を(offset,duration)で31セグへ集約し、各セグメント primary=映像asset(lane0)＋wavを元ストリーム順で lane-1,-2,-3 ネスト。**全セグメント保持／primaryのstartをネストへ流用しない**を厳守事項として明記。
- 協業: 本ターンは診断＋退避＋設計のみ＝Opus 役割内。実装は Gemini へ。[[role-boundary-opus-design-only]]
- 関連: `docs/handoff/P3-fcpxml-track-reorder.md`, `git stash@{0}`, `src/pipeline.py`, PITFALLS 2026-06-19(追記予定)

## 2026-06-19 22:10 — 協業分担の是正: 実装は Gemini へ正規ハンドオフへ復帰（決定: Opus 4.8）
- 経緯: 本セッションで Opus が pipeline/i18n/tests の実装を連続実施（_tracks relocate=B案、トラック順序整列）。ユーザーが「Gemini に渡さない理由」を質問→ Opus が「強い正当化は無い・速度優先の逸脱」と率直回答。是正案A/B/Cを提示しユーザーは **A** を選択。
- 決定: **今後の実装は設計書(`docs/handoff/`)化して Gemini へハンドオフ。Opus は設計・レビュー・診断に戻る**（[[role-boundary-opus-design-only]] / AGENTS §6.1 の本来運用へ復帰）。密ループだからと Opus 実装を続ける運用(C)は規律形骸化として却下。
- 在庫(in-flight)の扱い: 既に Opus が書いた「順序整列」コードは未コミット。author-match(§6.1)上は書いた本人=Opus がコミットしてよいが、**実機(Resolve)で lane 解釈の効果を検証してから**判断:
  - 効けば → Opus が自分の既存実装をコミット（逸脱は本ログで記録済）。
  - 要修正(lane→role 等の作り直し)→ **設計書を切って Gemini が実装**（A 適用の最初の実例）。
- 今後の新機能/改修は最初から Gemini 着手（設計=Opus→ハンドオフ→実装=Gemini→作者がコミット）。
- 関連: AGENTS §6.1, [[role-boundary-opus-design-only]], `docs/handoff/`

## 2026-06-19 16:50 — 多トラック音声 fcpxml の `_tracks` を掃除でなく出力先へ relocate（B案）（頭脳兼作業: Opus 4.8）
- 経緯: ユーザーが OBS 4トラック収録動画を resolve 出力→DaVinci 取込で「T1(全音声ミックス)だけ残り他3トラック未検出」と報告。
- 診断（実測で仮説訂正）: 初期仮説「auto-editor が fcpxml に音声1本しか宣言しない」を、合成4トラックmp4で resolve/premiere 両出力を生成し XML を実検査して**否定**。真因は **SnipSync 自身の `_tracks` 掃除（2026-06-19 初版）**。fcpxml は4トラックを宣言するが各分解トラックを `{stem}_tracks/*.wav` の絶対 file:// 参照で持つ→そのWAVを rmtree した3本が参照切れ。元mp4参照(映像+T1)だけ残存し報告と一致。premiere(.xml) は元mp4直参照だが DaVinci が分離4ストリームを trackindex 展開できず 8トラック/6無音（別問題・回避不可）→ resolve fcpxml + WAV温存が唯一クリーンと判断。
- 決定（B案採用・ユーザー選択）: fcpxml(resolve/final-cut-pro) のとき `_tracks` を**削除せず `out_dir` へ移動し、fcpxml 内の参照パスを書き換える**。premiere(.xml) は不要アセットゆえ従来どおり掃除。
- 実装の肝: `pipeline._rewrite_fcpxml_track_paths`（forward-slash優先・backslash保険でパス文字列置換）＋ step1直後・step2(字幕WAV抽出)**前**に relocate（2a が `_tracks` を再生成し得るため）。`out_dir==inp.parent` は移動不要で温存(`tracks_keep_in_place`)。移動失敗時も参照保護で温存にフォールバック。pre-existing フォルダは従来どおり不可侵。finally は「温存判定でない」場合のみ掃除（relocate後に2aが残したクラッタを削除）。
- i18n: `log_tracks_relocated` を ja/en 追加。
- 検証: 全32テスト緑（relocate(fcpxml)/cleanup(premiere) 2本に再編・+1）/ruff クリーン。実 auto-editor + 合成4トラックmp4で `run_pipeline(resolve)` E2E → 入力dirクリーン・出力dirに `_tracks` 移動・fcpxml の3 WAV参照が出力先へ書換、を確認。**DaVinci 実機での最終目視はユーザー側で実施予定（未）**。
- 協業逸脱: app実装(pipeline/i18n/tests)につき本来 Gemini 領域。ユーザー直接指示「Bで修正して」＋当セッション Opus 一貫のため Opus 実施。要望を鵜呑みにせず実測で初期仮説を訂正した点は AGENTS「矛盾は確認」に沿う。次の機能実装は通常分担へ。[[role-boundary-opus-design-only]]
- 関連: `src/pipeline.py`, `src/i18n.py`, `tests/test_pipeline.py`, `PITFALLS.md`（2026-06-19 fcpxml _tracks）

## 2026-06-19 — GPU(CUDA)字幕生成を Windows で実際に動作させる（venv内CUDAライブラリ）（頭脳兼作業: Opus 4.8）
- 経緯: 実機(NVIDIA GPU)で「GPU使用」チェック→ログ「GPU初期化に失敗。CPUにフォールバック」。診断で実例外 `RuntimeError: Library cublas64_12.dll is not found or cannot be loaded` を捕捉。原因: GPUドライバは在るが CUDA ランタイム(cuBLAS/cuDNN/cudart)が不在。`faster-whisper`/`ctranslate2` pip導入では同梱されない（CONTEXT §7 / README既述）。フォールバックは設計通りの正常動作だった。
- 決定: ホストにCUDA Toolkitを入れず、**nvidia-* wheel を venv 内に導入**してホスト非汚染のままGPU有効化。`pip install nvidia-cublas-cu12 nvidia-cudnn-cu12 nvidia-cuda-runtime-cu12`（DLLは `.venv/site-packages/nvidia/*/bin`）。pyproject に opt-in extra `[gpu]` を追加し再現可能化（`pip install -e ".[gpu]"`）。
- 実装の肝（実測で確定）: 導入しただけでは ctranslate2 がDLLを発見できず同エラー継続。**インポート/モデル構築前に nvidia の各 `bin` を `os.add_dll_directory` ＋ `PATH` 前置**すると cuda デコード成功。`add_dll_directory` 単独では不足で **PATH 前置が必須**だった（Windows の LoadLibrary 探索のため）。→ `subtitles.add_cuda_dll_dirs()`（win限定・nvidia不在/非win/再実行はno-op・1回限り）を新設し、`pipeline._decode` の cuda モデル構築直前(`dev=="cuda"`)で呼ぶ。
- 検証: 実 `run_pipeline(use_gpu=True, do_srt=True, model=medium)` で `device=cuda` ログ・フォールバック無し・srt生成・`_tracks`掃除を同時確認。全31テスト緑（DIモック経路は `add_cuda_dll_dirs` 不通過のため無影響）/ruffクリーン。
- トレードオフ: `[gpu]` extra は約1.3GB(cublas553MB/cudnn690MB/cudart/nvrtc)。既定 deps には入れない(opt-in)。配布EXEは引き続きGPU非同梱（利用者システムにCUDA要）。README(4言語)はEXE向け記述のまま正(venv [gpu] 経路は pyproject コメント＋本ログに記録)。
- 協業逸脱: アプリ実装(subtitles/pipeline)につき本来Gemini領域だがユーザー直接指示＋当セッションOpus一貫で実施。記録のみ。[[role-boundary-opus-design-only]]
- 関連: `src/subtitles.py`(add_cuda_dll_dirs), `src/pipeline.py`(_decode), `pyproject.toml`([gpu]), README動作要件

## 2026-06-19 — auto-editor の `{stem}_tracks` 残骸を処理後に自動掃除（頭脳兼作業: Opus 4.8）
- 経緯: 実動画（VRChat収録・音声3トラック）を初めて実パイプラインに通したところ、出力先とは別に**元動画の隣に `{stem}_tracks` フォルダ**（`_1.wav`/`_2.wav`/`_3.wav`＝トラック別展開）が残ると報告。ユーザーは「auto-editor に `--temp-dir` を渡す改修」を要望。
- 検証で要望案を棄却: 多トラック動画＋`--temp-dir <空dir>` で実測 → **`_tracks` は依然として入力の隣に出現し、指定 temp-dir は空のまま**。`--help` にもトラック出力先の制御/抑制フラグ無し。つまり `--temp-dir` ではこのクラッタを消せない（PITFALLS 追記）。
- 決定: auto-editor 側で抑止できないため、**SnipSync 側で処理後に掃除**する方式を採用（既存の一時WAV削除と同じ思想）。`run_pipeline` 冒頭で `tracks_dir = inp.parent/f"{inp.stem}_tracks"` の**事前存在を記録**し、`finally` で「本実行中に出現した場合のみ」`shutil.rmtree`。停止/失敗時も必ず後始末されるよう finally に配置。既存ユーザーデータ保護のため事前存在分は温存。
- i18n: `log_tracks_cleaned` を ja/en 追加（AGENTS §4.1）。ログは muted。
- テスト: `test_pipeline_tracks_cleanup`（新規出現分を削除＋ログ確認）/ `test_pipeline_tracks_preexisting_preserved`（事前存在は保護）を追加。全 31 passed（既存29＋2）。ruff クリーン。
- 検証: 実 auto-editor で多トラックmp4を `run_pipeline`（do_srt=False）に通し、処理後 src 隣に `_tracks` が残らない（src=動画のみ / out=fcpxml）ことをE2E確認。※検証harnessのconsole(cp932)が auto-editor の絵文字 `⏳`/`❌` で UnicodeEncodeError を起こしたが、これは print harness 固有で実アプリ（Tkログ欄）は無関係。
- 協業逸脱: 本変更は `src/pipeline.py`/`src/i18n.py`/tests の**アプリ実装**で本来 Gemini 領域（[[role-boundary-opus-design-only]]）。ユーザー直接指示＋当セッションが Opus 実装で一貫のため Opus が実施。次の機能実装は通常分担へ戻す。なお要望(`--temp-dir`)を鵜呑みにせず実測で否定し代替実装した点は AGENTS「矛盾は勝手に直さず確認」に沿い、根拠を本ログに残す。
- 関連: `src/pipeline.py`(tracks掃除), `src/i18n.py`(log_tracks_cleaned), `tests/test_pipeline.py`, `PITFALLS.md`

## 2026-06-19 — venv をホスト汚染境界に据える（依存 pyproject 単一ソース化）＋ホスト/コンテナ役割明文化（頭脳兼作業: Opus 4.8）
- 経緯: Dev Container 導入（2026-06-18）後、ユーザーが「ガイドの目的＝ローカル環境を汚さないが達成できているか」を診断要求。診断結論: コンテナは test/lint/agent は隔離できるが、SnipSync は GUIデスクトップ → headless で描画不可 → DoD#1 目視確認はホスト直実行 → **ホストに重依存フル導入が残り、汚染防止は半達成**。改善案として「ホスト venv を汚染境界の主役に、依存は pyproject 単一ソース、コンテナは lean のまま割り切り」を提案・採用。
- 決定1: 開発は `.venv` に隔離（`.gitignore` 済を確認）。依存導入を `pip install auto-editor faster-whisper customtkinter tkinterdnd2`（手書きリスト）から **`pip install -e ".[dev]"`** へ。pyproject の `dependencies` / `optional-dependencies` を単一ソース化し、3箇所（pyproject/requirements/postCreate）手書きのドリフトを解消。新規依存は pyproject だけに足す運用。
- 決定1の検証（仮定で文書化しない）: `src/` はフラット配置（正式パッケージ化前・ARCHITECTURE §2）のため `pip install -e .` がパッケージ認識できるか懸念 → 使い捨て venv で `pip install -e . --no-deps` を実行し成功、`find_spec` で `app`/`pipeline`/`presets` が `src/*.py` として解決されることを確認（setuptools が src-layout 自動認識）。重依存DLなしの高速検証。`[build-system]`/`[tool.setuptools]` の追記は不要だった。
- 決定2: ホスト venv とコンテナの役割を明文化。**ホスト `.venv`＝重依存フル（GUI目視確認・実パイプライン）/ Dev Container＝lean（test/lint/agent、subprocess・transcribe をモックするため auto-editor/faster-whisper を入れない）**。コンテナ postCreate はあえて `-e .[dev]` にせず lean 維持（ビルド高速・テスト利得ゼロのため）。理由を devcontainer.json コメントに明記。
- 決定3: ドキュメント反映先。AGENTS §3（正典・venv＋単一ソース）、CONTRIBUTING §4.0（新設・汚染境界とホスト/コンテナ分担）、devcontainer.json（分担コメント）。README Option B（4言語・エンドユーザ向け run-from-source）は今回未変更＝開発フローとは別レイヤ。同期は任意のフォローアップ（ユーザー判断待ち）。
- 協業逸脱: 本来 実装=Gemini だが、CI/lint/container と同じ**非UIインフラ設定＋ドキュメント**かつユーザー直接指示のため Opus が実装（2026-06-18 と同じ前例運用）。次の機能実装は通常分担へ戻す。[[role-boundary-opus-design-only]]
- 実施済み(2026-06-19 同日): 実 `.venv` を作成し `pip install -e ".[dev]"` 完了。venv内で pytest 29 passed / ruff クリーン / GUI 起動・目視確認OK。後続で GPU extra も導入（同日の別ログ参照）。i18n: UI 文字列変更なし → ja/en 追記 N/A。
- 関連: `AGENTS.md` §3, `CONTRIBUTING.md` §4.0, `.devcontainer/devcontainer.json`, `pyproject.toml`, `.gitignore`

## 2026-06-18 — CI/CD・リリース段階切り分け・Dev Container 導入 + ruff 整備（頭脳兼作業: Opus 4.8）
- 経緯: ワークフロー標準ガイド（Obsidian `App-Dev-Workflow-2026-Standard-Guide.md`）への準拠度を診断 → 芯（SDD/Git/Pitfalls）は良好だが **CI欠落・lint無し・段階切り分け無し** が判明。ユーザー指示で3点を実装。
- 決定1 (lint): `ruff` を採用し pyproject `[tool.ruff]` に集約。`select=E,F,W,I,B,UP` / `line-length=100` / `target-version=py310`。既存モノリス app.py を大量リフローしないため `ignore=E501,E701,B007`（スタイル系のみ。ARCHITECTURE §2 の分割時に締める）。209件の指摘は安全自動修正（W293空白141/I001/E401）+ 実バグ手修正（F401×10, F841×4, E741×3）で解消。
- 決定1の要注意: app.py の `APP_VERSION`/`format_timestamp` は **test_p0 用の再エクスポート**、`WhisperModel` は **可用性プローブ用 import** → 削除すると test破壊/機能破壊。`# noqa: F401` で保持（PITFALLS追記）。`subprocess/time/traceback`(app)・`Path`(autoeditor) は真の不要 import で削除。pipeline の `except ... as e:` で e未使用（format_exc 使用）の3箇所を bare `except` 化。
- 決定2 (CI): `.github/workflows/ci.yml`。lint=ubuntu / test=windows-latest × py3.10/3.11/3.12。**重依存（auto-editor/faster-whisper）は入れない** — テストは subprocess/transcribe をモックするため `customtkinter+pytest` のみで 29件グリーン。高速・安定。
- 決定3 (段階切り分け): スタンドアロン .exe にサーバ無 → guide §5/§10-2 の dev→staging→prod を **リリースチャネル**に写像。`.github/workflows/release.yml`（tag `v*` 起動）: `-rc/-beta/-alpha` 接尾辞（AGENTS §5.1）を検出し **prerelease=staging / stable=production**。GitHub Environments を job に紐付け、`production` に required-reviewer 保護を掛ければ **prod公開前の人間ゲート**になる。tag と `APP_VERSION` の不一致を CI で fail（§5 整合の機械強制）。`environment:` は steps出力を読めないため classify/build の2ジョブ分割（needs経由）。
- 決定4 (Dev Container): `.devcontainer/devcontainer.json`（image=python:3.12-bookworm, Codespaces互換）。postCreate で ffmpeg+python3-tk+ruff/pytest/customtkinter。**GUIは headless で描画不可** → 最終目視確認(DoD#1)は Windows ホスト維持、コンテナはテスト/lint/AIエージェント用と明記。
- i18n: 本変更は UI 文字列追加なし → ja/en 追記 N/A。
- 協業逸脱: 本来 実装=Gemini だが、ユーザー直接指示「作って」かつインフラ設定（CI/lint/container＝非UIコード）のため Opus が実装。P1 と同じ前例運用。次の機能実装は通常分担へ戻す。
- 検証: `ruff check .`=All passed / `pytest`=29 passed / app import スモーク OK。**GUI目視確認は未（ホスト人手要）**。CI/release は YAML/JSON 構文検証のみ（実 push 未）。
- 関連: `.github/workflows/{ci,release}.yml`, `.devcontainer/devcontainer.json`, `pyproject.toml`, `src/{app,autoeditor,pipeline}.py`, `tests/{test_p0,test_pipeline,test_presets}.py`

## 2026-06-17 05:28 — code-review 指摘5件の実装完了とテスト追加（作業: Gemini 3.5）
- 決定: 設計書 `docs/handoff/P3-review-fixes.md` に従い、GPUフォールバックバグ修正、多言語化（log_whisper_unavailable）、log_errorプレースホルダ修正、プリセット適用時モデルガードの5件を実装。
- 理由: CUDA OOM 等の実行時エラーが遅延ジェネレータの遅延評価（イテレーション）時に発生するため、確実に try-except 内で捕捉して CPU 再試行にフォールバックできるようにするため。また、既存コードの i18n 違反や不整合を解消するため。
- 影響/トレードオフ:
  1. `list(seg_iter)` でデコードを一括完走させてから SRT 書き込みを行うため、デコード中に 1 字幕ずつログ出力されていた動作は、デコード完了後に一括でログ出力されるように変更された。デコード中の進捗を隠さないよう、`log_srt_analyze` で開始情報を出力する。
  2. 遅延ジェネレータがイテレーション中に例外を投げる状況を再現するモックテスト (`test_pipeline_gpu_fallback_lazy_generator`) を追加し、フォールバックの動作検証を確実にした。
- 関連: `src/pipeline.py`, `src/app.py`, `src/i18n.py`, `tests/test_pipeline.py`

## 2026-06-17 05:45 — code-review 指摘5件の修正設計（頭脳: Opus 4.8）
- 経緯: `feat/p1-refactor`（P1/P2全実装・8コミット）へ /code-review high。確定5件。設計書 `docs/handoff/P3-review-fixes.md` を作成（実装は🔧Gemini）。
- 確定した実バグ #1: faster-whisper `transcribe()` は**遅延ジェネレータ**。実デコードは `segments` 反復時（SRT書込ループ）に起きるため、GPUフォールバックの try が model構築/呼出までしか覆っておらず、**デコード途中のCUDA実行時エラー（OOM等）がフォールバックを素通り**→ `log_unexpected` で握りつぶし＝CPU再試行されない。DIモックが即時例外で落ちるためテストでは露見しなかった。修正方針=`list(seg_iter)` で try 内にデコードを完走させ、フォールバック時 device/compute_type を同時にCPUへ。トレードオフ: デコード中のライブ字幕ログが一括化（正確性優先、GPUはopt-in/稀）。
- #2: `app.py:702` whisper未導入メッセージが日本語ハードコード（i18nキー無し）→ `log_whisper_unavailable` を ja/en 追加。P-1違反、P1/今回の取りこぼし。
- #3: `resolve_device` の `compute_type` が実パスで未使用（ハードコード）→ WhisperModel に渡す。#1と同ブロックで同時修正。
- #4: プリセット無効モデルキーのガード（将来のモデル改名/削除用）。#5: `log_error` 空detail（stderrはstdoutマージで既にライブ表示）→テンプレ単一化。
- 偽陽性として棄却2件（証拠付）: gpu_checkbox AttributeError（`_build_ui` がL95でL98チェック前に生成）/ `info` NameError（失敗transcribeはL190 re-raise→外側exceptでL209到達せず）。
- 協業: 設計=Opus（本コミット）、実装=Gemini。
- 関連: `docs/handoff/P3-review-fixes.md`, `src/pipeline.py`, `src/app.py`, `src/i18n.py`, `tests/test_pipeline.py`

## 2026-06-17 05:30 — バージョニング規則の策定（頭脳: Opus 4.8）
- 決定: SemVer 2.0 を正式採用し AGENTS.md §5 を「既知の不整合」記述から正式な規則へ書き換え。
- 桁の SnipSync 固有定義: MAJOR=ユーザー互換性破壊（出力XML構造変更でNLE取込不可 / エクスポート形式削除 / presets.jsonスキーマ破壊 / 対応NLE廃止 / 最低要件引上げ）、MINOR=後方互換の機能追加、PATCH=機能追加なしのバグ修正のみ。内部リファクタは単独では桁を動かさず相乗り。
- 単一ソース: `src/version.py` の `APP_VERSION`（既に 1.0.0 で一元化済・UIは参照のみ）。
- リリース手順を6ステップで固定（version→CHANGELOG確定→README4言語→chore(release)コミット→git tag→exe）。プレリリースは `-rc.N`/`-beta.N`。
- 次リリース判定: `[Unreleased]` にプリセット/GPU/即時停止＝**機能追加あり** → MINOR → 次は **1.1.0**（PATCHではない）。確定はリリース時。
- 経緯: ユーザーが非開発者向けに MAJOR(互換性破壊)の噛み砕き説明を要望→平易な例示で合意。記載先は AGENTS §5 拡張をユーザー選択。
- 関連: `AGENTS.md` §5, `src/version.py`, `CHANGELOG.md`, README×4

## 2026-06-17 05:10 — P2 完了の整理 + Gemini出力言語ルール追加（頭脳: Opus 4.8）
- 決定1: Gemini の出力する "Implementation Plan" / "Walkthrough" は**日本語で記述**するルールを AGENTS.md §4.1 に追記。理由: レビュー効率・チーム言語統一。見出し名は英語可・本文は日本語。
- 決定2: P0/P1/P2 が全完了（Gemini 実装 commit bab6009/3a95c9d ほか、tree clean）したのを受け、ドキュメント同期を実施。
  - CHANGELOG `[Unreleased]`: P1（モノリス分割・テスト・pyproject）・P2（即時停止・GPU・プリセット）を Added/Changed に反映。解消済みの「停止が即時でない」を Known Issues から削除。
  - ROADMAP: 完了 P0–P2 を削除（ROADMAP 自身のルール「完了は CHANGELOG へ移し消す」に従う）。残課題を P3（バッチ処理・macOS調査・完全パッケージ化）へ再編。
- 影響: ROADMAP に未着手 design タスクなし → 次の Opus 着手は P3（要精査）。優先度はユーザー確認待ち。
- 協業: 本コミットは docs のみ → Opus がコミット（AGENTS §6.1 作者一致）。
- 関連: `AGENTS.md`, `CHANGELOG.md`, `ROADMAP.md`

## 2026-06-17 04:38 — P2 出力プリセット保存の実装完了（作業: Gemini 3.5）
- 決定: 設計書 `docs/handoff/P2-output-presets.md` に基づき、名前付きプリセット保存/読込/削除および前回終了時設定の自動復元機能（last_used）を実装。
- 理由: ユーザーが起動するたびに設定を再入力する手間を排除し、よく使用する設定の組み合わせを簡単に保存・復元できるようにするため。
- 実装詳細:
  1. 新規 `src/presets.py` を作成し、Tk/UI 依存なしのピュア Python モジュールとして JSON I/O をカプセル化（`%APPDATA%/SnipSync/presets.json` への読み書き）。
  2. 既存の GPU オプトイン対応に合わせて `SETTING_KEYS` に `"gpu"` を追加。存在するキーだけを読み書き・適用する前方/後方互換設計。
  3. `src/app.py` にて `_collect_settings()` と `_apply_settings()` を実装し、UI 側での Tk 変数と辞書の相互変換をハンドリング。適用後はスライダーと値ラベル、SRT オプションを双方向同期。
  4. 設定カード上部にプリセット OptionMenu、および「保存」「削除」ボタンを追加。言語切替 (`_apply_lang`) の同期、起動時の last_used 復元、`WM_DELETE_WINDOW` 終了時の last_used 自動保存を実装。
  5. `src/i18n.py` に `preset_label` / `preset_none` / `preset_save` / `preset_delete` / `preset_name_prompt` / `log_preset_saved` / `log_preset_deleted` を日英双方に追加。
  6. 新規 `tests/test_presets.py` で temporary directory の隔離環境で load/save、壊れた JSON 処理、日本語/マルチバイト名の upsert/delete、last_used の往復をテスト。
- 検証: `tests/test_presets.py` を含む全 25 テストがグリーンであることを確認。
- 関連: `src/presets.py`, `src/app.py`, `src/i18n.py`, `tests/test_presets.py`, `ROADMAP.md`

## 2026-06-17 04:32 — P2 GPU対応の実装完了（作業: Gemini 3.5）
- 決定: 設計書 `docs/handoff/P2-gpu-support.md` に基づき、オプトイン方式の GPU (CUDA) サポートを実装。
- 理由: CUDAが利用可能な環境で ASR 字幕生成の処理速度を向上させるため。
- 実装詳細:
  1. `src/subtitles.py` に `cuda_available()` と `resolve_device()` を実装。
  2. `src/pipeline.py` にて `PipelineParams` に `use_gpu` を追加し、`resolve_device` を経由してモデルの初期化を行う。GPU での初期化・処理に失敗した場合は CPU での 1 回リトライ（フォールバック）を行い、その旨を警告ログとして可視化。
  3. `src/app.py` にて設定 UI 内に GPU チェックボックスを新設（既定 OFF、CUDA 不在または字幕機能 OFF 時は disabled）。
  4. `src/i18n.py` に `gpu_label` / `log_device` / `log_gpu_unavailable` / `log_gpu_fallback` キーを日英辞書に追加。また、`pipeline.py:211` の cleanup 警告を i18n 経由 (`log_cleanup_failed`) に修正。
  5. 各 `README*.md`（4言語）の動作要件に GPU 要件を追記。
- 検証: `tests/test_pipeline.py` に `cuda_available`、`resolve_device`、GPU フォールバックの単体・統合テストを追加し、既存テストを含む全 19 テストがグリーンであることを検証。
- 関連: `src/subtitles.py`, `src/pipeline.py`, `src/app.py`, `src/i18n.py`, `tests/test_pipeline.py`, `README.md`, `README_JA.md`, `README_KO.md`, `README_ZH.md`, `ROADMAP.md`

## 2026-06-17 04:26 — P2 残2件（GPU対応 / 出力プリセット）の設計（頭脳: Opus 4.8）
- 決定: 即時停止(課題C)の実装完了(commit 0dbe9e9)を受け、P2 残りの2件を設計。設計書を2本作成（実装は🔧Gemini へハンドオフ）: `docs/handoff/P2-gpu-support.md`, `docs/handoff/P2-output-presets.md`。
- GPU判断: CUDA/cuDNN は **EXE 非同梱**（CONTEXT §7 / 配布肥大回避）。**オプトイン（既定OFF）+ `ctranslate2.get_cuda_device_count()` 自動検出 + GPU失敗時CPUフォールバック**。compute_type は GPU時 `int8_float16` / CPU時 `int8`。`PipelineParams.use_gpu`（末尾・既定False＝後方互換）で意図のみ渡し、`subtitles.resolve_device()` で解決（UI非依存維持）。新規依存なし（torch等足さない）。
- プリセット設計: 新規 `src/presets.py`（Tk非依存・JSON I/O のみ）に store 操作を閉じ、UI が Tk変数⇄dict 変換を担当。永続先 `%APPDATA%/SnipSync/presets.json`（utf-8/ensure_ascii=False）。名前付きプリセット 保存/読込/削除 + 前回設定の自動復元(last_used, WM_DELETE_WINDOW)。壊れ/不在JSONでも落ちず既定構造。
- 並列性: 2件とも `app.py` 設定UI + `i18n.py` を編集 → **実装は直列**（後発リベース）。設計(本タスク)は衝突なしで両方先行。GPUの `gpu` キーはプリセットの「存在キーだけ読む」設計で順序非依存。
- 発見(未修正・Geminiへ申し送り): `pipeline.py:211` の `"Temp file cleanup failed: {e}"` は**ハードコードEN文字列**（AGENTS §4.1 / P-1 違反）。即時停止実装の取りこぼし。次の実装タスクで i18n キー化推奨。
- 協業: 設計=Opus（本コミット）、実装=Gemini（AGENTS §6.1 作者一致）。
- 関連: `docs/handoff/P2-gpu-support.md`, `docs/handoff/P2-output-presets.md`, ROADMAP P2, `src/pipeline.py`, `src/subtitles.py`, `src/app.py`, `src/i18n.py`

## 2026-06-17 — P2 課題C: 即時停止の実装（作業: Gemini 3.5）
- 決定: 設計書 `docs/handoff/P2-immediate-stop.md` に従い、`src/pipeline.py` に `_run_streaming` と `_kill_tree` を実装し、`run_pipeline` の外部プロセス呼び出し（メインカットおよび一時WAV抽出）を `subprocess.Popen` によるストリーミングに移行。
- 理由: ユーザーが停止ボタンを押した際に、実行中の外部プロセス（auto-editor/ffmpeg）を即座に強制終了し、無駄な処理を防止するため。
- 実装詳細: Windows では `creationflags=CREATE_NEW_PROCESS_GROUP` でプロセスグループを作成し、停止時に `taskkill /F /T /PID` で子プロセスを含めたプロセスツリーを強制終了。非 Windows では `proc.terminate()` 後に必要に応じて `proc.kill()` を呼び出す。i18n キー違反（ハードコード3箇所）を `log_stop_requested`/`log_srt_enabled`/`log_lang_detected` に置き換え。
- テスト: `tests/test_pipeline.py` を Popen モック用に全面改修。リアルタイムログストリーミング、中途停止時のプロセスツリー終了、エラーハンドリング、正常動作等の計19テストが全パス。
- 関連: `src/pipeline.py`, `src/app.py`, `src/i18n.py`, `tests/test_pipeline.py`


## 2026-06-17 — P2 課題C: 即時停止の設計（頭脳: Opus 4.8）
- 決定: P1 完了を受け P2 先頭「即時停止対応」を設計。設計書 `docs/handoff/P2-immediate-stop.md` を作成（実装は 🔧Gemini へハンドオフ）。
- 設計判断1: `pipeline.run_pipeline` の auto-editor 呼出を `subprocess.run`→`Popen` ストリーミング化し、`should_stop()` 監視で実行中プロセスを kill。`run_pipeline` の公開シグネチャは不変（内部ヘルパ `_run_streaming`/`_kill_tree` 追加）。kill は pipeline 内に閉じ、UI `_stop_process` は従来どおりフラグ立てのみ＝UI 非依存維持。
- 設計判断2: auto-editor は ffmpeg を子に持つため `terminate()` では孤児化。Windows は `CREATE_NEW_PROCESS_GROUP` + `taskkill /F /T /PID`（ツリー kill）で対応。**psutil 等の新規依存は足さない**（配布 EXE 肥大回避／要承認）。
- 設計判断3: 着手時に発見した i18n 違反3箇所（`app.py:458` SRT生成ログ, `app.py:501` 停止ログ, `pipeline.py:138` 音声検出ログ＝Gemini の P1 実装の取りこぼし）を、触る範囲なので本タスクで同時修正。i18n キー `log_stop_requested`/`log_srt_enabled`/`log_lang_detected` を ja/en 追加。
- 影響/トレードオフ: 停止が即時化。ただし `for line in proc.stdout` のブロッキング上、auto-editor 無出力ハング時のみ次行まで遅延（実用上ほぼ即時。完全即時=別スレッドポンプは非対象）。課題C は実装完了時に「解消」へ更新する。
- 協業: 設計=Opus（本コミット）、実装=Gemini（AGENTS §6.1 作者一致）。
- 関連: `docs/handoff/P2-immediate-stop.md`, `src/pipeline.py`, `src/app.py`, `src/i18n.py`, `tests/test_pipeline.py`, ROADMAP P2

## 2026-06-17 — P1 stage2: pipeline 抽出（コールバックI/F化）完了（作業: Gemini 3.5）
- 決定: `src/app.py` の `_worker` に同居していた処理オーケストレーションを UI 非依存の `src/pipeline.py` に `run_pipeline` として切り出した。
- 理由: モノリスを分割し、UI 非依存とすることで subprocess や transcribe をモックした単体テストを可能にするため。
- 実装: `run_pipeline` と `PipelineParams`/`PipelineResult` を `src/pipeline.py` に実装し、ログ・停止確認・翻訳はコールバック (`on_log`/`should_stop`/`tr`) で外から渡す。テスト `tests/test_pipeline.py` を追加し、6つの検証項目（SRT生成/不生成、途中停止、コマンド失敗、一時WAV不在/削除）をモックで検証 (全 green)。
- 影響/トレードオフ: `app.py` の `_worker` は `run_pipeline` を呼ぶ薄いラッパーになり、画面非表示やCLIからも再利用可能になった。
- 関連: `src/app.py`, `src/pipeline.py`, `tests/test_pipeline.py`, `ROADMAP.md`

## 2026-06-17 — P1 大半を実装（頭脳兼作業: Opus 4.8）
- 決定: P0 を PR#1 で main にマージ後、P1 を着手。並列性分析の結論「app.py 書込競合で #1/#2/#3 は直列、#4(pyproject) のみ独立」に基づき直列実装。
- 実装: 分割段階1 = `version.py`/`i18n.py`/`theme.py` を `src/app.py` から抽出（flat配置・PyInstaller の pathex=src で読込可、build/app.spec は無変更）。段階2(一部) = `autoeditor.py`(コマンド組立 `build_cut_cmd`/`build_extract_wav_cmd`)・`subtitles.py`(`format_timestamp`)。単体テスト `tests/test_unit.py`(7件 green)。`pyproject.toml`(直接依存)。
- 設計判断: 完全パッケージ化(`src/snipsync/`)は見送り。app.py を移すと build.spec / test import を壊すため、flat 配置で「一度に壊さない」を優先（ARCHITECTURE §2 目標へは段階移行）。`format_timestamp` は `app` から re-export し test_p0 を温存。
- 協業逸脱: 本来 🧠Opus=設計/🔧Gemini=実装 だが、セッション内に Gemini 不在かつユーザー「進めて」指示のため Opus が実装も実施。次回以降の分担は要再確認。
- 残: 段階2 の pipeline オーケストレーション抽出（`_worker` は UI/ログ結合のためコールバック設計が必要）。
- 検証: `pytest tests/`=7 passed、GUI 構築スモーク(build→言語切替→destroy)=OK。**人間の目視確認は未**（プログラム的スモークのみ）。
- 関連: `src/{version,i18n,theme,autoeditor,subtitles,app}.py`, `tests/test_unit.py`, `pyproject.toml`, ROADMAP P1

## 2026-06-16 — P0 タスク実装完了（作業: Gemini 3.5）
- 決定: 設計判断に沿って、バージョン一元化（v1.0.0への統一とI18Nへの適用）、Whisperの自動判定化（language=None）、READMEバッジの検証を完了。テスト（tests/test_p0.py）を作成し、floating pointによるミリ秒丸め誤差の修正を含めて全 green とした。
- 関連: `src/app.py` (format_timestamp, APP_VERSION, I18N, worker), `tests/test_p0.py`

## 2026-06-16 — P0 設計判断（頭脳: Opus 4.8）
- 決定1: 正準バージョンを **`1.0.0`** とする（ユーザー指定。README を正とし、コード側 title の `v1.3.1` 表示を下げる）。`APP_VERSION = "1.0.0"` 定数を `I18N` 定義前に置き、`title` を `f"SnipSync  v{APP_VERSION}"` 化。`src/snipsync/__init__.py` への移動はパッケージ分割（P1）まで遅延。
- 決定2: Whisper 言語ハードコード（課題B）の P0 対応は **`language=None`（自動判定）に変更するのみ**。検出言語は既存の `info.language` ログで可視。UI 言語セレクタは要求外の作り込みのため P2 へ（ROADMAP 更新）。
- 決定3: README 4 言語のバージョンバッジは既に `v1.0.0` で正準と一致 → **変更不要・検証のみ**。
- 理由: 既知の不整合・バグを最小差分で潰し、過剰実装を避ける（協業ポリシー「要求外の作り込み禁止」）。
- 影響: 実装・テスト実装・README 修正は作業役（Gemini 3.5）へ引き継ぐ。テストは本決定（設計）から作成し実装からは作成しない。
- 関連: `src/app.py` 43/98行(title), 684行(transcribe), `README*.md` 12行, CONTRIBUTING.md ワークフロー

## 2026-06-16 — AI 駆動開発用ドキュメント群を整備
- 決定: ルートに `AGENTS.md` / `CLAUDE.md` / `CONTEXT.md` / `ARCHITECTURE.md` / `DESIGN.md` / `MEMORY.md` / `PITFALLS.md` を新設。`AGENTS.md` を正典、`CLAUDE.md` はそれを `@import` するポインタとした。
- 理由: 752 行のモノリス `src/app.py` に対し AI が安全に部分編集するための文脈・ルールが欠如していた。役割を分離して参照負荷を下げる。
- 影響: ドキュメント保守コストが増えるが、編集衝突・仕様逸脱のリスクを下げる。
- 関連: ルート直下 markdown 群、`src/app.py`

---

## （既知の課題・未決定事項）

以下は発見済みだが本タスクでは未修正。着手時にこのセクションを更新すること。

### 課題A: バージョン番号の不整合
- 状態: 未修正。
- 内容: コード（`src/app.py` の `I18N["ja"|"en"]["title"]`）は `v1.3.1`、README 各言語は `v1.0.0`。
- 方針: `src/snipsync/__init__.py` に `__version__` を一元化し、UI とドキュメントが参照する形に統一する（ARCHITECTURE.md §5 TODO #1）。

### 課題B: Whisper の言語ハードコード
- 状態: 未修正（既知バグ）。
- 内容: `model.transcribe(str(temp_wav), beam_size=5, language="ja")` が日本語固定。英語など他言語動画で誤った文字起こしになる。
- 方針: `language=None` で自動判定にするか、UI に言語セレクタを追加（既存の `info.language_probability` ログと整合）。i18n の言語切替とは別概念なので混同しないこと。
- 関連: `src/app.py` `_worker` 2b ブロック（684 行付近）

### 課題C: 停止が即時でない
### 課題C: 停止が即時でない
- 状態: 解消。
- 内容: `subprocess.run` から `subprocess.Popen` へ移行し、`_run_streaming` 内で `should_stop()` を監視。停止時は `taskkill /F /T` によるプロセスツリーの即時強制終了を Windows で行い、非 Windows では `terminate()` と `kill()` で終了。
- 関連: `src/pipeline.py`, `src/app.py`, `tests/test_pipeline.py`
