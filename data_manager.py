# data_manager.py
import os
import sys
import csv
import json
import shutil
import glob
import zipfile
from collections import defaultdict
from datetime import datetime, timedelta
from config import SYSTEM_DIR_NAME, LOG_FILE
   
# data_manager.py (verify_integrityメソッドを含む DataManagerクラスの一部)

# data_manager.py (変更クラスのみ)

# data_manager.py (変更クラスのみ)

# data_manager.py (変更クラスのみ)

# data_manager.py (変更クラスのみ)

class DataManager:
    # ... (__init__, load_settings 等、他のメソッドは変更なし) ...
    def __init__(self):
        self.base_path = self.get_resource_path("")
        self.system_dir = os.path.join(self.base_path, SYSTEM_DIR_NAME)
        if not os.path.exists(self.system_dir): os.makedirs(self.system_dir)
        self.data_dir = os.path.join(self.system_dir, "data")
        if not os.path.exists(self.data_dir): os.makedirs(self.data_dir)
        self.backup_dir = os.path.join(self.system_dir, "logs")
        if not os.path.exists(self.backup_dir): os.makedirs(self.backup_dir)
        self.output_dir = os.path.join(self.base_path, "output")
        if not os.path.exists(self.output_dir): os.makedirs(self.output_dir)
        
        self.log_path = os.path.join(self.data_dir, LOG_FILE)
        self.settings_path = os.path.join(self.system_dir, "settings.json")
        self.menu_path_legacy = os.path.join(self.system_dir, "menu.txt")

        self.load_settings()
        if not os.path.exists(self.log_path): self.init_log_file()
        
        self.last_backup_time = None
        self.perform_backup()
        
        if os.path.exists(self.menu_path_legacy):
            try: os.remove(self.menu_path_legacy)
            except: pass

    def get_resource_path(self, filename):
        if getattr(sys, 'frozen', False):
            base_path = os.path.dirname(sys.executable)
        else:
            base_path = os.path.dirname(os.path.abspath(__file__))
        return os.path.join(base_path, filename)

    def init_log_file(self):
        try:
            with open(self.log_path, 'w', encoding='utf-8', newline='') as f:
                writer = csv.writer(f)
                writer.writerow(["Timestamp", "User", "Terminal", "Location", "Action", "Target", "Value"])
        except: pass

    def load_settings(self):
        default_settings = {
            "terms": ["1日目", "2日目", "3日目", "4日目"], 
            "adminPass": "password",
            "active_terms": ["1日目", "テスト", "調整"], 
            "ngrok_token": "", 
            "mobile_password": "1234",
            "mobile_info": "",
            "mobile_alert": "",
            "terminal_user": "", 
            "notify_alert": { "cash": True, "paypay": True },
            "ngrok_connect_enabled": True,
            "card_settings": {"width": 130, "height": 0, "overflow": 6},
            "menu": [
                {"name": "オリジナル", "price": 450, "visible": True, "mobile_visible": False, "order": 10},
            ]
        }
        if not os.path.exists(self.settings_path):
            self.save_settings_file(default_settings)
            return default_settings
        try:
            with open(self.settings_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                for k, v in default_settings.items():
                    if k not in data: data[k] = v
                if "card_settings" not in data:
                    data["card_settings"] = default_settings["card_settings"]
                elif "height" not in data["card_settings"]:
                    data["card_settings"]["height"] = 0
                if "menu" in data:
                    for i, item in enumerate(data["menu"]):
                        if "mobile_visible" not in item: item["mobile_visible"] = False
                        if "order" not in item: item["order"] = (i + 1) * 10
                self.save_settings_file(data)
                return data
        except: return default_settings
        
    def save_settings_file(self, data):
        try:
            with open(self.settings_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=4, ensure_ascii=False)
        except: pass

    def update_card_settings(self, width, height, overflow):
        data = self.load_settings()
        data["card_settings"] = {"width": width, "height": height, "overflow": overflow}
        self.save_settings_file(data)

    def update_notification_settings(self, cash_alert, paypay_alert, user_name):
        data = self.load_settings()
        data["notify_alert"]["cash"] = cash_alert
        data["notify_alert"]["paypay"] = paypay_alert
        self.save_settings_file(data)
        self.log_action(user_name, "Settings", "UpdateNotifyAlert", "Mobile", f"Cash:{cash_alert}, PayPay:{paypay_alert}")

    def get_notification_settings(self):
        return self.load_settings().get("notify_alert", {"cash": False, "paypay": False})

    def update_ngrok_connect_enabled(self, enabled, user_name):
        data = self.load_settings()
        data["ngrok_connect_enabled"] = enabled
        self.save_settings_file(data)
        self.log_action(user_name, "Settings", "ToggleNgrokConnect", "System", f"Enabled:{enabled}")

    def update_active_terms(self, active_list):
        data = self.load_settings()
        data["active_terms"] = active_list
        self.save_settings_file(data)

    def update_menu(self, new_menu_list):
        data = self.load_settings()
        data["menu"] = new_menu_list
        self.save_settings_file(data)

    def update_ngrok_token(self, token):
        data = self.load_settings()
        data["ngrok_token"] = token
        self.save_settings_file(data)
        
    def update_mobile_password(self, pw):
        data = self.load_settings()
        data["mobile_password"] = pw
        self.save_settings_file(data)

    def update_mobile_messages(self, info, alert):
        data = self.load_settings()
        data["mobile_info"] = info
        data["mobile_alert"] = alert
        self.save_settings_file(data)

    def set_terminal_user(self, name):
        data = self.load_settings()
        data["terminal_user"] = name
        self.save_settings_file(data)

    def get_terminal_user(self):
        return self.load_settings().get("terminal_user", "")

    def log_action(self, user, location, action, target, value):
        ts = datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')
        if not user: user = "General User"
        terminal_user = self.get_terminal_user()
        if not terminal_user: terminal_user = "Unassigned"

        try:
            with open(self.log_path, 'a', encoding='utf-8', newline='') as f:
                writer = csv.writer(f)
                writer.writerow([ts, user, terminal_user, location, action, target, value])
            self.check_auto_backup()
        except: pass

    def check_auto_backup(self):
        if self.last_backup_time is None: return
        if datetime.now() - self.last_backup_time > timedelta(minutes=10):
            self.perform_backup()

    def perform_backup(self):
        if not os.path.exists(self.log_path): return
        MAX_BACKUPS = 100 
        ts_str = datetime.now().strftime('%Y%m%d_%H%M%S')
        log_backup = os.path.join(self.backup_dir, f"log_{ts_str}.csv")
        settings_backup = os.path.join(self.backup_dir, f"settings_{ts_str}.json")
        try:
            shutil.copy2(self.log_path, log_backup)
            if os.path.exists(self.settings_path): shutil.copy2(self.settings_path, settings_backup)
            self.last_backup_time = datetime.now()
            log_files = glob.glob(os.path.join(self.backup_dir, "log_*.csv"))
            log_files.sort(key=os.path.getmtime) 
            if len(log_files) > MAX_BACKUPS:
                files_to_delete = log_files[:len(log_files) - MAX_BACKUPS]
                for old_log_path in files_to_delete:
                    filename = os.path.basename(old_log_path)
                    if filename.startswith("log_") and filename.endswith(".csv"):
                        ts = filename[4:-4] 
                        old_setting_path = os.path.join(self.backup_dir, f"settings_{ts}.json")
                        try: os.remove(old_log_path)
                        except Exception: pass
                        try: 
                            if os.path.exists(old_setting_path): os.remove(old_setting_path)
                        except Exception: pass
        except Exception: pass

    def clean_old_backups(self):
        log_files = glob.glob(os.path.join(self.backup_dir, "log_*.csv"))
        log_files.sort(key=os.path.getmtime, reverse=True)
        deleted_count = 0
        if len(log_files) > 10:
            for f in log_files[10:]:
                ts = f.split("log_")[-1].replace(".csv", "")
                old_setting = os.path.join(self.backup_dir, f"settings_{ts}.json")
                try:
                    os.remove(f); deleted_count += 1
                    if os.path.exists(old_setting): os.remove(old_setting)
                except: pass
        return deleted_count

    def get_available_backups(self):
        backups = []
        if os.path.exists(self.log_path):
            mtime = datetime.fromtimestamp(os.path.getmtime(self.log_path)).strftime('%Y-%m-%d %H:%M:%S')
            backups.append({"name": "現在のログ (current_log.csv)", "path": self.log_path, "time": mtime, "type": "CURRENT"})
        files = glob.glob(os.path.join(self.backup_dir, "log_*.csv"))
        files.sort(key=os.path.getmtime, reverse=True)
        for f in files:
            mtime = datetime.fromtimestamp(os.path.getmtime(f)).strftime('%Y-%m-%d %H:%M:%S')
            backups.append({"name": os.path.basename(f), "path": f, "time": mtime, "type": "BACKUP"})
        return backups

    def get_logs(self, limit=None, search_query=""):
        logs = []
        if not os.path.exists(self.log_path): return logs
        try:
            with open(self.log_path, 'r', encoding='utf-8') as f:
                reader = csv.reader(f); next(reader, None)
                rows = list(reader); rows.reverse()
                for row in rows:
                    if search_query and search_query.lower() not in str(row).lower(): continue
                    display_row = row
                    if len(row) < 7: display_row.extend([""] * (7 - len(row)))
                    logs.append(display_row)
                    if limit and len(logs) >= limit: break
        except: pass
        return logs

    def delete_all_logs(self):
        self.perform_backup()
        try: self.init_log_file(); return True
        except: return False

    def factory_reset(self, new_terms, new_menu_text, new_pass, admin_name):
        self.perform_backup()
        current_settings = self.load_settings()
        final_terms = new_terms if new_terms else current_settings.get("terms", [])
        final_menu = []
        if new_menu_text.strip():
            order_counter = 10
            for line in new_menu_text.strip().split("\n"):
                parts = line.split(",")
                if len(parts) >= 2:
                    try:
                        final_menu.append({"name": parts[0].strip(), "price": int(parts[1].strip()), "visible": True, "mobile_visible": False, "order": order_counter})
                        order_counter += 10
                    except: pass
        else:
            final_menu = current_settings.get("menu", [])
        final_pass = new_pass if new_pass else current_settings.get("adminPass", "password")
        current_settings["terms"] = final_terms
        current_settings["menu"] = final_menu
        current_settings["adminPass"] = final_pass
        current_settings["active_terms"] = [t for t in current_settings["active_terms"] if t in final_terms]
        if not current_settings["active_terms"] and final_terms: current_settings["active_terms"] = [final_terms[0]]
        current_settings["ngrok_connect_enabled"] = True
        self.save_settings_file(current_settings)
        self.init_log_file()
        self.log_action(admin_name, "System", "Factory Reset", "All Data", "Executed")
        for f in glob.glob(os.path.join(self.data_dir, "*.csv")):
            if os.path.basename(f) != LOG_FILE:
                try: os.remove(f)
                except: pass
        return True

    def get_detailed_sales_data(self):
        settings = self.load_settings()
        terms = settings.get("terms", []) + ["調整"]
        menu_list = settings.get("menu", [])
        data_matrix = defaultdict(lambda: {"price": 0, "total_qty": 0, "total_sales": 0})
        for m in menu_list: data_matrix[m["name"]]["price"] = int(m["price"])
        for t in terms:
            d = self.load_csv_data(f"{t}.csv")
            for name, counts in d.items():
                if name not in data_matrix: data_matrix[name]["price"] = 0
                q = counts['cash'] + counts['paypay']
                data_matrix[name][t] = q
                data_matrix[name]["total_qty"] += q
        result = []
        for name, info in data_matrix.items():
            info["total_sales"] = info["total_qty"] * info["price"]
            for t in terms:
                if t not in info: info[t] = 0
            row = {"name": name, "price": info["price"], "total_sales": info["total_sales"], "total_qty": info["total_qty"]}
            for t in terms: row[t] = info[t]
            result.append(row)
        return result, terms

    def get_all_trend_series(self, term, mode="amount"):
        settings = self.load_settings()
        menu_list = settings.get("menu", [])
        price_map = {m["name"]: int(m["price"]) for m in menu_list}
        series_data = defaultdict(list)
        current_totals = defaultdict(int)
        
        try:
            with open(self.log_path, 'r', encoding='utf-8') as f:
                reader = csv.reader(f); next(reader, None)
                for row in reader:
                    if len(row) < 7: continue
                    ts_str, _, _, loc, action, target, val_str = row
                    if loc != term: continue
                    if action not in ["Add", "Sub", "加算", "減算"]: continue
                    if " [" not in target: continue
                    try:
                        dt = datetime.strptime(ts_str, '%Y-%m-%d %H:%M:%S.%f')
                        name_part = target.rsplit(" [", 1)[0]
                        delta = int(val_str.split()[0].replace('+', ''))
                        
                        # Valueは符号付きなのでActionによる反転は不要
                        if mode == "amount":
                            price = price_map.get(name_part, 0)
                            val_delta = delta * price
                        else:
                            val_delta = delta
                        
                        current_totals[name_part] += val_delta
                        series_data[name_part].append((dt, current_totals[name_part]))
                        
                        current_totals["Total"] += val_delta
                        series_data["Total"].append((dt, current_totals["Total"]))
                    except: continue
        except: pass
        return series_data

    def get_excel_text(self):
        settings = self.load_settings()
        terms = settings.get("terms", []) + ["調整"]
        menu_list = settings.get("menu", [])
        headers = ["商品名", "単価", "合計売上", "合計個数"]
        for t in terms:
            headers.append(f"{t}(現数)")
            headers.append(f"{t}(現¥)")
            headers.append(f"{t}(Pay数)")
            headers.append(f"{t}(Pay¥)")
            headers.append(f"{t}(計¥)")
        lines = ["\t".join(headers)]
        for item in menu_list:
            name = item["name"]; price = int(item["price"])
            total_sales = 0; total_qty = 0; term_cols = []
            for t in terms:
                t_data = self.load_csv_data(f"{t}.csv")
                c_qty = t_data[name]['cash']; p_qty = t_data[name]['paypay']
                c_val = c_qty * price; p_val = p_qty * price; t_val = c_val + p_val
                term_cols.append(str(c_qty)); term_cols.append(str(c_val))
                term_cols.append(str(p_qty)); term_cols.append(str(p_val)); term_cols.append(str(t_val))
                total_qty += (c_qty + p_qty)
            total_sales = total_qty * price
            row = [name, str(price), str(total_sales), str(total_qty)] + term_cols
            lines.append("\t".join(row))
        return "\n".join(lines)

    # ★修正: 復元処理もValueの符号を信頼し、Actionによる反転を削除
    def restore_from_log(self, target_log_path, admin_name):
        fname = os.path.basename(target_log_path)
        if fname.startswith("log_"):
            ts_part = fname.replace("log_", "").replace(".csv", "")
            target_settings = os.path.join(self.backup_dir, f"settings_{ts_part}.json")
            if os.path.exists(target_settings):
                try: shutil.copy2(target_settings, self.settings_path)
                except: pass
        settings = self.load_settings()
        terms = settings.get("terms", []) + ["調整"]
        restored_data = defaultdict(lambda: defaultdict(lambda: {'cash': 0, 'paypay': 0}))
        try:
            with open(target_log_path, 'r', encoding='utf-8') as f:
                reader = csv.reader(f); header = next(reader, None) 
                if not header: return False, "ログファイルが空です。"
                for row in reader:
                    if len(row) < 7: continue 
                    loc, action, target, val_str = row[3], row[4], row[5], row[6]
                    if action == "ResetData":
                        target_term = target.replace(".csv", "")
                        if target_term in restored_data: restored_data[target_term].clear()
                        continue
                    if action == "Factory Reset": restored_data.clear(); continue
                    
                    if action not in ["Add", "Sub", "加算", "減算"] or " [" not in target: continue
                    if loc not in terms: continue
                    
                    try:
                        name_part, type_part = target.rsplit(" [", 1)
                        ptype = type_part.replace("]", "").lower()
                        delta_str = val_str.split()[0].replace('+', '')
                        delta = int(delta_str) 
                        
                        # ★修正: Valueはすでに符号付きなのでActionによる反転は削除
                        # if action in ["減算", "Sub"]: delta *= -1
                        
                        if ptype in ['cash', 'paypay']: restored_data[loc][name_part][ptype] += delta
                    except ValueError: continue 
                    
            for t in terms: self.reset_csv_data(f"{t}.csv")
            for t in terms:
                path = os.path.join(self.data_dir, f"{t}.csv")
                term_items = restored_data[t]
                if not term_items: continue
                with open(path, 'w', encoding='utf-8', newline='') as f:
                    writer = csv.writer(f)
                    for name, counts in term_items.items():
                        writer.writerow([name, counts['cash'], counts['paypay']])
            if target_log_path != self.log_path: shutil.copy2(target_log_path, self.log_path)
            self.log_action(admin_name, "Admin", "System Restore", "All Data", f"Restored from {os.path.basename(target_log_path)}")
            return True, "復元が完了しました。"
        except Exception as e: return False, f"復元エラー: {e}"

    def verify_integrity(self):
        log_path = self.log_path
        if not os.path.exists(log_path): return False, "❌ ログファイルが見つかりません。"
        settings = self.load_settings()
        terms = settings.get("terms", []) + ["調整"]
        calculated_data = defaultdict(lambda: defaultdict(lambda: {'cash': 0, 'paypay': 0}))
        try:
            with open(log_path, 'r', encoding='utf-8') as f:
                reader = csv.reader(f); next(reader, None)
                for i, row in enumerate(reader):
                    if len(row) < 7: continue
                    loc, action, target, val_str = row[3], row[4], row[5], row[6]
                    
                    if action == "ResetData":
                        t_term = target.replace(".csv", "")
                        if t_term in calculated_data: calculated_data[t_term].clear()
                        continue
                    if action == "Factory Reset":
                        calculated_data.clear()
                        continue
                        
                    if action in ["Add", "Sub", "加算", "減算"]:
                        if loc not in terms: continue
                        
                        # シンプルな解析 ("商品名 [タイプ]")
                        if " [" in target:
                            try:
                                # Targetの分割
                                name_part, type_part = target.rsplit(" [", 1)
                                ptype = type_part.replace("]", "").lower()
                                
                                # Valueから数値取得
                                delta_str = val_str.split()[0].replace('+', '')
                                delta = int(delta_str)
                                
                                # Action(Sub)による反転は行わない (Valueの符号を正とする)
                                
                                if ptype in ['cash', 'paypay']:
                                    calculated_data[loc][name_part][ptype] += delta
                            except:
                                continue
        except Exception as e: return False, f"❌ ログ解析中にエラーが発生: {e}"
        
        errors = []
        for t in terms:
            csv_data = self.load_csv_data(f"{t}.csv")
            all_keys = set(csv_data.keys()) | set(calculated_data[t].keys())
            for name in all_keys:
                csv_cash = csv_data[name]['cash']
                csv_pay = csv_data[name]['paypay']
                log_cash = calculated_data[t][name]['cash']
                log_pay = calculated_data[t][name]['paypay']
                
                if csv_cash != log_cash:
                    errors.append(f"[{t}] {name}(Cash): CSV={csv_cash}, Log={log_cash}")
                if csv_pay != log_pay:
                    errors.append(f"[{t}] {name}(Pay): CSV={csv_pay}, Log={log_pay}")
                    
        if errors:
            error_msg = "❌ データの不整合が検出されました:\n" + "\n".join(errors[:10])
            if len(errors) > 10: error_msg += "\n...他"
            return False, error_msg
        
        return True, "✅ ログと現在のデータの整合性は確認されました。"

    def load_csv_data(self, filename):
        path = os.path.join(self.data_dir, filename)
        data = defaultdict(lambda: {'cash': 0, 'paypay': 0})
        if os.path.exists(path):
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    reader = csv.reader(f)
                    for row in reader:
                        if len(row) >= 3:
                            data[row[0]]['cash'] = int(row[1])
                            data[row[0]]['paypay'] = int(row[2])
            except: pass
        return data

    def save_csv_data(self, filename, items):
        path = os.path.join(self.data_dir, filename)
        try:
            with open(path, 'w', encoding='utf-8', newline='') as f:
                writer = csv.writer(f)
                for item in items:
                    writer.writerow([item.name, item.counts['term']['cash'], item.counts['term']['paypay']])
        except: pass

    def reset_csv_data(self, filename):
        path = os.path.join(self.data_dir, filename)
        if os.path.exists(path):
            try: os.remove(path); return True
            except: return False
        return True

    def calculate_stats(self, current_mode, terms):
        all_data = {}
        for t in terms: all_data[t] = self.load_csv_data(f"{t}.csv")
        all_data["調整"] = self.load_csv_data("調整.csv")
        running = ["調整"]
        if current_mode in terms: running.extend(terms[:terms.index(current_mode)+1])
        stats = defaultdict(lambda: {'cumulative': {'cash': 0, 'paypay': 0}, 'total': {'cash': 0, 'paypay': 0}})
        for d in all_data.values():
            for name, v in d.items():
                stats[name]['total']['cash'] += v['cash']
                stats[name]['total']['paypay'] += v['paypay']
        for t in running:
            if t in all_data:
                for name, v in all_data[t].items():
                    stats[name]['cumulative']['cash'] += v['cash']
                    stats[name]['cumulative']['paypay'] += v['paypay']
        return stats  