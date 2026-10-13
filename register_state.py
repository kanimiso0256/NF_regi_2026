# register_state.py
"""ブラウザ版レジ画面の状態と処理（main.py の App から画面部分を除いたもの）。

ログ・CSV の書き方は Tkinter 版と同じにしているので、
復元・整合性チェックなど data_manager.py の機能はそのまま使える。

MobileServer は Tkinter 版の App を前提に作られているため、
同じ属性・メソッド（root.after, current_mode, active_sales_mode,
get_active_menu_status, update_cart_monitor, process_mobile_order_batch）をここで用意する。
"""
import threading
import uuid
from collections import defaultdict
from datetime import datetime
from types import SimpleNamespace

from mobile_server import MobileServer

PTYPES = ("cash", "paypay")
PTYPE_JP = {"cash": "現金", "paypay": "PayPay"}
SPECIAL_TERMS = ("調整", "テスト")

# main.py の load_items_and_data と同じキー割り当て（現金 ＋/入力/－, PayPay ＋/入力/－）
SHORTCUT_KEYS = [
    ('q', 'a', 'z', 'Q', 'A', 'Z'), ('w', 's', 'x', 'W', 'S', 'X'), ('e', 'd', 'c', 'E', 'D', 'C'),
    ('r', 'f', 'v', 'R', 'F', 'V'), ('t', 'g', 'b', 'T', 'G', 'B'), ('y', 'h', 'n', 'Y', 'H', 'N'),
    ('u', 'j', 'm', 'U', 'J', 'M'), ('i', 'k', ',', 'I', 'K', '<'), ('o', 'l', '.', 'O', 'L', '>'),
    ('p', ';', '/', 'P', '+', '?'),
]


class RegisterError(Exception):
    """画面にそのまま表示するエラー"""


class _RootShim:
    """MobileServer が呼ぶ root.after() を、ロックを取って即時実行する形に置き換える"""
    def __init__(self, lock):
        self._lock = lock

    def after(self, _ms, func):
        with self._lock:
            func()


class RegisterState:
    def __init__(self, data_manager):
        self.dm = data_manager
        self._lock = threading.RLock()
        self.root = _RootShim(self._lock)

        self.terminal_user = None
        self.current_mode = None
        self.active_sales_mode = False
        self.current_operator_name = "Unassigned"
        self.is_test_mode = False
        self.allow_negative = False
        self.current_csv_file = None

        self.items = []
        self.notifications = []
        self.cart_state = {}
        self.mobile_server = None

        # 毎秒の状態取得で settings.json を読み書きしないよう、モード開始時に読んでおく
        self._notify_alert = {"cash": False, "paypay": False}
        self._card_width = 150

    # ---------- ログイン・接続 ----------
    def login(self, name):
        name = str(name or "").strip()
        if not name:
            raise RegisterError("名前を入力してください")
        with self._lock:
            self.dm.set_terminal_user(name)
            self.terminal_user = name
            self.dm.log_action(name, "System", "Login", "Success", "Terminal Login")
            if self.mobile_server is None:
                self._start_mobile_server()

    def _start_mobile_server(self):
        settings = self.dm.load_settings()
        if not settings.get("ngrok_connect_enabled", True):
            return
        self.mobile_server = MobileServer(self, self.dm)
        self.mobile_server.set_auth_token(settings.get("ngrok_token", ""))
        # ngrok の接続待ちで画面が止まらないよう別スレッドで起動する
        threading.Thread(target=self.mobile_server.start, daemon=True).start()

    def connection_status(self):
        url = self.mobile_server.get_public_url() if self.mobile_server else None
        return {"online": bool(url), "url": url}

    # ---------- ダッシュボード ----------
    def dashboard(self):
        with self._lock:
            settings = self.dm.load_settings()
        active = set(settings.get("active_terms", []))
        kinds = {"調整": "adjust", "テスト": "test"}
        terms = settings.get("terms", []) + list(SPECIAL_TERMS)
        return {"terms": [{"name": t, "enabled": t in active, "kind": kinds.get(t, "normal")} for t in terms]}

    # ---------- 販売モード ----------
    def start_operation(self, mode, operator):
        mode = str(mode or "")
        operator = str(operator or "").strip()
        if not operator:
            raise RegisterError("担当者の名前を入力してください")
        with self._lock:
            settings = self.dm.load_settings()
            valid = settings.get("terms", []) + list(SPECIAL_TERMS)
            if mode not in valid or mode not in settings.get("active_terms", []):
                raise RegisterError(f"「{mode}」は現在選択できません")

            self.current_operator_name = operator
            self.current_mode = mode
            self.is_test_mode = mode == "テスト"
            self.allow_negative = mode == "調整"
            self.current_csv_file = f"{mode}.csv"
            self._notify_alert = settings.get("notify_alert", self._notify_alert)
            self._card_width = int(settings.get("card_settings", {}).get("width", 150))

            self.dm.log_action(operator, mode, "EnterMode", "Screen", "Start")
            self.notifications = []
            self._load_items(settings)
            self.active_sales_mode = True

    def _load_items(self, settings):
        menu = sorted(settings.get("menu", []), key=lambda m: m.get("order", 9999))
        term_data = {} if self.is_test_mode else self.dm.load_csv_data(self.current_csv_file)
        stats = self.dm.calculate_stats(self.current_mode, settings.get("terms", []))

        self.items = []
        for i, m in enumerate([m for m in menu if m.get("visible", True)]):
            name = m["name"]
            term = term_data.get(name, {"cash": 0, "paypay": 0})
            item = {
                "name": name,
                "price": int(m["price"]),
                "keys": SHORTCUT_KEYS[i] if i < len(SHORTCUT_KEYS) else None,
                "mobile_active": False,
                "term": {"cash": term["cash"], "paypay": term["paypay"]},
                "cumulative": dict(stats[name]["cumulative"]),
                "total": dict(stats[name]["total"]),
            }
            self.items.append(item)
            if m.get("mobile_visible", False):
                self._set_mobile(item, True)

    def exit_operation(self):
        with self._lock:
            self.active_sales_mode = False
            self.current_mode = None
            self.notifications = []
            self.items = []

    def change_operator(self, name):
        name = str(name or "").strip()
        if not name:
            raise RegisterError("名前を入力してください")
        with self._lock:
            self._require_active()
            self.current_operator_name = name
            self.dm.log_action(self.terminal_user, self.current_mode, "ChangeOperator", "System", f"Changed to {name}")

    def toggle_mobile(self, name):
        with self._lock:
            self._require_active()
            item = self._find_item(name)
            self._set_mobile(item, not item["mobile_active"])

    def commit_pc_order(self, drafts):
        with self._lock:
            self._require_active()
            changes = []
            for d in drafts or []:
                item = self._find_item(d.get("name"))
                for ptype in PTYPES:
                    try:
                        qty = int(d.get(ptype) or 0)
                    except (TypeError, ValueError):
                        raise RegisterError("個数が正しくありません")
                    if qty == 0:
                        continue
                    if not self.allow_negative and item["term"][ptype] + qty < 0:
                        raise RegisterError(f"{item['name']}（{PTYPE_JP[ptype]}）の個数がマイナスになります")
                    changes.append((item, ptype, qty))
            if not changes:
                raise RegisterError("確定する商品がありません")

            lines = [f"・{it['name']} ({PTYPE_JP[p]}) x{q:+d}" for it, p, q in changes]
            self._log(self.current_mode, "CommitOrder", "PC", f"合計 {len(changes)}種\n" + "\n".join(lines))
            for item, ptype, qty in changes:
                self._apply_count(item, ptype, qty, self.current_operator_name)
            self._save()

    # ---------- モバイル注文 ----------
    def approve_notification(self, notif_id):
        with self._lock:
            self._require_active()
            notif = self._pop_notification(notif_id)
            operator = self.current_operator_name
            user, ptype, items = notif["user"], notif["ptype"], notif["items"]

            lines = [f"・{oi['name']} ({PTYPE_JP.get(ptype, ptype)}) x{oi['amount']}" for oi in items]
            self.dm.log_action(operator, "Mobile", "CommitOrder", f"From {user}",
                               f"合計 {len(items)}種\n" + "\n".join(lines))
            lookup = {it["name"]: it for it in self.items}
            for oi in items:
                item = lookup.get(oi["name"])
                if item and oi["amount"] > 0 and ptype in PTYPES:
                    self._apply_count(item, ptype, oi["amount"], f"{operator} (via Mobile)")
            self._save()

    def cancel_notification(self, notif_id):
        with self._lock:
            self._require_active()
            notif = self._pop_notification(notif_id)
            self.dm.log_action(self.current_operator_name, "System", "CancelOrder", notif["user"], "Revert-Approved")

    # ---------- MobileServer から呼ばれる ----------
    def get_active_menu_status(self):
        with self._lock:
            if not self.active_sales_mode:
                return []
            return [{"name": it["name"], "price": it["price"]} for it in self.items if it["mobile_active"]]

    def update_cart_monitor(self, user, items):
        self.cart_state[user] = items

    def process_mobile_order_batch(self, user, items, ptype):
        if not self.active_sales_mode:
            return
        details = ", ".join(f"{i['name']} x{i['amount']}" for i in items)
        self.dm.log_action(user, "Mobile", "ReceiveOrder", ptype, f"From {user}: {details}")
        self.notifications.append({
            "id": str(uuid.uuid4()),
            "timestamp": datetime.now().strftime("%H:%M:%S"),
            "user": user,
            "ptype": ptype,
            "items": [{"name": i["name"], "amount": int(i["amount"])} for i in items],
        })
        self.update_cart_monitor(user, [])

    # ---------- 画面用スナップショット ----------
    def snapshot(self):
        with self._lock:
            watchers = defaultdict(list)
            for user, cart in self.cart_state.items():
                for c in cart:
                    watchers[c.get("name")].append(f"{user}:{c.get('amount')}")
            prices = {it["name"]: it["price"] for it in self.items}

            def total_of(key):
                return sum((it[key]["cash"] + it[key]["paypay"]) * it["price"] for it in self.items)

            return {
                "logged_in": self.terminal_user is not None,
                "terminal_user": self.terminal_user or "",
                "active": self.active_sales_mode,
                "mode": self.current_mode,
                "operator": self.current_operator_name,
                "is_test": self.is_test_mode,
                "allow_negative": self.allow_negative,
                "card_width": self._card_width,
                "notify_alert": dict(self._notify_alert),
                "items": [{
                    "name": it["name"],
                    "price": it["price"],
                    "keys": it["keys"],
                    "mobile_active": it["mobile_active"],
                    "term": dict(it["term"]),
                    "total": dict(it["total"]),
                    "watchers": watchers.get(it["name"], []),
                } for it in self.items],
                "totals": {k: total_of(k) for k in ("term", "cumulative", "total")},
                "notifications": [{
                    **n,
                    "items": [{**oi, "price": prices.get(oi["name"], 0),
                               "subtotal": oi["amount"] * prices.get(oi["name"], 0)} for oi in n["items"]],
                } for n in self.notifications],
            }

    # ---------- 内部処理 ----------
    def _require_active(self):
        if not self.active_sales_mode:
            raise RegisterError("販売モードではありません")

    def _find_item(self, name):
        for it in self.items:
            if it["name"] == name:
                return it
        raise RegisterError(f"商品が見つかりません: {name}")

    def _pop_notification(self, notif_id):
        for i, n in enumerate(self.notifications):
            if n["id"] == notif_id:
                return self.notifications.pop(i)
        raise RegisterError("この注文はすでに処理されています")

    def _log(self, mode, action, target, value):
        self.dm.log_action(self.current_operator_name, mode, action, target, value)

    def _set_mobile(self, item, on):
        item["mobile_active"] = on
        self._log(self.current_mode, "ToggleMobile", item["name"], "ON" if on else "OFF")

    def _apply_count(self, item, ptype, qty, by):
        new_val = item["term"][ptype] + qty
        action = "Add" if qty > 0 else "Sub"
        self._log(self.current_mode, action, f"{item['name']} [{ptype}]", f"{qty:+d} (Term: {new_val}) by {by}")
        item["term"][ptype] = new_val
        item["cumulative"][ptype] += qty
        item["total"][ptype] += qty

    def _save(self):
        if self.is_test_mode:
            return
        rows = [SimpleNamespace(name=it["name"], counts={"term": it["term"]}) for it in self.items]
        self.dm.save_csv_data(self.current_csv_file, rows)
