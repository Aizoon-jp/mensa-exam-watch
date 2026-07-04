#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
JAPAN MENSA 入会テストの「東京・神奈川」会場に
予約可能枠が出た／新しい日程が追加されたら Chatwork に通知する監視スクリプト。

対象ページは公開（ログイン不要）: https://mensa.jp/exam/
GitHub Actions の cron から数分おきに実行される想定。

検知ロジック:
  1. https://mensa.jp/exam/ を取得
  2. <ul class="list"> 単位で全テスト枠をパース（場所・日時・ステータス）
  3. 「東京」「神奈川」を含む会場だけ抽出
  4. state.json（前回のキー→ステータス）と比較
       - 予約可能(申し込む)になった枠         → 🔥 予約可能アラート
       - 新しい東京/神奈川の日程が現れた枠     → 🆕 新規日程アラート（現ステータス付き）
  5. 変化があれば Chatwork に通知
  6. state.json を現在値で上書き（→ GitHub Actions が commit）
"""

import json
import os
import re
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timezone, timedelta

EXAM_URL = "https://mensa.jp/exam/"
BASE_URL = "https://mensa.jp/"
STATE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "state.json")
JST = timezone(timedelta(hours=9))

# 監視したい会場キーワード（部分一致）
TARGET_PREFS = ("東京", "神奈川")

CHATWORK_TOKEN = os.environ.get("CHATWORK_API_TOKEN", "")
CHATWORK_ROOM = os.environ.get("CHATWORK_ROOM_ID", "")
# '1' のとき、変化が無くてもテスト通知を送る（疎通確認用）
TEST_NOTIFY = os.environ.get("TEST_NOTIFY", "")

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 mensa-exam-watch"


def now_jst():
    return datetime.now(JST).strftime("%Y-%m-%d %H:%M:%S JST")


def fetch_html(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as res:
        raw = res.read()
    return raw.decode("utf-8", errors="replace")


def clean(s):
    s = re.sub(r"<[^>]+>", "", s)
    s = s.replace("&nbsp;", " ")
    return re.sub(r"\s+", " ", s).strip()


def parse_slots(html):
    """全テスト枠を [{pref, datetime, place, status, apply_url, key}] で返す。"""
    slots = []
    # <ul class="list"> ... </ul> ブロックごとに分割
    blocks = re.split(r'<ul\s+class="list">', html)[1:]
    for b in blocks:
        b = b.split("</ul>")[0]

        m_place = re.search(r"場所\s*：\s*(.+?)<br", b)
        m_dt = re.search(r"日時\s*：\s*(.+?)<br", b)
        if not m_place or not m_dt:
            continue
        place = clean(m_place.group(1))
        dt = clean(m_dt.group(1))

        # ステータス判定
        if 'alt="申し込む"' in b or "entry_out.jpg" in b:
            status = "available"
            m_id = re.search(r'href="([^"]*notice/id/\d+/?[^"]*)"', b)
            apply_url = urllib.parse.urljoin(BASE_URL, m_id.group(1)) if m_id else EXAM_URL
        elif "entry_quota.jpg" in b or 'alt="満員"' in b:
            status = "満員"
            apply_url = ""
        elif "entry_expire.jpg" in b or 'alt="締切"' in b:
            status = "締切"
            apply_url = ""
        else:
            status = "unknown"
            apply_url = ""

        slots.append({
            "pref": clean(m_place.group(1)),
            "datetime": dt,
            "place": place,
            "status": status,
            "apply_url": apply_url,
            "key": f"{place} {dt}",
        })
    return slots


def load_state():
    try:
        with open(STATE_FILE, encoding="utf-8") as f:
            j = json.load(f)
        if isinstance(j.get("slots"), dict):
            return j["slots"]
    except FileNotFoundError:
        pass
    except Exception as e:
        print(f"state.json 読み込み失敗: {e}", file=sys.stderr)
    return {}


def save_state(slot_status):
    body = {"slots": slot_status, "updatedAt": datetime.now(timezone.utc).isoformat()}
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(body, f, ensure_ascii=False, indent=2)
        f.write("\n")


def send_chatwork(message):
    if not CHATWORK_TOKEN or not CHATWORK_ROOM:
        print("CHATWORK_API_TOKEN / CHATWORK_ROOM_ID 未設定のため通知スキップ", file=sys.stderr)
        print("---- 送信予定メッセージ ----\n" + message, file=sys.stderr)
        return
    url = f"https://api.chatwork.com/v2/rooms/{CHATWORK_ROOM}/messages"
    data = urllib.parse.urlencode({"body": message, "self_unread": "1"}).encode("utf-8")
    req = urllib.request.Request(
        url, data=data,
        headers={"X-ChatWorkToken": CHATWORK_TOKEN,
                 "Content-Type": "application/x-www-form-urlencoded"},
    )
    with urllib.request.urlopen(req, timeout=30) as res:
        print("Chatwork 送信OK:", res.status)


def build_message(available, new_slots):
    lines = []
    lines.append("[info][title]⚽🧠 メンサ入会テスト 空席アラート[/title]")
    if available:
        lines.append("🔥 東京・神奈川で【予約可能】な枠が出ました！お早めに！")
        for s in available:
            lines.append(f"　■ {s['datetime']}")
            lines.append(f"　　会場: {s['place']}")
            if s["apply_url"]:
                lines.append(f"　　申込: {s['apply_url']}")
    if new_slots:
        if available:
            lines.append("")
        lines.append("🆕 東京・神奈川で新しい日程が追加されました（現在の状態）:")
        for s in new_slots:
            lines.append(f"　■ {s['datetime']}（{s['place']}）… {s['status']}")
    lines.append("")
    lines.append(f"一覧: {EXAM_URL}")
    lines.append(f"（検知時刻 {now_jst()}）")
    lines.append("[/info]")
    return "\n".join(lines)


def main():
    html = fetch_html(EXAM_URL)
    slots = parse_slots(html)
    targets = [s for s in slots if any(p in s["place"] for p in TARGET_PREFS)]
    print(f"[{now_jst()}] 全{len(slots)}枠 / 東京・神奈川 {len(targets)}枠")
    for s in targets:
        print(f"  - {s['status']:>9} | {s['place']} {s['datetime']}")

    prev = load_state()  # {key: status}
    available, new_slots = [], []
    for s in targets:
        k, st = s["key"], s["status"]
        was = prev.get(k)
        if was is None:
            # 新規に出現した枠
            if st == "available":
                available.append(s)
            else:
                new_slots.append(s)
        elif was != "available" and st == "available":
            # 満員/締切 → 予約可能 に変化
            available.append(s)

    cur_status = {s["key"]: s["status"] for s in targets}

    if available or new_slots:
        msg = build_message(available, new_slots)
        send_chatwork(msg)
        print(f"通知送信: 予約可能{len(available)}件 / 新規{len(new_slots)}件")
    elif TEST_NOTIFY == "1":
        summary = "\n".join(f"　■ {s['datetime']}（{s['place']}）… {s['status']}" for s in targets) or "　（現在、東京・神奈川の枠はありません）"
        send_chatwork(f"[info][title]✅ メンサ監視ツール テスト通知[/title]"
                      f"監視は正常稼働中です。現在の東京・神奈川の枠:\n{summary}\n\n一覧: {EXAM_URL}\n（{now_jst()}）[/info]")
        print("テスト通知を送信しました。")
    else:
        print("変化なし。通知なし。")

    save_state(cur_status)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        import traceback
        traceback.print_exc()
        # 監視自体が壊れたら Chatwork で気づけるように
        try:
            send_chatwork(f"[info][title]⚠️ メンサ監視ツールが失敗しました[/title]"
                          f"実行中にエラーが発生しました。ページ仕様変更やアクセス遮断の可能性があります。\n"
                          f"{type(e).__name__}: {e}\n（{now_jst()}）[/info]")
        except Exception as e2:
            print(f"失敗通知も送れませんでした: {e2}", file=sys.stderr)
        sys.exit(1)
