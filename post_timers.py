"""Shugo.GG の timers.json から AION 2 のイベント時刻表を作り、Discord Webhook のメッセージを投稿/更新する。

- webhook.txt   : Webhook URL（秘密情報。1行）
- state.json    : 投稿済みメッセージID（初回投稿後に自動作成）
- 地域は REGION で切り替え（既定: global-as = アジア, UTC+9）
実行のたびに「次回の開催時刻」を再計算し、既存メッセージを編集する。
カウントダウンは Discord の <t:UNIX:R> 表記で、閲覧側で自動更新される。
"""
import json
import os
import sys
import urllib.request
import urllib.error
from datetime import datetime, timedelta, timezone
from pathlib import Path

BASE = Path(__file__).resolve().parent
REGION = "global-as"
TZ = timezone(timedelta(hours=9))  # アジア = JST/KST（夏時間なし）
TIMERS_URL = "https://shugo.gg/timers.json"
UA = "DiscordBot (local-timer-poster, 1.0)"

# 表示名（ページの日本語表記に合わせる）と並び順
NAMES = {
    "rift": "🌀 時空の亀裂",
    "shugo-festival": "🎪 シューゴ フェスタ",
    "dimensional-invasion": "🌌 次元侵攻",
    "battlefield": "⚔️ 戦場",
    "artifact-siege": "🏰 アーティファクト占領戦",
    "siege-bosses": "👹 占領戦ボス",
    "guardian-nahma": "🛡️ 守護神将ナフマ",
    "watcher-kaira": "👁️ 監視者カイラ",
    "argo-spirit-king": "🌿 精霊王アグロ",
}
WEEKDAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


def http(url, data=None, method=None, headers=None):
    h = {"User-Agent": UA}
    if headers:
        h.update(headers)
    req = urllib.request.Request(url, data=data, method=method, headers=h)
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read()


def hm(s):
    h, m = s.split(":")
    return int(h), int(m)


def occurrences(sched, now, dur_default, tz):
    """now の前後を含む開始時刻と所要分 (start, minutes) のリストを返す（昨日〜8日後）。"""
    out = []
    t = sched.get("type")
    days_back, days_fwd = 1, 9
    for d in range(-days_back, days_fwd):
        day = (now.astimezone(tz) + timedelta(days=d)).date()
        if t == "daily":
            durs = sched.get("durations")
            for i, tm in enumerate(sched["times"]):
                h, m = hm(tm)
                out.append((datetime(day.year, day.month, day.day, h, m, tzinfo=tz),
                            durs[i] if durs else dur_default))
        elif t == "weekly":
            if WEEKDAYS[day.weekday()] in sched["days"]:
                for tm in sched["times"]:
                    h, m = hm(tm)
                    out.append((datetime(day.year, day.month, day.day, h, m, tzinfo=tz), dur_default))
        elif t == "hourly":
            for h in range(24):
                out.append((datetime(day.year, day.month, day.day, h, sched["minute"], tzinfo=tz), dur_default))
    return sorted(out)


def ts(dt):
    return int(dt.timestamp())


def build(timers, now):
    """(進行中, 24時間以内に始まる, 週間イベント, リセット) の各行リストを返す。"""
    running_l, soon_l, weekly_l, reset_l = [], [], [], []
    horizon = now + timedelta(hours=24)
    for ev in timers["events"]:
        sched = ev["schedules"].get(REGION)
        if not sched:
            continue
        tz = TZ
        if sched.get("timeZone"):
            try:
                from zoneinfo import ZoneInfo
                tz = ZoneInfo(sched["timeZone"])
            except Exception:
                tz = TZ
        dur = ev.get("durationMinutes", 0)
        occ = occurrences(sched, now, dur, tz)
        kind = ev["kind"]
        name = NAMES.get(ev["id"], ev["name"])
        if ev["id"] == "daily-reset":
            name = "日間リセット"
        elif ev["id"] == "weekly-reset":
            name = "週間リセット"

        if dur:
            for s, m in occ:
                if s <= now < s + timedelta(minutes=m):
                    running_l.append((s + timedelta(minutes=m), f"{name}　終了 <t:{ts(s + timedelta(minutes=m))}:R>"))
                    break
        upcoming = [(s, m) for s, m in occ if s > now]
        if not upcoming:
            continue
        s, m = upcoming[0]
        if kind == "reset":
            reset_l.append((s, f"{name}　<t:{ts(s)}:F>　(<t:{ts(s)}:R>)"))
        elif sched["type"] == "weekly":
            same = [x for x, _ in upcoming if x.date() == s.date()]
            slots = " / ".join(x.astimezone(TZ).strftime("%H:%M") for x in same)
            weekly_l.append((s, f"{name}\n　<t:{ts(s)}:F>　(<t:{ts(s)}:R>)\n　グループ別 {slots}"))
        elif s <= horizon:
            soon_l.append((s, f"<t:{ts(s)}:t>　{name}　<t:{ts(s)}:R>"))
    out = []
    for lst in (running_l, soon_l, weekly_l, reset_l):
        lst.sort(key=lambda x: x[0])
        out.append([x[1] for x in lst])
    return out


def main():
    webhook = os.environ.get("WEBHOOK_URL", "").strip()
    if not webhook:
        webhook = (BASE / "webhook.txt").read_text(encoding="utf-8").strip()
    timers = json.loads(http(TIMERS_URL))
    now = datetime.now(timezone.utc)
    running_l, soon_l, weekly_l, reset_l = build(timers, now)

    def field(name, lines, empty="なし"):
        return {"name": name, "value": ("\n".join(lines) if lines else empty)[:1024], "inline": False}

    embed = {
        "title": "AION 2 タイマー（アジア）",
        "url": "https://shugo.gg/ja/timers",
        "description": "日本・韓国時間 (UTC+9) の定期イベント。時刻は各自のDiscordの時間帯で表示され、カウントダウンは自動で進みます。",
        "color": 0x5865F2,
        "fields": [
            field("🟢 進行中", running_l),
            field("⏱ 24時間以内に始まる（近い順）", soon_l),
            field("📆 週間イベント", weekly_l),
            field("🔄 リセット", reset_l),
        ],
        "footer": {"text": "出典: Shugo.GG（非公式の集計。NCSOFTの公式発表ではありません）・最終更新"},
        "timestamp": now.strftime("%Y-%m-%dT%H:%M:%S.000Z"),
    }
    body = json.dumps({"embeds": [embed], "username": "AION2 タイマー"}).encode("utf-8")
    hdr = {"Content-Type": "application/json"}

    state_path = BASE / "state.json"
    mid = os.environ.get("MESSAGE_ID", "").strip() or None
    if not mid and state_path.exists():
        mid = json.loads(state_path.read_text(encoding="utf-8")).get("message_id")

    if mid:
        try:
            http(f"{webhook}/messages/{mid}", data=body, method="PATCH", headers=hdr)
            print("edited", mid)
            return
        except urllib.error.HTTPError as e:
            if e.code != 404:
                raise
            print("message gone; posting a new one")
    res = json.loads(http(webhook + "?wait=true", data=body, method="POST", headers=hdr))
    state_path.write_text(json.dumps({"message_id": res["id"]}), encoding="utf-8")
    print("posted NEW message", res["id"], "- set MESSAGE_ID to this id")


if __name__ == "__main__":
    try:
        main()
    except urllib.error.HTTPError as e:
        print("HTTP", e.code, e.read().decode("utf-8", "replace")[:300])
        sys.exit(1)
