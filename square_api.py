# square_api.py
"""Square（アプリ版）との連携。

■ 自動取り込み（Orders API の SearchOrders）
Square アプリで「商品を選んで」会計すると、Square 側に何が何個売れたかが残る。
それを定期的に取得し、商品名がレジのメニューと同じものをレジの個数に足す（register_state.py）。
現金で受けた会計（Square アプリで「現金」を選んだもの）は「現金」の枠、それ以外は「Square」の枠に入る。

■ 照合（Payments API の ListPayments）
日ごとに
    レジに記録した Square の売上（current_log.csv の Add/Sub × 現在の単価）
    Square で実際に決済された金額（現金の決済は除く）
を並べて差額を出す。取り込めなかった会計（金額だけ打った会計など）や、価格の違いはここで分かる。
Square 側はその日の全決済を数えるので、同じ日に複数の期間（「テスト」など）を使った場合はその分も含まれる。

設定は settings.json の "square" に保存する（settings.json は Git の管理対象外）。
    access_token : Square Developer で発行したアクセストークン
                   （PAYMENTS_READ・ORDERS_READ・MERCHANT_PROFILE_READ が必要。個人用アクセストークンならすべて含まれる）
    environment  : "production"（本番）または "sandbox"（テスト用）
    location_id  : 店舗（ロケーション）ID。空なら Square のメインの店舗
    auto_import  : 会計を自動で取り込むか
    import_since : 自動取り込みをオンにした時刻。これより前の会計は取り込まない（手で入力済みの分を二重に数えないため）
"""
import csv
import threading
import time
from datetime import date, datetime, timedelta

import requests

API_BASE = {
    "production": "https://connect.squareup.com",
    "sandbox": "https://connect.squareupsandbox.com",
}
SQUARE_VERSION = "2025-01-23"
TIMEOUT_SEC = 10
CACHE_SEC_TODAY = 30      # 今日の分は 30 秒ごとに取り直す
CACHE_SEC_PAST = 600      # 過去の日はほぼ変わらないので 10 分
MIN_REFRESH_SEC = 5       # 「取得」ボタンの連打で API を叩きすぎないように
ERROR_RETRY_SEC = 20      # つながらなかったときは、しばらく問い合わせを控える（オフラインの会場で画面が重くならないように）

COUNT_ACTIONS = ("Add", "Sub", "加算", "減算")
SQUARE_PTYPE = "paypay"   # レジの「Square」枠（過去の CSV と合わせてキーは paypay のまま）

DEFAULT_SETTINGS = {
    "access_token": "",
    "environment": "production",
    "location_id": "",
    "auto_import": False,
    "import_since": "",
}


# 支払い方法の表示名（ダッシュボードの「支払い方法の内訳」）
CARD_BRANDS = {
    "VISA": "VISA", "MASTERCARD": "Mastercard", "JCB": "JCB", "AMERICAN_EXPRESS": "AMEX",
    "DISCOVER": "Discover", "DISCOVER_DINERS": "Diners", "CHINA_UNIONPAY": "銀聯",
}
FELICA_BRANDS = {"FELICA_TRANSPORTATION": "交通系IC", "FELICA_ID": "iD", "FELICA_QP": "QUICPay"}
WALLET_BRANDS = {
    "PAYPAY": "PayPay", "RAKUTEN_PAY": "楽天ペイ", "AU_PAY": "au PAY", "D_BARAI": "d払い",
    "MERPAY": "メルペイ", "ALIPAY": "Alipay", "WECHAT_PAY": "WeChat Pay", "CASH_APP": "Cash App",
}


class SquareError(Exception):
    """画面にそのまま表示するエラー"""


def load_config(settings):
    conf = dict(DEFAULT_SETTINGS)
    conf.update(settings.get("square") or {})
    if conf["environment"] not in API_BASE:
        conf["environment"] = "production"
    return conf


class SquareClient:
    def __init__(self, access_token, environment="production", location_id=""):
        if not access_token:
            raise SquareError("Square のアクセストークンが設定されていません")
        self.base = API_BASE.get(environment, API_BASE["production"])
        self.location_id = location_id
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"Bearer {access_token}",
            "Square-Version": SQUARE_VERSION,
            "Accept": "application/json",
        })

    def _get(self, path, params=None):
        return self._request("GET", path, params=params)

    def _post(self, path, body):
        return self._request("POST", path, json=body)

    def _request(self, method, path, **kwargs):
        try:
            res = self.session.request(method, self.base + path, timeout=TIMEOUT_SEC, **kwargs)
        except requests.RequestException:
            raise SquareError("Square に接続できません（インターネット接続を確認してください）")
        if res.status_code == 401:
            raise SquareError("アクセストークンが正しくないか、本番/サンドボックスの選択が違います")
        if res.status_code == 403:
            raise SquareError("アクセストークンに必要な権限がありません")
        if res.status_code == 429:
            raise SquareError("Square への問い合わせが多すぎます。少し待ってから再取得してください")
        try:
            data = res.json()
        except ValueError:
            data = {}
        if not res.ok:
            detail = "; ".join(e.get("detail") or e.get("code", "") for e in data.get("errors", []))
            raise SquareError(f"Square からエラーが返されました（{res.status_code}）{detail}")
        return data

    def list_locations(self):
        data = self._get("/v2/locations")
        return [{
            "id": loc["id"],
            "name": loc.get("name", loc["id"]),
            "currency": loc.get("currency", ""),
        } for loc in data.get("locations", []) if loc.get("status", "ACTIVE") == "ACTIVE"]

    def day_payments(self, day):
        """その日（PC の時刻で 0:00〜24:00）に完了した決済の一覧（現金を除く）。金額は返金分を差し引いたもの。

        [{"order_id": 会計の ID, "amount": 金額, "method": 支払い方法, "brand": カードのブランド or None}, ...]
        """
        begin = datetime(day.year, day.month, day.day).astimezone()
        end = begin + timedelta(days=1)
        params = {"begin_time": begin.isoformat(), "end_time": end.isoformat(), "limit": 100}
        if self.location_id:
            params["location_id"] = self.location_id

        payments = []
        while True:
            data = self._get("/v2/payments", params)
            for p in data.get("payments", []):
                # 現金はレジで数えるので、カード・電子マネー・QR などだけを数える
                if p.get("status") != "COMPLETED" or p.get("source_type") == "CASH":
                    continue
                paid = (p.get("amount_money") or {}).get("amount", 0)
                refunded = (p.get("refunded_money") or {}).get("amount", 0)
                method, brand = payment_method(p)
                payments.append({"order_id": p.get("order_id"), "amount": paid - refunded,
                                 "method": method, "brand": brand})
            cursor = data.get("cursor")
            if not cursor:
                return payments
            params = {"cursor": cursor}

    def resolve_location_id(self):
        """店舗 ID。設定が空なら Square のメインの店舗"""
        if not self.location_id:
            self.location_id = self._get("/v2/locations/main")["location"]["id"]
        return self.location_id

    def search_orders(self, begin, end):
        """begin〜end に完了した会計（注文）を、完了した順にすべて返す"""
        body = {
            "location_ids": [self.resolve_location_id()],
            "query": {
                "filter": {
                    "state_filter": {"states": ["COMPLETED"]},
                    "date_time_filter": {"closed_at": {"start_at": begin.isoformat(), "end_at": end.isoformat()}},
                },
                "sort": {"sort_field": "CLOSED_AT", "sort_order": "ASC"},
            },
            "limit": 100,
        }
        orders = []
        while True:
            data = self._post("/v2/orders/search", body)
            orders.extend(data.get("orders", []))
            cursor = data.get("cursor")
            if not cursor:
                return orders
            body["cursor"] = cursor


def payment_method(p):
    """決済 1 件の (支払い方法, カードのブランド)。カード以外はブランドが None"""
    source = p.get("source_type")
    if source == "CARD":
        card = (p.get("card_details") or {}).get("card") or {}
        felica = _find_key(p, "felica_brand")
        if felica or card.get("card_brand") == "FELICA":
            return FELICA_BRANDS.get(felica, "電子マネー"), None
        return "カード", CARD_BRANDS.get(card.get("card_brand"), "その他のカード")
    if source == "WALLET":
        return WALLET_BRANDS.get((p.get("wallet_details") or {}).get("brand"), "その他のQR"), None
    return "その他", None


def _find_key(obj, key):
    """入れ子の dict・list の中から key の値を探す（電子マネーの種類が入る場所は API の版で違うため）"""
    if isinstance(obj, dict):
        if obj.get(key):
            return obj[key]
        obj = list(obj.values())
    if isinstance(obj, list):
        for v in obj:
            found = _find_key(v, key)
            if found:
                return found
    return None


def _add(d, key, amount):
    d[key] = d.get(key, 0) + amount


def order_lines(order):
    """会計 1 件を (支払い方法, [(商品名, 個数, 金額), ...]) にする。返品は個数・金額がマイナス。

    支払い方法は、すべて現金で払われていれば "cash"、それ以外は Square の枠（"paypay"）
    """
    tenders = order.get("tenders") or []
    ptype = "cash" if tenders and all(t.get("type") == "CASH" for t in tenders) else SQUARE_PTYPE

    def qty_of(li):
        try:
            return int(float(li.get("quantity") or 0))
        except ValueError:
            return 0

    def name_of(li, default):
        return (li.get("name") or "").strip() or default

    def amount_of(li):
        return (li.get("total_money") or {}).get("amount", 0)

    lines = [(name_of(li, "金額指定"), qty_of(li), amount_of(li)) for li in order.get("line_items") or []]
    # 金額だけで返金すると、商品名のない返品になる（「取り込めなかった会計」に「返金」として出す）
    for ret in order.get("returns") or []:
        lines += [(name_of(li, "返金"), -qty_of(li), -amount_of(li)) for li in ret.get("return_line_items") or []]
    return ptype, [line for line in lines if line[1] != 0]


class SquareReconciler:
    def __init__(self, data_manager):
        self.dm = data_manager
        self._lock = threading.Lock()
        self._cache = {}          # (環境, 店舗, トークン末尾, 日付) → (取得時刻, day_payments の一覧)
        self._last_error = None   # (時刻, 環境・店舗・トークン末尾, メッセージ)

    def clear_cache(self):
        with self._lock:
            self._cache.clear()
            self._last_error = None

    def reconcile(self, term, include_today=False, refresh=False, belongs=None, extra_days=()):
        """期間 term の照合結果。

        belongs(決済, 日付) が渡されたときは、True を返す決済だけをこの期間の Square 実績として数える
        （自動取り込みで、会計ごとにどの期間へ取り込んだかが分かるとき）。
        渡されないときは、その日の決済をすべて数える。
        """
        settings = self.dm.load_settings()
        conf = load_config(settings)
        prices = {m["name"]: int(m.get("price", 0)) for m in settings.get("menu", [])}
        register = register_by_day(self.dm.log_path, term, prices)

        today = date.today()
        days = set(register) | set(extra_days)
        if include_today:
            days.add(today)
        days = sorted(days)

        result = {
            "term": term,
            "configured": bool(conf["access_token"]),
            "environment": conf["environment"],
            "days": [],
            "register": sum(register.values()),
            "square": None,
            "count": None,
            "diff": None,
            "error": None,
            "checked_at": None,
            "methods": {},        # 支払い方法ごとの金額（Square の決済。現金は含まない）
            "brands": {},         # クレジットカードのブランドごとの金額
            "scope": "term" if belongs else "day",   # Square 実績を期間ごとに分けて数えたか
        }
        if not result["configured"]:
            result["days"] = [{"date": d.isoformat(), "register": register.get(d, 0),
                               "square": None, "count": None, "diff": None} for d in days]
            return result

        client = SquareClient(conf["access_token"], conf["environment"], conf["location_id"])
        key_base = (conf["environment"], conf["location_id"], conf["access_token"][-8:])
        with self._lock:
            err = self._last_error
        if err and not refresh and err[1] == key_base and time.monotonic() - err[0] < ERROR_RETRY_SEC:
            result["error"] = err[2]

        sq_total = sq_count = 0
        methods, brands = {}, {}
        for d in days:
            reg = register.get(d, 0)
            row = {"date": d.isoformat(), "register": reg, "square": None, "count": None, "diff": None}
            if result["error"] is None:
                try:
                    pays = [p for p in self._day(client, key_base, d, today, refresh)
                            if belongs is None or belongs(p, d)]
                    amount = sum(p["amount"] for p in pays)
                    count = sum(1 for p in pays if p["amount"] > 0)   # 全額返金した決済は件数に数えない
                    row.update(square=amount, count=count, diff=amount - reg)
                    sq_total += amount
                    sq_count += count
                    for p in pays:
                        _add(methods, p["method"], p["amount"])
                        if p["brand"]:
                            _add(brands, p["brand"], p["amount"])
                except SquareError as e:
                    result["error"] = str(e)
                    with self._lock:
                        self._last_error = (time.monotonic(), key_base, str(e))
            result["days"].append(row)

        if result["error"] is None:
            result.update(square=sq_total, count=sq_count, diff=sq_total - result["register"],
                          methods=methods, brands=brands)
        result["checked_at"] = datetime.now().strftime("%H:%M:%S")
        return result

    def _day(self, client, key_base, day, today, refresh):
        key = key_base + (day,)
        max_age = CACHE_SEC_TODAY if day >= today else CACHE_SEC_PAST
        if refresh:
            max_age = MIN_REFRESH_SEC
        now = time.monotonic()
        with self._lock:
            hit = self._cache.get(key)
        if hit and now - hit[0] < max_age:
            return hit[1]
        payments = client.day_payments(day)
        with self._lock:
            self._cache[key] = (now, payments)
        return payments


def register_by_day(log_path, term, prices):
    """レジに記録した Square 枠の売上を日ごとに合計する（{date: 金額}）"""
    by_day = {}
    suffix = f" [{SQUARE_PTYPE}]"
    try:
        with open(log_path, "r", encoding="utf-8") as f:
            reader = csv.reader(f)
            next(reader, None)
            for row in reader:
                if len(row) < 7:
                    continue
                ts, _user, _terminal, loc, action, target, value = row[:7]
                if loc != term or action not in COUNT_ACTIONS or not target.endswith(suffix):
                    continue
                try:
                    delta = int(value.split()[0])
                    day = datetime.fromisoformat(ts).date()
                except (ValueError, IndexError):
                    continue
                name = target[:-len(suffix)]
                by_day[day] = by_day.get(day, 0) + delta * prices.get(name, 0)
    except OSError:
        pass
    return by_day
