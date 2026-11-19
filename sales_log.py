# sales_log.py
"""操作ログ（current_log.csv）の個数の増減の行を読み書きする。

個数が増減した行（Action が Add / Sub）の Value 欄には、その増減でいくら売れたかも書く:

    +2 ¥900 (Term: 5) by 名倉

金額は確定したときの単価 × 個数（Square から取り込んだ会計は、Square で実際に払われた金額）。
あとでメニューの値段を変えても、過去の売上の金額は変わらない。

金額が書かれていない古い行（この仕組みより前の記録・Tkinter 版の記録）は、
今のメニューの値段で計算する。
"""
import csv
import re
from datetime import datetime

COUNT_ACTIONS = ("Add", "Sub", "加算", "減算")
_AMOUNT = re.compile(r"¥(-?\d+)")


def format_value(qty, amount, new_val, by):
    """個数の増減の行の Value 欄（先頭は個数。data_manager.verify_integrity も先頭だけを読む）"""
    return f"{qty:+d} ¥{amount} (Term: {new_val}) by {by}"


def parse_count_row(row):
    """ログの 1 行が個数の増減なら、その内容を返す（それ以外は None）。

    {"ts", "term", "name", "ptype", "qty", "amount"}。amount は金額が書かれていない行では None
    """
    if len(row) < 7:
        return None
    ts, _user, _terminal, term, action, target, value = row[:7]
    if action not in COUNT_ACTIONS or " [" not in target:
        return None
    name, ptype = target.rsplit(" [", 1)
    words = value.split()
    try:
        qty = int(words[0])
    except (ValueError, IndexError):
        return None
    amount = None
    if len(words) > 1:
        m = _AMOUNT.fullmatch(words[1])
        if m:
            amount = int(m.group(1))
    return {"ts": ts, "term": term, "name": name, "ptype": ptype.rstrip("]").lower(),
            "qty": qty, "amount": amount}


def amount_of(entry, prices):
    """行の金額。書かれていなければ今の値段で計算する"""
    if entry["amount"] is not None:
        return entry["amount"]
    return entry["qty"] * prices.get(entry["name"], 0)


def row_time(entry):
    try:
        return datetime.strptime(entry["ts"], "%Y-%m-%d %H:%M:%S.%f")
    except ValueError:
        return datetime.fromisoformat(entry["ts"])


def read_rows(log_path):
    """ログの行を順に返す（ファイルがなければ何も返さない）"""
    try:
        with open(log_path, "r", encoding="utf-8") as f:
            reader = csv.reader(f)
            next(reader, None)
            yield from reader
    except OSError:
        return


def term_amounts(log_path, prices):
    """期間ごと・商品ごと・支払い方法ごとの売上金額 {期間: {商品名: {"cash": 円, "paypay": 円}}}。

    Tkinter 版のリセット（ResetData・Factory Reset）があれば、そこまでの分は数えない
    （data_manager.verify_integrity と同じ扱い）
    """
    out = {}
    for row in read_rows(log_path):
        if len(row) >= 7 and row[4] == "ResetData":
            out.pop(row[5].replace(".csv", ""), None)
            continue
        if len(row) >= 7 and row[4] == "Factory Reset":
            out.clear()
            continue
        e = parse_count_row(row)
        if e is None or e["ptype"] not in ("cash", "paypay"):
            continue
        c = out.setdefault(e["term"], {}).setdefault(e["name"], {"cash": 0, "paypay": 0})
        c[e["ptype"]] += amount_of(e, prices)
    return out
