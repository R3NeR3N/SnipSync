# テンプレート — Gemini 作業引継ぎプロンプト

> 🧠頭脳(Opus) が 🔧作業(Gemini) へ実装を渡す際の指示プロンプト雛形。
> `{{...}}` を差し替えて、Gemini への入力としてそのまま貼り付ける。
> 使い方: 設計書を `docs/handoff/<task>.md` に用意 → 下のブロックの `{{DESIGN_DOC}}` 等を埋める。

雛形の核は3つ: **①必読順 / ②タスク / ③DoD・コミット担当**。これさえ揃えば再利用可。

---

```text
SnipSync の実装作業を担当してください（あなた=🔧作業/Gemini）。

# 着手前に必読（この順）
1. AGENTS.md（正典・作業ルール／§4禁止事項／§6.1コミット担当）
2. PITFALLS.md（既知の失敗。特に {{RELEVANT_PITFALLS 例: P-2 margin/threshold同期, P-6 subprocess encoding}}）
3. {{DESIGN_DOC 例: docs/handoff/P1-pipeline-extraction.md}} ← 今回の設計書（地図）。これに厳密に従う

# ブランチ
{{BRANCH 例: git checkout feat/p1-refactor（既存。最新を pull）}}

# タスク
{{TASK_SUMMARY: 何を・どこから・どこへ。挙動を変えるのかリファクタのみか。対象外(やらないこと)も明記}}

# 守ること
- 文字列追加は I18N の ja/en 両方（§4）。UI直書き禁止。
- パスは Path(...).resolve()。subprocess は capture_output/text/encoding="utf-8"/errors="replace"。
- 既存ヘルパを再利用（再実装しない）: {{REUSE 例: format_timestamp=src/subtitles.py, cmd組立=src/autoeditor.py}}。
- flat配置維持（src/snipsync/ パッケージ化はしない。build/app.spec 無変更）。
- {{EXTRA_CONSTRAINTS 任意}}

# 完了の定義（DoD）
1. {{TESTS: 追加/更新するテストと観点}}
2. pytest が全 green。実行: venv/Scripts/python.exe -m pytest tests/ -q
3. python src/app.py を起動し {{機能}} が従来通り動くことを目視確認（GUIアプリのため必須）。
4. {{ARCH_INVARIANT 例: pipeline.py が customtkinter / self を参照しない（UI非依存）}}
5. ROADMAP.md の該当項目を [x] に、MEMORY.md に決定を追記。失敗は PITFALLS.md。

# コミット（AGENTS §6.1: 作者がコミット）
あなたが書いたコード/テストは **あなた（Gemini）がコミット**する。
Conventional Commits・1コミット=1論理変更・生成物(build/dist/venv)は含めない。

# 設計の疑問・矛盾
設計書と実コードに矛盾があれば勝手に直さず MEMORY.md に記録し、頭脳(Opus)/ユーザーへ確認。
```

---

## 記入例（実績: P1 pipeline 抽出）

`docs/handoff/P1-pipeline-extraction.md` を参照する形で上記を埋めたものが、その設計書とセットで運用された初回インスタンス。次回以降は本テンプレを複製して差し替えること。
