# web_main.py
"""ブラウザ版のレジ画面。

    python web_main.py

で起動すると http://127.0.0.1:5002/ がブラウザで開く（この PC からのみ使える）。

    python web_main.py --lan

で起動すると、この PC が「親機」になり、同じ Wi-Fi の PC・タブレット（子機）からも
ブラウザで http://<この PC のアドレス>:5002/ を開いて使える。
子機は、親機の Settings で決めた「子機のパスワード」を入れてログインする。
売上は親機にまとめて保存され、Square の取り込みも親機だけが行う。

    python web_main.py --dev

で起動すると、register.css を保存するたびにページを再読み込みせずに見た目だけ反映される。
register.html と register.js は保存後にブラウザで F5 を押せば反映される（再起動は不要）。

データ（system_data/）は Tkinter 版 main.py と共通。
両方を同時に起動すると、同じファイルへの書き込みやポートが衝突するので、どちらか一方だけを使うこと。
"""
import logging
import os
import secrets
import socket
import sys
import threading
import time
import webbrowser
from datetime import timedelta

from flask import Flask, abort, jsonify, render_template, request, session, url_for

import analytics
import share_sheet
from data_manager import DataManager
from register_state import RegisterError, RegisterState

PORT = 5002
SQUARE_SYNC_SEC = 15   # Square の会計を取り込む間隔
LOCAL_ADDRS = ("127.0.0.1", "::1")
LOCK_FILE = "register.lock"   # system_data の中。動いているレジがこのファイルをつかんでおく
EXIT_NOT_STARTED = 3          # 二重起動などで起動しなかったときの終了コード（レジ起動（親機）.bat は起動し直さない）

ALREADY_RUNNING = """
================================================================
  レジはすでにこの PC で起動しています。
  2 つ同時に動かすと、Square の会計を二重に取り込むなど売上がずれるので、
  この起動は止めました。

  ・すでに開いている黒いウィンドウ（レジ起動（親機））をそのまま使ってください。
  ・起動し直したいときは、そのウィンドウを閉じてから、もう一度起動してください。
================================================================
"""

PORT_IN_USE = """
================================================================
  ポート {port} をほかのアプリが使っているため、レジを起動できません。
  そのアプリを閉じてから、もう一度起動してください。
================================================================
"""

_lock_handle = None   # レジが動いている間ずっと開いておく（閉じるとロックが外れる）


def acquire_single_instance(system_dir):
    """同じデータ（system_data）を使うレジが、ほかに動いていないか確かめてロックする。

    ほかで動いていれば False。ロックはプロセスが終わると OS が外すので、強制終了しても残らない
    """
    global _lock_handle
    f = open(os.path.join(system_dir, LOCK_FILE), "a+")
    try:
        if os.name == "nt":
            import msvcrt
            f.seek(0)
            msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        f.close()
        return False
    _lock_handle = f
    return True


def port_in_use(port):
    """ほかのアプリがこのポートで待ち受けているか（Windows では同じポートで 2 つ起動できてしまうため）"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", port)) == 0


def create_app(state, dev=False, lan=False, secret_key=None, sharer=None):
    sharer = sharer or share_sheet.SheetSharer(state.dm)
    app = Flask(__name__)
    app.config.update(
        # 開発モードでは register.html の変更を再起動なしで反映する（F5 で読み直す）
        TEMPLATES_AUTO_RELOAD=dev,
        # 端末ごとのログイン（どの端末か）は、署名付きの Cookie に入れる
        SECRET_KEY=secret_key or secrets.token_hex(32),
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Strict",
        PERMANENT_SESSION_LIFETIME=timedelta(days=7),
    )

    @app.template_global()
    def asset(filename):
        """static のファイルの URL。更新日時を付けて、古い JS・CSS がブラウザに残らないようにする"""
        try:
            v = int(os.path.getmtime(os.path.join(app.static_folder, filename)))
        except OSError:
            v = 0
        return url_for("static", filename=filename, v=v)

    @app.before_request
    def require_json_for_post():
        # 他のサイトからのフォーム送信で操作されないよう、POST は JSON のみ受け付ける
        if request.method == "POST" and not request.is_json:
            abort(415)

    @app.errorhandler(RegisterError)
    def handle_register_error(e):
        return jsonify({"error": str(e)}), 400

    @app.errorhandler(401)
    def handle_not_logged_in(e):
        return jsonify({"error": "ログインしてください", "login": True, "need_passcode": not is_local()}), 401

    @app.errorhandler(403)
    def handle_not_admin(e):
        return jsonify({"error": "もう一度管理者ログインしてください"}), 403

    def body():
        return request.get_json(silent=True) or {}

    def is_local():
        return request.remote_addr in LOCAL_ADDRS

    def terminal():
        """この要求を送ってきた端末。ログインしていなければ None"""
        if not is_local() and session.get("lan_key") != state.passcode_key():
            return None   # 子機はパスワードが変わったらログインし直し
        return state.terminal(session.get("tid"), session.get("name"), is_local())

    def me():
        t = terminal()
        if t is None:
            abort(401)
        return t

    def require_admin():
        me()
        if not state.is_admin(request.headers.get("X-Admin-Token")):
            abort(403)

    @app.get("/")
    def index():
        return render_template("register.html", dev=dev)

    if dev:
        @app.get("/dev/css-mtime")
        def get_css_mtime():
            # CSS の更新日時。ブラウザ側がこれを監視して変わったら CSS だけ読み直す
            return str(os.path.getmtime(os.path.join(app.static_folder, "register.css")))

    # ---------- ログイン ----------
    @app.get("/pc/api/state")
    def get_state():
        t = terminal()
        if t is None:
            return jsonify({"logged_in": False, "need_passcode": not is_local()})
        return jsonify(state.snapshot(t))

    @app.post("/pc/api/login")
    def post_login():
        b = body()
        if not is_local():
            state.check_passcode(b.get("passcode"))
        t = state.login(b.get("name"), is_local())
        session.clear()
        session.permanent = True
        session.update(tid=t.id, name=t.name, lan_key=None if is_local() else state.passcode_key())
        return jsonify(state.snapshot(t))

    @app.post("/pc/api/logout")
    def post_logout():
        state.logout(me())
        session.clear()
        return jsonify({"logged_in": False, "need_passcode": not is_local()})

    # ---------- ダッシュボード ----------
    @app.get("/pc/api/dashboard")
    def get_dashboard():
        me()
        return jsonify(state.dashboard())

    @app.get("/pc/api/analytics")
    def get_analytics():
        t = me()
        return jsonify(analytics.build(state.dm, request.args.get("term"), t.mode if t.active else None))

    # ---------- 管理者設定 ----------
    @app.post("/pc/api/admin/login")
    def post_admin_login():
        return jsonify({"token": state.admin_login(me(), body().get("password"))})

    @app.get("/pc/api/admin/settings")
    def get_admin_settings():
        require_admin()
        return jsonify(state.admin_settings())

    @app.post("/pc/api/admin/settings")
    def post_admin_settings():
        require_admin()
        state.save_admin_settings(me(), body())
        return jsonify(state.admin_settings())

    def lan_info():
        info = state.lan_settings()
        info.update(lan=lan, urls=lan_urls(PORT) if lan else [])
        return info

    @app.get("/pc/api/admin/lan")
    def get_admin_lan():
        require_admin()
        return jsonify(lan_info())

    @app.post("/pc/api/admin/lan")
    def post_admin_lan():
        require_admin()
        state.save_lan_settings(me(), body())
        return jsonify(lan_info())

    @app.get("/pc/api/admin/square")
    def get_admin_square():
        require_admin()
        return jsonify(state.square_settings())

    @app.post("/pc/api/admin/square")
    def post_admin_square():
        require_admin()
        state.save_square_settings(me(), body())
        return jsonify(state.square_settings())

    @app.post("/pc/api/admin/square/locations")
    def post_admin_square_locations():
        require_admin()
        return jsonify({"locations": state.square_locations(body())})

    # ---------- ダッシュボードの共有（Google スプレッドシート） ----------
    @app.get("/pc/api/admin/share")
    def get_admin_share():
        require_admin()
        return jsonify(sharer.settings_view())

    @app.post("/pc/api/admin/share")
    def post_admin_share():
        require_admin()
        t = me()
        try:
            sharer.save(body())
        except ValueError as e:
            raise RegisterError(str(e))
        conf = share_sheet.load_config(state.dm.load_settings())
        state.dm.log_action(t.name, "Settings", "UpdateShare", "Web", "On" if conf["enabled"] else "Off", terminal=t.name)
        return jsonify(sharer.settings_view())

    @app.post("/pc/api/admin/share/send")
    def post_admin_share_send():
        require_admin()
        try:
            sharer.push(force=True)
        except ValueError as e:
            raise RegisterError(str(e))
        return jsonify(sharer.settings_view())

    # ---------- Square ----------
    @app.post("/pc/api/square/sync")
    def post_square_sync():
        t = me()
        state.square_sync()
        return jsonify(state.snapshot(t))

    @app.post("/pc/api/square/resolve")
    def post_square_resolve():
        return jsonify({"resolved": state.square_resolve_unmatched(me(), body().get("term"))})

    @app.get("/pc/api/square/reconcile")
    def get_square_reconcile():
        refresh = request.args.get("refresh") == "1"
        return jsonify(state.square_reconcile(me(), request.args.get("term"), refresh=refresh))

    # ---------- レジ（端末ごと） ----------
    @app.post("/pc/api/start")
    def post_start():
        t = me()
        b = body()
        state.start_operation(t, b.get("mode"), b.get("operator"))
        return jsonify(state.snapshot(t))

    @app.post("/pc/api/exit")
    def post_exit():
        t = me()
        state.exit_operation(t)
        return jsonify(state.snapshot(t))

    @app.post("/pc/api/operator")
    def post_operator():
        t = me()
        state.change_operator(t, body().get("name"))
        return jsonify(state.snapshot(t))

    @app.get("/pc/api/history")
    def get_history():
        return jsonify(state.history(me()))

    @app.post("/pc/api/commit")
    def post_commit():
        t = me()
        state.commit_pc_order(t, body().get("drafts"))
        return jsonify(state.snapshot(t))

    return app


def lan_urls(port):
    """子機から開くときのアドレス（この PC の Wi-Fi・有線のアドレス）"""
    ips = set()
    try:
        # 実際には通信しない。外へ出るときに使われるアドレスを調べるだけ
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("10.255.255.255", 1))
            ips.add(s.getsockname()[0])
    except OSError:
        pass
    try:
        ips.update(socket.gethostbyname_ex(socket.gethostname())[2])
    except OSError:
        pass
    return [f"http://{ip}:{port}/" for ip in sorted(ips) if not ip.startswith(("127.", "169.254."))]


def secret_key(dm):
    """Cookie の署名に使う鍵。settings.json に残し、親機を再起動しても子機がログインし直さずに済むようにする"""
    settings = dm.load_settings()
    if not settings.get("web_secret"):
        settings["web_secret"] = secrets.token_hex(32)
        dm.save_settings_file(settings)
    return settings["web_secret"]


def main():
    logging.getLogger("werkzeug").setLevel(logging.ERROR)
    dm = DataManager()
    # 二重起動を防ぐ（ログに書く前に確かめる）
    if not acquire_single_instance(dm.system_dir):
        print(ALREADY_RUNNING)
        sys.exit(EXIT_NOT_STARTED)
    if port_in_use(PORT):
        print(PORT_IN_USE.format(port=PORT))
        sys.exit(EXIT_NOT_STARTED)
    # 止まったあとに .bat が自動で起動し直したときは、ログに残して後から分かるようにする
    restarted = "--restarted" in sys.argv
    dm.log_action("System", "System", "Startup", "WebApp", "Restarted" if restarted else "Launched")
    if restarted:
        print("※ レジが止まったため、自動で起動し直しました")
    dev = "--dev" in sys.argv
    lan = "--lan" in sys.argv
    state = RegisterState(dm)
    sharer = share_sheet.SheetSharer(dm)
    app = create_app(state, dev=dev, lan=lan, secret_key=secret_key(dm), sharer=sharer)
    threading.Thread(target=square_sync_loop, args=(state,), daemon=True).start()
    threading.Thread(target=share_sheet.share_loop, args=(sharer,), daemon=True).start()

    url = f"http://127.0.0.1:{PORT}/"
    print(f"レジ画面: {url}  （終了するにはこのウィンドウで Ctrl+C）")
    if lan:
        print("親機として起動しました。子機のブラウザで次のどれかを開いてください:")
        for u in lan_urls(PORT) or ["（ネットワークにつながっていません）"]:
            print(f"    {u}")
        if not dm.load_settings().get("lan_passcode"):
            print("※ 子機のパスワードが未設定です。Settings →「子機の接続」で設定してください")
    if dev:
        print("開発モード: register.css を保存すると自動で反映されます")
    if "--no-browser" not in sys.argv:
        threading.Timer(1.0, webbrowser.open, args=(url,)).start()
    # --lan のときだけ、同じネットワークの他の端末からつなげるようにする
    app.run(host="0.0.0.0" if lan else "127.0.0.1", port=PORT, threaded=True, use_reloader=False)


def square_sync_loop(state):
    # 自動取り込みがオフ・販売していないときは、Square には問い合わせずにすぐ戻る
    while True:
        time.sleep(SQUARE_SYNC_SEC)
        try:
            state.square_sync()
        except Exception:
            logging.exception("Square の取り込みに失敗しました")


if __name__ == "__main__":
    main()
