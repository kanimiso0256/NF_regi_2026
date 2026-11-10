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
    "status_bar": "#78909C",         # 上部の帯（端末使用者の表示）
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