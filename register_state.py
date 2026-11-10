# register_state.py
"""ブラウザ版レジ画面の状態と処理（main.py の App から画面部分を除いたもの）。

ログ・CSV の書き方は Tkinter 版と同じにしているので、
復元・整合性チェックなど data_manager.py の機能はそのまま使える。
"""
import csv
import re
import secrets
import threading
from datetime import date, datetime
from types import SimpleNamespace

from square_api import API_BASE, SquareClient, SquareError, SquareReconciler, load_config, order_lines

PTYPES = ("cash", "paypay")
PTYPE_JP = {"cash": "現金", "paypay": "Square"}  # キーは過去の CSV と合わせて "paypay" のまま
SPECIAL_TERMS = ("調整", "テスト")
# 期間名はそのまま CSV のファイル名になるので、ファイル名に使えない文字は禁止する
BAD_NAME_CHARS = re.compile(r'[\\/:*?"<>|]')

# main.py の load_items_and_data と同じキー割り当て（現金 ＋/入力/－, Square ＋/入力/－）
SHORTCUT_KEYS = [
    ('q', 'a', 'z', 'Q', 'A', 'Z'), ('w', 's', 'x', 'W', 'S', 'X'), ('e', 'd', 'c', 'E', 'D', 'C'),
    ('r', 'f', 'v', 'R', 'F', 'V'), ('t', 'g', 'b', 'T', 'G', 'B'), ('y', 'h', 'n', 'Y', 'H', 'N'),
    ('u', 'j', 'm', 'U', 'J', 'M'), ('i', 'k', ',', 'I', 'K', '<'), ('o', 'l', '.', 'O', 'L', '>'),
    ('p', ';', '/', 'P', '+', '?'),
]


class RegisterError(Exception):
    """画面にそのまま表示するエラー"""


class RegisterState:
    def __init__(self, data_manager):
        self.dm = data_manager
        self._lock = threading.RLock()

        self.terminal_user = None
        self.current_mode = None
        self.active_sales_mode = False
        self.current_operator_name = "Unassigned"
        self.is_test_mode = False
        self.allow_negative = False
        self.current_csv_file = None

        self.items = []

        # 毎秒の状態取得で settings.json を読み書きしないよう、モード開始時に読んでおく
        self._card_width = 150

        self._admin_token = None
        self.square = SquareReconciler(data_manager)

        # Square の自動取り込み。取り込んだ会計の ID はログ（SquareImport）に残し、起動時に読み直す
        self._sq_sync_lock = threading.Lock()   # 取り込みが同時に 2 つ走らないように
        self._sq_imported = {}                  # 取り込んだ会計の ID → 取り込んだ期間
        self._sq_import_days = {}               # 期間 → 取り込みがあった日付の集合
        self._sq_unmatched = []                 # 取り込めなかった商品 {term, date, time, order, name, qty, amount}
        self._sq_status = {"state": "off", "message": "", "checked_at": None, "last_import": None}
        self._load_square_history()

    # ---------- ログイン ----------
    def login(self, name):
        name = str(name or "").strip()
        if not name:
            raise RegisterError("名前を入力してください")
        with self._lock:
            self.dm.set_terminal_user(name)
            self.terminal_user = name
            self.dm.log_action(name, "System", "Login", "Success", "Terminal Login")

    # ---------- ダッシュボード ----------
    def dashboard(self):
        with self._lock:
            settings = self.dm.load_settings()
        active = set(settings.get("active_terms", []))
        kinds = {"調整": "adjust", "テスト": "test"}
        terms = settings.get("terms", []) + list(SPECIAL_TERMS)
        return {"terms": [{"name": t, "enabled": t in active, "kind": kinds.get(t, "normal")} for t in terms]}

    # ---------- 管理者設定 ----------
    def admin_login(self, password):
        with self._lock:
            settings = self.dm.load_settings()
            if str(password or "") != str(settings.get("adminPass", "")):
                self.dm.log_action(self.terminal_user, "Settings", "AdminLogin", "Web", "Failed")
                raise RegisterError("パスワードが違います")
            self._admin_token = secrets.token_urlsafe(24)
            self.dm.log_action(self.terminal_user, "Settings", "AdminLogin", "Web", "Success")
            return self._admin_token

    def is_admin(self, token):
        return bool(token and self._admin_token and secrets.compare_digest(token, self._admin_token))

    def admin_settings(self):
        with self._lock:
            settings = self.dm.load_settings()
        menu = sorted(settings.get("menu", []), key=lambda m: m.get("order", 9999))
        terms = settings.get("terms", [])
        targets = settings.get("targets", {})
        return {
            "menu": [{
                "name": m["name"],
                "price": int(m.get("price", 0)),
                "visible": bool(m.get("visible", True)),
            } for m in menu],
            "terms": terms,
            "special_terms": list(SPECIAL_TERMS),
            "active_terms": settings.get("active_terms", []),
            "targets": {t: int(targets.get(t, 0) or 0) for t in terms},
            "operating": self.active_sales_mode,
        }

    def save_admin_settings(self, data):
        terms = [str(t).strip() for t in data.get("terms") or []]
        if not terms:
            raise RegisterError("期間を1つ以上登録してください")
        self._check_names(terms, "期間名")
        for t in terms:
            if t in SPECIAL_TERMS:
                raise RegisterError(f"「{t}」は期間名に使えません")

        menu = []
        for m in data.get("menu") or []:
            menu.append({
                "name": str(m.get("name", "")).strip(),
                "price": self._to_int(m.get("price"), "価格"),
                "visible": bool(m.get("visible")),
                "order": (len(menu) + 1) * 10,
            })
        self._check_names([m["name"] for m in menu], "商品名")

        targets = {t: self._to_int((data.get("targets") or {}).get(t), "目標金額") for t in terms}
        selectable = set(terms) | set(SPECIAL_TERMS)
        active = [t for t in data.get("active_terms") or [] if t in selectable]

        with self._lock:
            settings = self.dm.load_settings()
            settings.update({
                "terms": terms,
                "menu": menu,
                "targets": targets,
                "active_terms": active,
            })
            self.dm.save_settings_file(settings)
            self.dm.log_action(self.terminal_user, "Settings", "UpdateSettings", "Web", "Updated")

    # ---------- Square 連携 ----------
    def square_settings(self):
        with self._lock:
            conf = load_config(self.dm.load_settings())
        token = conf["access_token"]
        return {
            "environment": conf["environment"],
            "location_id": conf["location_id"],
            "token_set": bool(token),
            "token_hint": token[-4:] if token else "",
            "auto_import": bool(conf["auto_import"]),
            "import_since": conf["import_since"],
        }

    def save_square_settings(self, data):
        env = data.get("environment")
        if env not in API_BASE:
            raise RegisterError("接続先（本番/サンドボックス）を選んでください")
        token = str(data.get("access_token") or "").strip()
        with self._lock:
            settings = self.dm.load_settings()
            conf = load_config(settings)
            if data.get("clear_token"):
                conf["access_token"] = ""
            elif token:
                conf["access_token"] = token
            conf["environment"] = env
            conf["location_id"] = str(data.get("location_id") or "").strip()
            auto = bool(data.get("auto_import"))
            if auto and not conf["auto_import"]:
                # オンにした時刻より前の会計は、手で入力済みのはずなので取り込まない
                conf["import_since"] = datetime.now().astimezone().isoformat(timespec="seconds")
            conf["auto_import"] = auto
            settings["square"] = conf
            self.dm.save_settings_file(settings)
            self.dm.log_action(self.terminal_user, "Settings", "UpdateSquare", "Web", env)
        self.square.clear_cache()

    def square_locations(self, data):
        """入力中（空なら保存済み）のトークンで Square につなぎ、店舗の一覧を返す（接続テスト）"""
        env = data.get("environment")
        if env not in API_BASE:
            raise RegisterError("接続先（本番/サンドボックス）を選んでください")
        token = str(data.get("access_token") or "").strip()
        if not token:
            with self._lock:
                token = load_config(self.dm.load_settings())["access_token"]
        try:
            return SquareClient(token, env).list_locations()
        except SquareError as e:
            raise RegisterError(str(e))

    def square_reconcile(self, term=None, refresh=False):
        # Square への問い合わせは時間がかかることがあるので、ロックは持たずに行う
        with self._lock:
            current = self.current_mode if self.active_sales_mode else None
        term = term or current
        if not term:
            raise RegisterError("期間を指定してください")
        with self._lock:
            auto = load_config(self.dm.load_settings())["auto_import"]
            order_terms = dict(self._sq_imported)
            import_days = set(self._sq_import_days.get(term, ()))
        today = date.today()

        def belongs(payment, day):
            # 取り込んだ会計は、取り込んだ期間の Square 実績に数える。
            # まだ取り込んでいない今日の会計は、次の取り込みで入る「販売中の期間」に数える
            t = order_terms.get(payment["order_id"])
            if t is not None:
                return t == term
            return term == current and day == today

        # 自動取り込みがオフのときは、会計がどの期間のものか分からないので、その日の決済をすべて数える
        result = self.square.reconcile(term, include_today=(term == current), refresh=refresh,
                                       belongs=belongs if auto else None, extra_days=import_days)
        with self._lock:
            result["unmatched"] = [u for u in self._sq_unmatched if u["term"] == term]
            result["sync"] = dict(self._sq_status)
        return result

    # ---------- Square の会計の自動取り込み ----------
    def square_sync(self):
        """Square で完了した会計を取り込む（web_main.py のスレッドから 15 秒ごとに呼ばれる）"""
        if not self._sq_sync_lock.acquire(blocking=False):
            return
        try:
            self._square_sync()
        finally:
            self._sq_sync_lock.release()

    def _square_sync(self):
        with self._lock:
            conf = load_config(self.dm.load_settings())
            mode = self.current_mode if self.active_sales_mode else None
        if not conf["access_token"] or not conf["auto_import"]:
            return self._set_sq_status("off")
        if mode is None:
            return self._set_sq_status("paused", "販売を始めると取り込みます")
        if mode in SPECIAL_TERMS:
            return self._set_sq_status("paused", f"「{mode}」では取り込みません")

        # 今日の 0:00（自動取り込みをオンにしたのが今日ならその時刻）から今までの会計
        now = datetime.now().astimezone()
        begin = now.replace(hour=0, minute=0, second=0, microsecond=0)
        try:
            begin = max(begin, datetime.fromisoformat(conf["import_since"]))
        except (TypeError, ValueError):
            begin = now
        try:
            client = SquareClient(conf["access_token"], conf["environment"], conf["location_id"])
            orders = client.search_orders(begin, now) if begin < now else []
        except SquareError as e:
            return self._set_sq_status("error", str(e))

        with self._lock:
            # 問い合わせている間に販売が終わった・期間が変わったときは、次の回に回す
            if not (self.active_sales_mode and self.current_mode == mode):
                return
            new = [o for o in orders if o.get("id") and o["id"] not in self._sq_imported]
            qty = sum(self._import_order(o) for o in new)
            if new:
                self._save()
                self._sq_status["last_import"] = {
                    "time": datetime.now().strftime("%H:%M"), "orders": len(new), "qty": qty}
        self._set_sq_status("ok")

    def _import_order(self, order):
        """会計 1 件をレジの個数に足す（ロックを持って呼ぶ）。足した個数を返す"""
        ptype, lines = order_lines(order)
        oid = order["id"]
        closed = _local_time(order.get("closed_at"))
        total = sum(amount for _, _, amount in lines)
        when = f"{closed:%Y-%m-%d %H:%M:%S} " if closed else ""
        self.dm.log_action("Square", self.current_mode, "SquareImport", oid, f"{when}合計 ¥{total:,}")
        added = 0
        unmatched = []
        for name, qty, amount in lines:
            item = next((it for it in self.items if it["name"] == name), None)
            if item:
                self._apply_count(item, ptype, qty, "Square", user="Square")
                added += qty
            else:
                unmatched.append((name, qty, amount))
        # メニューにない商品・金額だけ打った会計は、画面に出して手で入力してもらう。
        # 集計（analytics.py）は SquareImport の直後に続く Add/Sub を 1 件の会計とみなすので、Add/Sub の後に書く
        for name, qty, amount in unmatched:
            u = _unmatched(self.current_mode, closed or datetime.now(), oid, name, qty, amount)
            self.dm.log_action("Square", self.current_mode, "SquareUnmatched", oid, _unmatched_text(u))
            self._sq_unmatched.append(u)
        self._remember_import(oid, self.current_mode, datetime.now().date())
        return added

    def _remember_import(self, order_id, term, day):
        self._sq_imported[order_id] = term
        self._sq_import_days.setdefault(term, set()).add(day)

    def square_resolve_unmatched(self, term):
        """取り込めなかった商品を「確認済み」にして一覧から消す（手で入力し終えたあとなど）"""
        with self._lock:
            done = [u for u in self._sq_unmatched if u["term"] == term]
            user = self.current_operator_name if self.active_sales_mode else self.terminal_user
            for u in done:
                self.dm.log_action(user, term, "SquareResolved", u["order"], _unmatched_text(u))
            self._sq_unmatched = [u for u in self._sq_unmatched if u["term"] != term]
            return len(done)

    def _set_sq_status(self, state, message=""):
        with self._lock:
            self._sq_status.update(state=state, message=message, checked_at=datetime.now().strftime("%H:%M:%S"))

    def _load_square_history(self):
        try:
            with open(self.dm.log_path, "r", encoding="utf-8") as f:
                reader = csv.reader(f)
                next(reader, None)
                for row in reader:
                    if len(row) < 7:
                        continue
                    ts, _user, _terminal, loc, action, target, value = row[:7]
                    if action == "SquareImport":
                        try:
                            day = datetime.fromisoformat(ts).date()
                        except ValueError:
                            continue
                        self._remember_import(target, loc, day)
                    elif action == "SquareUnmatched":
                        m = re.fullmatch(r"(.*) x(-?\d+) ¥(-?\d+)", value)
                        if not m:
                            continue
                        try:
                            when = datetime.fromisoformat(ts)
                        except ValueError:
                            continue
                        self._sq_unmatched.append(
                            _unmatched(loc, when, target, m.group(1), int(m.group(2)), int(m.group(3))))
                    elif action == "SquareResolved":
                        for i, u in enumerate(self._sq_unmatched):
                            if u["order"] == target and _unmatched_text(u) == value:
                                del self._sq_unmatched[i]
                                break
        except OSError:
            pass

    @staticmethod
    def _check_names(names, label):
        seen = set()
        for n in names:
            if not n:
                raise RegisterError(f"{label}が空の行があります")
            if BAD_NAME_CHARS.search(n):
                raise RegisterError(f"{label}「{n}」に使えない文字が含まれています")
            if n in seen:
                raise RegisterError(f"{label}「{n}」が重複しています")
            seen.add(n)

    @staticmethod
    def _to_int(value, label):
        try:
            n = int(value or 0)
        except (TypeError, ValueError):
            raise RegisterError(f"{label}は数字で入力してください")
        if n < 0:
            raise RegisterError(f"{label}にマイナスは入力できません")
        return n

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
            self._card_width = int(settings.get("card_settings", {}).get("width", 150))

            self.dm.log_action(operator, mode, "EnterMode", "Screen", "Start")
            self._load_items(settings)
            self.active_sales_mode = True
        # 販売を始めたら、待たずに Square の会計を取り込む
        threading.Thread(target=self.square_sync, daemon=True).start()

    def _load_items(self, settings):
        menu = sorted(settings.get("menu", []), key=lambda m: m.get("order", 9999))
        term_data = {} if self.is_test_mode else self.dm.load_csv_data(self.current_csv_file)
        stats = self.dm.calculate_stats(self.current_mode, settings.get("terms", []))

        self.items = []
        for i, m in enumerate([m for m in menu if m.get("visible", True)]):
            name = m["name"]
            term = term_data.get(name, {"cash": 0, "paypay": 0})
            self.items.append({
                "name": name,
                "price": int(m["price"]),
                "keys": SHORTCUT_KEYS[i] if i < len(SHORTCUT_KEYS) else None,
                "term": {"cash": term["cash"], "paypay": term["paypay"]},
                "cumulative": dict(stats[name]["cumulative"]),
                "total": dict(stats[name]["total"]),
            })

    def exit_operation(self):
        with self._lock:
            self.active_sales_mode = False
            self.current_mode = None
            self.items = []

    def change_operator(self, name):
        name = str(name or "").strip()
        if not name:
            raise RegisterError("名前を入力してください")
        with self._lock:
            self._require_active()
            self.current_operator_name = name
            self.dm.log_action(self.terminal_user, self.current_mode, "ChangeOperator", "System", f"Changed to {name}")

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

    # ---------- 画面用スナップショット ----------
    def snapshot(self):
        with self._lock:
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
                "items": [{
                    "name": it["name"],
                    "price": it["price"],
                    "keys": it["keys"],
                    "term": dict(it["term"]),
                    "total": dict(it["total"]),
                } for it in self.items],
                "totals": {k: total_of(k) for k in ("term", "cumulative", "total")},
                "square": {
                    **self._sq_status,
                    "unmatched": sum(1 for u in self._sq_unmatched if u["term"] == self.current_mode),
                },
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

    def _log(self, mode, action, target, value):
        self.dm.log_action(self.current_operator_name, mode, action, target, value)

    def _apply_count(self, item, ptype, qty, by, user=None):
        new_val = item["term"][ptype] + qty
        action = "Add" if qty > 0 else "Sub"
        self.dm.log_action(user or self.current_operator_name, self.current_mode, action,
                           f"{item['name']} [{ptype}]", f"{qty:+d} (Term: {new_val}) by {by}")
        item["term"][ptype] = new_val
        item["cumulative"][ptype] += qty
        item["total"][ptype] += qty

    def _save(self):
        if self.is_test_mode:
            return
        rows = [SimpleNamespace(name=it["name"], counts={"term": it["term"]}) for it in self.items]
        self.dm.save_csv_data(self.current_csv_file, rows)


def _local_time(iso):
    """Square の時刻（UTC の ISO 形式）を PC の時刻に直す"""
    try:
        return datetime.fromisoformat(str(iso).replace("Z", "+00:00")).astimezone().replace(tzinfo=None)
    except ValueError:
        return None


def _unmatched_text(u):
    # ログの Value 欄の書き方（起動時に _load_square_history で読み直す）
    return f"{u['name']} x{u['qty']} ¥{u['amount']}"


def _unmatched(term, when, order_id, name, qty, amount):
    return {
        "term": term,
        "date": when.strftime("%Y-%m-%d"),
        "time": when.strftime("%H:%M"),
        "order": order_id,
        "name": name,
        "qty": qty,
        "amount": amount,
    }
