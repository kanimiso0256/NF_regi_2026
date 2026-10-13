# mobile_server.py (変更クラスのみ)

import threading
import logging
import time
import os
import sys
from flask import Flask, request, jsonify, render_template_string, make_response
from pyngrok import ngrok, conf

import subprocess
import pyngrok.process

_original_popen = subprocess.Popen

def _no_console_popen(*args, **kwargs):
    if isinstance(args[0], (list, tuple)) and "ngrok" in args[0][0].lower():
        kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
    return _original_popen(*args, **kwargs)

subprocess.Popen = _no_console_popen

log = logging.getLogger('werkzeug')
log.setLevel(logging.ERROR)

VER = int(time.time())

MOBILE_HTML = f"""
<!DOCTYPE html>
<html lang="ja">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
    <meta http-equiv="Pragma" content="no-cache">
    <meta http-equiv="Cache-Control" content="no-cache">
    <meta http-equiv="Expires" content="0">
    <title>オーダー端末 v{VER}</title>
    <style>
        * {{ box-sizing: border-box; touch-action: manipulation; -webkit-tap-highlight-color: transparent; }}
        body {{ font-family: -apple-system, BlinkMacSystemFont, "Helvetica Neue", Arial, sans-serif; background-color: #F5F7F9; margin: 0; padding: 0; color: #333; padding-bottom: 160px; }}
        
        .header {{ background: #37474F; color: white; padding: 15px; position: sticky; top: 0; z-index: 10; box-shadow: 0 2px 5px rgba(0,0,0,0.1); display: flex; justify-content: space-between; align-items: center; }}
        .staff-name {{ font-weight: bold; font-size: 1.1rem; color: #80CBC4; }}
        .status {{ font-size: 0.8rem; color: #CFD8DC; }}

        #info-area {{ padding: 15px 15px 0 15px; display: none; }}
        
        .info-box {{ 
            background: #FFFFFF; 
            border: 1px solid #E0E0E0;
            border-top: 3px solid #29B6F6; 
            color: #455A64; 
            padding: 15px; 
            border-radius: 4px; 
            font-size: 0.95rem; 
            line-height: 1.6;
            margin-bottom: 15px; 
            box-shadow: 0 1px 2px rgba(0,0,0,0.05);
            text-align: left;
            white-space: pre-wrap;
        }}

        .alert-msg-box {{ 
            background: #FFEBEE; 
            border: 1px solid #FFCDD2;
            border-top: 3px solid #EF5350; 
            color: #C62828; 
            padding: 15px; 
            border-radius: 4px; 
            font-size: 1.0rem; 
            font-weight: bold; 
            margin-bottom: 15px; 
            text-align: left; 
            box-shadow: 0 1px 2px rgba(0,0,0,0.05);
            white-space: pre-wrap;
        }}

        #login-area {{ position: fixed; top: 0; left: 0; width: 100%; height: 100%; background: #263238; z-index: 100; display: flex; flex-direction: column; justify-content: center; align-items: center; padding: 20px; }}
        .login-card {{ background: white; padding: 30px 20px; border-radius: 12px; width: 100%; max-width: 400px; text-align: center; box-shadow: 0 4px 15px rgba(0,0,0,0.3); }}
        input[type="text"], input[type="password"] {{ font-size: 1.2rem; padding: 15px; width: 100%; margin-bottom: 15px; border: 1px solid #CFD8DC; border-radius: 8px; text-align: center; background: #FAFAFA; }}
        .btn-login {{ background: #009688; color: white; border: none; padding: 15px; border-radius: 8px; font-size: 1.2rem; font-weight: bold; width: 100%; cursor: pointer; box-shadow: 0 4px 0 #00796B; margin-top: 10px; }}
        
        #menu-area {{ padding: 10px; display: none; }}
        .item-row {{ background: white; border-radius: 8px; padding: 15px; margin-bottom: 10px; display: flex; justify-content: space-between; align-items: center; box-shadow: 0 1px 3px rgba(0,0,0,0.05); transition: 0.3s; border: 1px solid #ECEFF1; }}
        .item-row.disabled {{ background: #FFEBEE; border: 1px solid #EF5350; opacity: 0.8; pointer-events: none; }}
        .item-row.disabled .item-name {{ color: #D32F2F; text-decoration: line-through; }}
        .item-info {{ flex: 1; }}
        .item-name {{ font-weight: bold; font-size: 1.1rem; margin-bottom: 4px; color: #37474F; }}
        .item-price {{ color: #78909C; font-size: 0.9rem; }}
        .item-controls {{ display: flex; align-items: center; gap: 15px; background: #F5F5F5; padding: 5px; border-radius: 30px; }}
        .btn-circle {{ width: 45px; height: 45px; border-radius: 50%; border: none; font-size: 1.5rem; font-weight: bold; color: white; cursor: pointer; display: flex; align-items: center; justify-content: center; transition: 0.1s; }}
        .btn-circle:active {{ transform: scale(0.95); }}
        .btn-minus {{ background: #B0BEC5; }}
        .btn-minus.active {{ background: #EF5350; }}
        .btn-plus {{ background: #29B6F6; }}
        .count-val {{ font-size: 1.4rem; font-weight: bold; min-width: 35px; text-align: center; color: #37474F; }}

        .footer {{ position: fixed; bottom: 0; left: 0; width: 100%; background: white; box-shadow: 0 -2px 15px rgba(0,0,0,0.08); padding: 15px; z-index: 20; display: none; flex-direction: column; gap: 10px; border-top: 1px solid #EEE; }}
        .total-area {{ display: flex; justify-content: space-between; align-items: center; margin-bottom: 5px; border-bottom: 1px solid #eee; padding-bottom: 10px; }}
        .total-label {{ font-size: 1rem; color: #555; }}
        .total-price {{ font-size: 1.6rem; font-weight: bold; color: #263238; }}
        .action-btns {{ display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }}
        .btn-action {{ border: none; padding: 15px; border-radius: 8px; font-size: 1.1rem; font-weight: bold; color: white; cursor: pointer; opacity: 0.5; pointer-events: none; transition: 0.2s; position: relative; overflow: hidden; }}
        .btn-action.ready {{ opacity: 1; pointer-events: auto; }}
        .btn-cash {{ background: #66BB6A; box-shadow: 0 4px 0 #00796B; }}
        .btn-pay {{ background: #EF5350; box-shadow: 0 4px 0 #D32F2F; }}
        .btn-action:active {{ transform: translateY(4px); box-shadow: none; }}
        
        .alert-box {{ background: #D32F2F; color: white; padding: 12px; border-radius: 8px; font-size: 0.9rem; margin-bottom: 10px; display: none; text-align: center; font-weight: bold; box-shadow: 0 2px 5px rgba(0,0,0,0.2); }}
    </style>
</head>
<body>
    <div id="login-area">
        <div class="login-card">
            <h2 style="margin-bottom:20px; color:#37474F;">担当者ログイン</h2>
            <input type="text" id="username" placeholder="名前 (例: 佐藤)">
            <input type="password" id="pass" placeholder="パスワード">
            <button class="btn-login" onclick="doLogin()">開始する</button>
            <div id="login-msg" style="color:red; margin-top:10px; font-size:0.9rem;"></div>
        </div>
    </div>

    <div class="header">
        <div class="staff-name" id="disp-name">担当: 未設定</div>
        <div class="status" id="status">接続中...</div>
    </div>

    <div id="info-area"></div>

    <div id="menu-area">
        <div class="alert-box" id="alert-box">⚠ 選択中の商品が販売停止になりました</div>
        <div id="menu-list"></div>
    </div>

    <div class="footer" id="footer">
        <div class="total-area">
            <span class="total-label">カート計: <span id="total-count">0</span>点</span>
            <span class="total-price">¥<span id="total-yen">0</span></span>
        </div>
        <div class="action-btns">
            <button class="btn-action btn-cash" id="btn-cash" onclick="submitOrder('cash')">現金で送信</button>
            <button class="btn-action btn-pay" id="btn-pay" onclick="submitOrder('paypay')">Payで送信</button>
        </div>
    </div>

    <script>
        const API_BASE = "";
        let currentUser = "";
        let menuItems = [];
        let cart = {{}}; 
        let lastCartJson = "";
        let lastInfo = "";
        let lastAlert = "";

        document.addEventListener('DOMContentLoaded', () => {{
            try {{
                const saved = localStorage.getItem("pos_username");
                if (saved) document.getElementById('username').value = saved;
            }} catch(e) {{}}
        }});

        async function doLogin() {{
            const name = document.getElementById('username').value.trim();
            const pass = document.getElementById('pass').value.trim();
            const msg = document.getElementById('login-msg');
            
            if (!name || !pass) {{ msg.innerText = "名前とパスワードを入力してください"; return; }}
            msg.innerText = "認証中...";
            
            try {{
                const res = await fetch(API_BASE + '/api/login', {{
                    method: 'POST',
                    headers: {{ 'Content-Type': 'application/json' }},
                    body: JSON.stringify({{ username: name, password: pass }})
                }});
                const data = await res.json();
                if (data.success) {{
                    currentUser = name;
                    try {{ localStorage.setItem("pos_username", name); }} catch(e) {{}}
                    showMain();
                }} else {{
                    msg.innerText = "パスワードが違います";
                }}
            }} catch(e) {{
                msg.innerText = "通信エラー: " + e.message;
            }}
        }}

        function showMain() {{
            document.getElementById('login-area').style.display = 'none';
            document.getElementById('menu-area').style.display = 'block';
            document.getElementById('footer').style.display = 'flex';
            document.getElementById('info-area').style.display = 'block';
            document.getElementById('disp-name').innerText = `担当: ${{currentUser}}`;
            poll(); 
        }}

        async function poll() {{
            try {{
                const res = await fetch(API_BASE + '/api/menu', {{ headers: {{ "ngrok-skip-browser-warning": "true" }} }});
                if (!res.ok) throw new Error("Network Error");
                const data = await res.json();
                
                if (data.info !== lastInfo || data.alert !== lastAlert) {{
                    lastInfo = data.info;
                    lastAlert = data.alert;
                    let html = "";
                    if (lastAlert) html += `<div class="alert-msg-box">${{lastAlert}}</div>`;
                    if (lastInfo) html += `<div class="info-box">${{lastInfo}}</div>`;
                    document.getElementById('info-area').innerHTML = html;
                    document.getElementById('info-area').style.display = (html ? 'block' : 'none');
                }}

                if (!data.mode) {{
                    document.getElementById('status').innerText = "準備中";
                    document.getElementById('menu-list').innerHTML = '<div style="text-align:center; padding:40px; color:#777;">PC側で販売を開始してください</div>';
                }} else {{
                    document.getElementById('status').innerText = `モード: ${{data.mode}}`;
                    updateMenuUI(data.items);
                    menuItems = data.items;
                    sendCartStatus();
                }}
            }} catch (e) {{
                document.getElementById('status').innerText = "通信切断";
            }}
            setTimeout(poll, 2000); 
        }}

        function updateMenuUI(items) {{
            const container = document.getElementById('menu-list');
            const validNames = items.map(i => i.name);
            let hasDisabledInCart = false;
            let html = "";
            
            items.forEach(item => {{
                const count = cart[item.name] || 0;
                const minusClass = count > 0 ? "btn-circle btn-minus active" : "btn-circle btn-minus";
                html += `
                <div class="item-row">
                    <div class="item-info">
                        <div class="item-name">${{item.name}}</div>
                        <div class="item-price">@${{item.price.toLocaleString()}}</div>
                    </div>
                    <div class="item-controls">
                        <button class="${{minusClass}}" onclick="changeCount('${{item.name}}', -1)">－</button>
                        <div class="count-val">${{count}}</div>
                        <button class="btn-circle btn-plus" onclick="changeCount('${{item.name}}', 1)">＋</button>
                    </div>
                </div>`;
            }});

            Object.keys(cart).forEach(name => {{
                if (cart[name] > 0 && !validNames.includes(name)) {{
                    hasDisabledInCart = true;
                    html += `
                    <div class="item-row disabled">
                        <div class="item-info">
                            <div class="item-name">${{name}}</div>
                            <div class="item-price">販売停止</div>
                        </div>
                        <div class="item-controls">
                            <button class="btn-circle btn-minus active" style="pointer-events:auto;" onclick="changeCount('${{name}}', -999)">削除</button>
                            <div class="count-val">${{cart[name]}}</div>
                        </div>
                    </div>`;
                }}
            }});

            container.innerHTML = html;
            const alertBox = document.getElementById('alert-box');
            if (hasDisabledInCart) {{ alertBox.style.display = "block"; toggleSubmit(false); }}
            else {{ alertBox.style.display = "none"; updateTotal(items); }}
        }}

        function changeCount(name, delta) {{
            if (!cart[name]) cart[name] = 0;
            cart[name] += delta;
            if (cart[name] <= 0) delete cart[name];
            updateMenuUI(menuItems);
            sendCartStatus();
        }}

        function updateTotal(items) {{
            let totalCount = 0; let totalYen = 0;
            items.forEach(item => {{
                const c = cart[item.name] || 0;
                if (c > 0) {{ totalCount += c; totalYen += c * item.price; }}
            }});
            document.getElementById('total-count').innerText = totalCount;
            document.getElementById('total-yen').innerText = totalYen.toLocaleString();
            toggleSubmit(totalCount > 0);
        }}

        function toggleSubmit(enable) {{
            const cBtn = document.getElementById('btn-cash');
            const pBtn = document.getElementById('btn-pay');
            if (enable) {{ cBtn.classList.add('ready'); pBtn.classList.add('ready'); }}
            else {{ cBtn.classList.remove('ready'); pBtn.classList.remove('ready'); }}
        }}

        async function sendCartStatus() {{
            const currentCartJson = JSON.stringify(cart);
            if (currentCartJson === lastCartJson) return; 
            const cartItems = [];
            Object.keys(cart).forEach(name => {{ cartItems.push({{ name: name, amount: cart[name] }}); }});
            try {{
                await fetch(API_BASE + '/api/cart_update', {{
                    method: 'POST',
                    headers: {{ 'Content-Type': 'application/json', "ngrok-skip-browser-warning": "true" }},
                    body: JSON.stringify({{ user: currentUser, items: cartItems }})
                }});
                lastCartJson = currentCartJson;
            }} catch(e) {{}}
        }}

        async function submitOrder(ptype) {{
            const orderItems = [];
            let confirmMsg = "【注文確認】\\n";
            menuItems.forEach(item => {{
                const c = cart[item.name] || 0;
                if (c > 0) {{ orderItems.push({{ name: item.name, amount: c }}); confirmMsg += `${{item.name}} x${{c}}\\n`; }}
            }});
            if (orderItems.length === 0) return;
            
            confirmMsg += `\\n支払: ${{ptype === 'cash' ? '現金' : 'PayPay'}}\\nよろしいですか？`;
            
            if (ptype === 'paypay') {{
                if (!confirm("【重要】\\nPayPayの決済完了画面を\\nLINEで送信しましたか？")) return;
            }}
            
            if (!confirm(confirmMsg)) return;

            try {{
                const res = await fetch(API_BASE + '/api/order', {{
                    method: 'POST',
                    headers: {{ 'Content-Type': 'application/json', "ngrok-skip-browser-warning": "true" }},
                    body: JSON.stringify({{ user: currentUser, items: orderItems, type: ptype }})
                }});
                const result = await res.json();
                if (result.success) {{
                    alert("送信しました！");
                    cart = {{}}; lastCartJson = "";
                    updateMenuUI(menuItems); sendCartStatus(); 
                }} else {{
                    alert("エラー: " + result.message);
                }}
            }} catch (e) {{ alert("通信エラー"); }}
        }}
    </script>
</body>
</html>
"""

class MobileServer:
    def __init__(self, tk_app, data_manager):
        self.app = Flask(__name__)
        self.tk_app = tk_app
        self.dm = data_manager
        self.setup_routes()
        self.server_thread = None
        
        self.public_url = None
        self.is_host = False
        self.connection_error = None

    def setup_routes(self):
        @self.app.route('/')
        def index():
            response = make_response(render_template_string(MOBILE_HTML))
            response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
            return response

        @self.app.route('/api/login', methods=['POST'])
        def login():
            data = request.json
            name = data.get("username", "Unknown")
            pw = data.get("password", "")
            correct_pass = self.dm.load_settings().get("mobile_password", "1234")
            
            if pw == correct_pass:
                self.dm.log_action(name, "Mobile", "Login", "System", "Success")
                return jsonify({"success": True})
            
            self.dm.log_action(name, "Mobile", "Login", "System", "Failed: Wrong Pass")
            return jsonify({"success": False})

        @self.app.route('/api/menu')
        def get_menu():
            menu_data = self.tk_app.get_active_menu_status()
            mode = self.tk_app.current_mode if getattr(self.tk_app, 'active_sales_mode', False) else None
            settings = self.dm.load_settings()
            info = settings.get("mobile_info", "")
            alert = settings.get("mobile_alert", "")
            return jsonify({"mode": mode, "items": menu_data, "info": info, "alert": alert})

        @self.app.route('/api/cart_update', methods=['POST'])
        def cart_update():
            data = request.json
            user = data.get('user', 'Unknown')
            items = data.get('items', [])
            self.tk_app.root.after(0, lambda: self.tk_app.update_cart_monitor(user, items))
            return jsonify({"success": True})

        @self.app.route('/api/order', methods=['POST'])
        def order():
            if not getattr(self.tk_app, 'active_sales_mode', False):
                return jsonify({"success": False, "message": "PC側で販売を終了しています"})
            data = request.json
            user = data.get('user', 'Unknown')
            items = data.get('items', []) 
            ptype = data.get('type', 'paypay')
            if items:
                self.tk_app.root.after(0, lambda: self.tk_app.process_mobile_order_batch(user, items, ptype))
                return jsonify({"success": True})
            else:
                return jsonify({"success": False, "message": "空の注文です"})

    def set_auth_token(self, token):
        if token:
            try: ngrok.set_auth_token(token)
            except Exception as e: print(f"Auth Token Error: {e}")

    def start(self):
        PORT = 5001
        
        # ★変更: ngrok.exeが同階層にあればそれを使う (ポータブル対応)
        if getattr(sys, 'frozen', False):
            base_path = os.path.dirname(sys.executable)
        else:
            base_path = os.path.dirname(os.path.abspath(__file__))
            
        ngrok_exe = os.path.join(base_path, "ngrok.exe")
        
        ngrok_config = conf.get_default()
        ngrok_config.log_level = "critical"
        
        if os.path.exists(ngrok_exe):
            ngrok_config.ngrok_path = ngrok_exe
            print(f"Using local ngrok: {ngrok_exe}")
        
        self.server_thread = threading.Thread(
            target=lambda: self.app.run(host='127.0.0.1', port=PORT, use_reloader=False), 
            daemon=True
        )
        self.server_thread.start()
        
        try:
            # pyngrok_configを渡して接続
            tunnel = ngrok.connect(PORT, pyngrok_config=ngrok_config) 
            self.public_url = tunnel.public_url.replace("http://", "https://")
            self.is_host = True
            self.connection_error = None 
            print(f"Mobile Server Host Established: {self.public_url}")
        except Exception as e:
            print(f"Ngrok Connection Warning: {e}")
            self.public_url = None
            self.is_host = False
            self.connection_error = str(e)

    def get_public_url(self):
        if not self.is_host:
            return None
        try:
            tunnels = ngrok.get_tunnels()
            if not tunnels: return None
            for t in tunnels:
                if t.public_url.startswith("http"):
                    return t.public_url.replace("http://", "https://")
        except: return None
        return None