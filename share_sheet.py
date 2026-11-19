# share_sheet.py
"""ダッシュボードの数字を Google スプレッドシートに送り、VPN なしで見られるようにする。

スプレッドシートに付けた Apps Script（share/dashboard_sheet.gs）を「ウェブアプリ」として公開し、
その URL を Settings の「ダッシュボードの共有」に入れると、親機が 1 分ごとに売上を送る。
親機から外へ送るだけなので、外から親機にはつながらない。

送るのは期間ごとの売上・目標・会計件数・現金・PayPay・Square の内訳、商品ごとの個数と売上、時間別の売上。
中身が変わったときと、最後に送ってから HEARTBEAT_SEC たったとき（最終更新の時刻を進めるため）だけ送る。
"""
import json
import logging
import re
import threading
import time
from datetime import datetime

import requests

import analytics
import sales_log

URL_PATTERN = re.compile(r"https://script\.google\.com/macros/s/[A-Za-z0-9_-]+/exec")
INTERVAL_SEC = 60        # 変わったかどうかを調べる間隔
HEARTBEAT_SEC = 300      # 変わっていなくても、この間隔で送る
TIMEOUT_SEC = 30
SPECIAL_TERMS = ("テスト", "調整")


def load_config(settings):
    share = settings.get("share") or {}
    return {"url": str(share.get("url") or ""), "enabled": bool(share.get("enabled"))}


def build_payload(dm):
    """スプレッドシートに送る中身"""
    settings = dm.load_settings()
    terms = [t for t in settings.get("terms", []) if t not in SPECIAL_TERMS]
    menu = sorted(settings.get("menu", []), key=lambda m: m.get("order", 9999))
    prices = {m["name"]: int(m.get("price", 0)) for m in menu}
    amounts = sales_log.term_amounts(dm.log_path, prices)

    summary, items, hourly = [], [], {}
    totals = {}   # 商品名 → 全期間の合計
    for term in terms:
        d = analytics.build(dm, term)
        summary.append({
            "term": term,
            "sales": d["sales"],
            "target": d["target"],
            "transactions": d["transactions"],
            "cash": d["pay"]["cash"],
            "paypay": d["pay"]["paypay"],
            "square": d["pay"]["square"],
        })
        for h in d["hourly"]:
            hourly.setdefault(h["hour"], {})[term] = h["amount"]

        counts = dm.load_csv_data(f"{term}.csv")
        term_amounts = amounts.get(term, {})
        names = [m["name"] for m in menu]
        names += [n for n in sorted(set(counts) | set(term_amounts)) if n not in prices]
        for name in names:
            c = counts.get(name, {})
            row = {"name": name, "cash": c.get("cash", 0), "paypay": c.get("pp", 0), "square": c.get("paypay", 0),
                   "amount": sum(term_amounts.get(name, {}).values())}
            if name not in prices and not (row["cash"] or row["paypay"] or row["square"] or row["amount"]):
                continue
            items.append({"term": term, **row})
            t = totals.setdefault(name, {"name": name, "cash": 0, "paypay": 0, "square": 0, "amount": 0})
            for k in ("cash", "paypay", "square", "amount"):
                t[k] += row[k]

    return {
        "terms": terms,
        "summary": summary,
        "totals": list(totals.values()),
        "items": items,
        "hourly": [{"hour": h, "amounts": [hourly[h].get(t, 0) for t in terms]} for h in sorted(hourly)],
    }


class SheetSharer:
    def __init__(self, dm):
        self.dm = dm
        self._lock = threading.Lock()      # 送信が同時に 2 つ走らないように
        self._last_body = None
        self._last_sent = 0.0
        self.status = {"state": "off", "message": "", "sent_at": None}

    # ---------- 設定 ----------
    def settings_view(self):
        conf = load_config(self.dm.load_settings())
        return {**conf, "status": dict(self.status)}

    def save(self, data):
        """設定を保存する。URL がおかしければ ValueError"""
        url = str(data.get("url") or "").strip()
        enabled = bool(data.get("enabled"))
        if url and not URL_PATTERN.fullmatch(url):
            raise ValueError("URL は Apps Script の「ウェブアプリ」の URL（https://script.google.com/macros/s/…/exec）を入れてください")
        if enabled and not url:
            raise ValueError("送るには URL を入れてください")
        settings = self.dm.load_settings()
        settings["share"] = {"url": url, "enabled": enabled}
        self.dm.save_settings_file(settings)
        self._last_body = None      # 設定を変えたらすぐ送り直す
        if not enabled:
            self.status = {"state": "off", "message": "", "sent_at": self.status.get("sent_at")}

    # ---------- 送信 ----------
    def push(self, force=False):
        """必要なら送る。送った・送らなかった結果を status に残して返す"""
        conf = load_config(self.dm.load_settings())
        if not (conf["enabled"] and conf["url"]) and not force:
            return self.status
        if not conf["url"]:
            raise ValueError("URL が設定されていません")
        with self._lock:
            payload = build_payload(self.dm)
            body = json.dumps(payload, ensure_ascii=False, sort_keys=True)
            now = time.monotonic()
            if not force and body == self._last_body and now - self._last_sent < HEARTBEAT_SEC:
                return self.status
            payload["updated"] = datetime.now().strftime("%Y-%m-%d %H:%M")
            try:
                res = requests.post(conf["url"], json=payload, timeout=TIMEOUT_SEC)
                result = res.json() if res.ok else None
            except (requests.RequestException, ValueError):
                result = None
                res = None
            if result and result.get("ok"):
                self._last_body, self._last_sent = body, now
                self.status = {"state": "ok", "message": "", "sent_at": datetime.now().strftime("%H:%M:%S")}
            else:
                self.status = {**self.status, "state": "error", "message": _error_text(res, result)}
            return self.status


def _error_text(res, result):
    if res is None:
        return "スプレッドシートに送れませんでした（インターネットにつながっているか確認してください）"
    if result and result.get("error"):
        return f"スプレッドシート側でエラー: {result['error']}"
    if res.status_code in (401, 403) or "accounts.google.com" in res.url:
        return "スプレッドシートに送れませんでした。ウェブアプリの「アクセスできるユーザー」を「全員」にしてください"
    return f"スプレッドシートに送れませんでした（{res.status_code}）"


def share_loop(sharer):
    while True:
        time.sleep(INTERVAL_SEC)
        try:
            sharer.push()
        except Exception:   # 送れなくてもレジは止めない
            logging.exception("ダッシュボードの共有に失敗しました")
