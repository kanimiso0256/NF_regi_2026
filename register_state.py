# register_state.py
"""ブラウザ版レジの状態と処理（main.py の App から画面部分を除いたもの）。

親機（web_main.py を起動している PC）と、同じ Wi-Fi の子機（ブラウザで親機を開いた PC・タブレット）が
同時に使えるよう、状態を 2 つに分けて持つ。

    端末ごと（Terminal）  : 端末の名前・選んでいる期間・担当者・販売中かどうか
    全端末で共通          : 期間ごとの個数（<期間>.csv）・Square の取り込み・設定

ログ・CSV の書き方は Tkinter 版と同じにしているので、
復元・整合性チェックなど data_manager.py の機能はそのまま使える。
"""
import csv
import hashlib
import re
import secrets
import threading
import time
from datetime import date, datetime
from types import SimpleNamespace

from square_api import API_BASE, SquareClient, SquareError, SquareReconciler, load_config, order_lines

PTYPES = ("cash", "paypay")
PTYPE_JP = {"cash": "現金", "paypay": "Square"}  # キーは過去の CSV と合わせて "paypay" のまま
SPECIAL_TERMS = ("調整", "テスト")
TEST_TERM = "テスト"        # 個数は保存せず、親機を再起動すると消える
ADJUST_TERM = "調整"        # マイナスの入力ができる
# 期間名はそのまま CSV のファイル名になるので、ファイル名に使えない文字は禁止する
BAD_NAME_CHARS = re.compile(r'[\\/:*?"<>|]')
FRESH_SEC = 120            # これより長く通信のない端末は、Square の取り込み先を決めるときに後回しにする

# main.py の load_items_and_data と同じキー割り当て（現金 ＋/入力/－, Square ＋/入力/－）
SHORTCUT_KEYS = [
    ('q', 'a', 'z', 'Q', 'A', 'Z'), ('w', 's', 'x', 'W', 'S', 'X'), ('e', 'd', 'c', 'E', 'D', 'C'),
    ('r', 'f', 'v', 'R', 'F', 'V'), ('t', 'g', 'b', 'T', 'G', 'B'), ('y', 'h', 'n', 'Y', 'H', 'N'),
    ('u', 'j', 'm', 'U', 'J', 'M'), ('i', 'k', ',', 'I', 'K', '<'), ('o', 'l', '.', 'O', 'L', '>'),
    ('p', ';', '/', 'P', '+', '?'),
]


class RegisterError(Exception):
    """画面にそのまま表示するエラー"""


class Terminal:
    """ログインしている端末（ブラウザ）1 つ分の状態"""

    def __init__(self, tid, name, is_local):
        self.id = tid
        self.name = name
        self.is_local = is_local      # 親機そのもので開いているか
        self.operator = name
        self.mode = None              # 選んでいる期間
        self.active = False           # 販売中か
        self.started_at = 0.0         # 販売を始めた時刻（Square の取り込み先を決めるのに使う）
        self.last_seen = time.time()

    @property
    def is_test(self):
        return self.mode == TEST_TERM

    @property
    def allow_negative(self):
        return self.mode == ADJUST_TERM


class RegisterState:
    def __init__(self, data_manager):
        self.dm = data_manager
        self._lock = threading.RLock()

        self.terminals = {}           # 端末 ID → Terminal
        self._counts = {}             # 期間 → {商品名: {"cash": 個数, "paypay": 個数}}（CSV を読んだもの）
        self._admin_tokens = set()

        # 毎秒の状態取得で settings.json を読み書きしないよう、メニューなどは読んでおく
        self._conf = {}
        self.reload_settings_cache()

        self.square = SquareReconciler(data_manager)

        # Square の自動取り込み。取り込んだ会計の ID はログ（SquareImport）に残し、起動時に読み直す
        self._sq_sync_lock = threading.Lock()   # 取り込みが同時に 2 つ走らないように
        self._sq_imported = {}                  # 取り込んだ会計の ID → 取り込んだ期間
        self._sq_import_days = {}               # 期間 → 取り込みがあった日付の集合
        self._sq_unmatched = []                 # 取り込めなかった商品 {term, date, time, order, name, qty, amount}
        self._sq_status = {"state": "off", "message": "", "checked_at": None, "last_import": None}
        self._load_square_history()

    def reload_settings_cache(self):
        settings = self.dm.load_settings()
        with self._lock:
            self._conf = {
                "menu": sorted(settings.get("menu", []), key=lambda m: m.get("order", 9999)),
                "terms": list(settings.get("terms", [])),
                "card_width": int(settings.get("card_settings", {}).get("width", 150)),
            }

    def _log(self, user, location, action, target, value, terminal):
        self.dm.log_action(user, location, action, target, value, terminal=terminal)

    # ---------- 端末のログイン ----------
    def login(self, name, is_local):
        name = str(name or "").strip()
        if not name:
            raise RegisterError("名前を入力してください")
        with self._lock:
            t = Terminal(secrets.token_urlsafe(16), name, is_local)
            self.terminals[t.id] = t
            if is_local:
                self.dm.set_terminal_user(name)   # Tkinter 版の入力欄の初期値にも使われる
            self._log(name, "System", "Login", "Success", "Terminal Login" if is_local else "LAN Login", name)
            return t

    def terminal(self, tid, name=None, is_local=False):
        """セッションの端末。親機を再起動して消えていたら、名前から作り直す（販売は終わった状態になる）"""
        if not tid:
            return None
        with self._lock:
            t = self.terminals.get(tid)
            if t is None and name:
                t = Terminal(tid, name, is_local)
                self.terminals[tid] = t
            if t is not None:
                t.last_seen = time.time()
            return t

    def logout(self, t):
        with self._lock:
            self.terminals.pop(t.id, None)
            self._log(t.name, "System", "Logout", "Success", "", t.name)

    # 子機のパスワード。変えると、それまでにログインしていた子機はログインし直しになる
    def passcode_key(self):
        code = str(self.dm.load_settings().get("lan_passcode", "") or "")
        return hashlib.sha256(code.encode("utf-8")).hexdigest()[:16] if code else None

    def check_passcode(self, code):
        expected = str(self.dm.load_settings().get("lan_passcode", "") or "")
        if not expected:
            raise RegisterError("親機の Settings で「子機のパスワード」を設定してください")
        if not secrets.compare_digest(str(code or ""), expected):
            raise RegisterError("パスワードが違います")

    # ---------- ダッシュボード ----------
    def dashboard(self):
        settings = self.dm.load_settings()
        active = set(settings.get("active_terms", []))
        kinds = {ADJUST_TERM: "adjust", TEST_TERM: "test"}
        terms = settings.get("terms", []) + list(SPECIAL_TERMS)
        return {"terms": [{"name": t, "enabled": t in active, "kind": kinds.get(t, "normal")} for t in terms]}

    # ---------- 管理者設定 ----------
    def admin_login(self, t, password):
        settings = self.dm.load_settings()
        with self._lock:
            if str(password or "") != str(settings.get("adminPass", "")):
                self._log(t.name, "Settings", "AdminLogin", "Web", "Failed", t.name)
                raise RegisterError("パスワードが違います")
            token = secrets.token_urlsafe(24)
            self._admin_tokens.add(token)
            self._log(t.name, "Settings", "AdminLogin", "Web", "Success", t.name)
            return token

    def is_admin(self, token):
        with self._lock:
            return bool(token) and any(secrets.compare_digest(token, x) for x in self._admin_tokens)

    def admin_settings(self):
        settings = self.dm.load_settings()
        menu = sorted(settings.get("menu", []), key=lambda m: m.get("order", 9999))
        terms = settings.get("terms", [])
        targets = settings.get("targets", {})
        with self._lock:
            operating = any(x.active for x in self.terminals.values())
        return {
            "menu": [{
                "name": m["name"],
                "price": int(m.get("price", 0)),
                "visible": bool(m.get("visible", True)),
            } for m in menu],
            "terms": terms,
            "special_terms": list(SPECIAL_TERMS),
            "active_terms": settings.get("active_terms", []),
            "targets": {x: int(targets.get(x, 0) or 0) for x in terms},
            "operating": operating,
        }

    def save_admin_settings(self, t, data):
        terms = [str(x).strip() for x in data.get("terms") or []]
        if not terms:
            raise RegisterError("期間を1つ以上登録してください")
        self._check_names(terms, "期間名")
        for x in terms:
            if x in SPECIAL_TERMS:
                raise RegisterError(f"「{x}」は期間名に使えません")

        menu = []
        for m in data.get("menu") or []:
            menu.append({
                "name": str(m.get("name", "")).strip(),
                "price": self._to_int(m.get("price"), "価格"),
                "visible": bool(m.get("visible")),
                "order": (len(menu) + 1) * 10,
            })
        self._check_names([m["name"] for m in menu], "商品名")

        targets = {x: self._to_int((data.get("targets") or {}).get(x), "目標金額") for x in terms}
        selectable = set(terms) | set(SPECIAL_TERMS)
        active = [x for x in data.get("active_terms") or [] if x in selectable]

        with self._lock:
            settings = self.dm.load_settings()
            settings.update({
                "terms": terms,
                "menu": menu,
                "targets": targets,
                "active_terms": active,
            })
            self.dm.save_settings_file(settings)
            self._log(t.name, "Settings", "UpdateSettings", "Web", "Updated", t.name)
        # メニュー・価格の変更は、販売中の端末にもすぐ反映される
        self.reload_settings_cache()

    # ---------- 子機の接続 ----------
    def lan_settings(self):
        settings = self.dm.load_settings()
        now = time.time()
        with self._lock:
            terminals = sorted(self.terminals.values(), key=lambda x: (not x.is_local, x.name))
            return {
                "passcode": str(settings.get("lan_passcode", "") or ""),
                "terminals": [{
                    "name": x.name,
                    "is_local": x.is_local,
                    "mode": x.mode if x.active else None,
                    "operator": x.operator if x.active else None,
                    "seen": _ago(now - x.last_seen),
                } for x in terminals],
            }

    def save_lan_settings(self, t, data):
        code = str(data.get("passcode") or "").strip()
        if code and len(code) < 4:
            raise RegisterError("パスワードは 4 文字以上にしてください")
        with self._lock:
            settings = self.dm.load_settings()
            settings["lan_passcode"] = code
            self.dm.save_settings_file(settings)
            self._log(t.name, "Settings", "UpdateLanPasscode", "Web", "Set" if code else "Cleared", t.name)

    # ---------- Square 連携 ----------
    def square_settings(self):
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

    def save_square_settings(self, t, data):
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
            self._log(t.name, "Settings", "UpdateSquare", "Web", env, t.name)
        self.square.clear_cache()

    def square_locations(self, data):
        """入力中（空なら保存済み）のトークンで Square につなぎ、店舗の一覧を返す（接続テスト）"""
        env = data.get("environment")
        if env not in API_BASE:
            raise RegisterError("接続先（本番/サンドボックス）を選んでください")
        token = str(data.get("access_token") or "").strip()
        if not token:
            token = load_config(self.dm.load_settings())["access_token"]
        try:
            return SquareClient(token, env).list_locations()
        except SquareError as e:
            raise RegisterError(str(e))

    def square_reconcile(self, t, term=None, refresh=False):
        with self._lock:
            mine = t.mode if t.active else None
            current = self._import_term()
            term = term or mine
            if not term:
                raise RegisterError("期間を指定してください")
            order_terms = dict(self._sq_imported)
            import_days = set(self._sq_import_days.get(term, ()))
        auto = load_config(self.dm.load_settings())["auto_import"]
        today = date.today()

        def belongs(payment, day):
            # 取り込んだ会計は、取り込んだ期間の Square 実績に数える。
            # まだ取り込んでいない今日の会計は、次の取り込みで入る期間に数える
            x = order_terms.get(payment["order_id"])
            if x is not None:
                return x == term
            return term == current and day == today

        # Square への問い合わせは時間がかかることがあるので、ロックは持たずに行う。
        # 自動取り込みがオフのときは、会計がどの期間のものか分からないので、その日の決済をすべて数える
        result = self.square.reconcile(term, include_today=term in (current, mine), refresh=refresh,
                                       belongs=belongs if auto else None, extra_days=import_days)
        with self._lock:
            result["unmatched"] = [u for u in self._sq_unmatched if u["term"] == term]
            result["sync"] = dict(self._sq_status)
        return result

    # ---------- Square の会計の自動取り込み ----------
    def _import_term(self):
        """Square の会計を取り込む期間：いちばん最後に販売を始めた端末の期間（テスト・調整は除く）。
        しばらく通信のない端末（閉じたまま放置されたブラウザなど）より、動いている端末を優先する"""
        selling = [x for x in self.terminals.values() if x.active and x.mode not in SPECIAL_TERMS]
        fresh = [x for x in selling if time.time() - x.last_seen < FRESH_SEC]
        cands = fresh or selling
        return max(cands, key=lambda x: x.started_at).mode if cands else None

    def square_sync(self):
        """Square で完了した会計を取り込む（web_main.py のスレッドから 15 秒ごとに呼ばれる）"""
        if not self._sq_sync_lock.acquire(blocking=False):
            return
        try:
            self._square_sync()
        finally:
            self._sq_sync_lock.release()

    def _square_sync(self):
        conf = load_config(self.dm.load_settings())
        with self._lock:
            term = self._import_term()
            special = any(x.active and x.mode in SPECIAL_TERMS for x in self.terminals.values())
        if not conf["access_token"] or not conf["auto_import"]:
            return self._set_sq_status("off")
        if term is None:
            return self._set_sq_status(
                "paused", "テスト・調整では取り込みません" if special else "販売を始めると取り込みます")

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
            if self._import_term() != term:
                return
            new = [o for o in orders if o.get("id") and o["id"] not in self._sq_imported]
            qty = sum(self._import_order(o, term) for o in new)
            if new:
                self._save_term(term)
                self._sq_status["last_import"] = {
                    "time": datetime.now().strftime("%H:%M"), "orders": len(new), "qty": qty, "term": term}
        self._set_sq_status("ok")

    def _import_order(self, order, term):
        """会計 1 件を期間 term の個数に足す（ロックを持って呼ぶ）。足した個数を返す"""
        ptype, lines = order_lines(order)
        oid = order["id"]
        closed = _local_time(order.get("closed_at"))
        total = sum(amount for _, _, amount in lines)
        when = f"{closed:%Y-%m-%d %H:%M:%S} " if closed else ""
        self._log("Square", term, "SquareImport", oid, f"{when}合計 ¥{total:,}", "Square")
        names = {m["name"] for m in self._visible_menu()}
        added = 0
        unmatched = []
        for name, qty, amount in lines:
            if name in names:
                self._apply_count(term, name, ptype, qty, by="Square", user="Square", terminal="Square")
                added += qty
            else:
                unmatched.append((name, qty, amount))
        # メニューにない商品・金額だけ打った会計は、画面に出して手で入力してもらう。
        # 集計（analytics.py）は SquareImport の直後に続く Add/Sub を 1 件の会計とみなすので、Add/Sub の後に書く
        for name, qty, amount in unmatched:
            u = _unmatched(term, closed or datetime.now(), oid, name, qty, amount)
            self._log("Square", term, "SquareUnmatched", oid, _unmatched_text(u), "Square")
            self._sq_unmatched.append(u)
        self._remember_import(oid, term, datetime.now().date())
        return added

    def _remember_import(self, order_id, term, day):
        self._sq_imported[order_id] = term
        self._sq_import_days.setdefault(term, set()).add(day)

    def square_resolve_unmatched(self, t, term):
        """取り込めなかった商品を「確認済み」にして一覧から消す（手で入力し終えたあとなど）"""
        with self._lock:
            done = [u for u in self._sq_unmatched if u["term"] == term]
            user = t.operator if t.active else t.name
            for u in done:
                self._log(user, term, "SquareResolved", u["order"], _unmatched_text(u), t.name)
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

    # ---------- 販売モード（端末ごと） ----------
    def start_operation(self, t, mode, operator):
        mode = str(mode or "")
        operator = str(operator or "").strip()
        if not operator:
            raise RegisterError("担当者の名前を入力してください")
        settings = self.dm.load_settings()
        valid = settings.get("terms", []) + list(SPECIAL_TERMS)
        if mode not in valid or mode not in settings.get("active_terms", []):
            raise RegisterError(f"「{mode}」は現在選択できません")
        self.reload_settings_cache()
        with self._lock:
            # テストの個数は、誰もテストを使っていないところから始めるときに 0 に戻す
            if mode == TEST_TERM and not any(x.active and x.is_test for x in self.terminals.values() if x is not t):
                self._counts[TEST_TERM] = {}
            t.operator = operator
            t.mode = mode
            t.active = True
            t.started_at = time.time()
            self._log(operator, mode, "EnterMode", "Screen", "Start", t.name)
        # 販売を始めたら、待たずに Square の会計を取り込む
        threading.Thread(target=self.square_sync, daemon=True).start()

    def exit_operation(self, t):
        with self._lock:
            t.active = False
            t.mode = None

    def change_operator(self, t, name):
        name = str(name or "").strip()
        if not name:
            raise RegisterError("名前を入力してください")
        with self._lock:
            self._require_active(t)
            t.operator = name
            self._log(t.name, t.mode, "ChangeOperator", "System", f"Changed to {name}", t.name)

    def commit_pc_order(self, t, drafts):
        with self._lock:
            self._require_active(t)
            names = {m["name"] for m in self._visible_menu()}
            counts = self._term_counts(t.mode)
            changes = []
            for d in drafts or []:
                name = d.get("name")
                if name not in names:
                    raise RegisterError(f"商品が見つかりません: {name}")
                for ptype in PTYPES:
                    try:
                        qty = int(d.get(ptype) or 0)
                    except (TypeError, ValueError):
                        raise RegisterError("個数が正しくありません")
                    if qty == 0:
                        continue
                    now = counts.get(name, {}).get(ptype, 0)
                    if not t.allow_negative and now + qty < 0:
                        raise RegisterError(f"{name}（{PTYPE_JP[ptype]}）の個数がマイナスになります")
                    changes.append((name, ptype, qty))
            if not changes:
                raise RegisterError("確定する商品がありません")

            lines = [f"・{n} ({PTYPE_JP[p]}) x{q:+d}" for n, p, q in changes]
            self._log(t.operator, t.mode, "CommitOrder", "PC", f"合計 {len(changes)}種\n" + "\n".join(lines), t.name)
            for name, ptype, qty in changes:
                self._apply_count(t.mode, name, ptype, qty, by=t.operator, user=t.operator, terminal=t.name)
            self._save_term(t.mode)

    # ---------- 画面用スナップショット ----------
    def snapshot(self, t):
        with self._lock:
            items, totals = self._items_for(t.mode) if t.active else ([], {"term": 0, "cumulative": 0, "total": 0})
            return {
                "logged_in": True,
                "terminal_user": t.name,
                "is_local": t.is_local,
                "active": t.active,
                "mode": t.mode,
                "operator": t.operator,
                "is_test": t.is_test,
                "allow_negative": t.allow_negative,
                "card_width": self._conf["card_width"],
                "items": items,
                "totals": totals,
                "square": {
                    **self._sq_status,
                    "unmatched": sum(1 for u in self._sq_unmatched if u["term"] == t.mode),
                    "import_term": self._import_term(),
                },
            }

    def _items_for(self, mode):
        """期間 mode の商品カードの内容と、料金・累積・総合"""
        terms = self._conf["terms"]
        # 累積は「調整」とその期間までの合計、総合は全期間（テストは含めない）
        running = [ADJUST_TERM] + (terms[:terms.index(mode) + 1] if mode in terms else [])
        everything = terms + [ADJUST_TERM]
        zero = {"cash": 0, "paypay": 0}

        def sum_of(name, term_list):
            out = dict(zero)
            for x in term_list:
                c = self._term_counts(x).get(name, zero)
                out["cash"] += c["cash"]
                out["paypay"] += c["paypay"]
            return out

        items = []
        totals = {"term": 0, "cumulative": 0, "total": 0}
        for i, m in enumerate(self._visible_menu()):
            name, price = m["name"], int(m.get("price", 0))
            term = dict(self._term_counts(mode).get(name, zero))
            cumulative = sum_of(name, running)
            total = sum_of(name, everything)
            items.append({
                "name": name,
                "price": price,
                "keys": SHORTCUT_KEYS[i] if i < len(SHORTCUT_KEYS) else None,
                "term": term,
                "total": total,
            })
            for key, c in (("term", term), ("cumulative", cumulative), ("total", total)):
                totals[key] += (c["cash"] + c["paypay"]) * price
        return items, totals

    # ---------- 内部処理 ----------
    def _visible_menu(self):
        return [m for m in self._conf["menu"] if m.get("visible", True)]

    def _term_counts(self, term):
        """期間の個数（初めて使うときに CSV から読む）。全端末で共有する"""
        if term not in self._counts:
            data = {} if term == TEST_TERM else self.dm.load_csv_data(f"{term}.csv")
            self._counts[term] = {name: dict(c) for name, c in data.items()}
        return self._counts[term]

    @staticmethod
    def _require_active(t):
        if not t.active:
            raise RegisterError("販売モードではありません")

    def _apply_count(self, term, name, ptype, qty, by, user, terminal):
        c = self._term_counts(term).setdefault(name, {"cash": 0, "paypay": 0})
        new_val = c[ptype] + qty
        action = "Add" if qty > 0 else "Sub"
        self._log(user, term, action, f"{name} [{ptype}]", f"{qty:+d} (Term: {new_val}) by {by}", terminal)
        c[ptype] = new_val

    def _save_term(self, term):
        if term == TEST_TERM:
            return
        rows = [SimpleNamespace(name=name, counts={"term": c}) for name, c in self._term_counts(term).items()]
        self.dm.save_csv_data(f"{term}.csv", rows)


def _ago(sec):
    if sec < 10:
        return "今"
    if sec < 60:
        return f"{int(sec)}秒前"
    if sec < 3600:
        return f"{int(sec // 60)}分前"
    return f"{int(sec // 3600)}時間前"


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
