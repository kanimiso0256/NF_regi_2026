# gui_parts.py
import tkinter as tk
from tkinter import ttk, messagebox
from datetime import datetime
from config import COLORS, FONT_L, FONT_M, FONT_S, FONT_XS, FONT_NORMAL, CARD_WIDTH, CARD_HEIGHT
import os
import platform


class TermSettingsWindow(tk.Toplevel):
    """★追加: ダッシュボード表示ターム設定ウィンドウ"""
    def __init__(self, parent, data_manager, callback):
        super().__init__(parent)
        self.dm = data_manager
        self.callback = callback
        self.title("表示ターム設定")
        self.geometry("400x350")
        self.configure(bg="#F5F7FA")
        self.transient(parent)
        self.grab_set()
        self.focus_force()
        
        self.setup_ui()

    def setup_ui(self):
        tk.Label(self, text="表示する営業日を選択", font=("Helvetica", 14, "bold"), bg="#F5F7FA", fg="#37474F").pack(pady=(20, 10))
        
        settings = self.dm.load_settings()
        # termsには「調整」「テスト」を含まない
        all_terms = settings.get("terms", []) + ["調整", "テスト"] 
        active_terms = set(settings.get("active_terms", []))
        self.term_vars = {}
        
        grid_f = tk.Frame(self, bg="#F5F7FA", padx=10)
        grid_f.pack(fill="x", padx=20, pady=10)
        
        cols = 3
        for i, t in enumerate(all_terms):
            v = tk.BooleanVar(value=(t in active_terms))
            self.term_vars[t] = v
            cb = tk.Checkbutton(grid_f, text=t, variable=v, bg="#F5F7FA", font=("Helvetica", 11), 
                                activebackground="#F5F7FA", selectcolor="white", cursor="hand2", anchor="w")
            cb.grid(row=i//cols, column=i%cols, sticky="w", padx=10, pady=5)
        for i in range(cols): grid_f.columnconfigure(i, weight=1)
        
        tk.Frame(self, bg="#E0E0E0", height=1).pack(fill="x", pady=15)
        
        tk.Button(self, text="設定を保存", bg="#78909C", fg="white", font=("Helvetica", 11, "bold"), 
                  relief="flat", padx=15, pady=8, command=self.save_terms).pack()

    def save_terms(self):
        new_active = [t for t, v in self.term_vars.items() if v.get()]
        self.dm.update_active_terms(new_active)
        self.dm.log_action("General User", "Dashboard", "UpdateTerms", "Settings", str(new_active))
        messagebox.showinfo("保存", "表示設定を保存しました")
        self.destroy()
        if self.callback: self.callback()


class DetailWindow(tk.Toplevel):
    def __init__(self, parent, data_obj):
        super().__init__(parent.winfo_toplevel())
        self.title(f"注文詳細: {data_obj['data']['user']}")
        self.geometry("500x400") 
        self.transient(parent.winfo_toplevel())
        self.grab_set()
        
        self.bind('<Key-space>', lambda e: self.destroy())
        self.focus_force()

        main_f = tk.Frame(self, bg="#F5F7FA", padx=20, pady=20)
        main_f.pack(fill="both", expand=True)
        
        # --- 事前計算 ---
        total_items = 0
        total_yen = 0
        all_menu = parent.dm.load_settings().get("menu", [])
        price_map = {item['name']: item.get('price', 0) for item in all_menu}
        item_row_data = []

        for item in data_obj['data']['items']:
            qty = item['amount']
            name = item['name']
            price = price_map.get(name, 0)
            subtotal = qty * price
            
            total_items += qty
            total_yen += subtotal
            item_row_data.append({'name': name, 'qty': qty, 'price': price, 'subtotal': subtotal})
        
        # --- 1. ヘッダー情報 (TOP) ---
        tk.Label(main_f, text="モバイル注文 - 全詳細", font=("Helvetica", 16, "bold"), bg="#F5F7FA", fg="#37474F").pack(anchor="w", pady=(0, 5))
        tk.Label(main_f, text=f"担当者: {data_obj['data']['user']} / 支払: {data_obj['data']['ptype'].upper()}", font=("Helvetica", 10), bg="#F5F7FA", fg="#546E7A").pack(anchor="w", pady=(0, 10))

        # --- 2. 閉じるボタン (BOTTOMに固定) ---
        tk.Button(main_f, text="閉じる (Space)", command=self.destroy, bg="#37474F", fg="white", relief="flat").pack(side="bottom", fill="x", pady=5)

        # --- 3. 合計金額表示エリア (BOTTOMに固定、ボタンの上) ---
        f_total_wrapper = tk.Frame(main_f, bg="#F5F7FA", pady=5)
        f_total_wrapper.pack(fill="x", side="bottom")
        
        f_total = tk.Frame(f_total_wrapper, bg="#B0BEC5", padx=15, pady=10) 
        f_total.pack(fill="x")
        
        tk.Label(f_total, text="総計 (税抜)", font=("Helvetica", 12, "bold"), fg="#263238", bg="#B0BEC5").pack(side="left")
        tk.Label(f_total, text=f"¥{total_yen:,}", font=("Helvetica", 18, "bold"), fg="#263238", bg="#B0BEC5").pack(side="right")
        
        tk.Label(f_total_wrapper, text=f"合計点数: {total_items} 点", font=("Helvetica", 10), fg="#546E7A", bg="#F5F7FA").pack(anchor="e", pady=(5, 0))
        
        # --- 4. 注文リストエリア (CENTER - 拡張) ---
        list_area_frame = tk.Frame(main_f, bg="white", highlightthickness=1, highlightbackground="#CFD8DC")
        list_area_frame.pack(fill="both", expand=True, pady=(5, 10))

        list_canvas = tk.Canvas(list_area_frame, bg="white", highlightthickness=0)
        list_canvas.pack(side="left", fill="both", expand=True) 
        
        v_sb = ttk.Scrollbar(list_area_frame, orient="vertical", command=list_canvas.yview)
        v_sb.pack(side="right", fill="y")
        list_canvas.configure(yscrollcommand=v_sb.set)
        
        item_frame = tk.Frame(list_canvas, bg="white")
        
        # ★修正: item_frameをキャンバスに追加し、IDを保存
        self.item_window_id = list_canvas.create_window((0, 0), window=item_frame, anchor="nw")
        
        item_frame.bind("<Configure>", lambda e: list_canvas.configure(scrollregion=list_canvas.bbox("all")))
        
        # ★修正: 保存したIDを使って itemconfig を呼び出す
        list_canvas.bind('<Configure>', lambda e: list_canvas.itemconfig(self.item_window_id, width=e.width))

        # --- 注文リストテーブルヘッダー ---
        f_header = tk.Frame(item_frame, bg="#37474F", height=30)
        f_header.pack(fill="x")
        f_header.pack_propagate(False)
        
        tk.Label(f_header, text="商品名", font=("Helvetica", 10, "bold"), fg="white", bg="#37474F", anchor="w").pack(side="left", padx=10, fill="x", expand=True)
        tk.Label(f_header, text="単価", font=("Helvetica", 10, "bold"), fg="white", bg="#37474F", anchor="e", width=7).pack(side="left")
        tk.Label(f_header, text="数量", font=("Helvetica", 10, "bold"), fg="white", bg="#37474F", anchor="e", width=7).pack(side="left")
        tk.Label(f_header, text="小計", font=("Helvetica", 10, "bold"), fg="white", bg="#37474F", anchor="e", width=10).pack(side="left", padx=10)


        # --- 5. 商品の行 ---
        for i, row_data in enumerate(item_row_data):
            f_row = tk.Frame(item_frame, bg="white", pady=1)
            f_row.pack(fill="x")
            
            name = row_data['name']
            qty = row_data['qty']
            price = row_data['price']
            subtotal = row_data['subtotal']
            
            tk.Label(f_row, text=name, font=("Helvetica", 10), bg="white", anchor="w").pack(side="left", padx=10, fill="x", expand=True)
            tk.Label(f_row, text=f"@{price:,}", font=("Helvetica", 10), bg="white", anchor="e", width=7).pack(side="left")
            tk.Label(f_row, text=str(qty), font=("Helvetica", 10), bg="white", anchor="e", width=7).pack(side="left")
            tk.Label(f_row, text=f"¥{subtotal:,}", font=("Helvetica", 10, "bold"), bg="white", fg="#455A64", anchor="e", width=10).pack(side="left", padx=10)
            
            if i < len(item_row_data) - 1:
                tk.Frame(item_frame, bg="#ECEFF1", height=1).pack(fill="x")



class AdminLoginWindow(tk.Toplevel):
    """管理者認証画面"""
    def __init__(self, parent, data_manager, callback):
        super().__init__(parent)
        self.dm = data_manager
        self.callback = callback
        self.title("管理者認証")
        self.geometry("400x300")
        self.configure(bg=COLORS["bg"])
        self.transient(parent)
        self.grab_set()
        self.focus_force()
        
        tk.Label(self, text="管理者ログイン", font=FONT_M, bg=COLORS["bg"]).pack(pady=20)
        tk.Label(self, text="管理者名 (記録用)", bg=COLORS["bg"]).pack(anchor="w", padx=40)
        self.ent_name = tk.Entry(self, width=30, font=FONT_NORMAL)
        self.ent_name.pack(pady=(0,10))
        tk.Label(self, text="パスワード", bg=COLORS["bg"]).pack(anchor="w", padx=40)
        self.ent_pass = tk.Entry(self, width=30, font=FONT_NORMAL, show="*")
        self.ent_pass.pack(pady=(0,20))
        self.ent_pass.focus_set()
        tk.Button(self, text="認証", bg=COLORS["btn_primary"], fg="white", width=15, font=FONT_S, command=self.check).pack()
        self.bind('<Return>', lambda e: self.check())

    def check(self):
        name = self.ent_name.get().strip()
        pw = self.ent_pass.get().strip()
        real_pass = self.dm.load_settings().get("adminPass", "password")
        if not name:
            messagebox.showwarning("エラー", "名前を入力してください")
            return
        if pw == real_pass:
            self.destroy()
            self.callback(name)
        else:
            messagebox.showerror("エラー", "パスワードが違います")


# gui_parts.py (AdminPanel, SalesOverviewWindow のみを上書き)


class FactoryResetWindow(tk.Toplevel):
    def __init__(self, parent, data_manager, callback, admin_name):
        super().__init__(parent)
        self.dm = data_manager
        self.callback = callback
        self.admin_name = admin_name
        self.title("【危険】システム初期化")
        self.geometry("600x700")
        self.configure(bg=COLORS["danger_zone_bg"])
        self.transient(parent)
        self.grab_set()
        self.focus_force()
        self.setup_ui()

    def setup_ui(self):
        tk.Label(self, text="⚠ DANGER ZONE ⚠\nシステム初期化", font=("Helvetica", 20, "bold"), 
                 bg=COLORS["danger_zone_bg"], fg=COLORS["danger_text"]).pack(pady=20)
        tk.Label(self, text="売上データ・ログを削除し、\n設定を再構築します。（バックアップは残ります）", 
                 font=FONT_NORMAL, bg=COLORS["danger_zone_bg"], fg="#333").pack()

        tk.Label(self, text="1. ターム設定 (1行に1つ)", font=FONT_S, bg=COLORS["danger_zone_bg"]).pack(anchor="w", padx=30, pady=(20, 5))
        self.txt_terms = tk.Text(self, height=4, width=40, font=("Helvetica", 11))
        self.txt_terms.pack(padx=30)
        curr_terms = self.dm.load_settings().get("terms", [])
        self.txt_terms.insert("1.0", "\n".join(curr_terms))

        tk.Label(self, text="2. メニュー設定 (商品名,単価)", font=FONT_S, bg=COLORS["danger_zone_bg"]).pack(anchor="w", padx=30, pady=(20, 5))
        self.txt_menu = tk.Text(self, height=8, width=40, font=("Helvetica", 11))
        self.txt_menu.pack(padx=30)
        curr_menu = self.dm.load_settings().get("menu", [])
        # メニュー設定の復元表示
        menu_str_list = []
        for m in curr_menu:
            menu_str_list.append(f"{m['name']},{m['price']}")
        self.txt_menu.insert("1.0", "\n".join(menu_str_list))

        tk.Label(self, text="3. 管理者パスワード設定 (空欄なら変更なし)", font=FONT_S, bg=COLORS["danger_zone_bg"]).pack(anchor="w", padx=30, pady=(20, 5))
        self.ent_pass = tk.Entry(self, width=30, font=("Helvetica", 11))
        self.ent_pass.pack(padx=30)

        tk.Button(self, text="初期化を実行 (元に戻せません)", font=FONT_S, bg=COLORS["btn_danger"], fg="white", height=2, 
                  command=self.do_reset).pack(pady=30, fill="x", padx=50)

    def do_reset(self):
        if not messagebox.askyesno("最終確認", "本当に初期化しますか？\n現在のデータは全て消えます。"): return
        
        # テキストボックスから設定値を取得
        raw_terms = self.txt_terms.get("1.0", tk.END).strip()
        new_terms = [t.strip() for t in raw_terms.split("\n") if t.strip()]
        
        raw_menu = self.txt_menu.get("1.0", tk.END).strip()
        new_pass = self.ent_pass.get().strip()
        
        # 初期化実行
        self.dm.factory_reset(new_terms, raw_menu, new_pass, self.admin_name)
        messagebox.showinfo("完了", "システムを初期化しました。\nホームに戻ります。")
        self.destroy()
        self.callback()

class RestoreWindow(tk.Toplevel):
    def __init__(self, parent, data_manager, callback):
        super().__init__(parent)
        self.dm = data_manager
        self.callback = callback
        self.title("復元ポイントの選択")
        self.geometry("700x550")
        self.configure(bg=COLORS["bg"])
        self.transient(parent)
        self.grab_set()
        self.focus_force()
        self.setup_ui()

    def setup_ui(self):
        tk.Label(self, text="復元ポイントを選択", font=FONT_M, bg=COLORS["bg"]).pack(pady=15)
        cols = ("Type", "Time", "Name")
        self.tree = ttk.Treeview(self, columns=cols, show="headings", height=15)
        self.tree.heading("Type", text="種類"); self.tree.column("Type", width=80, anchor="center")
        self.tree.heading("Time", text="更新日時"); self.tree.column("Time", width=180, anchor="center")
        self.tree.heading("Name", text="ファイル名"); self.tree.column("Name", width=300)
        self.tree.pack(fill="both", expand=True, padx=20)
        
        style = ttk.Style(); style.configure("Treeview", font=FONT_NORMAL, rowheight=25); style.configure("Treeview.Heading", font=FONT_XS)
        backups = self.dm.get_available_backups()
        
        # ★修正: MouseButton-1 (左クリック) イベントを処理するバインドを追加
        self.tree.bind("<Button-1>", self.on_tree_click) 
        
        for b in backups:
            tag = "current" if b["type"] == "CURRENT" else "backup"
            # pathを tags の2番目の要素として保存
            self.tree.insert("", "end", values=(b["type"], b["time"], b["name"]), tags=(tag, b["path"]))
        self.tree.tag_configure("current", foreground="blue")
        
        btn_f = tk.Frame(self, bg=COLORS["bg"]); btn_f.pack(fill="x", pady=20, padx=20)
        tk.Button(btn_f, text="キャンセル", command=self.destroy, bg="white", font=FONT_S).pack(side="right")
        tk.Button(btn_f, text="復元を実行", command=self.do_restore, bg=COLORS["btn_danger"], fg="white", font=FONT_S).pack(side="right", padx=15)

    def on_tree_click(self, event):
        """ツリービューのクリック時に選択を強制する"""
        item = self.tree.identify_row(event.y)
        if item:
            self.tree.selection_set(item) 
            self.tree.focus(item)

    def do_restore(self):
        sel = self.tree.selection()
        if not sel: 
            messagebox.showwarning("警告", "復元対象を選択してください。")
            return
            
        # ★修正: tagsからパスを取得
        selected_item_id = sel[0]
        tags = self.tree.item(selected_item_id, "tags")
        
        if len(tags) < 2:
            messagebox.showerror("エラー", "復元パスが不正です。")
            return
            
        path = tags[1]
        
        # 復元確認
        if not messagebox.askyesno("最終確認", f"【{self.tree.item(selected_item_id, 'values')[0]}】\n'{self.tree.item(selected_item_id, 'values')[2]}' から\nデータを復元しますか？\n\n現在のデータは上書きされます。"): 
            return
            
        self.callback(path)
        self.destroy()

class NumberPad(tk.Toplevel):
    def __init__(self, parent, title, name, price, ptype, callback):
        super().__init__(parent)
        self.parent = parent
        self.callback = callback
        self.price = price
        self.title(title)
        self.geometry("340x520")
        self.configure(bg="white")  # 全体背景を白に
        
        # モーダル設定
        self.transient(parent)
        self.grab_set()
        
        # UI構築
        self.setup_ui(name, ptype)
        
        # ウィンドウ中央配置
        self.update_idletasks()
        x = parent.winfo_rootx() + (parent.winfo_width() // 2) - 170
        y = parent.winfo_rooty() + (parent.winfo_height() // 2) - 260
        self.geometry(f"+{x}+{y}")

        # イベントバインド
        self.protocol("WM_DELETE_WINDOW", self.close)
        self.bind('<Return>', lambda e: self.enter())
        self.bind('<KP_Enter>', lambda e: self.enter())
        self.bind('<Escape>', lambda e: self.close())
        self.bind('<Key>', self.key_input)
        
        self.focus_force()

    def setup_ui(self, name, ptype):
        # ヘッダー色設定
        h_bg = COLORS["cash_bg"] if ptype=='cash' else COLORS["pay_bg"]
        h_fg = "#1B5E20" if ptype=='cash' else "#B71C1C"
        
        # ヘッダーエリア
        h = tk.Frame(self, bg=h_bg, pady=15, padx=20)
        h.pack(fill="x")
        tk.Label(h, text=f"{ptype.upper()} 入力", font=("Helvetica", 10), bg=h_bg, fg=h_fg).pack(anchor="w")
        tk.Label(h, text=name, font=("Helvetica", 14, "bold"), bg=h_bg, fg="#333", wraplength=300, justify="left").pack(anchor="w", pady=(5,0))
        tk.Label(h, text=f"単価: @{self.price:,}", font=("Helvetica", 11), bg=h_bg, fg="#555").pack(anchor="w")

        # 計算結果表示エリア
        f_disp = tk.Frame(self, bg="white", pady=20, padx=20)
        f_disp.pack(fill="x")
        
        # 金額表示（右寄せで大きく）
        self.lbl_calc = tk.Label(f_disp, text="¥0", font=("Helvetica", 36, "bold"), bg="white", fg="#333")
        self.lbl_calc.pack(anchor="e")
        
        # 入力個数表示（右寄せで控えめに）
        self.var = tk.StringVar(value="0")
        f_count = tk.Frame(f_disp, bg="white")
        f_count.pack(anchor="e")
        tk.Label(f_count, text="個数:", font=("Helvetica", 12), bg="white", fg="#999").pack(side="left")
        tk.Label(f_count, textvariable=self.var, font=("Helvetica", 16, "bold"), bg="white", fg="#555").pack(side="left", padx=(5,0))

        # 区切り線
        tk.Frame(self, bg="#EEE", height=1).pack(fill="x")

        # キーパッドエリア
        bf = tk.Frame(self, bg="white", padx=10, pady=10)
        bf.pack(fill="both", expand=True)
        
        keys = [
            ('7', 0, 0), ('8', 0, 1), ('9', 0, 2),
            ('4', 1, 0), ('5', 1, 1), ('6', 1, 2),
            ('1', 2, 0), ('2', 2, 1), ('3', 2, 2),
            ('0', 3, 0), ('-', 3, 1), ('C', 3, 2) # C: Clear
        ]
        
        for (char, r, c) in keys:
            cmd = lambda k=char: self.clk(k)
            # フラットなボタンデザイン
            btn = tk.Button(bf, text=char, font=("Helvetica", 20), bg="white", fg="#333",
                            relief="flat", activebackground="#F5F5F5", bd=0, command=cmd)
            btn.grid(row=r, column=c, sticky="nsew", padx=5, pady=5)
        
        # グリッドの重み付け（均等配置）
        for i in range(4): bf.rowconfigure(i, weight=1)
        for i in range(3): bf.columnconfigure(i, weight=1)

        # 確定ボタン（下部に大きく）
        f_btm = tk.Frame(self, bg="white", padx=20, pady=20)
        f_btm.pack(fill="x")
        tk.Button(f_btm, text="確定 (Enter)", font=("Helvetica", 14, "bold"), 
                  bg=COLORS["btn_primary"], fg="white", relief="flat", bd=0, height=2,
                  activebackground="#455A64", activeforeground="white",
                  command=self.enter).pack(fill="x")

    def clk(self, k):
        v = self.var.get()
        if k == 'C':
            self.var.set("0")
        elif k == '-':
            if v.startswith('-'): self.var.set(v[1:])
            elif v != "0": self.var.set('-' + v)
            else: self.var.set('-')
        else:
            if v == "0": self.var.set(k)
            else: self.var.set(v + k)
        self.upd()

    def key_input(self, e):
        if e.char in "0123456789-":
            self.clk(e.char)
        elif e.keysym == "BackSpace":
            v = self.var.get()
            if len(v) > 1: self.var.set(v[:-1])
            else: self.var.set("0")
            self.upd()

    def upd(self):
        try:
            val_str = self.var.get()
            if val_str == "" or val_str == "-": count = 0
            else: count = int(val_str)
            self.lbl_calc.config(text=f"¥{count * self.price:,}")
        except:
            self.lbl_calc.config(text="¥0")

    def enter(self):
        try:
            val_str = self.var.get()
            if val_str == "" or val_str == "-": val = 0
            else: val = int(val_str)
            self.callback(val)
        except: pass
        self.close()

    def close(self):
        self.grab_release()
        self.destroy()
        self.parent.focus_set()

class MobileSettingsWindow(tk.Toplevel):
    def __init__(self, parent, data_manager, user_name): # on_save_callback を削除
        super().__init__(parent)
        self.dm = data_manager
        self.user_name = user_name
        # self.on_save_callback = on_save_callback # 削除
        self.title("モバイル設定")
        self.geometry("550x780") 
        self.configure(bg="#F7F9FC") 
        self.transient(parent); self.grab_set(); self.focus_force()
        
        settings = self.dm.load_settings()
        notify_settings = settings.get("notify_alert", {"cash": False, "paypay": True}) 
        
        # --- スクロール設定 ---
        canvas = tk.Canvas(self, bg="#F7F9FC", highlightthickness=0)
        sb = ttk.Scrollbar(self, orient="vertical", command=canvas.yview)
        inner = tk.Frame(canvas, bg="#F7F9FC", padx=30)
        
        inner.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        window_id = canvas.create_window((0,0), window=inner, anchor="nw")
        
        def on_canvas_resize(event):
            canvas.itemconfig(window_id, width=event.width)
        canvas.bind("<Configure>", on_canvas_resize)

        canvas.configure(yscrollcommand=sb.set)
        canvas.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        
        # ★修正: ホイールスクロール機能を追加
        def _on_mousewheel(event):
            if platform.system() == 'Windows':
                canvas.yview_scroll(int(-1*(event.delta/120)), "units")
            elif platform.system() == 'Darwin': 
                canvas.yview_scroll(int(-1*event.delta), "units")
            else:
                if event.num == 4: canvas.yview_scroll(-1, "units")
                elif event.num == 5: canvas.yview_scroll(1, "units")

        canvas.bind_all("<MouseWheel>", _on_mousewheel)
        canvas.bind_all("<Button-4>", _on_mousewheel)
        canvas.bind_all("<Button-5>", _on_mousewheel)
        
        # --- UI構築 ---
        header = tk.Frame(inner, bg="#F7F9FC", pady=20)
        header.pack(fill="x")
        tk.Label(header, text="Mobile Configuration", font=("Helvetica", 18, "bold"), bg="#F7F9FC", fg="#37474F").pack(anchor="w")
        tk.Label(header, text="モバイルオーダー端末の表示・接続・通知設定", font=("Helvetica", 10), bg="#F7F9FC", fg="#78909C").pack(anchor="w")

        content = tk.Frame(inner, bg="#F7F9FC")
        content.pack(fill="both", expand=True)

        def create_section(parent_frame, title, desc):
            f = tk.Frame(parent_frame, bg="white", padx=20, pady=20)
            f.pack(fill="x", pady=(0, 20))
            tk.Frame(f, bg="#E0E0E0", height=1).pack(side="bottom", fill="x")
            head = tk.Frame(f, bg="white")
            head.pack(fill="x", pady=(0, 15))
            tk.Label(head, text=title, font=("Helvetica", 11, "bold"), bg="white", fg="#263238").pack(anchor="w")
            tk.Label(head, text=desc, font=("Helvetica", 9), bg="white", fg="#90A4AE").pack(anchor="w")
            return f

        # 1. セキュリティ
        sec_frame = create_section(content, "Authentication", "スタッフが端末でログインする際のパスワード")
        f_inp = tk.Frame(sec_frame, bg="#FAFAFA", padx=10, pady=5, highlightbackground="#ECEFF1", highlightthickness=1)
        f_inp.pack(fill="x")
        tk.Label(f_inp, text="Password", bg="#FAFAFA", fg="#546E7A", font=("Helvetica", 9, "bold")).pack(side="left", padx=10)
        self.var_pass = tk.StringVar(value=settings.get("mobile_password", "1234"))
        tk.Entry(f_inp, textvariable=self.var_pass, font=("Helvetica", 12), width=20, bd=0, bg="#FAFAFA", justify="right").pack(side="right", padx=10)

        # 2. PC通知設定
        notif_frame = create_section(content, "PC Notification Alert", "注文受信時にPCで音と画面点滅を行うか")
        f_sw = tk.Frame(notif_frame, bg="white")
        f_sw.pack(fill="x")
        
        self.var_alert_cash = tk.BooleanVar(value=notify_settings.get("cash", False))
        self.var_alert_paypay = tk.BooleanVar(value=notify_settings.get("paypay", True))
        
        def create_check(parent, text, var, color):
            c = tk.Checkbutton(parent, text=text, variable=var, bg="white", activebackground="white", 
                               font=("Helvetica", 10), selectcolor="white", fg=color)
            c.pack(side="left", padx=(0, 20))

        create_check(f_sw, "現金注文 (Cash Alert)", self.var_alert_cash, "#2E7D32")
        create_check(f_sw, "PayPay注文 (PayPay Alert)", self.var_alert_paypay, "#C62828")

        # 3. メッセージ設定
        msg_frame = create_section(content, "Display Messages", "モバイル端末上部に表示するアナウンス")
        tk.Label(msg_frame, text="Info Message (通常)", font=("Helvetica", 9, "bold"), bg="white", fg="#0288D1").pack(anchor="w", pady=(0,5))
        self.txt_info = tk.Text(msg_frame, height=2, font=("Helvetica", 10), bg="#F1F8E9", bd=0, padx=10, pady=10)
        self.txt_info.pack(fill="x", pady=(0, 15))
        self.txt_info.insert("1.0", settings.get("mobile_info", ""))

        tk.Label(msg_frame, text="Alert Message (警告・停止中)", font=("Helvetica", 9, "bold"), bg="white", fg="#D32F2F").pack(anchor="w", pady=(0,5))
        self.txt_alert = tk.Text(msg_frame, height=2, font=("Helvetica", 10), bg="#FFEBEE", bd=0, padx=10, pady=10)
        self.txt_alert.pack(fill="x")
        self.txt_alert.insert("1.0", settings.get("mobile_alert", ""))

        # ----------------------------------------------------
        # ★修正: 保存ボタンをスクロールコンテンツの最下部に配置
        # ----------------------------------------------------
        # footer の親を inner (スクロール可能なフレーム) に変更
        footer = tk.Frame(inner, bg="#F7F9FC", pady=20) 
        # footer を inner の中に fill="x" で配置
        footer.pack(fill="x") 
        
        # ダミーフレームを置いて、上部ボタンとは分離させる (innerの中)
        tk.Frame(inner, height=10, bg="#F7F9FC").pack(fill="x") 

        # 「設定を保存 (Save)」
        tk.Button(footer, text="設定を保存", bg=COLORS["btn_success"], fg="white", font=("Helvetica", 10, "bold"), 
                  relief="flat", height=2, cursor="hand2", command=self.save).pack(fill="x")

    def save(self):
        # 1. メッセージ・パスワード・通知設定のみを更新（Ngrok設定は ConnectionSetting で処理される想定）
        self.dm.update_mobile_messages(self.txt_info.get("1.0", "end").strip(), self.txt_alert.get("1.0", "end").strip())
        self.dm.update_mobile_password(self.var_pass.get().strip())
        self.dm.update_notification_settings(self.var_alert_cash.get(), self.var_alert_paypay.get(), self.user_name)
        
        self.dm.log_action(self.user_name, "Settings", "UpdateMobileConfig", "Messages/PW/Notify", "Updated")
        
        messagebox.showinfo("完了", "メッセージ・パスワード・通知設定を保存しました。")
        self.destroy()


class ConnectionSetting(tk.Toplevel):
    def __init__(self, parent, data_manager, user_name, on_save_callback=None):
        super().__init__(parent)
        self.dm = data_manager
        self.user_name = user_name # ログ用
        self.on_save_callback = on_save_callback
        self.title("通信設定 (Ngrok)")
        self.geometry("500x350")
        self.configure(bg=COLORS["bg"])
        self.transient(parent); self.grab_set(); self.focus_force()
        
        settings = self.dm.load_settings()
        
        tk.Label(self, text="Ngrok 通信設定", font=FONT_M, bg=COLORS["bg"]).pack(pady=10)
        
        # 1. トグルスイッチ
        f_toggle = tk.Frame(self, bg=COLORS["bg"], pady=10)
        f_toggle.pack(fill="x", padx=40)
        tk.Label(f_toggle, text="外部接続を有効にする (ON/OFF)", bg=COLORS["bg"], fg=COLORS["text_main"], font=FONT_S).pack(side="left")
        self.var_connect = tk.BooleanVar(value=settings.get("ngrok_connect_enabled", True))
        tk.Checkbutton(f_toggle, variable=self.var_connect, bg=COLORS["bg"], activebackground=COLORS["bg"], selectcolor="white", 
                       font=FONT_S, cursor="hand2").pack(side="right")
        
        # 2. Authtoken
        tk.Label(self, text="Authtokenを入力してください", bg=COLORS["bg"]).pack(pady=(10, 0))
        self.var_token = tk.StringVar(value=settings.get("ngrok_token", ""))
        self.ent_token = tk.Entry(self, textvariable=self.var_token, width=50, font=("Helvetica", 11))
        self.ent_token.pack(pady=10, padx=20)
        
        # 3. 再接続ボタン
        tk.Button(self, text="設定を保存し、Ngrok接続を再開", bg=COLORS["btn_success"], fg="white", font=("Helvetica", 11, "bold"), 
                  command=self.save_and_reconnect, height=2).pack(pady=20, padx=40, fill="x")

    def save_and_reconnect(self):
        """Ngrok設定を保存し、接続再開のコールバックを実行する"""
        
        token = self.var_token.get().strip()
        is_enabled = self.var_connect.get()
        
        if is_enabled and not token:
            messagebox.showwarning("エラー", "接続を有効にするにはNgrok Authtokenが必要です。")
            return
            
        # データマネージャに保存
        self.dm.update_ngrok_token(token)
        self.dm.update_ngrok_connect_enabled(is_enabled, self.user_name)
        
        self.dm.log_action(self.user_name, "Settings", "SaveAndReconnect", "Ngrok", "Saved & Restarting")
        
        messagebox.showinfo("保存完了", "Ngrok設定を保存しました。接続を再試行します。")
        self.destroy()
        
        if self.on_save_callback:
            self.on_save_callback()


class LoginPanel(tk.Frame):
    def __init__(self, parent, data_manager, callback):
        super().__init__(parent, bg="#F0F2F5")
        self.dm = data_manager
        self.callback = callback
        self.place(relx=0, rely=0, relwidth=1, relheight=1)
        
        self.shadow = tk.Frame(self, bg="#E0E0E0")
        self.shadow.place(relx=0.5, rely=0.5, anchor="center", width=404, height=454)
        
        self.card = tk.Frame(self, bg="white", padx=40, pady=50)
        self.card.place(relx=0.5, rely=0.5, anchor="center", width=400, height=450)

        tk.Label(self.card, text="レジシステム", font=("Helvetica", 24, "bold"), bg="white", fg="#263238").pack(pady=(20, 5))
        tk.Label(self.card, text="Cash Register System", font=("Helvetica", 10), bg="white", fg="#90A4AE").pack(pady=(0, 30))
        tk.Frame(self.card, bg="#ECEFF1", height=1, width=300).pack(pady=(0, 30))

        self.show_login_ui()

    def show_login_ui(self):
        f_content = tk.Frame(self.card, bg="white")
        f_content.pack(fill="both", expand=True)

        tk.Label(f_content, text="TERMINAL LOGIN", font=("Helvetica", 9, "bold"), bg="white", fg="#90A4AE").pack(pady=(10, 10))
        tk.Label(f_content, text="端末使用者の名前を入力してください", font=("Helvetica", 10), bg="white", fg="#546E7A").pack(pady=(0, 15))
        
        f_entry = tk.Frame(f_content, bg="white", highlightbackground="#B0BEC5", highlightthickness=1)
        f_entry.pack(ipady=5)
        self.ent_name = tk.Entry(f_entry, font=("Helvetica", 14), width=20, bd=0, bg="white", justify="center")
        self.ent_name.pack(padx=10, pady=5)
        self.ent_name.focus_set()
        
        btn = tk.Button(f_content, text="システムを開始 (Start)", bg="#263238", fg="white", font=("Helvetica", 11, "bold"),
                        relief="flat", cursor="hand2", height=2,
                        command=self.do_login, activebackground="#455A64", activeforeground="white")
        btn.pack(fill="x", pady=(20, 10))
        
        self.ent_name.bind('<Return>', lambda e: self.do_login())

    def do_login(self):
        name = self.ent_name.get().strip()
        if not name:
            messagebox.showwarning("入力エラー", "名前を入力してください")
            return
        self.dm.set_terminal_user(name)
        self.destroy()
        self.callback(name)

    

# gui_parts.py (変更クラスのみ)

class AdminPanel(tk.Frame):
    def __init__(self, parent, app_instance, admin_name, terminal_user):
        super().__init__(parent, bg="#F5F7FA")
        self.app = app_instance
        self.dm = app_instance.data_manager
        self.admin_name = admin_name
        self.terminal_user = terminal_user
        self.pack(fill="both", expand=True)
        
        h = tk.Frame(self, bg="white", pady=20, padx=30)
        h.pack(fill="x", side="top")
        tk.Frame(h, bg="#E0E0E0", height=1).place(relx=0, rely=1, relwidth=1, anchor="sw")
        
        tk.Label(h, text="System Administration", font=("Helvetica", 20, "bold"), fg="#263238", bg="white").pack(side="left")
        user_info_text = f"|  Admin: {admin_name}  (Terminal: {terminal_user})"
        tk.Label(h, text=user_info_text, font=("Helvetica", 12, "bold"), fg="#546E7A", bg="white").pack(side="left", padx=15)
        
        tk.Button(h, text="閉じる (Close)", command=self.master.destroy, bg="#546E7A", fg="white", 
                  font=("Helvetica", 10, "bold"), relief="flat", padx=15, pady=5, cursor="hand2").pack(side="right")
        
        canvas = tk.Canvas(self, bg="#F5F7FA", highlightthickness=0)
        sb = ttk.Scrollbar(self, orient="vertical", command=canvas.yview)
        self.inner = tk.Frame(canvas, bg="#F5F7FA", padx=40, pady=30)
        
        self.inner.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        self.window_id = canvas.create_window((0,0), window=self.inner, anchor="nw")
        
        def on_canvas_resize(event):
            canvas.itemconfig(self.window_id, width=event.width)
        canvas.bind("<Configure>", on_canvas_resize)
        
        canvas.configure(yscrollcommand=sb.set)
        canvas.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        
        def _on_mousewheel(event):
            if platform.system() == 'Windows':
                canvas.yview_scroll(int(-1*(event.delta/120)), "units")
            elif platform.system() == 'Darwin': 
                canvas.yview_scroll(int(-1*event.delta), "units")
            else:
                if event.num == 4: canvas.yview_scroll(-1, "units")
                elif event.num == 5: canvas.yview_scroll(1, "units")

        canvas.bind_all("<MouseWheel>", _on_mousewheel)
        canvas.bind_all("<Button-4>", _on_mousewheel)
        canvas.bind_all("<Button-5>", _on_mousewheel)

        self.setup_data_operations()
        self.setup_danger_zone()

    def create_card(self, title, icon="■"):
        frame = tk.Frame(self.inner, bg="white", padx=25, pady=20)
        frame.pack(fill="x", pady=(0, 25))
        tk.Frame(frame, bg="#E0E0E0", height=1).pack(side="bottom", fill="x")
        
        h = tk.Frame(frame, bg="white")
        h.pack(fill="x", pady=(0, 15))
        tk.Label(h, text=icon, font=("Helvetica", 12), fg="#546E7A", bg="white").pack(side="left", padx=(0, 10))
        tk.Label(h, text=title, font=("Helvetica", 14, "bold"), fg="#37474F", bg="white").pack(side="left")
        return frame

    def setup_data_operations(self):
        card = self.create_card("Data Management (データ運用)", "💾")
        btn_grid = tk.Frame(card, bg="white")
        btn_grid.pack(fill="x")
        
        def mk_btn(parent, txt, cmd, r, c, col="#0288D1"):
            b = tk.Button(parent, text=txt, bg=col, fg="white", font=("Helvetica", 10, "bold"),
                          relief="flat", width=20, height=2, cursor="hand2", command=cmd)
            b.grid(row=r, column=c, padx=10, pady=10, sticky="ew")

        if self.app.active_sales_mode:
             menu_cmd = lambda: MenuManager(self.app.root, self.dm, self.admin_name, self.app.load_items_and_data)
        else:
             menu_cmd = lambda: MenuManager(self.app.root, self.dm, self.admin_name)

        mk_btn(btn_grid, "手動バックアップ", self.do_manual_backup, 0, 0, "#78909C")
        mk_btn(btn_grid, "全データ出力 (CSV)", self.export_data, 0, 1, "#43A047")
        mk_btn(btn_grid, "メニュー管理", menu_cmd, 0, 2, "#EC407A")
        
        mk_btn(btn_grid, "ログから復元", self.open_restore, 1, 0, "#AB47BC")
        mk_btn(btn_grid, "整合性チェック", self.check_integrity, 1, 1, "#FB8C00")
        mk_btn(btn_grid, "古いログ削除", self.clean_backups, 1, 2, "#90A4AE")
        
        for i in range(3): btn_grid.columnconfigure(i, weight=1)

    def setup_danger_zone(self):
        card = self.create_card("Danger Zone (初期化・削除)", "⚠")
        
        f_row1 = tk.Frame(card, bg="white", pady=5)
        f_row1.pack(fill="x")
        tk.Label(f_row1, text="特定日の売上データ削除:", font=("Helvetica", 10, "bold"), fg="#D32F2F", bg="white").pack(side="left")
        
        settings = self.dm.load_settings()
        all_terms = settings.get("terms", []) + ["調整", "テスト"]
        for t in all_terms:
            tk.Button(f_row1, text=f"{t}", bg="#FFEBEE", fg="#C62828", font=("Helvetica", 9), relief="flat",
                      command=lambda x=t: self.reset_term(x)).pack(side="left", padx=5)

        tk.Frame(card, bg="#EEEEEE", height=1).pack(fill="x", pady=15)

        f_row2 = tk.Frame(card, bg="white")
        f_row2.pack(fill="x")
        tk.Label(f_row2, text="システム完全リセット:", font=("Helvetica", 10, "bold"), fg="#D32F2F", bg="white").pack(side="left")
        tk.Button(f_row2, text="全データ・ログ削除して初期化", bg="#D32F2F", fg="white", font=("Helvetica", 10, "bold"),
                  relief="flat", padx=15, pady=5, command=lambda: FactoryResetWindow(self.app.root, self.dm, lambda: [self.master.destroy(), self.app.show_dashboard()], self.admin_name)).pack(side="right")

    def do_manual_backup(self):
        self.dm.perform_backup()
        self.dm.log_action(self.admin_name, "Admin", "ManualBackup", "System", "Executed")
        messagebox.showinfo("OK", "バックアップを完了しました")

    def export_data(self):
        s, p = self.dm.export_all_data()
        if s: 
            self.dm.log_action(self.admin_name, "Admin", "ExportData", "CSV", "Executed")
            messagebox.showinfo("成功", f"出力しました:\n{p}")
        else: messagebox.showerror("エラー", p)
    
    def open_restore(self):
        # ★修正: 復元成功時にメインアプリをリフレッシュするコールバックを作成
        def on_restore_complete(path):
            success, msg = self.dm.restore_from_log(path, self.admin_name)
            messagebox.showinfo("結果", msg)
            if success:
                # メインアプリの再描画と集計更新
                if self.app:
                    self.app.load_items_and_data()
                    self.app.update_total_header()

        RestoreWindow(self.app.root, self.dm, on_restore_complete)
    
    def check_integrity(self):
        o, m = self.dm.verify_integrity()
        self.dm.log_action(self.admin_name, "Admin", "CheckIntegrity", "System", f"Result:{o}")
        if o: messagebox.showinfo("OK", m)
        else: messagebox.showerror("Error", m)
    
    def clean_backups(self):
        c = self.dm.clean_old_backups()
        self.dm.log_action(self.admin_name, "Admin", "CleanBackups", "System", f"Deleted {c} files")
        messagebox.showinfo("完了", f"{c}件のファイルを削除しました")
    
    def reset_term(self, term):
        if messagebox.askyesno("警告", f"「{term}」の売上データを削除しますか？\nこの操作は取り消せません。"):
            self.dm.reset_csv_data(f"{term}.csv")
            self.dm.log_action(self.admin_name, "Admin", "ResetData", term, "Executed")
            messagebox.showinfo("完了", "削除しました")
            # 削除後もリフレッシュが必要な場合があるため念のため
            if self.app:
                self.app.load_items_and_data()
                self.app.update_total_header()


# ★追加: 担当者入力用の新しいダイアログクラス
# gui_parts.py の OperatorLoginDialog クラスをこれに書き換えてください

class OperatorLoginDialog(tk.Toplevel):
    def __init__(self, parent, title, prompt):
        super().__init__(parent)
        self.result = None
        self.title(title)
        self.geometry("400x220")
        self.configure(bg="white")
        self.transient(parent)
        self.grab_set()
        
        # 中央配置
        w, h = 400, 220
        sw = parent.winfo_screenwidth()
        sh = parent.winfo_screenheight()
        x = (sw - w) // 2
        y = (sh - h) // 2
        self.geometry(f"+{x}+{y}")
        
        self.setup_ui(prompt)
        self.wait_window()

    def setup_ui(self, prompt):
        f = tk.Frame(self, bg="white", padx=30, pady=30)
        f.pack(fill="both", expand=True)
        
        tk.Label(f, text=prompt, font=("Helvetica", 11), bg="white", fg="#546E7A").pack(anchor="w", pady=(0,10))
        
        self.ent = tk.Entry(f, font=("Helvetica", 14), bg="#F5F5F5", bd=0, justify="center")
        self.ent.pack(fill="x", ipady=8, pady=5)
        self.ent.focus_set()
        self.ent.bind('<Return>', lambda e: self.ok())
        
        tk.Frame(f, bg="white", height=20).pack()
        
        tk.Button(f, text="OK", command=self.ok, bg="#263238", fg="white", font=("Helvetica", 11, "bold"),
                  relief="flat", height=2, cursor="hand2").pack(fill="x")

    def ok(self):
        val = self.ent.get().strip()
        if val:
            self.result = val
            self.destroy()
        else:
            from tkinter import messagebox
            messagebox.showwarning("入力エラー", "名前を入力してください")
            self.ent.focus_set()

# ★変更: 新規アイテム追加用のダイアログ
class ItemAddDialog(tk.Toplevel):
    def __init__(self, parent):
        super().__init__(parent)
        self.title("新規商品追加")
        self.geometry("400x300")
        self.transient(parent)
        self.grab_set()
        
        # センタリング
        w, h = 400, 300
        sw = parent.winfo_screenwidth(); sh = parent.winfo_screenheight()
        x = (sw - w) // 2; y = (sh - h) // 2
        self.geometry(f"+{x}+{y}")
        
        self.result = None
        
        f = tk.Frame(self, padx=30, pady=30)
        f.pack(fill="both", expand=True)
        
        tk.Label(f, text="商品名:", anchor="w").pack(fill="x")
        self.ent_name = tk.Entry(f, font=("Helvetica", 12)); self.ent_name.pack(fill="x", pady=(0, 15))
        
        tk.Label(f, text="単価 (円):", anchor="w").pack(fill="x")
        self.ent_price = tk.Entry(f, font=("Helvetica", 12)); self.ent_price.pack(fill="x", pady=(0, 20))
        
        tk.Button(f, text="追加", command=self.ok, bg=COLORS["btn_info"], fg="white", font=("Helvetica", 11, "bold"), height=2).pack(fill="x")
        
        self.ent_name.focus_set()
        self.bind('<Return>', lambda e: self.ok())
        
        self.wait_window()

    def ok(self):
        name = self.ent_name.get().strip()
        price_str = self.ent_price.get().strip()
        
        if not name:
            messagebox.showwarning("エラー", "商品名を入力してください")
            return
        if not price_str.isdigit():
            messagebox.showwarning("エラー", "単価は数値を入力してください")
            return
            
        self.result = (name, int(price_str))
        self.destroy()

class MenuManager(tk.Toplevel):
    def __init__(self, parent, data_manager, user_name, on_save_callback=None): 
        super().__init__(parent)
        self.dm = data_manager
        self.user_name = user_name 
        self.on_save_callback = on_save_callback 
        self.title("メニュー管理 (表示設定・Order設定)")
        self.geometry("750x800")
        self.configure(bg="#F5F7FA")
        self.transient(parent)
        self.grab_set()
        self.focus_force()
        
        self.menu_data = self.dm.load_settings().get("menu", [])
        for i, item in enumerate(self.menu_data):
            if "order" not in item: item["order"] = (i + 1) * 10

        self.setup_ui()

    def setup_ui(self):
        top_f = tk.Frame(self, bg="#F5F7FA", pady=20, padx=30)
        top_f.pack(fill="x")
        tk.Label(top_f, text="Menu Settings", font=("Helvetica", 18, "bold"), bg="#F5F7FA", fg="#37474F").pack(anchor="w")
        tk.Label(top_f, text="管理画面では「登録順」で表示されます。\nレジ画面での並び順を変える場合は「Order」の数値を変更してください。", font=("Helvetica", 10), bg="#F5F7FA", fg="#78909C").pack(anchor="w")

        container = tk.Frame(self, bg="#F5F7FA")
        container.pack(fill="both", expand=True, padx=30, pady=(0, 20))
        
        canvas = tk.Canvas(container, bg="#F5F7FA", highlightthickness=0)
        sb = ttk.Scrollbar(container, orient="vertical", command=canvas.yview)
        self.scroll_f = tk.Frame(canvas, bg="#F5F7FA")
        
        self.scroll_f.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas_win = canvas.create_window((0, 0), window=self.scroll_f, anchor="nw")
        
        def on_canvas_resize(event):
            canvas.itemconfig(canvas_win, width=event.width)
        canvas.bind("<Configure>", on_canvas_resize)
        
        canvas.configure(yscrollcommand=sb.set)
        canvas.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")

        self.refresh_list()

        btn_f = tk.Frame(self, bg="white", pady=15, padx=30) 
        btn_f.pack(fill="x", side="bottom")
        
        tk.Button(btn_f, text="+ 新規商品追加", bg=COLORS["btn_info"], fg="white", font=FONT_S, height=2, relief="flat",
                  command=self.add_item_dialog).pack(side="left")

        tk.Button(btn_f, text="設定を保存", bg=COLORS["btn_success"], fg="white", font=FONT_S, width=25, height=2, relief="flat",
                  command=self.save).pack(side="right")

    def refresh_list(self):
        for w in self.scroll_f.winfo_children(): w.destroy()
        self.item_vars = []

        for i, item in enumerate(self.menu_data):
            card = tk.Frame(self.scroll_f, bg="white", padx=15, pady=12)
            card.pack(fill="x", pady=5)
            tk.Frame(card, bg="#E0E0E0", height=1).pack(side="bottom", fill="x")

            f_ord = tk.Frame(card, bg="white", width=60)
            f_ord.pack(side="left", padx=(0, 15))
            tk.Label(f_ord, text="Order", font=("Arial", 8), fg="#BBB", bg="white").pack(anchor="w")
            v_order = tk.IntVar(value=item.get("order", (i+1)*10))
            tk.Entry(f_ord, textvariable=v_order, width=4, font=("Helvetica", 12), justify="center", bg="#F5F5F5", bd=0).pack(pady=2)

            f_info = tk.Frame(card, bg="white")
            f_info.pack(side="left", fill="x", expand=True)
            tk.Label(f_info, text=item["name"], font=("Helvetica", 12, "bold"), bg="white", fg="#37474F", anchor="w").pack(fill="x")
            tk.Label(f_info, text=f"@{item['price']:,} 円", font=("Helvetica", 10), bg="white", fg="#90A4AE", anchor="w").pack(fill="x")

            f_sw = tk.Frame(card, bg="white")
            f_sw.pack(side="right")
            
            v_vis = tk.BooleanVar(value=item.get("visible", True))
            v_mob = tk.BooleanVar(value=item.get("mobile_visible", False))
            
            def create_sw(parent, text, var, color):
                f = tk.Frame(parent, bg="white", padx=8)
                f.pack(side="left")
                l = tk.Label(f, text=text, font=("Helvetica", 8, "bold"), bg="white", fg="#999")
                l.pack()
                tk.Checkbutton(f, variable=var, bg="white", activebackground="white", selectcolor="white").pack()

            create_sw(f_sw, "PC表示", v_vis, "#4CAF50")
            create_sw(f_sw, "Mobile", v_mob, "#2196F3")
            
            self.item_vars.append({
                "order": v_order,
                "vis": v_vis, 
                "mob": v_mob
            })

    def add_item_dialog(self):
        # ★変更: カスタムダイアログを使用
        dlg = ItemAddDialog(self)
        if dlg.result:
            name, price = dlg.result
            
            max_order = 0
            self.sync_from_ui() 
            for item in self.menu_data:
                o = item.get("order", 0)
                if o > max_order: max_order = o
            new_order = max_order + 10
            
            self.menu_data.append({
                "name": name, 
                "price": price, 
                "visible": True, 
                "mobile_visible": False,
                "order": new_order
            })
            self.refresh_list()
            self.scroll_f.update_idletasks()
            self.scroll_f.master.yview_moveto(1.0)

    def sync_from_ui(self):
        for i, v in enumerate(self.item_vars):
            try:
                self.menu_data[i]["order"] = int(v["order"].get())
            except: pass 
            self.menu_data[i]["visible"] = v["vis"].get()
            self.menu_data[i]["mobile_visible"] = v["mob"].get()

    def save(self):
        self.sync_from_ui()
        self.dm.update_menu(self.menu_data)
        self.dm.log_action(self.user_name, "Admin", "UpdateMenu", "Settings", "Updated")
        messagebox.showinfo("保存", "設定を保存しました。\nOrder値に基づく並び替えはレジ画面に反映されます。")
        self.destroy()
        if self.on_save_callback:
            self.on_save_callback()

# gui_parts.py

# ★変更: show_opt_btn引数を追加し、担当者変更ボタンの表示を制御
class CollapsibleControlPanel(tk.Frame):
    def __init__(self, parent, app_instance, show_opt_btn=True):
        super().__init__(parent, bg=COLORS["sidebar_bg"])
        self.app = app_instance
        self.is_expanded = False
        self.width_expanded = 220
        self.width_collapsed = 60
        self.configure(width=self.width_collapsed)
        self.pack_propagate(False)

        self.header_f = tk.Frame(self, bg=COLORS["sidebar_bg"], height=60)
        self.header_f.pack(fill="x", side="top")
        self.header_f.pack_propagate(False)
        self.btn_menu = tk.Button(self.header_f, text="≡", font=("Helvetica", 20), bg=COLORS["sidebar_bg"], fg="white",
                                  bd=0, relief="flat", activebackground=COLORS["sidebar_btn_hover"],
                                  command=self.toggle)
        self.btn_menu.place(relx=0.5, rely=0.5, anchor="center")

        self.content_f = tk.Frame(self, bg=COLORS["sidebar_bg"])
        
        self.lbl_term_user = tk.Label(self.content_f, text="Term: User", font=FONT_S, bg=COLORS["sidebar_bg"], fg=COLORS["sidebar_fg"], anchor="w")
        self.lbl_term_user.pack(fill="x", padx=20, pady=(20, 5))

        self.lbl_operator = tk.Label(self.content_f, text="Op: Unassigned", font=("Helvetica", 10), bg=COLORS["sidebar_bg"], fg="#B0BEC5", anchor="w")
        self.lbl_operator.pack(fill="x", padx=20, pady=(0, 20))
        
        def mk_btn(txt, cmd):
            b = tk.Button(self.content_f, text=txt, font=FONT_NORMAL, bg=COLORS["sidebar_bg"], fg="white", anchor="w", padx=20,
                          bd=0, relief="flat", activebackground=COLORS["sidebar_btn_hover"], command=cmd)
            b.pack(fill="x", pady=2, ipady=8)

        # レジモード中のみ表示
        if show_opt_btn:
            tk.Label(self.content_f, text="OPERATION", font=("Helvetica", 8, "bold"), fg="#90A4AE", bg=COLORS["sidebar_bg"], anchor="w").pack(fill="x", padx=15, pady=(10,2))
            mk_btn("👤 担当者変更", self.app.change_operator) 

        tk.Label(self.content_f, text="DATA", font=("Helvetica", 8, "bold"), fg="#90A4AE", bg=COLORS["sidebar_bg"], anchor="w").pack(fill="x", padx=15, pady=(10,2))
        mk_btn("📊 売上状況", self.app.open_sales_overview)
        mk_btn("📝 ログ閲覧", self.app.open_log_viewer)
        mk_btn("📅 表示ターム設定", self.open_term_settings) 
        
        tk.Label(self.content_f, text="MOBILE", font=("Helvetica", 8, "bold"), fg="#90A4AE", bg=COLORS["sidebar_bg"], anchor="w").pack(fill="x", padx=15, pady=(20,2))
        mk_btn("📱 接続QR表示", self.app.show_qr_code)
        mk_btn("⚙️ モバイル設定", self.app.open_mobile_settings)
        mk_btn("📡 通信設定", self.app.open_connection_settings) 
        
        tk.Label(self.content_f, text="SYSTEM", font=("Helvetica", 8, "bold"), fg="#90A4AE", bg=COLORS["sidebar_bg"], anchor="w").pack(fill="x", padx=15, pady=(20,2))
        mk_btn("🔧 管理者設定", self.app.show_admin_login)

    def open_term_settings(self):
        if self.app.active_sales_mode:
            messagebox.showwarning("警告", "レジモード中は表示タームの変更はできません。")
            return
        TermSettingsWindow(self.app.root, self.app.data_manager, self.app.show_dashboard)

    def toggle(self):
        if self.is_expanded:
            self.content_f.pack_forget()
            self.configure(width=self.width_collapsed)
            self.btn_menu.configure(bg=COLORS["sidebar_bg"])
        else:
            self.configure(width=self.width_expanded)
            self.content_f.pack(fill="both", expand=True, side="top")
            self.btn_menu.configure(bg=COLORS["sidebar_btn_hover"])
        self.is_expanded = not self.is_expanded

    def update_status(self, term_user, is_online):
        self.lbl_term_user.config(text=term_user)
        
    def set_operator_name(self, op_name):
        self.lbl_operator.config(text=f"Op: {op_name}")


# gui_parts.py の SalesCard クラス（念のための確認用）

# gui_parts.py

# ★変更: 汎用化された注文確認ウィンドウ


# gui_parts.py

class ItemAddDialog(tk.Toplevel):
    def __init__(self, parent):
        super().__init__(parent)
        self.title("新規商品追加")
        self.geometry("400x300")
        self.transient(parent)
        self.grab_set()
        
        # センタリング
        w, h = 400, 300
        sw = parent.winfo_screenwidth(); sh = parent.winfo_screenheight()
        x = (sw - w) // 2; y = (sh - h) // 2
        self.geometry(f"+{x}+{y}")
        
        self.result = None
        
        f = tk.Frame(self, padx=30, pady=30)
        f.pack(fill="both", expand=True)
        
        tk.Label(f, text="商品名:", anchor="w").pack(fill="x")
        self.ent_name = tk.Entry(f, font=("Helvetica", 12)); self.ent_name.pack(fill="x", pady=(0, 15))
        
        tk.Label(f, text="単価 (円):", anchor="w").pack(fill="x")
        self.ent_price = tk.Entry(f, font=("Helvetica", 12)); self.ent_price.pack(fill="x", pady=(0, 20))
        
        tk.Button(f, text="追加", command=self.ok, bg=COLORS["btn_info"], fg="white", font=("Helvetica", 11, "bold"), height=2).pack(fill="x")
        
        self.ent_name.focus_set()
        self.bind('<Return>', lambda e: self.ok())
        
        self.wait_window()

    def ok(self):
        name = self.ent_name.get().strip()
        price_str = self.ent_price.get().strip()
        
        if not name:
            messagebox.showwarning("エラー", "商品名を入力してください")
            return
        if not price_str.isdigit():
            messagebox.showwarning("エラー", "単価は数値を入力してください")
            return
            
        self.result = (name, int(price_str))
        self.destroy()


# gui_parts.py

# ★変更: メニュー管理画面にホイールスクロールを追加
class MenuManager(tk.Toplevel):
    def __init__(self, parent, data_manager, user_name, on_save_callback=None): 
        super().__init__(parent)
        self.dm = data_manager
        self.user_name = user_name 
        self.on_save_callback = on_save_callback 
        self.title("メニュー管理 (表示設定・Order設定)")
        self.geometry("750x800")
        self.configure(bg="#F5F7FA")
        self.transient(parent)
        self.grab_set()
        self.focus_force()
        
        self.menu_data = self.dm.load_settings().get("menu", [])
        for i, item in enumerate(self.menu_data):
            if "order" not in item: item["order"] = (i + 1) * 10

        self.setup_ui()

    def setup_ui(self):
        top_f = tk.Frame(self, bg="#F5F7FA", pady=20, padx=30)
        top_f.pack(fill="x")
        tk.Label(top_f, text="Menu Settings", font=("Helvetica", 18, "bold"), bg="#F5F7FA", fg="#37474F").pack(anchor="w")
        tk.Label(top_f, text="管理画面では「登録順」で表示されます。\nレジ画面での並び順を変える場合は「Order」の数値を変更してください。", font=("Helvetica", 10), bg="#F5F7FA", fg="#78909C").pack(anchor="w")

        container = tk.Frame(self, bg="#F5F7FA")
        container.pack(fill="both", expand=True, padx=30, pady=(0, 20))
        
        canvas = tk.Canvas(container, bg="#F5F7FA", highlightthickness=0)
        sb = ttk.Scrollbar(container, orient="vertical", command=canvas.yview)
        self.scroll_f = tk.Frame(canvas, bg="#F5F7FA")
        
        self.scroll_f.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas_win = canvas.create_window((0, 0), window=self.scroll_f, anchor="nw")
        
        def on_canvas_resize(event):
            canvas.itemconfig(canvas_win, width=event.width)
        canvas.bind("<Configure>", on_canvas_resize)
        
        # ★追加: ホイールスクロール
        def _on_mousewheel(event):
            if platform.system() == 'Windows':
                canvas.yview_scroll(int(-1*(event.delta/120)), "units")
            elif platform.system() == 'Darwin': 
                canvas.yview_scroll(int(-1*event.delta), "units")
            else:
                if event.num == 4: canvas.yview_scroll(-1, "units")
                elif event.num == 5: canvas.yview_scroll(1, "units")

        canvas.bind_all("<MouseWheel>", _on_mousewheel)
        canvas.bind_all("<Button-4>", _on_mousewheel)
        canvas.bind_all("<Button-5>", _on_mousewheel)
        
        canvas.configure(yscrollcommand=sb.set)
        canvas.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")

        self.refresh_list()

        btn_f = tk.Frame(self, bg="white", pady=15, padx=30) 
        btn_f.pack(fill="x", side="bottom")
        
        tk.Button(btn_f, text="+ 新規商品追加", bg=COLORS["btn_info"], fg="white", font=FONT_S, height=2, relief="flat",
                  command=self.add_item_dialog).pack(side="left")

        tk.Button(btn_f, text="設定を保存", bg=COLORS["btn_success"], fg="white", font=FONT_S, width=25, height=2, relief="flat",
                  command=self.save).pack(side="right")

    def refresh_list(self):
        for w in self.scroll_f.winfo_children(): w.destroy()
        self.item_vars = []

        for i, item in enumerate(self.menu_data):
            card = tk.Frame(self.scroll_f, bg="white", padx=15, pady=12)
            card.pack(fill="x", pady=5)
            tk.Frame(card, bg="#E0E0E0", height=1).pack(side="bottom", fill="x")

            f_ord = tk.Frame(card, bg="white", width=60)
            f_ord.pack(side="left", padx=(0, 15))
            tk.Label(f_ord, text="Order", font=("Arial", 8), fg="#BBB", bg="white").pack(anchor="w")
            v_order = tk.IntVar(value=item.get("order", (i+1)*10))
            tk.Entry(f_ord, textvariable=v_order, width=4, font=("Helvetica", 12), justify="center", bg="#F5F5F5", bd=0).pack(pady=2)

            f_info = tk.Frame(card, bg="white")
            f_info.pack(side="left", fill="x", expand=True)
            tk.Label(f_info, text=item["name"], font=("Helvetica", 12, "bold"), bg="white", fg="#37474F", anchor="w").pack(fill="x")
            tk.Label(f_info, text=f"@{item['price']:,} 円", font=("Helvetica", 10), bg="white", fg="#90A4AE", anchor="w").pack(fill="x")

            f_sw = tk.Frame(card, bg="white")
            f_sw.pack(side="right")
            
            v_vis = tk.BooleanVar(value=item.get("visible", True))
            v_mob = tk.BooleanVar(value=item.get("mobile_visible", False))
            
            def create_sw(parent, text, var, color):
                f = tk.Frame(parent, bg="white", padx=8)
                f.pack(side="left")
                l = tk.Label(f, text=text, font=("Helvetica", 8, "bold"), bg="white", fg="#999")
                l.pack()
                tk.Checkbutton(f, variable=var, bg="white", activebackground="white", selectcolor="white").pack()

            create_sw(f_sw, "PC表示", v_vis, "#4CAF50")
            create_sw(f_sw, "Mobile", v_mob, "#2196F3")
            
            self.item_vars.append({
                "order": v_order,
                "vis": v_vis, 
                "mob": v_mob
            })

    def add_item_dialog(self):
        dlg = ItemAddDialog(self)
        if dlg.result:
            name, price = dlg.result
            max_order = 0
            self.sync_from_ui() 
            for item in self.menu_data:
                o = item.get("order", 0)
                if o > max_order: max_order = o
            new_order = max_order + 10
            
            self.menu_data.append({
                "name": name, 
                "price": price, 
                "visible": True, 
                "mobile_visible": False,
                "order": new_order
            })
            self.refresh_list()
            self.scroll_f.update_idletasks()
            self.scroll_f.master.yview_moveto(1.0)

    def sync_from_ui(self):
        for i, v in enumerate(self.item_vars):
            try:
                self.menu_data[i]["order"] = int(v["order"].get())
            except: pass 
            self.menu_data[i]["visible"] = v["vis"].get()
            self.menu_data[i]["mobile_visible"] = v["mob"].get()

    def save(self):
        self.sync_from_ui()
        self.dm.update_menu(self.menu_data)
        self.dm.log_action(self.user_name, "Admin", "UpdateMenu", "Settings", "Updated")
        messagebox.showinfo("保存", "設定を保存しました。\nOrder値に基づく並び替えはレジ画面に反映されます。")
        self.destroy()
        if self.on_save_callback:
            self.on_save_callback()

class NotificationPanel(tk.Frame):
    def __init__(self, parent, data_manager):
        super().__init__(parent, bg=COLORS["notify_bg"], height=170) 
        self.dm = data_manager 
        self.pack_propagate(False)
        
        h = tk.Frame(self, bg="#263238", pady=4)
        h.pack(fill="x")
        # ★変更: 操作説明を更新 (Space:承認)
        tk.Label(h, text="▲ モバイル注文 (←/→:選択, Space:承認, Del:取消)", font=("Helvetica", 9, "bold"), fg="#ECEFF1", bg="#263238").pack(side="left", padx=10)
        
        self.canvas = tk.Canvas(self, bg=COLORS["notify_bg"], highlightthickness=0)
        self.sb = ttk.Scrollbar(self, orient="horizontal", command=self.canvas.xview)
        self.inner = tk.Frame(self.canvas, bg=COLORS["notify_bg"])
        
        self.inner.bind("<Configure>", lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.window_id = self.canvas.create_window((0,0), window=self.inner, anchor="nw")
        
        self.canvas.configure(xscrollcommand=self.sb.set)
        self.sb.pack(side="bottom", fill="x")
        self.canvas.pack(side="left", fill="both", expand=True)
        
        self.notifications = []
        self.selected_index = -1

    def add_notification(self, data, on_approve=None, on_cancel=None):
        card_container = tk.Frame(self.inner, bd=0, relief="flat", bg=COLORS["notify_bg"])
        border = tk.Frame(card_container, bg=COLORS["notify_border_base"], padx=1, pady=1)
        border.pack(fill="both", expand=True, padx=3, pady=3)
        
        content_bg = "#FFFFFF"
        content = tk.Frame(border, bg=content_bg, padx=4, pady=4, width=160, height=125) 
        content.pack_propagate(False)
        content.pack(fill="both", expand=True)
        
        btn_f = tk.Frame(content, bg=content_bg, pady=0)
        btn_f.pack(side="top", fill="x", pady=(0, 2))
        
        def approve_cmd():
            if on_approve and on_approve():
                idx = self.get_notification_index_by_id(data['id'])
                if idx != -1: self.remove_notification(idx)
        
        def cancel_cmd():
            if on_cancel and on_cancel():
                idx = self.get_notification_index_by_id(data['id'])
                if idx != -1: self.remove_notification(idx)

        # ★変更: ボタンテキストを更新 (Spc)
        b_ok = tk.Button(btn_f, text="承認(Spc)", bg="#E8F5E9", fg="#2E7D32", font=("Helvetica", 8, "bold"), 
                         relief="flat", bd=0, command=approve_cmd, cursor="hand2", takefocus=0)
        b_ok.pack(side="left", fill="x", expand=True, padx=1)
        
        b_ng = tk.Button(btn_f, text="取消", bg="#FFEBEE", fg="#C62828", font=("Helvetica", 8, "bold"), 
                         relief="flat", bd=0, command=cancel_cmd, cursor="hand2", takefocus=0)
        b_ng.pack(side="left", fill="x", expand=True, padx=1)
        
        h_frame = tk.Frame(content, bg=content_bg)
        h_frame.pack(fill="x")
        tk.Label(h_frame, text=f"{data['timestamp']}", font=("Arial", 8), fg="#90A4AE", bg=content_bg).pack(side="right")
        tk.Label(h_frame, text=data['user'], font=("Helvetica", 9, "bold"), fg="#37474F", bg=content_bg).pack(side="left")
        
        type_color = "#43A047" if data['ptype'] == 'cash' else "#E53935"
        tk.Label(content, text=f"【{data['ptype'].upper()}】注文", font=("Arial", 8, "bold"), fg=type_color, bg=content_bg, anchor="w").pack(fill="x", pady=(0,0))
        
        items_f = tk.Frame(content, bg=content_bg)
        items_f.pack(fill="both", expand=True, pady=0)
        
        item_strings = [f"{item['name']}×{item['amount']}" for item in data['items']]
        full_text = ", ".join(item_strings)
        
        CHAR_LIMIT = 26
        if len(full_text) > CHAR_LIMIT:
            display_text = full_text[:CHAR_LIMIT] + "..."
        else:
            display_text = full_text
            
        tk.Label(items_f, text=display_text, font=("Helvetica", 9), bg=content_bg, fg="#333", 
                 anchor="nw", justify="left", wraplength=150).pack(fill="both", expand=True)

        card_container.pack(side="left", anchor="n", fill="y")
        
        notif_obj = {
            'data': data,
            'widget': card_container,
            'border': border,
            'content': content,
            'approve_func': approve_cmd,
            'cancel_func': cancel_cmd
        }
        self.notifications.append(notif_obj)
        
        self.inner.update_idletasks()

        if self.selected_index != -1 and self.selected_index < len(self.notifications) - 1:
            pass 
        else:
            new_idx = len(self.notifications) - 1
            self.select_index(new_idx)
            self.canvas.xview_moveto(1.0)
            
        self.trigger_alert(notif_obj, data['ptype'])

    def trigger_alert(self, notif_obj, ptype):
        try:
            settings = self.dm.get_notification_settings()
        except:
            settings = {"cash": False, "paypay": False}
        
        if settings.get(ptype, False):
            self.master.bell()
            original_col = "#2196F3" if self.selected_index != -1 and notif_obj == self.notifications[self.selected_index] else COLORS["notify_border_base"]
            alert_col = "#FFC107"
            def flash(count):
                if count == 0:
                    self._set_border_style(notif_obj, original_col, 1)
                    return
                new_col = alert_col if count % 2 == 0 else original_col
                padding = 3 if new_col == alert_col else 1
                self._set_border_style(notif_obj, new_col, padding)
                self.update_idletasks() 
                self.after(150, lambda: flash(count - 1))
            flash(8)

    def _style_card(self, notif_obj, selected):
        if selected:
            bd_col = "#2196F3"; pad = 3
        else:
            bd_col = COLORS["notify_border_base"]; pad = 1
        self._set_border_style(notif_obj, bd_col, pad)

    def _set_border_style(self, notif_obj, color, padding):
        notif_obj['border'].config(bg=color, padx=padding, pady=padding)

    def select_index(self, index):
        if not self.notifications: return
        if 0 <= self.selected_index < len(self.notifications):
            self._style_card(self.notifications[self.selected_index], False)
        if index < 0: index = 0
        if index >= len(self.notifications): index = len(self.notifications) - 1
        self.selected_index = index
        self._style_card(self.notifications[index], True)
        if len(self.notifications) > 1:
            pos = index / (len(self.notifications) - 1)
            self.canvas.xview_moveto(pos)

    def select_next(self): self.select_index(self.selected_index + 1)
    def select_prev(self): self.select_index(self.selected_index - 1)
    def get_selected_data(self):
        if 0 <= self.selected_index < len(self.notifications): return self.notifications[self.selected_index]['data']
        return None

    def trigger_selected_action(self, action_type):
        if 0 <= self.selected_index < len(self.notifications):
            target = self.notifications[self.selected_index]
            if action_type == 'approve':
                if target['approve_func'](): self.remove_selected()
            elif action_type == 'cancel':
                target['cancel_func']()

    def remove_selected(self): self.remove_notification(self.selected_index)
    def remove_notification(self, index):
        if 0 <= index < len(self.notifications):
            target = self.notifications.pop(index)
            target['widget'].destroy()
            if self.selected_index >= len(self.notifications): self.selected_index = len(self.notifications) - 1
            if self.selected_index >= 0: self.select_index(self.selected_index)
            else: self.selected_index = -1
            self.inner.update_idletasks()
            self.canvas.configure(scrollregion=self.canvas.bbox("all"))
    def get_notification_index_by_id(self, notif_id):
        for i, n in enumerate(self.notifications):
            if n['data']['id'] == notif_id: return i
        return -1

# ★変更: 色付けと敬称制御を追加した注文確認ウィンドウ

# gui_parts.py (変更クラスのみ)

# gui_parts.py (変更クラスのみ)

class OrderSummaryWindow(tk.Toplevel):
    def __init__(self, parent, items, total_qty, total_yen, on_confirm_callback, mode="PC", user_name=None):
        super().__init__(parent)
        self.on_confirm = on_confirm_callback
        self.items = items
        self.total_qty = total_qty
        self.total_yen = total_yen
        self.mode = mode
        self.user_name = user_name

        if self.mode == "MOBILE":
            self.theme_color = "#E3F2FD" 
            self.title_text = "モバイル注文承認"
            self.header_main = f"{user_name} からの注文"
            self.header_sub = "Mobile Order Confirmation"
        else:
            self.theme_color = "#F1F8E9"
            self.title_text = "注文確認"
            self.header_main = "注文内容を確認して確定してください"
            self.header_sub = "Order Confirmation"

        self.title(self.title_text)
        
        w, h = 600, 600
        sw = parent.winfo_screenwidth(); sh = parent.winfo_screenheight()
        x = (sw - w) // 2; y = (sh - h) // 2
        self.geometry(f"{w}x{h}+{x}+{y}")
        
        self.configure(bg="white")
        self.transient(parent)
        self.grab_set()
        self.focus_force()
        
        self.bind('<Return>', lambda e: self.do_confirm())
        self.bind('<Escape>', lambda e: self.destroy())

        self.setup_ui()

    def setup_ui(self):
        h_frame = tk.Frame(self, bg=self.theme_color, padx=20, pady=20)
        h_frame.pack(fill="x")
        
        tk.Label(h_frame, text=self.header_sub, font=("Helvetica", 10, "bold"), bg=self.theme_color, fg="#90A4AE").pack(anchor="w")
        tk.Label(h_frame, text=self.header_main, font=("Helvetica", 16, "bold"), bg=self.theme_color, fg="#333").pack(anchor="w")

        lh = tk.Frame(self, bg="#ECEFF1", height=35, padx=10)
        lh.pack(fill="x", padx=20)
        lh.pack_propagate(False)
        tk.Label(lh, text="商品名", font=("Helvetica", 10, "bold"), bg="#ECEFF1", fg="#546E7A", width=25, anchor="w").pack(side="left")
        tk.Label(lh, text="支払", font=("Helvetica", 10, "bold"), bg="#ECEFF1", fg="#546E7A", width=8, anchor="center").pack(side="left")
        tk.Label(lh, text="数量", font=("Helvetica", 10, "bold"), bg="#ECEFF1", fg="#546E7A", width=6, anchor="center").pack(side="left")
        tk.Label(lh, text="小計", font=("Helvetica", 10, "bold"), bg="#ECEFF1", fg="#546E7A", width=10, anchor="e").pack(side="right")

        f_list = tk.Frame(self, bg="white", padx=20)
        f_list.pack(fill="both", expand=True)
        
        canvas = tk.Canvas(f_list, bg="white", highlightthickness=0)
        sb = ttk.Scrollbar(f_list, orient="vertical", command=canvas.yview)
        inner = tk.Frame(canvas, bg="white")
        
        inner.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas_win = canvas.create_window((0,0), window=inner, anchor="nw", width=540)
        canvas.bind('<Configure>', lambda e: canvas.itemconfig(canvas_win, width=e.width))

        canvas.configure(yscrollcommand=sb.set)
        canvas.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        
        for i, item in enumerate(self.items):
            bg_col = "#FAFAFA" if i % 2 == 1 else "white"
            self.create_row(inner, item, bg_col)
                
        tk.Frame(self, bg="#CFD8DC", height=1).pack(fill="x", pady=0)
        
        f_total = tk.Frame(self, bg="#F5F7FA", padx=30, pady=20)
        f_total.pack(fill="x")
        
        r1 = tk.Frame(f_total, bg="#F5F7FA"); r1.pack(fill="x")
        tk.Label(r1, text="Total Qty:", font=("Helvetica", 11), bg="#F5F7FA", fg="#78909C").pack(side="left")
        tk.Label(r1, text=f"{self.total_qty} 点", font=("Helvetica", 14, "bold"), bg="#F5F7FA", fg="#37474F").pack(side="right")
        
        r2 = tk.Frame(f_total, bg="#F5F7FA"); r2.pack(fill="x", pady=(5,0))
        tk.Label(r2, text="Total Amount:", font=("Helvetica", 11), bg="#F5F7FA", fg="#78909C").pack(side="left")
        tk.Label(r2, text=f"¥{self.total_yen:,}", font=("Helvetica", 22, "bold"), bg="#F5F7FA", fg="#37474F").pack(side="right")
        
        f_btn = tk.Frame(self, bg="white", padx=30, pady=20)
        f_btn.pack(fill="x")
        tk.Button(f_btn, text="キャンセル (Esc)", font=("Helvetica", 11), bg="#ECEFF1", fg="#546E7A", 
                  relief="flat", height=2, width=15, command=self.destroy).pack(side="left")
        
        btn_text = "確定する (Enter)"
        btn_bg = COLORS["btn_success"]
        if self.mode == "MOBILE":
            btn_bg = COLORS["btn_info"]
            
        tk.Button(f_btn, text=btn_text, font=("Helvetica", 11, "bold"), bg=btn_bg, fg="white", 
                  relief="flat", height=2, width=20, command=self.do_confirm).pack(side="right")

    def create_row(self, parent, item, bg_color):
        f = tk.Frame(parent, bg=bg_color, pady=8, padx=10)
        f.pack(fill="x")
        
        name = item['name']
        ptype = item['ptype']
        qty = item['qty']
        sub = item['subtotal']
        
        q_str = f"{qty:+d}" if qty > 0 else f"{qty}"
        
        if ptype == "現金" or ptype == "cash":
            ptype_disp = "現金"
            type_bg = "#E8F5E9"; type_fg = "#1B5E20"
        else:
            ptype_disp = "PayPay"
            type_bg = "#FFEBEE"; type_fg = "#B71C1C"

        tk.Label(f, text=name, font=("Helvetica", 11), bg=bg_color, fg="#333", width=25, anchor="w", wraplength=200, justify="left").pack(side="left")
        
        lbl_type = tk.Label(f, text=ptype_disp, font=("Helvetica", 9, "bold"), bg=type_bg, fg=type_fg, width=8)
        lbl_type.pack(side="left")
        
        tk.Label(f, text=q_str, font=("Helvetica", 12, "bold"), bg=bg_color, fg="#333", width=6, anchor="center").pack(side="left")
        tk.Label(f, text=f"¥{sub:,}", font=("Helvetica", 11), bg=bg_color, fg="#546E7A", width=10, anchor="e").pack(side="right")

    # ★変更: コールバックが成功(True)を返した場合のみウィンドウを閉じる
    def do_confirm(self):
        if self.on_confirm():
            self.destroy()

# gui_parts.py (変更クラスのみ)
# gui_parts.py (変更クラスのみ)

class LogViewer(tk.Toplevel):
    def __init__(self, parent, data_manager):
        super().__init__(parent)
        self.dm = data_manager
        self.title("ログ閲覧")
        self.geometry("1250x750")
        self.configure(bg=COLORS["bg"])
        
        # ヘッダーエリア
        f_header = tk.Frame(self, bg=COLORS["bg"], pady=15, padx=15)
        f_header.pack(fill="x")
        
        # 検索フォーム
        f_search = tk.Frame(f_header, bg=COLORS["bg"])
        f_search.pack(side="left")
        tk.Label(f_search, text="キーワード検索:", bg=COLORS["bg"], font=("Helvetica", 10)).pack(side="left")
        self.ent = tk.Entry(f_search, width=25, font=("Helvetica", 11))
        self.ent.pack(side="left", padx=5)
        tk.Button(f_search, text="検索", command=self.load, bg="#90A4AE", fg="white", relief="flat", padx=10).pack(side="left")

        # モード切替ボタンエリア
        f_mode = tk.Frame(f_header, bg=COLORS["bg"], padx=30)
        f_mode.pack(side="left")
        
        self.view_mode = tk.StringVar(value="summary") # デフォルト: 簡易
        
        def set_mode(m):
            self.view_mode.set(m)
            self.update_mode_buttons()
            self.load()

        # タブ風ボタン
        self.btn_summary = tk.Button(f_mode, text="簡易ログ (重要)", command=lambda: set_mode("summary"), 
                                     font=("Helvetica", 10, "bold"), relief="flat", width=15, cursor="hand2")
        self.btn_summary.pack(side="left", padx=1)
        
        self.btn_full = tk.Button(f_mode, text="全ログ (詳細)", command=lambda: set_mode("full"), 
                                  font=("Helvetica", 10, "bold"), relief="flat", width=15, cursor="hand2")
        self.btn_full.pack(side="left", padx=1)
        
        self.update_mode_buttons()

        # メインエリア
        paned = tk.PanedWindow(self, orient="vertical", sashwidth=6, bg=COLORS["bg"], sashrelief="ridge")
        paned.pack(fill="both", expand=True, padx=15, pady=(0, 15))
        
        # 上部: リスト
        f_tree = tk.Frame(paned)
        paned.add(f_tree, height=450)
        
        cols = ("Time", "User", "Terminal", "Loc", "Act", "Target", "Value")
        self.tree = ttk.Treeview(f_tree, columns=cols, show="headings")
        
        col_configs = [
            ("Time", 160), ("User", 120), ("Terminal", 100), 
            ("Loc", 80), ("Act", 120), ("Target", 160), ("Value", 400)
        ]
        for c, w in col_configs:
            self.tree.heading(c, text=c)
            self.tree.column(c, width=w)
            
        vsb = ttk.Scrollbar(f_tree, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")
        
        self.tree.bind("<<TreeviewSelect>>", self.on_select)
        
        # 下部: 詳細
        f_detail = tk.Frame(paned, bg="white", bd=1, relief="solid")
        paned.add(f_detail)
        
        h_detail = tk.Frame(f_detail, bg="#ECEFF1", pady=5, padx=10)
        h_detail.pack(fill="x")
        tk.Label(h_detail, text="詳細内容 (Full Message)", font=("Helvetica", 10, "bold"), bg="#ECEFF1", fg="#455A64").pack(anchor="w")
        
        self.txt_detail = tk.Text(f_detail, font=("Consolas", 11), wrap="word", padx=15, pady=15, bg="white", bd=0)
        self.txt_detail.pack(fill="both", expand=True)
        
        self.load()

    def update_mode_buttons(self):
        m = self.view_mode.get()
        active_bg = "#546E7A"
        active_fg = "white"
        inactive_bg = "#CFD8DC"
        inactive_fg = "#546E7A"
        
        if m == "summary":
            self.btn_summary.config(bg=active_bg, fg=active_fg)
            self.btn_full.config(bg=inactive_bg, fg=inactive_fg)
        else:
            self.btn_summary.config(bg=inactive_bg, fg=inactive_fg)
            self.btn_full.config(bg=active_bg, fg=active_fg)

    def load(self):
        q = self.ent.get()
        mode = self.view_mode.get()
        
        for i in self.tree.get_children(): self.tree.delete(i)
        self.log_map = {} 

        # 簡易モードで除外するもの: 個別の加減算と、受信通知
        exclude_actions = ["Add", "Sub", "加算", "減算", "ReceiveOrder"]

        for r in self.dm.get_logs(limit=None, search_query=q): 
            if len(r) < 7: continue
            action = r[4]
            
            if mode == "summary":
                if action in exclude_actions:
                    continue
            
            display_vals = list(r)
            raw_val = display_vals[6]
            # 一覧では改行をスペースに置換
            if "\n" in raw_val:
                display_vals[6] = raw_val.replace("\n", "  ")[:60] + " ..."
            
            item_id = self.tree.insert("", "end", values=display_vals)
            self.log_map[item_id] = raw_val 

    def on_select(self, event):
        sel = self.tree.selection()
        if not sel: return
        item_id = sel[0]
        full_text = self.log_map.get(item_id, "")
        self.txt_detail.delete("1.0", "end")
        self.txt_detail.insert("1.0", full_text)


# gui_parts.py (変更クラスのみ)

# gui_parts.py (SalesCardクラスのみ変更)


class CollapsibleControlPanel(tk.Frame):
    def __init__(self, parent, app_instance, show_opt_btn=True):
        super().__init__(parent, bg=COLORS["sidebar_bg"])
        self.app = app_instance
        self.is_expanded = False
        self.width_expanded = 220
        self.width_collapsed = 60
        self.configure(width=self.width_collapsed)
        self.pack_propagate(False)

        self.header_f = tk.Frame(self, bg=COLORS["sidebar_bg"], height=60)
        self.header_f.pack(fill="x", side="top")
        self.header_f.pack_propagate(False)
        self.btn_menu = tk.Button(self.header_f, text="≡", font=("Helvetica", 20), bg=COLORS["sidebar_bg"], fg="white",
                                  bd=0, relief="flat", activebackground=COLORS["sidebar_btn_hover"],
                                  command=self.toggle)
        self.btn_menu.place(relx=0.5, rely=0.5, anchor="center")

        self.content_f = tk.Frame(self, bg=COLORS["sidebar_bg"])
        
        self.lbl_term_user = tk.Label(self.content_f, text="Term: User", font=FONT_S, bg=COLORS["sidebar_bg"], fg=COLORS["sidebar_fg"], anchor="w")
        self.lbl_term_user.pack(fill="x", padx=20, pady=(20, 5))

        self.lbl_operator = tk.Label(self.content_f, text="Op: Unassigned", font=("Helvetica", 10), bg=COLORS["sidebar_bg"], fg="#B0BEC5", anchor="w")
        self.lbl_operator.pack(fill="x", padx=20, pady=(0, 20))
        
        def mk_btn(txt, cmd):
            b = tk.Button(self.content_f, text=txt, font=FONT_NORMAL, bg=COLORS["sidebar_bg"], fg="white", anchor="w", padx=20,
                          bd=0, relief="flat", activebackground=COLORS["sidebar_btn_hover"], command=cmd)
            b.pack(fill="x", pady=2, ipady=8)

        if show_opt_btn:
            tk.Label(self.content_f, text="OPERATION", font=("Helvetica", 8, "bold"), fg="#90A4AE", bg=COLORS["sidebar_bg"], anchor="w").pack(fill="x", padx=15, pady=(10,2))
            mk_btn("👤 担当者変更", self.app.change_operator) 
            # ★追加: カード設定ボタン
            mk_btn("🛠 カード表示設定", self.open_card_settings)

        tk.Label(self.content_f, text="DATA", font=("Helvetica", 8, "bold"), fg="#90A4AE", bg=COLORS["sidebar_bg"], anchor="w").pack(fill="x", padx=15, pady=(10,2))
        mk_btn("📊 売上状況", self.app.open_sales_overview)
        mk_btn("📝 ログ閲覧", self.app.open_log_viewer)
        mk_btn("📅 表示ターム設定", self.open_term_settings) 
        
        tk.Label(self.content_f, text="MOBILE", font=("Helvetica", 8, "bold"), fg="#90A4AE", bg=COLORS["sidebar_bg"], anchor="w").pack(fill="x", padx=15, pady=(20,2))
        mk_btn("📱 接続QR表示", self.app.show_qr_code)
        mk_btn("⚙️ モバイル設定", self.app.open_mobile_settings)
        mk_btn("📡 通信設定", self.app.open_connection_settings) 
        
        tk.Label(self.content_f, text="SYSTEM", font=("Helvetica", 8, "bold"), fg="#90A4AE", bg=COLORS["sidebar_bg"], anchor="w").pack(fill="x", padx=15, pady=(20,2))
        mk_btn("🔧 管理者設定", self.app.show_admin_login)
        
        self.lbl_err = tk.Label(self.content_f, text="", fg="#FF5252", bg=COLORS["sidebar_bg"], font=("Arial", 9), wraplength=180, justify="left")
        self.lbl_err.pack(side="bottom", fill="x", padx=15, pady=20)

    def open_term_settings(self):
        if self.app.active_sales_mode:
            messagebox.showwarning("警告", "レジモード中は表示タームの変更はできません。")
            return
        TermSettingsWindow(self.app.root, self.app.data_manager, self.app.show_dashboard)

    # ★追加: カード設定を開く
    def open_card_settings(self):
        # 設定保存後にカードレイアウトを更新するコールバックを渡す
        CardSettingsWindow(self.app.root, self.app.data_manager, self.app.update_card_layout)

    def toggle(self):
        if self.is_expanded:
            self.content_f.pack_forget()
            self.configure(width=self.width_collapsed)
            self.btn_menu.configure(bg=COLORS["sidebar_bg"])
        else:
            self.configure(width=self.width_expanded)
            self.content_f.pack(fill="both", expand=True, side="top")
            self.btn_menu.configure(bg=COLORS["sidebar_btn_hover"])
        self.is_expanded = not self.is_expanded

    def update_status(self, term_user, is_online):
        self.lbl_term_user.config(text=term_user)
        
    def set_operator_name(self, op_name):
        self.lbl_operator.config(text=f"Op: {op_name}")

    def set_ngrok_error(self, msg):
        self.lbl_err.config(text=f"⚠ {msg}")

    def clear_ngrok_error(self):
        self.lbl_err.config(text="")

# gui_parts.py (SalesCard クラス全文)

# gui_parts.py (SalesCard クラス全文)

class SalesCard(tk.Frame):
    def __init__(self, parent, name, price, item_index, key_hint, key_list, 
                 open_numpad_callback, auto_save_callback, log_func, current_mode, allow_negative, height=520, width=130):
        super().__init__(parent, bg=COLORS["card_bg"], bd=0, width=width, height=height)
        self.pack_propagate(False)
        self.grid_propagate(False)
        
        self.card_width = width 
        self.name = name
        self.price = int(price)
        self.keys = key_list
        self.item_index = item_index
        self.current_mode = current_mode
        self.allow_negative = allow_negative
        
        self.open_numpad_callback = open_numpad_callback
        self.auto_save_callback = auto_save_callback
        self.log_func = log_func
        
        self.counts = {'term': {'cash': 0, 'paypay': 0}, 'cumulative': {'cash': 0, 'paypay': 0}, 'total': {'cash': 0, 'paypay': 0}}
        self.draft_counts = {'cash': 0, 'paypay': 0}
        
        self.mobile_active = False
        self.labels = {}
        self.setup_ui()

    def setup_ui(self):
        if self.item_index < 9: key_char = str(self.item_index + 1)
        elif self.item_index == 9: key_char = "0"
        else: key_char = "-"

        self.btn_mobile = tk.Button(self, text=f"Mob: OFF [{key_char}]", font=("Helvetica", 9, "bold"), 
                                    bg=COLORS["mob_off_bg"], fg=COLORS["mob_off_fg"], 
                                    relief="flat", bd=0, command=self.toggle_mobile, takefocus=0)
        self.btn_mobile.pack(side="top", fill="x", ipady=3)

        h = tk.Frame(self, bg=COLORS["card_bg"], pady=5, height=55)
        h.pack(side="top", fill="x")
        h.pack_propagate(False)
        
        # 名前ラベル
        self.lbl_name = tk.Label(h, text=self.name, font=("Helvetica", 11, "bold"), bg=COLORS["card_bg"], fg=COLORS["text_main"], 
                 justify="center")
        self.lbl_name.place(relx=0.5, rely=0.4, anchor="center")
        self._update_name_label() 
        
        tk.Label(h, text=f"@{self.price:,}", font=FONT_XS, bg=COLORS["card_bg"], fg=COLORS["text_sub"]).place(relx=0.5, rely=0.85, anchor="center")
        
        sf = tk.Frame(self, bg=COLORS["card_bg"], pady=5); sf.pack(side="top", fill="x", padx=4)
        for i, t in enumerate(["Term", "総合"]): 
            tk.Label(sf, text=t, font=("Helvetica", 8, "bold"), bg=COLORS["card_bg"], fg="#999").grid(row=0, column=i+1)
        for i, k in enumerate(['term', 'total']):
            self.labels[k] = tk.Label(sf, text="¥0", font=("Helvetica", 10), bg=COLORS["card_bg"], fg="#333") 
            self.labels[k].grid(row=1, column=i+1, padx=2)
        sf.columnconfigure(1, weight=1); sf.columnconfigure(2, weight=1)
        
        cc = tk.Frame(self, bg=COLORS["bg"]); cc.pack(side="top", fill="both", expand=True, pady=(5,0))
        self.create_col(cc, 'cash', COLORS["cash_bg"], COLORS["cash_fg"], COLORS["cash_btn"], "現", 0)
        self.create_col(cc, 'paypay', COLORS["pay_bg"], COLORS["pay_fg"], COLORS["pay_btn"], "Pay", 1)
        
        self.monitor_frame = tk.Frame(self, bg=COLORS["card_bg"], height=40)
        self.monitor_frame.pack(side="bottom", fill="x")
        self.monitor_label = tk.Label(self.monitor_frame, text="", font=("Helvetica", 9), bg=COLORS["card_bg"], fg="#999", anchor="w", wraplength=self.card_width-5)
        self.monitor_label.pack(fill="both", padx=5, pady=2)

    def resize(self, width, height):
        self.config(width=width, height=height)
        self.card_width = width
        self._update_name_label()
        self.monitor_label.config(wraplength=width-5)

    def _update_name_label(self):
        try:
            from data_manager import DataManager
            settings = DataManager().load_settings()
            limit = int(settings.get("card_settings", {}).get("overflow", 6))
            
            display_name = self.name
            if len(display_name) > limit:
                display_name = display_name[:limit] + "…"
            self.lbl_name.config(text=display_name)
        except:
            pass

    def create_col(self, parent, ptype, bg, fg, btn_bg, title, col_idx):
        f = tk.Frame(parent, bg=bg); f.pack(side="left", fill="both", expand=True, padx=(0 if col_idx==0 else 1, 0))
        h = tk.Frame(f, bg=bg, pady=5); h.pack(side="top", fill="x")
        tk.Label(h, text=title, font=("Helvetica", 9, "bold"), bg=bg, fg=fg).pack()
        
        count_area = tk.Frame(h, bg=bg)
        count_area.pack()

        self.labels[f'{ptype}_count'] = tk.Label(count_area, text="0", font=("Helvetica", 16, "bold"), bg=bg, fg=fg)
        self.labels[f'{ptype}_count'].pack(side="top")
        
        d_frame = tk.Frame(count_area, bg=bg, pady=2, padx=5)
        d_frame.pack(side="top", pady=(2, 0))
        
        self.labels[f'{ptype}_draft_bg'] = d_frame
        self.labels[f'{ptype}_draft'] = tk.Label(d_frame, text="", font=("Arial", 9, "bold"), bg=bg)
        self.labels[f'{ptype}_draft'].pack()
        
        bf = tk.Frame(f, bg=bg, padx=2, pady=2); bf.pack(side="top", fill="both", expand=True)
        
        if len(self.keys) == 6:
            ca, ci, cs, pa, pi, ps = self.keys
            if ptype == 'cash': k_add, k_inp, k_sub = ca, ci, cs
            else: k_add, k_inp, k_sub = pa, pi, ps
        else: k_add, k_inp, k_sub = "", "", ""

        tk.Button(bf, text=f"＋\n{k_add}", font=("Helvetica", 12, "bold"), bg=btn_bg, bd=0, relief="flat", takefocus=0, command=lambda: self.update_draft_count(ptype, 1)).pack(side="top", fill="both", expand=True, pady=1)
        tk.Button(bf, text=f"⌨\n{k_inp}", font=("Helvetica", 10, "bold"), bg="white", bd=0, relief="flat", takefocus=0, command=lambda: self.open_numpad_callback(self, ptype)).pack(side="top", fill="both", expand=True, pady=1)
        tk.Button(bf, text=f"－\n{k_sub}", font=("Helvetica", 12, "bold"), bg=btn_bg, bd=0, relief="flat", takefocus=0, command=lambda: self.update_draft_count(ptype, -1)).pack(side="top", fill="both", expand=True, pady=1)

    def update_draft_count(self, ptype, amount):
        current_draft = self.draft_counts[ptype]
        new_draft = current_draft + amount
        current_term = self.counts['term'][ptype]
        if not self.allow_negative and (current_term + new_draft) < 0: return 
        self.draft_counts[ptype] = new_draft
        self.refresh_display()

    # ★変更: 指定した支払い方法へドラフトを統合・移動する
    def move_drafts_to(self, target_ptype):
        total = self.draft_counts['cash'] + self.draft_counts['paypay']
        if total == 0: return

        if target_ptype == 'cash':
            self.draft_counts['cash'] = total
            self.draft_counts['paypay'] = 0
        else:
            self.draft_counts['cash'] = 0
            self.draft_counts['paypay'] = total
        
        self.refresh_display()

    def clear_drafts(self):
        if self.draft_counts['cash'] == 0 and self.draft_counts['paypay'] == 0: return
        self.draft_counts['cash'] = 0
        self.draft_counts['paypay'] = 0
        self.refresh_display()

    def has_drafts(self):
        return self.draft_counts['cash'] != 0 or self.draft_counts['paypay'] != 0

    def commit_draft(self, operator_name):
        changes = False
        for ptype in ['cash', 'paypay']:
            draft = self.draft_counts[ptype]
            if draft != 0:
                old_val = self.counts['term'][ptype]
                new_val = old_val + draft
                action = "Add" if draft > 0 else "Sub"
                val_str = f"{draft:+d} (Term: {new_val}) by {operator_name}"
                target_str = f"{self.name} [{ptype}]"
                self.log_func(self.current_mode, action, target_str, val_str)
                
                self.counts['term'][ptype] = new_val
                self.counts['cumulative'][ptype] += draft
                self.counts['total'][ptype] += draft
                
                self.draft_counts[ptype] = 0
                changes = True
        if changes: self.refresh_display()
            
    def update_term_count(self, ptype, amount, user_name=None):
        old_val = self.counts['term'][ptype]
        new_val = old_val + amount
        if not self.allow_negative and new_val < 0: return
        
        real_diff = new_val - old_val
        if real_diff == 0: return

        action = "Add" if real_diff > 0 else "Sub"
        val_str = f"{real_diff:+d} (Term: {new_val})"
        target_str = f"{self.name} [{ptype}]"
        if user_name: val_str += f" by {user_name}"

        self.log_func(self.current_mode, action, target_str, val_str)
        
        self.counts['term'][ptype] = new_val
        self.counts['cumulative'][ptype] += real_diff
        self.counts['total'][ptype] += real_diff
        self.refresh_display()
        if self.auto_save_callback: self.auto_save_callback()

    def refresh_display(self):
        if 'cash_count' in self.labels: self.labels['cash_count'].config(text=str(self.counts['term']['cash']))
        if 'paypay_count' in self.labels: self.labels['paypay_count'].config(text=str(self.counts['term']['paypay']))
        
        for ptype in ['cash', 'paypay']:
            d_val = self.draft_counts[ptype]
            lbl = self.labels.get(f'{ptype}_draft')
            frame = self.labels.get(f'{ptype}_draft_bg')
            
            if lbl and frame:
                base_bg = lbl.master.master.cget("bg")
                if d_val == 0:
                    lbl.config(text="", bg=base_bg)
                    frame.config(bg=base_bg)
                else:
                    bg_col = "#1976D2" if d_val > 0 else "#D32F2F"
                    fg_col = "white"
                    sign = "+" if d_val > 0 else ""
                    frame.config(bg=bg_col)
                    lbl.config(text=f"{sign}{d_val}", fg=fg_col, bg=bg_col)
        
        fmt = lambda d: f"¥{(d['cash'] + d['paypay']) * self.price:,}"
        if 'term' in self.labels: self.labels['term'].config(text=fmt(self.counts['term']))
        if 'total' in self.labels: self.labels['total'].config(text=fmt(self.counts['total']))

    def get_draft_counts(self):
        return self.draft_counts.copy()

    def load_initial_data(self, t, c, tot):
        self.counts['term'], self.counts['cumulative'], self.counts['total'] = t, c, tot
        self.draft_counts = {'cash': 0, 'paypay': 0} 
        self.refresh_display()
        
    def toggle_mobile(self):
        self.mobile_active = not self.mobile_active
        if self.item_index < 9: key_char = str(self.item_index + 1)
        elif self.item_index == 9: key_char = "0"
        else: key_char = "-"

        if self.mobile_active:
            self.btn_mobile.config(text=f"📡 Mob: ON [{key_char}]", bg=COLORS["mob_on_bg"], fg=COLORS["mob_on_fg"])
            self.log_func(self.current_mode, "ToggleMobile", self.name, "ON")
        else:
            self.btn_mobile.config(text=f"Mob: OFF [{key_char}]", bg=COLORS["mob_off_bg"], fg=COLORS["mob_off_fg"])
            self.log_func(self.current_mode, "ToggleMobile", self.name, "OFF")
    
    def update_monitor(self, watchers):
        watchers_text = ", ".join(watchers)
        txt = "🛒 " + watchers_text if watchers else ""
        if watchers:
            bg_col = COLORS["monitor_active_bg"]; fg_col = COLORS["monitor_text"]
        else:
            bg_col = COLORS["card_bg"]; fg_col = "#999"
        if self.monitor_label.cget("text") != txt:
            self.monitor_label.config(text=txt, bg=bg_col, fg=fg_col)
            self.monitor_frame.config(bg=bg_col)
    
    def get_totals(self):
        calc = lambda d: (d['cash'] + d['paypay']) * self.price
        return calc(self.counts['term']), calc(self.counts['cumulative']), calc(self.counts['total'])

class SalesOverviewWindow(tk.Toplevel):
    def __init__(self, parent, data_manager):
        super().__init__(parent)
        self.dm = data_manager
        self.title("売上状況")
        self.geometry("1100x750")
        self.configure(bg=COLORS["bg"])
        self.setup_ui()

    def setup_ui(self):
        h = tk.Frame(self, bg=COLORS["header_bg"], pady=15, padx=30)
        h.pack(side="top", fill="x")
        tk.Label(h, text="Sales Overview", font=("Helvetica", 18, "bold"), fg="white", bg=COLORS["header_bg"]).pack(side="left")
        tk.Button(h, text="閉じる", bg="#546E7A", fg="white", font=("Helvetica", 10), relief="flat", padx=15, command=self.destroy).pack(side="right")

        stats_f = tk.Frame(self, bg=COLORS["bg"])
        stats_f.pack(fill="x", padx=40, pady=25)
        
        data_list, terms = self.dm.get_detailed_sales_data()
        total_sales = sum(i["total_sales"] for i in data_list)
        total_qty = sum(i["total_qty"] for i in data_list)
        
        def create_modern_stat(parent, title, value, accent_color):
            f = tk.Frame(parent, bg="white", padx=0, pady=0)
            f.pack(side="left", padx=15, fill="y")
            bar = tk.Frame(f, bg=accent_color, width=6)
            bar.pack(side="left", fill="y")
            content = tk.Frame(f, bg="white", padx=20, pady=15)
            content.pack(side="left", fill="both")
            tk.Label(content, text=title, font=("Helvetica", 10), fg="#78909C", bg="white").pack(anchor="w")
            tk.Label(content, text=value, font=("Helvetica", 24, "bold"), fg="#263238", bg="white").pack(anchor="w", pady=(5,0))

        create_modern_stat(stats_f, "Total Sales (総売上)", f"¥{total_sales:,}", COLORS["btn_success"])
        create_modern_stat(stats_f, "Total Quantity (総点数)", f"{total_qty:,} 点", COLORS["btn_info"])
        
        nb = ttk.Notebook(self)
        nb.pack(fill="both", expand=True, padx=40, pady=(0, 40))
        
        style = ttk.Style()
        style.configure("Sales.Treeview", font=("Helvetica", 11), rowheight=35)
        style.configure("Sales.Treeview.Heading", font=("Helvetica", 10, "bold"), padding=5)
        
        tab_table = tk.Frame(nb, bg="white")
        tab_amount = tk.Frame(nb, bg="white")
        tab_qty = tk.Frame(nb, bg="white")
        tab_trend = tk.Frame(nb, bg="white")
        tab_excel = tk.Frame(nb, bg="white")
        
        nb.add(tab_table, text=" 詳細データ ")
        nb.add(tab_amount, text=" 金額グラフ ")
        nb.add(tab_qty, text=" 個数グラフ ")
        nb.add(tab_trend, text=" 推移グラフ ")
        nb.add(tab_excel, text=" Excel形式 ")
        
        # テーブルタブ
        cols = ["Name", "Price", "TotalSales", "TotalQty"] + terms
        tree = ttk.Treeview(tab_table, columns=cols, show="headings", style="Sales.Treeview")
        
        tree.heading("Name", text="商品名"); tree.column("Name", width=180, anchor="w")
        tree.heading("Price", text="単価"); tree.column("Price", width=80, anchor="e")
        tree.heading("TotalSales", text="合計売上"); tree.column("TotalSales", width=120, anchor="e")
        tree.heading("TotalQty", text="合計個数"); tree.column("TotalQty", width=100, anchor="e")
        for t in terms:
            tree.heading(t, text=t)
            tree.column(t, width=80, anchor="e")
        
        vsb = ttk.Scrollbar(tab_table, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=vsb.set)
        tree.pack(side="left", fill="both", expand=True, padx=15, pady=15)
        vsb.pack(side="right", fill="y", pady=15)
        
        tree.tag_configure('odd', background='#FAFAFA')
        tree.tag_configure('even', background='#FFFFFF')
        
        for idx, item in enumerate(data_list):
            vals = [item["name"], f"@{item['price']:,}", f"¥{item['total_sales']:,}", f"{item['total_qty']:,}"]
            for t in terms: vals.append(f"{item[t]:,}")
            tree.insert("", "end", values=vals, tags=('odd' if idx%2==1 else 'even',))
            
        # グラフタブ
        self.setup_graph(tab_amount, "売上金額 (円)", "total_sales", COLORS["graph_bar"], "¥", "", data_list)
        self.setup_graph(tab_qty, "販売個数 (点)", "total_qty", COLORS["graph_bar_qty"], "", "点", data_list)

        # 推移グラフタブ
        self.setup_trend_graph(tab_trend, terms)

        # Excelタブ
        excel_txt = self.dm.get_excel_text()
        f_ex_top = tk.Frame(tab_excel, bg="white", pady=10); f_ex_top.pack(fill="x", padx=20)
        def copy_to_clip():
            self.clipboard_clear(); self.clipboard_append(excel_txt)
            messagebox.showinfo("コピー", "クリップボードにコピーしました。")
        tk.Button(f_ex_top, text="クリップボードにコピー", bg=COLORS["btn_info"], fg="white", font=FONT_S, command=copy_to_clip).pack(anchor="w")
        txt_area = tk.Text(tab_excel, font=("Consolas", 10), wrap="none")
        txt_area.pack(fill="both", expand=True, padx=20, pady=(0, 20))
        hsb = ttk.Scrollbar(tab_excel, orient="horizontal", command=txt_area.xview); hsb.pack(fill="x", side="bottom")
        txt_area.configure(xscrollcommand=hsb.set); txt_area.insert("1.0", excel_txt)

    def setup_graph(self, parent, title, key, color, prefix, suffix, data):
        canvas = tk.Canvas(parent, bg=COLORS["graph_bg"])
        sb = ttk.Scrollbar(parent, orient="vertical", command=canvas.yview)
        frame = tk.Frame(canvas, bg=COLORS["graph_bg"])
        frame.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=frame, anchor="nw")
        canvas.configure(yscrollcommand=sb.set)
        canvas.pack(side="left", fill="both", expand=True); sb.pack(side="right", fill="y")
        
        tk.Label(frame, text=title, font=("Helvetica", 14, "bold"), bg=COLORS["graph_bg"], fg="#546E7A").pack(pady=20, padx=20, anchor="w")
        
        vals = [i[key] for i in data]; max_val = max(vals) if vals and max(vals) > 0 else 1
        BAR_W = 600
        
        for item in data:
            row = tk.Frame(frame, bg=COLORS["graph_bg"], pady=8)
            row.pack(fill="x", padx=30)
            tk.Label(row, text=item["name"], width=20, anchor="e", bg=COLORS["graph_bg"], font=FONT_NORMAL, fg="#333").pack(side="left")
            
            bar_area = tk.Frame(row, bg="#ECEFF1", height=25, width=BAR_W)
            bar_area.pack_propagate(False)
            bar_area.pack(side="left", padx=15)
            
            bw = int((item[key] / max_val) * BAR_W)
            if bw > 0: 
                tk.Frame(bar_area, bg=color, height=25, width=bw).pack(side="left")
                
            tk.Label(row, text=f"{prefix}{item[key]:,}{suffix}", bg=COLORS["graph_bg"], font=("Helvetica", 11, "bold"), fg="#37474F").pack(side="left")

    def setup_trend_graph(self, parent, terms):
        f_ctrl = tk.Frame(parent, bg="#F5F7FA", pady=15, padx=20, relief="groove", bd=1)
        f_ctrl.pack(fill="x", padx=20, pady=(20, 0))
        
        lbl_style = {"bg": "#F5F7FA", "font": ("Helvetica", 10, "bold"), "fg": "#546E7A"}
        
        # ターム
        tk.Label(f_ctrl, text="対象ターム:", **lbl_style).pack(side="left")
        term_var = tk.StringVar()
        if terms: term_var.set(terms[0])
        cb_term = ttk.Combobox(f_ctrl, textvariable=term_var, values=terms, state="readonly", width=12)
        cb_term.pack(side="left", padx=(5, 20))
        
        # 商品
        tk.Label(f_ctrl, text="対象商品:", **lbl_style).pack(side="left")
        settings = self.dm.load_settings()
        menu_names = [m["name"] for m in settings.get("menu", [])]
        item_opts = ["全体 (合計)", "全メニュー混合"] + menu_names
        item_var = tk.StringVar(value="全体 (合計)")
        cb_item = ttk.Combobox(f_ctrl, textvariable=item_var, values=item_opts, state="readonly", width=18)
        cb_item.pack(side="left", padx=(5, 20))

        # モード
        tk.Label(f_ctrl, text="集計モード:", **lbl_style).pack(side="left")
        mode_var = tk.StringVar(value="金額")
        cb_mode = ttk.Combobox(f_ctrl, textvariable=mode_var, values=["金額", "個数"], state="readonly", width=8)
        cb_mode.pack(side="left", padx=(5, 20))
        
        btn = tk.Button(f_ctrl, text="グラフ表示", bg=COLORS["btn_info"], fg="white", relief="flat", font=("Helvetica", 10, "bold"),
                        command=lambda: self.draw_trend(canvas, term_var.get(), item_var.get(), mode_var.get()))
        btn.pack(side="left", padx=10)
        
        canvas = tk.Canvas(parent, bg="white", highlightthickness=0)
        canvas.pack(fill="both", expand=True, padx=20, pady=20)
        
        if terms:
            self.after(100, lambda: self.draw_trend(canvas, terms[0], "全体 (合計)", "金額"))

    def draw_trend(self, canvas, term, target_item_disp, mode_disp):
        canvas.delete("all")
        
        if target_item_disp == "全体 (合計)":
            target_keys = ["Total"]
        elif target_item_disp == "全メニュー混合":
            target_keys = "ALL_MIXED"
        else:
            target_keys = [target_item_disp]
            
        mode = "amount" if mode_disp == "金額" else "qty"
        
        all_series = self.dm.get_all_trend_series(term, mode)
        
        if not all_series:
            canvas.create_text(400, 300, text="データがありません", font=("Helvetica", 14), fill="#999")
            return

        draw_data = {}
        if target_keys == "ALL_MIXED":
            for k, v in all_series.items():
                if k != "Total": draw_data[k] = v
        else:
            for k in target_keys:
                if k in all_series: draw_data[k] = all_series[k]

        if not draw_data:
            canvas.create_text(400, 300, text="表示対象データなし", font=("Helvetica", 14), fill="#999")
            return

        w = canvas.winfo_width()
        h = canvas.winfo_height()
        if w < 10: w = 800
        if h < 10: h = 500
        
        margin_x = 60
        margin_y = 50
        graph_w = w - margin_x * 2
        graph_h = h - margin_y * 2
        
        all_points = []
        for series in draw_data.values():
            all_points.extend(series)
            
        if not all_points: return
        
        start_time = min(p[0] for p in all_points)
        end_time = max(p[0] for p in all_points)
        max_val = max(p[1] for p in all_points)
        
        if max_val == 0: max_val = 1
        time_span = (end_time - start_time).total_seconds()
        if time_span == 0: time_span = 1
        
        # 軸線
        canvas.create_line(margin_x, h - margin_y, w - margin_x, h - margin_y, fill="#999", width=2) # X
        canvas.create_line(margin_x, h - margin_y, margin_x, margin_y, fill="#999", width=2) # Y
        
        # Y軸目盛り (最大値と0)
        unit = "¥" if mode == "amount" else ""
        suffix = "" if mode == "amount" else "点"
        canvas.create_text(margin_x - 10, margin_y, text=f"{unit}{max_val:,}{suffix}", anchor="e", font=("Arial", 9))
        canvas.create_text(margin_x - 10, h - margin_y, text="0", anchor="e", font=("Arial", 9))

        # ★変更: X軸目盛り (時間を等間隔で細かく表示)
        num_ticks = 7 # ラベル数
        for i in range(num_ticks):
            ratio = i / (num_ticks - 1)
            x = margin_x + ratio * graph_w
            y = h - margin_y
            
            # タイムスタンプから計算してdatetimeに戻す
            current_ts = start_time.timestamp() + ratio * time_span
            current_dt = datetime.fromtimestamp(current_ts)
            time_str = current_dt.strftime("%H:%M")
            
            # アンカー調整
            if i == 0: anchor = "w"
            elif i == num_ticks - 1: anchor = "e"
            else: anchor = "center"
            
            canvas.create_text(x, y + 20, text=time_str, anchor=anchor, font=("Arial", 9), fill="#555")
            canvas.create_line(x, y, x, y + 5, fill="#999", width=1)

        colors = ['#E57373', '#64B5F6', '#81C784', '#FFD54F', '#BA68C8', '#4DB6AC', '#A1887F', '#90A4AE', '#7986CB', '#FF8A65']
        
        # プロットループ
        legend_x = w - margin_x - 10
        legend_y = margin_y + 10
        
        for idx, (name, series) in enumerate(draw_data.items()):
            line_color = colors[idx % len(colors)]
            
            prev_x, prev_y = None, None
            for dt, val in series:
                delta_sec = (dt - start_time).total_seconds()
                x = margin_x + (delta_sec / time_span) * graph_w
                y = (h - margin_y) - (val / max_val) * graph_h
                
                if prev_x is not None:
                    canvas.create_line(prev_x, prev_y, x, y, fill=line_color, width=2)
                prev_x, prev_y = x, y
            
            # 凡例
            if len(draw_data) > 1:
                canvas.create_rectangle(legend_x - 10, legend_y, legend_x, legend_y + 10, fill=line_color, outline="")
                canvas.create_text(legend_x - 15, legend_y + 5, text=name, anchor="e", font=("Arial", 9), fill="#555")
                legend_y += 20
        
        if len(draw_data) == 1:
            name = list(draw_data.keys())[0]
            canvas.create_text(w/2, margin_y/2, text=f"[{name}] の推移", font=("Helvetica", 12, "bold"), fill="#333")


class CardSettingsWindow(tk.Toplevel):
    def __init__(self, parent, data_manager, callback):
        super().__init__(parent)
        self.dm = data_manager
        self.callback = callback
        self.title("カード表示設定")
        self.geometry("400x400") # 高さを少し増やす
        self.transient(parent)
        self.grab_set()
        
        w, h = 400, 400
        sw = parent.winfo_screenwidth()
        sh = parent.winfo_screenheight()
        x = (sw - w) // 2; y = (sh - h) // 2
        self.geometry(f"+{x}+{y}")
        
        self.current_settings = self.dm.load_settings().get("card_settings", {"width": 130, "height": 0, "overflow": 6})
        
        self.setup_ui()

    def setup_ui(self):
        f = tk.Frame(self, padx=30, pady=30)
        f.pack(fill="both", expand=True)
        
        # 横幅
        tk.Label(f, text="カード横幅 (px):", anchor="w").pack(fill="x")
        self.ent_width = tk.Entry(f, font=("Helvetica", 12))
        self.ent_width.insert(0, str(self.current_settings["width"]))
        self.ent_width.pack(fill="x", pady=(0, 15))
        
        # ★追加: 縦幅
        tk.Label(f, text="カード縦幅 (px):", anchor="w").pack(fill="x")
        tk.Label(f, text="※0 にするとウィンドウに合わせて自動計算", font=("Arial", 8), fg="#777", anchor="w").pack(fill="x")
        self.ent_height = tk.Entry(f, font=("Helvetica", 12))
        # 初期値がない場合0で補完
        curr_h = self.current_settings.get("height", 0)
        self.ent_height.insert(0, str(curr_h))
        self.ent_height.pack(fill="x", pady=(0, 15))
        
        # 文字数
        tk.Label(f, text="省略文字数 (文字):", anchor="w").pack(fill="x")
        tk.Label(f, text="※この文字数を超えると「…」になります", font=("Arial", 8), fg="#777", anchor="w").pack(fill="x")
        self.ent_overflow = tk.Entry(f, font=("Helvetica", 12))
        self.ent_overflow.insert(0, str(self.current_settings["overflow"]))
        self.ent_overflow.pack(fill="x", pady=(0, 20))
        
        tk.Button(f, text="保存して適用", command=self.save, bg=COLORS["btn_success"], fg="white", font=("Helvetica", 11, "bold"), height=2).pack(fill="x")

    def save(self):
        try:
            w = int(self.ent_width.get())
            h = int(self.ent_height.get())
            o = int(self.ent_overflow.get())
            
            if w < 100: w = 100
            if h < 0: h = 0 # 負の値は0に
            
            self.dm.update_card_settings(w, h, o)
            messagebox.showinfo("完了", "設定を保存しました。\n画面を更新します。")
            self.destroy()
            if self.callback: self.callback()
        except ValueError:
            messagebox.showerror("エラー", "数値を入力してください")