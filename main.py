# main.py
import tkinter as tk
from tkinter import ttk, messagebox
from datetime import datetime
import uuid
from collections import defaultdict
import platform # OS判定用
from tkinter import simpledialog

try:
    import qrcode
    from PIL import ImageTk
except ImportError:
    qrcode = None

from config import COLORS, FONT_L, FONT_M, FONT_S, CARD_HEIGHT, CARD_WIDTH, FONT_NORMAL
from data_manager import DataManager
from gui_parts import (
    NotificationPanel, FactoryResetWindow, MenuManager, CollapsibleControlPanel,
    ConnectionSetting, RestoreWindow, LogViewer, NumberPad, SalesCard,
    LoginPanel, SalesOverviewWindow, MobileSettingsWindow,
    AdminLoginWindow, AdminPanel, OrderSummaryWindow, OperatorLoginDialog, ItemAddDialog
)
from mobile_server import MobileServer

class App:

    def stop_server_service(self):
        """データパッキング時などにサーバーを強制停止する"""
        try:
            from pyngrok import ngrok
            ngrok.kill()
            self.mobile_server.is_host = False
            self.mobile_server.public_url = None
            self.check_connection_status() # 即座に反映
        except Exception as e:
            print(f"Server stop error: {e}")


    def is_input_active(self):
        focused = self.root.focus_get()
        if isinstance(focused, tk.Entry): return True
        if self.current_numpad:
            try:
                if self.current_numpad.winfo_exists(): return True
            except tk.TclError: self.current_numpad = None
        return False

    def get_active_menu_status(self):
        if not self.active_sales_mode: return []
        res = []
        for item in self.items:
            if item.mobile_active:
                res.append({"name": item.name, "price": item.price})
        return res





    def open_sales_overview(self):
        SalesOverviewWindow(self.root, self.data_manager)
    def open_log_viewer(self):
        LogViewer(self.root, self.data_manager)
    

    def show_admin_login(self):
        # 管理者認証を経て、別ウィンドウでパネルを開く
        AdminLoginWindow(self.root, self.data_manager, self.show_admin_panel)

    def show_admin_panel(self, admin_name):
        # 画面遷移ではなく、Toplevelウィンドウとして開く
        win = tk.Toplevel(self.root)
        win.title("管理者パネル")
        win.geometry("1100x750")
        win.configure(bg=COLORS["bg"])
        win.transient(self.root)
        win.grab_set()
        
        # ★修正: 現在の端末使用者(current_user_name)も渡す
        AdminPanel(win, self, admin_name, self.current_user_name)

    def confirm_exit(self):
        if messagebox.askokcancel("モード終了", "ダッシュボードに戻りますか？\n\n【注意】\n・モバイル連携はこのモードで停止します\n・未処理の通知は全て削除されます"):
            self.show_dashboard()




    def on_notification_action(self, act):
        if not self.notification_panel: return
        
        # 'detail' アクションのハンドリングを追加
        if act in ['approve', 'cancel', 'detail']:
            self.notification_panel.trigger_selected_action(act)
        
        if act == 'approve':
            pass
            #self.notification_panel.remove_selected()
        elif act == 'cancel':
            pass

    def toggle_mob_key(self, idx):
        if self.is_input_active(): return
        # idx 0('1') -> 0番目 ... idx 9('0') -> 9番目
        target = idx
        if target < len(self.items):
            self.items[target].toggle_mobile()



    def auto_save(self):
        self.update_total_header()
        if not self.is_test_mode: self.data_manager.save_csv_data(self.current_csv_file, self.items)

    def update_total_header(self):
        v = [0,0,0]
        for i in self.items:
            for j, val in enumerate(i.get_totals()): v[j] += val
        for i, k in enumerate(['t','c','a']): self.total_labels[k].config(text=f"¥{v[i]:,}")

    def setup_shortcuts(self):
        for item in self.items:
            if len(item.keys) == 6:
                ca, ci, cs, pa, pi, ps = item.keys
                if not ca: continue
                self.root.bind(f'<Key-{ca}>', lambda e, it=item: self.do_sc(it, 'cash', 1))
                self.root.bind(f'<Key-{ci}>', lambda e, it=item: self.open_numpad_singleton(it, 'cash'))
                self.root.bind(f'<Key-{cs}>', lambda e, it=item: self.do_sc(it, 'cash', -1))
                self.root.bind(f'<Key-{pa}>', lambda e, it=item: self.do_sc(it, 'paypay', 1))
                self.root.bind(f'<Key-{pi}>', lambda e, it=item: self.open_numpad_singleton(it, 'paypay'))
                self.root.bind(f'<Key-{ps}>', lambda e, it=item: self.do_sc(it, 'paypay', -1))



    def check_connection_status(self):
        url = self.mobile_server.get_public_url()
        
        if url:
            self.is_online = True
            bg_col = COLORS["status_bar_online"]
            txt = "CHANNEL OPEN"
        else:
            self.is_online = False
            bg_col = COLORS["status_bar_offline"]
            txt = "CHANNEL CLOSED"
        
        try:
            self.status_bar.config(bg=bg_col)
            self.lbl_status_text.config(text=txt, bg=bg_col)
            # 背景色だけ更新、テキストは維持
            self.lbl_current_user.config(bg=bg_col)
            if self.side_panel:
                self.side_panel.update_status(self.current_user_name, self.is_online)
        except: pass
            
        self.root.after(3000, self.check_connection_status)


  



    def update_cart_monitor(self, user, items):
        self.cart_state[user] = items
        item_watchers = defaultdict(list)
        for u, u_items in self.cart_state.items():
            for i in u_items: item_watchers[i['name']].append(f"{u}:{i['amount']}")
        if self.active_sales_mode:
            # 個々のカードの描画負荷は SalesCard 側で軽減される
            for card in self.items:
                watchers = item_watchers.get(card.name, [])
                card.update_monitor(watchers)
            
            # ★UX改善: 多くのウィジェット更新後、まとめて描画を処理し、ブレを軽減
            self.root.update_idletasks() 



   
    def show_qr_code(self):
        url = self.mobile_server.get_public_url()
        top = tk.Toplevel(self.root)
        top.title("モバイル接続 QRコード")
        top.geometry("400x550") # サイズ調整
        top.configure(bg="white")
        
        tk.Label(top, text="モバイル端末でアクセス", font=FONT_M, bg="white").pack(pady=(20, 10))

        if not url:
            tk.Label(top, text="⚠ チャンネルが閉鎖されているか、\nNgrok接続に失敗しています。\nモバイル設定を確認してください。", 
                     font=FONT_S, bg="#FFEBEE", fg="red", padx=10, pady=10).pack(pady=10)
            url_display = "接続失敗 / 待機中"
        else:
            try:
                # QRコード生成と表示
                if qrcode:
                    img = qrcode.make(url, box_size=8, border=2)
                    tk_img = ImageTk.PhotoImage(img)
                    lbl_qr = tk.Label(top, image=tk_img, bg="white")
                    lbl_qr.image = tk_img
                    lbl_qr.pack(pady=20)
                else:
                     tk.Label(top, text="QRコード生成ライブラリがありません", bg="white").pack(pady=20)
            except Exception as e:
                tk.Label(top, text=f"QR生成エラー: {e}", bg="white").pack(pady=20)
            
            url_display = url

        f_in = tk.Frame(top, bg="white"); f_in.pack(pady=10)
        tk.Label(f_in, text="URL:", bg="white", font=FONT_S).pack(anchor="w")
        self.url_var = tk.StringVar(value=url_display)
        # Entryはreadonlyにしてユーザーがコピペできるようにする
        tk.Entry(f_in, textvariable=self.url_var, font=("Helvetica",12), width=35, bg="#FAFAFA", state='readonly').pack()
        
        tk.Button(top, text="閉じる", command=top.destroy, bg=COLORS["btn_primary"], fg="white", relief="flat").pack(pady=20)




    def reload_ngrok_connection(self):
        """Ngrok設定変更時、またはトグル時に接続をリフレッシュする"""
        print("Reloading Ngrok connection...")
        self.stop_server_service()
        # 少し待機してから再接続
        self.root.after(1000, self._start_ngrok_after_reload)

    def _start_ngrok_after_reload(self):
        settings = self.data_manager.load_settings()
        token = settings.get("ngrok_token", "")
        
        # 既存の接続エラーメッセージをクリア
        try:
            if self.side_panel:
                self.side_panel.clear_ngrok_error()
        except:
            pass

        # トグル状態を確認
        if settings.get("ngrok_connect_enabled", True): # デフォルトはTrue
            try:
                self.mobile_server.set_auth_token(token)
                self.mobile_server.start()
                
                # 接続確認。Ngrok接続開始後、public_urlが取れない場合は失敗と見なす
                if not self.mobile_server.get_public_url():
                    error_msg = "Ngrok接続に失敗しました。トークンまたは設定を確認してください。"
                    messagebox.showerror("接続エラー", error_msg)
                    if self.side_panel:
                        self.side_panel.set_ngrok_error(error_msg)
                
                # 状態確認を再開
                self.check_connection_status()
            except Exception as e:
                error_msg = f"Ngrok起動エラー: {e}"
                messagebox.showerror("接続エラー", error_msg)
                if self.side_panel:
                    self.side_panel.set_ngrok_error(error_msg)
                self.is_online = False
        else:
            # トグルがOFFの場合、接続をクローズした状態を維持
            self.is_online = False
            self.status_bar.config(bg=COLORS["status_bar_offline"])
            self.lbl_status_text.config(text="CHANNEL CLOSED", bg=COLORS["status_bar_offline"])
            self.lbl_current_user.config(bg=COLORS["status_bar_offline"])

    def open_connection_settings(self):
        # ★修正: Ngrok/通信設定用の新しいウィンドウを開く
        ConnectionSetting(self.root, self.data_manager, self.current_user_name, on_save_callback=self.reload_ngrok_connection)

    def open_mobile_settings(self):
        # ★修正: MobileSettingsWindow を開き、メッセージ/パスワード/通知設定のみを扱う
        MobileSettingsWindow(self.root, self.data_manager, self.current_user_name) 

# main.py の変更・追加されたメソッドのみ記述します

    def show_login(self):
        self.status_bar.pack_forget()
        for w in self.container.winfo_children(): w.destroy()
        LoginPanel(self.container, self.data_manager, self.on_login_success)

    def on_login_success(self, user_name):
        self.current_user_name = user_name
        self.lbl_current_user.config(text=f"Terminal : {user_name}")
        
        # ログイン自体のログは "General User" として記録
        self.data_manager.log_action(user_name, "System", "Login", "Success", "Terminal Login")
        
        self.status_bar.pack(side="top", fill="x", before=self.container)
        self.status_bar.pack_propagate(False)
        
        self.mobile_server = MobileServer(self, self.data_manager)
        settings = self.data_manager.load_settings()
        
        # トグル設定をロード
        self.connect_enabled = settings.get("ngrok_connect_enabled", True)

        if self.connect_enabled:
            # 設定値に基づいて接続を開始
            self.mobile_server.set_auth_token(settings.get("ngrok_token", ""))
            self.mobile_server.start()
            self.check_connection_status()
        else:
            self.is_online = False
            self.status_bar.config(bg=COLORS["status_bar_offline"])
            self.lbl_status_text.config(text="CHANNEL CLOSED", bg=COLORS["status_bar_offline"])
            self.lbl_current_user.config(bg=COLORS["status_bar_offline"])
            self.check_connection_status() # 状態確認ループは開始しておく

        self.show_dashboard()


    def log_wrapper(self, mode, action, target, value, user=None):
        # 指定がなければ 現在のOperatorを使用
        log_user = user if user else self.current_operator_name
        self.data_manager.log_action(log_user, mode, action, target, value)

    def do_sc(self, item, ptype, amount):
        if not self.active_sales_mode or self.is_input_active(): return
        # ドラフトへの加算処理
        item.update_draft_count(ptype, amount)

    def open_numpad_singleton(self, card, ptype):
        if self.is_input_active(): return 
        if self.current_numpad: self.current_numpad.destroy()
        def on_input(val):
            # ドラフトへの加算処理（テンキー入力分を加算）
            card.update_draft_count(ptype, val)
            self.current_numpad = None
        self.current_numpad = NumberPad(self.root, card.name, card.name, card.price, ptype, on_input)



# main.py

    # ★変更: ダッシュボードでは担当者変更ボタンを表示しない設定(show_opt_btn=False)を渡す

    # ★変更: モード内では担当者変更ボタンを表示(show_opt_btn=True)
# main.py

    # ★変更: モバイル注文受信時の承認フローを変更

# main.py

    # ★変更: 汎用ウィンドウへデータを渡すように修正


    # ★変更: 通知パネルから呼ばれるが、承認時は OrderSummaryWindow (Mode=MOBILE) を開く

# main.py

    # ★変更: ダッシュボードでも担当者変更ボタンを表示(show_opt_btn=True)
    def show_dashboard(self):
        self.active_sales_mode = False
        self.notification_panel = None
        self.side_panel = None
        self.current_mode = None
        
        for w in self.container.winfo_children(): w.destroy()
        
        self.side_panel = CollapsibleControlPanel(self.container, self, show_opt_btn=True)
        self.side_panel.pack(side="left", fill="y")
        self.side_panel.update_status(self.current_user_name, self.is_online)

        main_area = tk.Frame(self.container, bg=COLORS["bg"])
        main_area.pack(side="right", fill="both", expand=True)

        cf = tk.Frame(main_area, bg=COLORS["bg"])
        cf.place(relx=0.5, rely=0.5, anchor="center")
        
        tk.Label(cf, text="DASHBOARD", font=FONT_L, bg=COLORS["bg"], fg=COLORS["text_main"]).pack(pady=(0, 40))
        
        settings = self.data_manager.load_settings()
        active_terms = settings.get("active_terms", [])
        btns = settings.get("terms", []) + ["調整", "テスト"]
        
        grid_f = tk.Frame(cf, bg=COLORS["bg"])
        grid_f.pack()
        
        for i, t in enumerate(btns):
            bg, fg = "white", COLORS["text_main"]
            state = "normal"
            
            if t not in active_terms:
                state = "disabled"
                bg, fg = COLORS["disabled"], "#90A4AE"
            else:
                if t == "調整":
                    bg, fg = "#FFCC80", "#E65100"
                elif t == "テスト":
                    bg, fg = "#90CAF9", "#1565C0"
            
            cmd = lambda x=t: self.start_operation(x, is_test=(x=="テスト"), allow_neg=(x=="調整"))
            
            tk.Button(grid_f, text=t, font=FONT_M, bg=bg, fg=fg, relief="flat", width=16, height=2, state=state, command=cmd).grid(row=i//2, column=i%2, padx=10, pady=10)

        self.root.unbind('<Left>'); self.root.unbind('<Right>')
        self.root.unbind('<F1>'); self.root.unbind('<Return>')
        self.root.unbind('<Delete>'); self.root.unbind('<BackSpace>')
        self.root.unbind('<Escape>'); self.root.unbind('<Key-space>')
        for k in "1234567890": self.root.unbind(k)

    # ★変更: レジモード以外ではアラートを出して中断
    def change_operator(self):
        if not self.active_sales_mode:
            messagebox.showwarning("操作不可", "レジ担当者の変更は、販売モード（各日程の画面）に入ってから行ってください。")
            return

        dlg = OperatorLoginDialog(self.root, "担当者変更", "新しいレジ担当者の名前を入力してください")
        operator = dlg.result
        
        if operator:
            self.current_operator_name = operator
            self.data_manager.log_action(self.current_user_name, self.current_mode, "ChangeOperator", "System", f"Changed to {operator}")
            if self.side_panel:
                self.side_panel.set_operator_name(operator)
            messagebox.showinfo("変更完了", f"レジ担当者を {operator} に変更しました。")


# main.py




    def confirm_pc_order(self):
        if not self.active_sales_mode or self.is_input_active(): return
        
        display_items = []
        draft_target_cards = []
        
        total_qty = 0
        total_yen = 0
        log_lines = []
        
        for item in self.items:
            draft = item.get_draft_counts() 
            
            for ptype in ['cash', 'paypay']:
                qty = draft[ptype]
                if qty != 0:
                    sub = qty * item.price
                    total_qty += qty
                    total_yen += sub
                    
                    display_items.append({
                        'name': item.name,
                        'ptype': "現金" if ptype=="cash" else "PayPay",
                        'qty': qty,
                        'subtotal': sub
                    })
                    
                    ptype_jp = "現金" if ptype=="cash" else "PayPay"
                    log_lines.append(f"・{item.name} ({ptype_jp}) x{qty:+d}")
            
            if draft['cash'] != 0 or draft['paypay'] != 0:
                draft_target_cards.append(item)
        
        if not display_items:
            return 

        def on_confirm():
            # ★変更: 実行前の最終確認アラート (Yes/No)
            if not messagebox.askyesno("確認", "注文を確定しますか？"):
                return False # Falseを返すとウィンドウを閉じない

            # 1. 確定サマリーログ
            log_content = "\n".join(log_lines)
            self.data_manager.log_action(
                self.current_operator_name, 
                self.current_mode, 
                "CommitOrder", 
                "PC", 
                f"合計 {len(display_items)}種\n{log_content}"
            )
            
            # 2. 個別のAdd/Subログ & データ更新
            for card in draft_target_cards:
                card.commit_draft(self.current_operator_name) 
                
            self.auto_save()
            # ★変更: 「完了しました」アラートは削除
            return True # 処理完了、ウィンドウを閉じる

        OrderSummaryWindow(self.root, display_items, total_qty, total_yen, on_confirm, mode="PC")


    def process_mobile_order_batch(self, user_name, items, ptype):
        if not self.active_sales_mode: return
        
        mobile_user_label = user_name 
        item_details = ", ".join([f"{i['name']} x{i['amount']}" for i in items])
        
        self.data_manager.log_action(mobile_user_label, "Mobile", "ReceiveOrder", ptype, f"From {user_name}: {item_details}")
        
        notif_id = str(uuid.uuid4())

        def open_confirm_window():
            display_items = []
            total_qty = 0
            total_yen = 0
            
            for order_item in items:
                name = order_item['name']
                qty = int(order_item['amount'])
                
                price = 0
                for card in self.items:
                    if card.name == name:
                        price = card.price
                        break
                
                sub = qty * price
                total_qty += qty
                total_yen += sub
                
                display_items.append({
                    'name': name,
                    'ptype': "現金" if ptype=="cash" else "PayPay",
                    'qty': qty,
                    'subtotal': sub
                })
            
            OrderSummaryWindow(self.root, display_items, total_qty, total_yen, final_commit, mode="MOBILE", user_name=user_name)
            return False 

        def final_commit():
            # ★変更: モバイル承認時も確認アラートを出す
            if not messagebox.askyesno("確認", "注文を確定しますか？"):
                return False

            log_lines = []
            ptype_jp = "現金" if ptype=="cash" else "PayPay"
            operator_name = self.current_operator_name
            
            for order_item in items:
                name = order_item['name']
                amount = int(order_item['amount'])
                log_lines.append(f"・{name} ({ptype_jp}) x{amount}")

            # 1. 承認サマリーログ
            log_content = "\n".join(log_lines)
            self.data_manager.log_action(
                operator_name, 
                "Mobile", 
                "CommitOrder", 
                f"From {user_name}", 
                f"合計 {len(items)}種\n{log_content}"
            )
            
            # 2. 個別のAddログ
            for order_item in items:
                name = order_item['name']
                amount = int(order_item['amount'])
                target_card = None
                for item in self.items:
                    if item.name == name: target_card = item; break
                
                if target_card and amount > 0:
                    target_card.update_term_count(ptype, amount, user_name=f"{operator_name} (via Mobile)")

            if self.notification_panel:
                idx = self.notification_panel.get_notification_index_by_id(notif_id)
                if idx != -1: self.notification_panel.remove_notification(idx)
            
            return True

        def revert_order():
            self.root.unbind('<Return>') 
            ans = messagebox.askyesno("注文取消し確認", f"❌ {user_name} の注文を破棄しますか？\n売上は計上されません。")
            self.root.after(200, lambda: self.root.bind('<Return>', lambda e: self.confirm_pc_order()))
            
            if ans:
                 self.data_manager.log_action(self.current_operator_name, "System", "CancelOrder", user_name, "Revert-Approved")
                 return True
            return False

        if self.notification_panel:
            ts = datetime.now().strftime("%H:%M:%S")
            data = {
                "id": notif_id,
                "timestamp": ts,
                "user": user_name,
                "ptype": ptype,
                "items": items
            }
            self.notification_panel.add_notification(data, on_approve=open_confirm_window, on_cancel=revert_order)
            
        self.update_cart_monitor(user_name, [])


# main.py (変更メソッドのみ)

 
    def load_items_and_data(self):
        for item in self.items: item.destroy()
        self.items = []
        
        settings = self.data_manager.load_settings()
        menu_list = settings.get("menu", [])
        
        menu_list_sorted = sorted(menu_list, key=lambda x: x.get("order", 9999))

        t_data = {}
        if not self.is_test_mode: t_data = self.data_manager.load_csv_data(self.current_csv_file)
        stats = self.data_manager.calculate_stats(self.current_mode, settings.get("terms", []))
        keys = [('q','a','z','Q','A','Z'), ('w','s','x','W','S','X'), ('e','d','c','E','D','C'), ('r','f','v','R','F','V'), ('t','g','b','T','G','B'), ('y','h','n','Y','H','N'), ('u','j','m','U','J','M'), ('i','k',',','I','K','<'), ('o','l','.','O','L','>'), ('p',';','/','P','+','?')]
        
        for i, item in enumerate([m for m in menu_list_sorted if m.get("visible", True)]):
            name = item["name"]; price = item["price"]
            k = keys[i] if i < len(keys) else ('','','','','','')
            
            # ★変更: width引数を渡す
            card = SalesCard(self.scrollable_frame, name, price, i, "", k, 
                             self.open_numpad_singleton, self.auto_save, self.log_wrapper, 
                             self.current_mode, self.allow_negative, 
                             height=self.current_card_height, width=self.current_card_width)
            
            if item.get("mobile_visible", False): card.toggle_mobile()
            d = t_data.get(name, {'cash':0,'paypay':0})
            if self.is_test_mode: d = {'cash':0,'paypay':0}
            card.load_initial_data(d, stats[name]['cumulative'], stats[name]['total'])
            self.items.append(card)
            card.grid(row=0, column=i, padx=5, pady=10)
        
        self.setup_shortcuts()
        self.scrollable_frame.update_idletasks()

# main.py (変更メソッドのみ)

# main.py (変更メソッドのみ)


# main.py (変更メソッドのみ)

    # ★追加: リサイズイベントハンドラ
    def on_window_resize(self, event):
        # ルートウィンドウのリサイズのみに反応させる
        if event.widget == self.root:
            # サイズが変わっていないなら無視（無限ループ防止）
            if event.width == self.last_win_width and event.height == self.last_win_height:
                return
            
            self.last_win_width = event.width
            self.last_win_height = event.height
            
            # レイアウト再計算とカード更新
            self.update_card_layout()

    # ★追加: サイズ計算とカード更新を一括で行うメソッド
# main.py (変更メソッドと末尾ブロックのみ)

    # __init__ は前回の変更（DPI削除済み）のままでOKですが、念のため全文載せます
    def __init__(self, root):
        self.root = root
        self.root.title("レジシステム")
        self.root.geometry("1280x950") 
        self.root.configure(bg=COLORS["bg"])
        
        # ★変更: DPI設定コードはここにも入れない
        
        # 起動時に最大化 (Windows用)
        try:
            self.root.state('zoomed')
        except:
            pass 
        
        self.data_manager = DataManager()
        self.data_manager.log_action("System", "System", "Startup", "App", "Launched")
        
        self.current_mode = None 
        self.active_sales_mode = False
        self.current_user_name = "Unknown"
        self.current_operator_name = "Unassigned" 
        self.is_online = False

        self.current_numpad = None
        self.current_card_height = 520
        self.current_card_width = 140 
        
        # リサイズ検知用キャッシュ
        self.last_win_width = 0
        self.last_win_height = 0
        
        self.status_bar = tk.Frame(root, bg=COLORS["status_bar_offline"], height=30)
        self.lbl_status_text = tk.Label(self.status_bar, text="OFFLINE", bg=COLORS["status_bar_offline"], fg=COLORS["status_text"], font=("Helvetica", 10, "bold"))
        self.lbl_status_text.pack(side="right", padx=20)
        self.lbl_current_user = tk.Label(self.status_bar, text="", bg=COLORS["status_bar_offline"], fg=COLORS["status_text"], font=("Helvetica", 10))
        self.lbl_current_user.pack(side="left", padx=20)

        self.container = tk.Frame(root, bg=COLORS["bg"])
        self.container.pack(fill="both", expand=True)
        
        self.side_panel = None
        self.notification_panel = None
        self.items = [] 
        self.cart_state = {} 

        self.show_login()


# ... (中略: setup_operation_screen など他のメソッドは変更なし) ...

# main.py (変更メソッドのみ)
# main.py (変更メソッドのみ)


# main.py (変更メソッドのみ)

 
    def update_card_layout(self):
        if not self.active_sales_mode: return
        
        self.root.update_idletasks()

        win_height = self.root.winfo_height()
        
        # 縦幅計算
        calc_height = win_height - 420
        if calc_height < 350: calc_height = 350
        self.current_card_height = calc_height
        
        # ★変更: 横幅は設定値を使用
        settings = self.data_manager.load_settings()
        self.current_card_width = int(settings.get("card_settings", {}).get("width", 130))
        
        try:
            self.canvas.config(height=calc_height + 30)
            for card in self.items:
                card.resize(self.current_card_width, self.current_card_height)
        except: pass

# main.py (変更メソッドのみ)

    def setup_operation_screen(self, parent):
        h = tk.Frame(parent, bg=COLORS["header_bg"], pady=10); h.pack(side="top", fill="x")
        tb = tk.Frame(h, bg=COLORS["header_bg"]); tb.pack(fill="x", padx=20)
        tk.Button(tb, text="← 終了 (Esc)", command=self.confirm_exit, bg=COLORS["btn_primary"], fg="white", relief="flat", font=FONT_S).pack(side="left")
        tk.Label(tb, text=f"{self.current_mode}", fg="white", bg=COLORS["header_bg"], font=FONT_M).pack(side="left", padx=20)
        
        sc = tk.Frame(h, bg=COLORS["header_bg"]); sc.pack(pady=10)
        self.total_labels = {}
        for i, (t, k) in enumerate([("Term", "t"), ("累積", "c"), ("総合", "a")]):
            f = tk.Frame(sc, bg=COLORS["stat_panel"], padx=15, pady=5); f.grid(row=0, column=i, padx=10)
            tk.Label(f, text=t, fg="#B0BEC5", bg=COLORS["stat_panel"], font=("Helvetica", 9)).pack()
            l = tk.Label(f, text="¥0", fg=COLORS["stat_val"], bg=COLORS["stat_panel"], font=("Helvetica", 18, "bold")); l.pack()
            self.total_labels[k] = l
            
        self.notification_panel = NotificationPanel(parent, self.data_manager)
        self.notification_panel.pack(side="bottom", fill="x")
        
        wrapper = tk.Frame(parent, bg=COLORS["bg"]); wrapper.pack(side="top", fill="both", expand=True)
        self.v_center_f = tk.Frame(wrapper, bg=COLORS["bg"])
        self.v_center_f.pack(expand=True, fill="x")
        
        # 設定読み込み
        settings = self.data_manager.load_settings()
        card_conf = settings.get("card_settings", {})
        
        # ★変更: 縦幅の決定 (設定値優先、0なら自動計算)
        fixed_h = int(card_conf.get("height", 0))
        if fixed_h > 0:
            calc_height = fixed_h
        else:
            # 自動計算
            win_height = self.root.winfo_height()
            calc_height = win_height - 420
            if calc_height < 350: calc_height = 350
            
        self.current_card_height = calc_height
        self.current_card_width = int(card_conf.get("width", 130))

        self.canvas = tk.Canvas(self.v_center_f, bg=COLORS["bg"], height=calc_height + 30, highlightthickness=0)
        self.scrollbar = ttk.Scrollbar(self.v_center_f, orient="horizontal", command=self.canvas.xview)
        self.scrollable_frame = tk.Frame(self.canvas, bg=COLORS["bg"])
        
        self.scrollable_frame.bind("<Configure>", lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        
        def on_canvas_configure(event):
            req_w = self.scrollable_frame.winfo_reqwidth()
            if req_w < event.width: self.canvas.create_window((event.width // 2, 15), window=self.scrollable_frame, anchor="n")
            else: self.canvas.create_window((0, 15), window=self.scrollable_frame, anchor="nw")
                
        def _on_mousewheel(event):
            try:
                if platform.system() == 'Windows':
                    if event.delta: self.canvas.xview_scroll(int(-1*(event.delta/120)), "units")
                elif platform.system() == 'Darwin': 
                    if event.delta: self.canvas.xview_scroll(int(-1*event.delta), "units")
                else:
                    if event.num == 4: self.canvas.xview_scroll(-1, "units")
                    elif event.num == 5: self.canvas.xview_scroll(1, "units")
            except: pass

        self.canvas.bind("<Configure>", on_canvas_configure)
        self.canvas.bind_all("<MouseWheel>", _on_mousewheel)
        self.canvas.bind_all("<Button-4>", _on_mousewheel)
        self.canvas.bind_all("<Button-5>", _on_mousewheel)

        self.canvas.configure(xscrollcommand=self.scrollbar.set)
        self.canvas.pack(side="top", fill="x", pady=10)
        self.scrollbar.pack(side="bottom", fill="x")
        
        self.items = []
        
        self.root.bind("<Configure>", self.on_window_resize)
        self.root.update_idletasks()

        self.load_items_and_data()
        
        self.root.after(200, self.update_card_layout)
        
        self.setup_shortcuts()
        self.update_total_header()

    def update_card_layout(self):
        if not self.active_sales_mode: return
        
        self.root.update_idletasks()

        settings = self.data_manager.load_settings()
        card_conf = settings.get("card_settings", {})
        
        # ★変更: 縦幅ロジック
        fixed_h = int(card_conf.get("height", 0))
        
        if fixed_h > 0:
            self.current_card_height = fixed_h
        else:
            win_height = self.root.winfo_height()
            if win_height <= 100: win_height = self.root.winfo_screenheight()
            
            calc_height = win_height - 420
            if calc_height < 350: calc_height = 350
            self.current_card_height = calc_height
        
        self.current_card_width = int(card_conf.get("width", 130))
        
        try:
            self.canvas.config(height=self.current_card_height + 30)
            for card in self.items:
                card.resize(self.current_card_width, self.current_card_height)
        except: pass

    def start_operation(self, mode_name, is_test=False, allow_neg=False):
        dlg = OperatorLoginDialog(self.root, "担当者入力", "レジ担当者の名前を入力してください")
        operator = dlg.result
        if not operator: return
            
        self.current_operator_name = operator
        self.current_mode = mode_name
        self.is_test_mode = is_test
        self.allow_negative = allow_neg
        self.current_csv_file = f"{mode_name}.csv"
        
        self.data_manager.log_action(self.current_operator_name, mode_name, "EnterMode", "Screen", "Start")
        
        for w in self.container.winfo_children(): w.destroy()
        
        self.side_panel = CollapsibleControlPanel(self.container, self, show_opt_btn=True)
        self.side_panel.pack(side="left", fill="y")
        self.side_panel.update_status(self.current_user_name, self.is_online)
        self.side_panel.set_operator_name(self.current_operator_name)
        
        main_area = tk.Frame(self.container, bg=COLORS["bg"])
        main_area.pack(side="right", fill="both", expand=True)

        self.setup_operation_screen(main_area)
        self.active_sales_mode = True
        
        self.root.bind('<Left>', lambda e: self.notification_panel.select_prev())
        self.root.bind('<Right>', lambda e: self.notification_panel.select_next())
        
        self.root.bind('<Key-space>', lambda e: self.on_notification_action('approve'))
        self.root.bind('<Return>', lambda e: self.confirm_pc_order())
        
        self.root.bind('<Delete>', lambda e: self.handle_backspace())
        self.root.bind('<BackSpace>', lambda e: self.handle_backspace())
        
        # ★変更: F1で現金へ、F2でPayPayへ一括移動（Tabは廃止）
        self.root.bind('<F1>', lambda e: self.move_all_drafts('cash'))
        self.root.bind('<F2>', lambda e: self.move_all_drafts('paypay'))
        
        self.root.bind('<Escape>', lambda e: self.confirm_exit())

        for i, k in enumerate("1234567890"):
            self.root.bind(k, lambda e, idx=i: self.toggle_mob_key(idx))

    # ★追加: 全カードのドラフトを指定の支払い方法へ移動
    def move_all_drafts(self, target_ptype):
        if not self.active_sales_mode or self.is_input_active(): return
        for item in self.items:
            item.move_drafts_to(target_ptype)
        return "break"

    # BackSpace/Deleteキーのハンドリング（前回と同様）
    def handle_backspace(self):
        if not self.active_sales_mode or self.is_input_active(): return

        has_draft = False
        for item in self.items:
            if item.has_drafts():
                has_draft = True
                break
        
        if has_draft:
            for item in self.items:
                item.clear_drafts()
        else:
            self.on_notification_action('cancel')
if __name__ == "__main__":


    root = tk.Tk()
    app = App(root)
    root.mainloop()