# analytics.py
"""ダッシュボード用の集計。

売上金額は current_log.csv に記録した金額（売れたときの値段）で出す（レジ画面の「Term」と同じ）。
金額の書かれていない古い記録だけは今の値段で計算する（sales_log.py）。
個数は期間ごとの CSV（<期間>.csv）、時間別売上・売上の推移・会計件数はログから計算する。

ログでは 1 回の会計が
    CommitOrder（PC での確定）または SquareImport（Square の会計の取り込み）
    Add / Sub（商品ごとの増減。Location が期間名）
の順に書かれるので、その直後に続く Add/Sub をまとめて 1 件として数える。
"""
from collections import defaultdict

import sales_log

COMMIT_ACTIONS = ("CommitOrder", "SquareImport")
DEFAULT_HOURS = (9, 17)   # データが少なくてもこの時間帯は表示する
MAX_TREND_POINTS = 80
MIX_MAX_ITEMS = 5         # これより多い商品は「その他」にまとめる


def build(dm, term=None, current_mode=None):
    settings = dm.load_settings()
    terms = settings.get("terms", [])
    prices = {m["name"]: int(m.get("price", 0)) for m in settings.get("menu", [])}
    amounts = sales_log.term_amounts(dm.log_path, prices)

    sales_by_term = {t: _term_sales(dm, t, amounts)[0] for t in terms}
    term = _pick_term(term, terms, current_mode, sales_by_term)
    if term is None:
        return {"terms": [], "term": None}

    sales, mix = _term_sales(dm, term, amounts)
    pay = _pay_split(amounts, term)
    hourly, trend, transactions = _scan_log(dm.log_path, term, prices)

    idx = terms.index(term)
    prev_term = terms[idx - 1] if idx > 0 else None
    prev_sales = sales_by_term.get(prev_term) if prev_term else None
    change = (sales - prev_sales) / prev_sales * 100 if prev_sales else None

    target = int(settings.get("targets", {}).get(term, 0) or 0)
    peak = max(hourly, key=lambda h: h["amount"]) if any(h["amount"] for h in hourly) else None

    return {
        "terms": terms,
        "term": term,
        "sales": sales,
        "target": target,
        "rate": sales / target * 100 if target else None,
        "transactions": transactions,
        "average": round(sales / transactions) if transactions else None,
        "prev_term": prev_term,
        "change": change,
        "hourly": hourly,
        "peak": peak,
        "mix": mix,
        "pay": pay,
        "trend": trend,
    }


def _pick_term(term, terms, current_mode, sales_by_term):
    if term in terms:
        return term
    if current_mode in terms:
        return current_mode
    with_sales = [t for t in terms if sales_by_term.get(t)]
    if with_sales:
        return with_sales[-1]
    return terms[0] if terms else None


def _term_sales(dm, term, amounts):
    counts = dm.load_csv_data(f"{term}.csv")
    term_amounts = amounts.get(term, {})
    rows = []
    for name in set(counts) | set(term_amounts):
        c = counts.get(name, {"cash": 0, "paypay": 0})
        a = term_amounts.get(name, {"cash": 0, "paypay": 0})
        qty = c["cash"] + c["paypay"]
        amount = a["cash"] + a["paypay"]
        if amount > 0:
            rows.append({"name": name, "qty": qty, "amount": amount})
    rows.sort(key=lambda r: r["amount"], reverse=True)
    total = sum(r["amount"] for r in rows)

    if len(rows) > MIX_MAX_ITEMS:
        rest = rows[MIX_MAX_ITEMS - 1:]
        rows = rows[:MIX_MAX_ITEMS - 1] + [{
            "name": "その他",
            "qty": sum(r["qty"] for r in rest),
            "amount": sum(r["amount"] for r in rest),
            "other": True,
        }]
    for r in rows:
        r["pct"] = r["amount"] / total * 100 if total else 0
    return total, rows


def _pay_split(amounts, term):
    """レジに記録した売上を、現金と Square の枠に分けた金額"""
    term_amounts = amounts.get(term, {})
    return {
        "cash": sum(a["cash"] for a in term_amounts.values()),
        "square": sum(a["paypay"] for a in term_amounts.values()),
    }


def _scan_log(log_path, term, prices):
    hourly = defaultdict(int)
    points = []          # (時刻, 累計売上)
    running = 0
    transactions = 0
    commit = None        # 処理中の会計 {"loc": 期間, "qty": 個数の合計}

    def close_commit():
        nonlocal transactions, commit
        # 取消だけの確定（個数がマイナス）は会計として数えない
        if commit and commit["loc"] == term and commit["qty"] > 0:
            transactions += 1
        commit = None

    for row in sales_log.read_rows(log_path):
        if len(row) < 7:
            continue
        action = row[4]
        if action not in sales_log.COUNT_ACTIONS:
            close_commit()
            if action in COMMIT_ACTIONS:
                commit = {"loc": None, "qty": 0}
            continue

        e = sales_log.parse_count_row(row)
        if e is None:
            continue
        try:
            dt = sales_log.row_time(e)
        except ValueError:
            continue

        if commit is not None:
            if commit["loc"] is None:
                commit["loc"] = e["term"]
            if commit["loc"] == e["term"]:
                commit["qty"] += e["qty"]

        if e["term"] != term:
            continue
        amount = sales_log.amount_of(e, prices)
        hourly[dt.hour] += amount
        running += amount
        points.append((dt, running))
    close_commit()

    hours = list(hourly) + list(DEFAULT_HOURS)
    hourly_list = [{"hour": h, "amount": hourly.get(h, 0)} for h in range(min(hours), max(hours) + 1)]
    return hourly_list, _downsample(points), transactions


def _downsample(points):
    if len(points) > MAX_TREND_POINTS:
        step = len(points) / MAX_TREND_POINTS
        points = [points[int(i * step)] for i in range(MAX_TREND_POINTS - 1)] + [points[-1]]
    return [{"t": dt.strftime("%H:%M"), "v": v} for dt, v in points]
