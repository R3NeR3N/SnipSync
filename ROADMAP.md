# ROADMAP.md — 開発計画

> 今後の作業と優先度。完了したら CHANGELOG.md へ移し、ここから消す。
> 各項目に「担当モデル（頭脳/作業）」を明記する（CONTRIBUTING.md の協業方針に対応）。

凡例: 担当 = 🧠 頭脳(Opus 4.8) / 🔧 作業(Gemini) / 🧠→🔧 設計は頭脳・実装は作業

---

> P0 / P1 / P2 はすべて完了。履歴は CHANGELOG.md `[Unreleased]` 参照。

## P3（候補・要精査）

- [ ] **code-review 指摘5件の修正** — GPUフォールバック取りこぼし(#1実バグ)/whisper未導入i18n(#2)/compute_type未使用(#3)/プリセット無効モデルガード(#4)/log_error空detail(#5)。**設計済**: `docs/handoff/P3-review-fixes.md`（実装は Gemini）。担当: 🧠(設計)→🔧
- macOS 対応の可否調査。担当: 🧠(調査)
- **実 NLE での取り込み検証**: マーカー / 倍速 / VAD 経路の FCPXML・Premiere XML（`docs/handoff/verification-2026-10.md`）。担当: ユーザー(実機)
- NG テイク（言い直し）の検出をマーカーで提示（削除はしない）。担当: 🧠(設計)→🔧
- フィラー語は Whisper が書き起こさないため自動カットは見送り。単語間の不自然な空白をマーカー化する案。担当: 🧠(調査)
- 完全パッケージ化（`src/snipsync/`）— build.spec / test import への影響あり、段階移行（ARCHITECTURE §2）。担当: 🧠→🔧

---

> 優先度・担当の変更は MEMORY.md に理由を残すこと。
