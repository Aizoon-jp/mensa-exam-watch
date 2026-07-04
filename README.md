# mensa-exam-watch

JAPAN MENSA 入会テストの **東京・神奈川会場** に予約可能枠が出た／新しい日程が
追加されたら **Chatwork に即通知** する監視ツール。

対象ページは公開（ログイン不要）: <https://mensa.jp/exam/>
GitHub Actions の cron から **5分おき**に実行される。

## 仕組み

1. `https://mensa.jp/exam/` を取得（Python 標準ライブラリのみ・依存なし）
2. `<ul class="list">` 単位で全テスト枠をパース（場所・日時・ステータス）
3. 「東京」「神奈川」を含む会場だけ抽出
4. `state.json`（前回のキー→ステータス）と比較
   - 満員/締切 → **予約可能（申し込む）** に変化 → 🔥 予約可能アラート
   - 東京/神奈川に **新しい日程** が出現 → 🆕 新規日程アラート
5. 変化があれば Chatwork に通知（申込ページURL付き）
6. `state.json` を現在値で上書き（Actions が commit）

## 通知先

- Chatwork マイチャット（room 338026677）
- スマホの Chatwork アプリにプッシュ通知が届く

## セットアップ（GitHub Secrets）

| Secret | 値 |
| --- | --- |
| `CHATWORK_API_TOKEN` | Chatwork の API トークン |
| `CHATWORK_ROOM_ID` | 通知先ルームID（例: 338026677） |

## 手動実行・テスト

Actions タブ → `mensa-exam-watch` → **Run workflow** →
`test_notify` に `1` を入れて実行すると、変化が無くてもテスト通知が届く。

ローカル実行:

```bash
CHATWORK_API_TOKEN=xxxx CHATWORK_ROOM_ID=338026677 TEST_NOTIFY=1 python3 watcher.py
```

## メモ

- ステータスは画像で表現される: `entry_quota.jpg`=満員 / `entry_expire.jpg`=締切 /
  `entry_out.jpg`(alt="申し込む")=予約可能。
- ページ仕様が変わってパースに失敗した場合も Chatwork にエラー通知が飛ぶ。
- 監視対象の会場は `watcher.py` の `TARGET_PREFS` で変更可能。
