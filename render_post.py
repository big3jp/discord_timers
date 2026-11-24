"""AION 2 (アジア) のイベント時刻表を画像にして、Discord Webhook のメッセージを投稿/更新する。

- 時刻表は https://shugo.gg/timers.json（取得失敗時は同梱の timers-data.json）
- 画像は Pillow で描画（ブラウザ不要）。表示時刻は JST 固定。
- メッセージ本文に <t:UNIX:R> を入れ、直近のイベントのカウントダウンは Discord 側で自動更新される。
- 環境変数 WEBHOOK_URL が必須。投稿済みメッセージIDは message_id.txt に保存する。
使い方:  python render_post.py          (投稿/更新)
         python render_post.py --png out.png   (画像だけ出力、投稿しない)
"""
import json
import os
import sys
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

BASE = Path(__file__).resolve().parent
REGION = "global-as"
JST = timezone(timedelta(hours=9))
TIMERS_URL = "https://shugo.gg/timers.json"
UA = "DiscordBot (aion2-timer-poster, 1.0)"
ID_FILE = BASE / "message_id.txt"
CACHE = BASE / "timers-data.json"

NAMES = {
    "rift": "時空の亀裂", "battlefield": "戦場", "dimensional-invasion": "次元侵攻",
    "shugo-festival": "シューゴ フェスタ", "watcher-kaira": "監視者カイラ",
    "argo-spirit-king": "精霊王アグロ", "artifact-siege": "アーティファクト占領戦",
    "siege-bosses": "占領戦ボス", "guardian-nahma": "守護神将ナフマ",
    "daily-reset": "日間リセット", "weekly-reset": "週間リセット",
}
TAG = {"pvp": "PVP", "event": "イベント", "boss": "ボス", "abyss": "アビス", "reset": "リセット"}
TL_ORDER = ["rift", "battlefield", "dimensional-invasion", "shugo-festival", "watcher-kaira",
            "argo-spirit-king", "artifact-siege", "siege-bosses", "guardian-nahma"]
WD = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]  # datetime.weekday()
WD_JA = ["月", "火", "水", "木", "金", "土", "日"]

BG = (11, 18, 32); PANEL = (17, 26, 44); PANEL2 = (14, 22, 38); LINE = (30, 42, 66)
TEXT = (230, 236, 247); MUTED = (138, 151, 179)
ORANGE = (245, 158, 11); BROWN = (138, 90, 28); GREEN = (52, 211, 153)
TAGC = {"pvp": ((59, 29, 36), (248, 113, 113)), "event": ((27, 44, 74), (96, 165, 250)),
        "boss": ((58, 31, 31), (251, 146, 60)), "abyss": ((42, 33, 71), (167, 139, 250)),
        "reset": ((18, 51, 43), (52, 211, 153))}

FONT_CANDIDATES = [
    ("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc", "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc"),
    ("C:/Windows/Fonts/YuGothR.ttc", "C:/Windows/Fonts/YuGothB.ttc"),
    ("C:/Windows/Fonts/meiryo.ttc", "C:/Windows/Fonts/meiryob.ttc"),
]


def font(size, bold=False):
    for reg, bld in FONT_CANDIDATES:
        p = bld if bold else reg
        if os.path.exists(p):
            return ImageFont.truetype(p, size)
    raise SystemExit("日本語フォントが見つかりません")


def http(url, data=None, method=None, headers=None):
    h = {"User-Agent": UA}
    h.update(headers or {})
    req = urllib.request.Request(url, data=data, method=method, headers=h)
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read()


def load_timers():
    try:
        raw = http(TIMERS_URL, headers={"User-Agent": "Mozilla/5.0 (aion2-timer-poster)"})
        d = json.loads(raw)
        CACHE.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
        return d
    except Exception as e:  # noqa: BLE001
        print("timers.json の取得に失敗、同梱データを使用:", e)
        return json.loads(CACHE.read_text(encoding="utf-8"))


def hm(s):
    h, m = s.split(":")
    return int(h), int(m)


def occurrences(ev, now):
    sc = ev["schedules"].get(REGION)
    if not sc:
        return None
    out = []
    for k in range(-2, 11):
        day = (now + timedelta(days=k)).date()
        wd = WD[day.weekday()]
        def push(h, m, dur):
            s = datetime(day.year, day.month, day.day, h, m, tzinfo=JST)
            out.append({"s": s, "e": s + timedelta(minutes=dur),
                        "portal": timedelta(minutes=ev.get("portalMinutes", 0))})
        t = sc["type"]
        if t == "daily":
            for i, tm in enumerate(sc["times"]):
                push(*hm(tm), (sc.get("durations") or [ev.get("durationMinutes", 0)] * 99)[i])
        elif t == "weekly":
            if wd in sc["days"]:
                for tm in sc["times"]:
                    push(*hm(tm), ev.get("durationMinutes", 0))
        elif t == "hourly":
            for h in range(24):
                push(h, sc["minute"], ev.get("durationMinutes", 0))
    out.sort(key=lambda o: o["s"])
    return sc, out


def fmt_hm(dt):
    return dt.strftime("%H:%M")


def when(dt, now):
    if dt.date() == now.date():
        return f"今日 {fmt_hm(dt)}"
    if dt.date() == (now + timedelta(days=1)).date():
        return f"明日 {fmt_hm(dt)}"
    return f"{WD_JA[dt.weekday()]} {fmt_hm(dt)}"


def sched_text(sc):
    if sc["type"] == "hourly":
        return f"毎時{sc['minute']:02d}分"
    if sc["type"] == "weekly":
        days = "・".join(WD_JA[WD.index(d)] for d in sc["days"])
        if sc.get("timeLabels"):
            slots = " / ".join(f"G{i + 1} {t}" for i, t in enumerate(sc["times"]))
            return f"{days} {slots}"
        return f"{days} {', '.join(sc['times'])}"
    return "毎日 " + ", ".join(sc["times"])


def collect(timers, now):
    rows = []
    for ev in timers["events"]:
        r = occurrences(ev, now)
        if not r:
            continue
        sc, occ = r
        dur = ev.get("durationMinutes", 0)
        live = next((o for o in occ if dur and o["s"] <= now < o["e"]), None)
        nxt = next((o for o in occ if o["s"] > now), None)
        if not live and not nxt:
            continue
        key = (live["e"] - timedelta(days=3650)) if live else nxt["s"]
        rows.append({"ev": ev, "name": NAMES.get(ev["id"], ev["name"]), "sc": sc, "occ": occ,
                     "live": live, "nxt": nxt, "key": key})
    rows.sort(key=lambda x: x["key"])
    return rows


# ---------------- drawing ----------------
W = 1100
M = 20


def rrect(d, box, r, fill):
    d.rounded_rectangle(box, radius=r, fill=fill)


def text_w(d, s, f):
    return d.textlength(s, font=f)


def render(timers, now):
    rows = collect(timers, now)
    by_id = {x["ev"]["id"]: x for x in rows}
    f10, f12, f13, f14, f16 = font(11), font(12), font(13), font(14), font(16)
    b13, b14, b16, b18, b22 = font(13, True), font(14, True), font(16, True), font(18, True), font(24, True)

    tl_rows = [by_id[i] for i in TL_ORDER if i in by_id]
    h_head = 60
    h_tl = 52 + len(tl_rows) * 30 + 34
    ev_rows = rows
    h_ev = 48 + len(ev_rows) * 56 + 10
    H = M + h_head + 12 + h_tl + 14 + h_ev + M + 26
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)

    # header
    d.text((M + 4, M + 6), "AION 2 タイマー（アジア）", font=b22, fill=TEXT)
    stamp = f"更新 {now.strftime('%H:%M')} JST（日本・韓国時間）"
    d.text((W - M - 4 - text_w(d, stamp, f14), M + 14), stamp, font=f14, fill=MUTED)

    # timeline panel
    y0 = M + h_head + 12
    rrect(d, (M, y0, W - M, y0 + h_tl), 12, PANEL)
    d.text((M + 18, y0 + 14), "今後24時間", font=b16, fill=TEXT)
    x_name = M + 18
    x0 = M + 18 + 190
    x1 = W - M - 18
    span = timedelta(hours=24)
    end = now + span

    def px(t):
        return x0 + (x1 - x0) * max(0.0, min(1.0, (t - now) / span))

    ay = y0 + 40
    d.text((x0 - 6, ay), "今", font=f12, fill=MUTED)
    t = now.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
    ticks = []
    while t < end:
        if t.hour % 6 == 0 and (px(t) - x0) > 40:
            ticks.append(t)
            lab = f"{t.hour:02d}:00"
            d.text((px(t) - text_w(d, lab, f12) / 2, ay), lab, font=f12, fill=MUTED)
        t += timedelta(hours=1)
    ty = ay + 24
    for i, row in enumerate(tl_rows):
        ry = ty + i * 30
        rrect(d, (x0, ry + 3, x1, ry + 25), 4, PANEL2)
    for tk in ticks:
        for yy in range(ty, ty + len(tl_rows) * 30, 6):
            d.line((px(tk), yy, px(tk), yy + 3), fill=(42, 58, 92))
    for i, row in enumerate(tl_rows):
        ry = ty + i * 30
        d.ellipse((x_name, ry + 8, x_name + 10, ry + 18), fill=TAGC[row["ev"]["kind"]][1])
        d.text((x_name + 20, ry + 4), row["name"], font=f14, fill=TEXT)
        any_bar = False
        for o in row["occ"]:
            if o["e"] < now or o["s"] > end:
                continue
            any_bar = True
            xa, xb = px(o["s"]), px(min(o["e"], end))
            xb = max(xb, xa + 5)
            live = o["s"] <= now < o["e"]
            rrect(d, (xa, ry + 7, xb, ry + 21), 4, ORANGE if live else BROWN)
            if o["portal"]:
                xp = px(o["s"] + o["portal"])
                if xp - xa > 2:
                    rrect(d, (xa, ry + 7, xp, ry + 21), 4, GREEN)
        if not any_bar and row["nxt"]:
            n = row["nxt"]["s"]
            left = n - now
            txt = f"次回 {when(n, now)}（あと{left.days}日{left.seconds // 3600}時間）"
            d.text((x0 + 10, ry + 6), txt, font=f12, fill=MUTED)
    # now line
    d.line((x0, ay + 18, x0, ty + len(tl_rows) * 30), fill=ORANGE, width=2)
    ly = ty + len(tl_rows) * 30 + 8
    lx = x_name
    for col, lab in ((ORANGE, "進行中"), (BROWN, "予定"), (GREEN, "ポータル出現時間帯")):
        rrect(d, (lx, ly + 3, lx + 12, ly + 15), 3, col)
        d.text((lx + 18, ly), lab, font=f12, fill=MUTED)
        lx += 18 + text_w(d, lab, f12) + 22

    # events panel
    y1 = y0 + h_tl + 14
    rrect(d, (M, y1, W - M, y1 + h_ev), 12, PANEL)
    d.text((M + 18, y1 + 14), "イベント", font=b16, fill=TEXT)
    sub = "開催中を先頭に、近い順"
    d.text((W - M - 18 - text_w(d, sub, f12), y1 + 18), sub, font=f12, fill=MUTED)
    ry = y1 + 48
    for i, row in enumerate(ev_rows):
        ev = row["ev"]
        if row["live"]:
            rrect(d, (M + 8, ry, W - M - 8, ry + 52), 8, (27, 30, 38))
        else:
            d.line((M + 18, ry, W - M - 18, ry), fill=LINE)
        bgc, fgc = TAGC[ev["kind"]]
        d.ellipse((M + 22, ry + 12, M + 50, ry + 40), fill=bgc, outline=fgc)
        d.text((M + 62, ry + 6), row["name"], font=b16, fill=TEXT)
        tag = TAG.get(ev["kind"], "")
        tw = text_w(d, tag, f10)
        rrect(d, (M + 62, ry + 30, M + 62 + tw + 12, ry + 46), 4, bgc)
        d.text((M + 68, ry + 32), tag, font=f10, fill=fgc)
        d.text((M + 62 + tw + 20, ry + 30), sched_text(row["sc"]), font=f12, fill=MUTED)
        # right side: absolute time
        if row["live"]:
            lab = "● ライブ"
            lw = text_w(d, lab, f12)
            rrect(d, (W - M - 250 - lw - 20, ry + 14, W - M - 250, ry + 38), 12, (62, 44, 14))
            d.text((W - M - 250 - lw - 10, ry + 19), lab, font=f12, fill=ORANGE)
            big, small, col = fmt_hm(row["live"]["e"]), "終了", ORANGE
        else:
            big, small, col = fmt_hm(row["nxt"]["s"]), when(row["nxt"]["s"], now).rsplit(" ", 1)[0] + " 開始", TEXT
        bw = text_w(d, big, b22)
        d.text((W - M - 24 - bw, ry + 4), big, font=b22, fill=col)
        sw = text_w(d, small, f12)
        d.text((W - M - 24 - sw, ry + 34), small, font=f12, fill=MUTED)
        ry += 56

    foot = "出典: Shugo.GG の公開データに基づく非公式の表示。NCSOFT の公式発表ではありません。ずれている場合はゲーム内を優先してください。"
    d.text((M + 4, H - M - 12), foot, font=f12, fill=MUTED)
    return img, rows


def message_text(rows, now):
    def ts(dt):
        return int(dt.timestamp())
    lives = [x for x in rows if x["live"]]
    nexts = [x for x in rows if not x["live"] and x["ev"]["kind"] != "reset"][:4]
    lines = []
    if lives:
        lines.append("🟢 **進行中** " + " / ".join(f"{x['name']}（終了 <t:{ts(x['live']['e'])}:R>）" for x in lives))
    if nexts:
        lines.append("⏭ **次** " + " / ".join(f"{x['name']} <t:{ts(x['nxt']['s'])}:R>" for x in nexts))
    resets = [x for x in rows if x["ev"]["kind"] == "reset" and x["nxt"]]
    if resets:
        lines.append("🔄 " + " / ".join(f"{x['name']} <t:{ts(x['nxt']['s'])}:R>" for x in resets))
    lines.append("-# 時刻は各自の時間帯で表示されます。画像は更新時点のものです。")
    return "\n".join(lines)


def multipart(payload, png_bytes):
    b = uuid.uuid4().hex
    body = b""
    body += (f"--{b}\r\nContent-Disposition: form-data; name=\"payload_json\"\r\n"
             f"Content-Type: application/json\r\n\r\n").encode() + json.dumps(payload, ensure_ascii=False).encode("utf-8") + b"\r\n"
    body += (f"--{b}\r\nContent-Disposition: form-data; name=\"files[0]\"; filename=\"timers.png\"\r\n"
             f"Content-Type: image/png\r\n\r\n").encode() + png_bytes + b"\r\n"
    body += f"--{b}--\r\n".encode()
    return body, f"multipart/form-data; boundary={b}"


def main():
    now = datetime.now(JST)
    timers = load_timers()
    img, rows = render(timers, now)
    if "--png" in sys.argv:
        out = sys.argv[sys.argv.index("--png") + 1]
        img.save(out)
        print("saved", out)
        print(message_text(rows, now))
        return
    import io
    buf = io.BytesIO()
    img.save(buf, "PNG", optimize=True)
    png = buf.getvalue()
    webhook = os.environ["WEBHOOK_URL"].strip()
    payload = {"content": message_text(rows, now), "username": "AION2 タイマー",
               "allowed_mentions": {"parse": []}}
    mid = ID_FILE.read_text().strip() if ID_FILE.exists() else ""
    if mid:
        try:
            body, ct = multipart(dict(payload, attachments=[]), png)
            http(f"{webhook}/messages/{mid}", data=body, method="PATCH", headers={"Content-Type": ct})
            print("edited", mid)
            return
        except urllib.error.HTTPError as e:
            if e.code != 404:
                raise
            print("メッセージが見つからないため、新規投稿します")
    body, ct = multipart(payload, png)
    res = json.loads(http(webhook + "?wait=true", data=body, method="POST", headers={"Content-Type": ct}))
    ID_FILE.write_text(res["id"])
    print("posted", res["id"])


if __name__ == "__main__":
    try:
        main()
    except urllib.error.HTTPError as e:
        print("HTTP", e.code, e.read().decode("utf-8", "replace")[:300])
        sys.exit(1)
