# web_main.py
"""ブラウザ版のレジ画面。

    python web_main.py

で起動すると http://127.0.0.1:5002/ がブラウザで開く。
見た目は static/register.css、画面の動きは static/register.js で編集できる。

    python web_main.py --dev

で起動すると、register.css を保存するたびにページを再読み込みせずに見た目だけ反映される。
register.html と register.js は保存後にブラウザで F5 を押せば反映される（再起動は不要）。

データ（system_data/）は Tkinter 版 main.py と共通。
両方を同時に起動すると、同じファイルへの書き込みやポートが衝突するので、どちらか一方だけを使うこと。
"""
import logging
import os
import sys
import threading
import time
import webbrowser

from flask import Flask, abort, jsonify, render_template, request

import analytics
from data_manager import DataManager
from register_state import RegisterError, RegisterState

# この PC からのみアクセス可能
HOST = "127.0.0.1"
PORT = 5002
SQUARE_SYNC_SEC = 15   # Square の会計を取り込む間隔


def create_app(state, dev=False):
    app = Flask(__name__)
    # 開発モードでは register.html の変更を再起動なしで反映する（F5 で読み直す）
    app.config["TEMPLATES_AUTO_RELOAD"] = dev

    @app.before_request
    def require_json_for_post():
        # 他のサイトからのフォーム送信で操作されないよう、POST は JSON のみ受け付ける
        if request.method == "POST" and not request.is_json:
            abort(415)

    @app.errorhandler(RegisterError)
    def handle_register_error(e):
        return jsonify({"error": str(e)}), 400

    def body():
        return request.get_json(silent=True) or {}

    @app.get("/")
    def index():
        return render_template("register.html", dev=dev)

    if dev:
        @app.get("/dev/css-mtime")
        def get_css_mtime():
            # CSS の更新日時。ブラウザ側がこれを監視して変わったら CSS だけ読み直す
            return str(os.path.getmtime(os.path.join(app.static_folder, "register.css")))

    @app.get("/pc/api/state")
    def get_state():
        return jsonify(state.snapshot())

    @app.get("/pc/api/dashboard")
    def get_dashboard():
        return jsonify(state.dashboard())

    @app.get("/pc/api/analytics")
    def get_analytics():
        return jsonify(analytics.build(state.dm, request.args.get("term"), state.current_mode))

    @app.post("/pc/api/admin/login")
    def post_admin_login():
        return jsonify({"token": state.admin_login(body().get("password"))})

    def require_admin():
        if not state.is_admin(request.headers.get("X-Admin-Token")):
            abort(401)

    @app.get("/pc/api/admin/settings")
    def get_admin_settings():
        require_admin()
        return jsonify(state.admin_settings())

    @app.post("/pc/api/admin/settings")
    def post_admin_settings():
        require_admin()
        state.save_admin_settings(body())
        return jsonify(state.admin_settings())

    @app.get("/pc/api/admin/square")
    def get_admin_square():
        require_admin()
        return jsonify(state.square_settings())

    @app.post("/pc/api/admin/square")
    def post_admin_square():
        require_admin()
        state.save_square_settings(body())
        return jsonify(state.square_settings())

    @app.post("/pc/api/admin/square/locations")
    def post_admin_square_locations():
        require_admin()
        return jsonify({"locations": state.square_locations(body())})

    @app.post("/pc/api/square/sync")
    def post_square_sync():
        state.square_sync()
        return jsonify(state.snapshot())

    @app.post("/pc/api/square/resolve")
    def post_square_resolve():
        return jsonify({"resolved": state.square_resolve_unmatched(body().get("term"))})

    @app.get("/pc/api/square/reconcile")
    def get_square_reconcile():
        refresh = request.args.get("refresh") == "1"
        return jsonify(state.square_reconcile(request.args.get("term"), refresh=refresh))

    @app.post("/pc/api/login")
    def post_login():
        state.login(body().get("name"))
        return jsonify(state.snapshot())

    @app.post("/pc/api/start")
    def post_start():
        b = body()
        state.start_operation(b.get("mode"), b.get("operator"))
        return jsonify(state.snapshot())

    @app.post("/pc/api/exit")
    def post_exit():
        state.exit_operation()
        return jsonify(state.snapshot())

    @app.post("/pc/api/operator")
    def post_operator():
        state.change_operator(body().get("name"))
        return jsonify(state.snapshot())

    @app.post("/pc/api/commit")
    def post_commit():
        state.commit_pc_order(body().get("drafts"))
        return jsonify(state.snapshot())

    return app


def main():
    logging.getLogger("werkzeug").setLevel(logging.ERROR)
    dm = DataManager()
    dm.log_action("System", "System", "Startup", "WebApp", "Launched")
    dev = "--dev" in sys.argv
    state = RegisterState(dm)
    app = create_app(state, dev=dev)
    threading.Thread(target=square_sync_loop, args=(state,), daemon=True).start()

    url = f"http://{HOST}:{PORT}/"
    print(f"レジ画面: {url}  （終了するにはこのウィンドウで Ctrl+C）")
    if dev:
        print("開発モード: register.css を保存すると自動で反映されます")
    if "--no-browser" not in sys.argv:
        threading.Timer(1.0, webbrowser.open, args=(url,)).start()
    app.run(host=HOST, port=PORT, threaded=True, use_reloader=False)


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
