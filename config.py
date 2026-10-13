# config.py
import os

# === デザイン設定 ===
COLORS = {
    "bg": "#ECEFF1",             # 全体背景
    "card_bg": "#FFFFFF",        # カード背景
    "text_main": "#263238",      # メイン文字
    "text_sub": "#546E7A",       # サブ文字
    "header_bg": "#37474F",      # ヘッダー背景
    
    # ステータスバー
    "status_bar_online": "#43A047",  # オンライン時の緑帯
    "status_bar_offline": "#78909C", # オフライン時の灰色帯
    "status_text": "#FFFFFF",        # ステータス文字色

    # ログイン画面
    "login_bg": "#263238",       
    "login_card": "#FFFFFF",     
    "login_btn": "#009688",      
    "login_btn_hover": "#00796B",
    
    # コントロールパネル（サイドバー）
    "sidebar_bg": "#263238",     
    "sidebar_fg": "#ECEFF1",     
    "sidebar_btn_hover": "#455A64",
    
    # 統計パネル
    "stat_panel": "#455A64", 
    "stat_val": "#81C784",       
    
    # 商品カード (Cash/Pay)
    "cash_bg": "#E8F5E9", "cash_fg": "#1B5E20", "cash_btn": "#A5D6A7",
    "pay_bg": "#FFEBEE",  "pay_fg": "#B71C1C",  "pay_btn": "#EF9A9A",
    
    # ボタン色
    "btn_primary": "#546E7A", 
    "btn_danger": "#E57373", 
    "btn_success": "#66BB6A", 
    "btn_warn": "#FFA726",
    "btn_info": "#42A5F5",
    "btn_clean": "#7986CB",
    "btn_setting": "#90A4AE",
    
    # 危険エリア
    "danger_zone_bg": "#FFEBEE",
    "danger_text": "#B71C1C",
    
    # グラフ
    "graph_bar": "#5C6BC0",
    "graph_bar_qty": "#26A69A", 
    "graph_bg": "#FAFAFA",
    "disabled": "#CFD8DC",

    # 通知エリア
    "notify_bg": "#37474F",
    "notify_card_base": "#FFFFFF",
    "notify_card_selected": "#FFF9C4", # 選択中の背景
    "notify_border_base": "#90A4AE",
    "notify_border_selected": "#FFD600", # 選択中の枠線（黄色）

    # モバイル状態スイッチ
    "mob_on_bg": "#009688", "mob_on_fg": "#FFFFFF",
    "mob_off_bg": "#CFD8DC", "mob_off_fg": "#546E7A",

    # 監視エリア
    "monitor_active_bg": "#FFF8E1", 
    "monitor_text": "#F57C00",
}

# フォント設定
FONT_L = ("Helvetica", 24, "bold")
FONT_M = ("Helvetica", 16, "bold")
FONT_S = ("Helvetica", 12, "bold")
FONT_XS = ("Helvetica", 10, "bold")
FONT_NORMAL = ("Helvetica", 11)

# カード幅設定
CARD_WIDTH = 150
CARD_HEIGHT = 555  # ★修正: 560 -> 555
SYSTEM_DIR_NAME = "system_data"
LOG_FILE = "current_log.csv"