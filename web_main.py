# web_main.py
"""ブラウザ版のレジ画面。

    python web_main.py

で起動すると http://127.0.0.1:5002/ がブラウザで開く。
見た目は static/register.css、画面の動きは static/register.js で編集できる。

    python web_main.py --dev

で起動すると、register.css を保存するたびにページを再読み込みせずに見た目だけ反映される。

データ（system_data/）は Tkinter 版 main.py と共通。
両方を同時に起動すると、同じファイルへの書き込みやポートが衝突するので、どちらか一方だけを使うこと。
"""
import io
import logging
import os
import sys
import threading
import webbrowser

from flask import Flask, abort, jsonify, render_template, request, send_file

from data_manager import DataManager
from register_state import RegisterError, RegisterState

try:
    import qrcode
except ImportError:
    qrcode = None

# この PC からのみアクセス可能（ngrok で外部公開するのはモバイル用の 5001 番だけ）
HOST = "127.0.0.1"
PORT = 5002


def create_app(state, dev=False):
    app = Flask(__name__)

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

    @app.get("/pc/api/connection")
    def get_connection():
        return jsonify(state.connection_status())

    @app.get("/pc/qr.png")
    def get_qr():
        url = state.connection_status()["url"]
        if not url or qrcode is None:
            abort(404)
        buf = io.BytesIO()
        qrcode.make(url, box_size=8, border=2).save(buf)
        buf.seek(0)
        return send_file(buf, mimetype="image/png")

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

    @app.post("/pc/api/toggle_mobile")
    def post_toggle_mobile():
        state.toggle_mobile(body().get("name"))
        return jsonify(state.snapshot())

    @app.post("/pc/api/commit")
    def post_commit():
        state.commit_pc_order(body().get("drafts"))
        return jsonify(state.snapshot())

    @app.post("/pc/api/notifications/<notif_id>/approve")
    def post_approve(notif_id):
        state.approve_notification(notif_id)
        return jsonify(state.snapshot())

    @app.post("/pc/api/notifications/<notif_id>/cancel")
    def post_cancel(notif_id):
        state.cancel_notification(notif_id)
        return jsonify(state.snapshot())

    return app


def main():
    logging.getLogger("werkzeug").setLevel(logging.ERROR)
    dm = DataManager()
    dm.log_action("System", "System", "Startup", "WebApp", "Launched")
    dev = "--dev" in sys.argv
    app = create_app(RegisterState(dm), dev=dev)

    url = f"http://{HOST}:{PORT}/"
    print(f"レジ画面: {url}  （終了するにはこのウィンドウで Ctrl+C）")
    if dev:
        print("開発モード: register.css を保存すると自動で反映されます")
    if "--no-browser" not in sys.argv:
        threading.Timer(1.0, webbrowser.open, args=(url,)).start()
    app.run(host=HOST, port=PORT, threaded=True, use_reloader=False)


if __name__ == "__main__":
    main()
