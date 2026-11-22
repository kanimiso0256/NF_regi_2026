# analytics.py
"""ダッシュボード用の集計。

売上金額は current_log.csv に記録した金額（売れたときの値段）で出す（レジ画面の「Term」と同じ）。
金額の書かれていない古い記録だけは今の値段で計算する（sales_log.py）。
個数は期間ごとの CSV（<期間>.csv）、時間別売上・売上の推移・会計件数はログから計算する。

予想売上（閉店時の売上の見込み）は、営業時間のうちどれだけ過ぎたかと、
同じ営業時間の前の期間がその時点までに 1 日の売上の何割を売っていたかから出す（_forecast）。

ログでは 1 回の会計が
    CommitOrder（PC での確定）または SquareImport（Square の会計の取り込み）
    Add / Sub（商品ごとの増減。Location が期間名）
の順に書かれるので、その直後に続く Add/Sub をまとめて 1 件として数える。
"""
from collections import defaultdict
from datetime import date, datetime, timedelta

import sales_log

COMMIT_ACTIONS = ("CommitOrder", "SquareImport")
DEFAULT_OPEN = ("09:00", "18:00")   # 営業時間が設定されていない期間の時間帯（時間別売上はこの範囲を必ず表示する）
MAX_TREND_POINTS = 80
MIX_MAX_ITEMS = 5         # これより多い商品は「その他」にまとめる
FORECAST_MIN_ELAPSED = timedelta(minutes=30)   # 開店直後は予想がぶれるので出さない
FORECAST_MIN_SHARE = 0.05  # 前の期間がこの割合も売っていない時点では、その売れ方を使わない


def build(dm, term=None, current_mode=None, now=None):
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
    hours = open_hours(settings, term)
    hourly, trend, transactions = _scan_log(dm.log_path, term, prices, hours)

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
        "forecast": _forecast(settings, dm.log_path, prices, terms, term, sales, sales_by_term, now or datetime.now()),
        "prev_term": prev_term,
        "change": change,
        "hourly": hourly,
        "open": {"start": hours[0], "end": hours[1]},   # 営業時間（時間別売上の見出しに出す）
        "peak": peak,
        "mix": mix,
        "pay": pay,
        "trend": trend,
    }


def _term_date(settings, term):
    try:
        return date.fromisoformat(str((settings.get("dates") or {}).get(term, "")))
    except ValueError:
        return None


def _open_window(settings, term, day):
    """その日の開店・閉店の日時"""
    start, end = open_hours(settings, term)
    to_dt = lambda hm: datetime.combine(day, datetime.strptime(hm, "%H:%M").time())
    return to_dt(start), to_dt(end)


def _forecast(settings, log_path, prices, terms, term, sales, sales_by_term, now):
    """閉店時の売上の予想 {"status", "value", "basis"}。

    status: "live"（営業中）/ "before"（開店前）/ "closed"（営業終了。value は確定した売上）/ "unknown"（日付が未設定）
    basis:  予想に使った前の期間の名前、または "pace"（今のペースが閉店まで続いた場合）
    """
    day = _term_date(settings, term)
    if day is None:
        return {"status": "unknown", "value": None, "basis": None}
    open_at, close_at = _open_window(settings, term, day)
    if now < open_at:
        return {"status": "before", "value": None, "basis": None}
    if now >= close_at or close_at <= open_at:
        return {"status": "closed", "value": sales, "basis": None}

    elapsed = now - open_at
    if elapsed < FORECAST_MIN_ELAPSED or sales <= 0:
        return {"status": "live", "value": None, "basis": None}
    progress = elapsed / (close_at - open_at)

    # 同じ営業時間で売上のある、いちばん近い前の期間の売れ方を使う
    hours = open_hours(settings, term)
    earlier = [t for t in terms[:terms.index(term)]
               if sales_by_term.get(t, 0) > 0 and open_hours(settings, t) == hours and _term_date(settings, t)]
    if earlier:
        ref = earlier[-1]
        ref_open, ref_close = _open_window(settings, ref, _term_date(settings, ref))
        until = ref_open + (ref_close - ref_open) * progress
        points = _term_points(log_path, prices, ref)
        total = sum(a for _, a in points)
        share = sum(a for dt, a in points if dt <= until) / total if total > 0 else 0
        if share >= FORECAST_MIN_SHARE:
            return {"status": "live", "value": max(sales, round(sales / share)), "basis": ref}

    return {"status": "live", "value": max(sales, round(sales / progress)), "basis": "pace"}


def _term_points(log_path, prices, term):
    """期間の売上の記録 [(日時, 金額)]。リセットがあればそこまでの分は使わない（term_amounts と同じ扱い）"""
    points = []
    for row in sales_log.read_rows(log_path):
        if len(row) >= 7 and ((row[4] == "ResetData" and row[5].replace(".csv", "") == term)
                              or row[4] == "Factory Reset"):
            points = []
            continue
        e = sales_log.parse_count_row(row)
        if e is None or e["term"] != term or e["ptype"] not in sales_log.PTYPES:
            continue
        try:
            points.append((sales_log.row_time(e), sales_log.amount_of(e, prices)))
        except ValueError:
            continue
    return points


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
        qty = sum(counts.get(name, {}).values())
        amount = sum(term_amounts.get(name, {}).values())
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
    """レジに記録した売上を、現金・PayPay（手入力）・Square の枠に分けた金額"""
    term_amounts = amounts.get(term, {})
    return {
        "cash": sum(a.get("cash", 0) for a in term_amounts.values()),
        "paypay": sum(a.get("pp", 0) for a in term_amounts.values()),
        "square": sum(a.get("paypay", 0) for a in term_amounts.values()),
    }


def open_hours(settings, term):
    """期間の営業時間 ("HH:MM", "HH:MM")。設定されていなければ DEFAULT_OPEN"""
    h = (settings.get("hours") or {}).get(term) or {}
    return (h.get("start") or DEFAULT_OPEN[0], h.get("end") or DEFAULT_OPEN[1])


def _hour_range(start, end):
    """営業時間に含まれる「何時台」の範囲（18:20〜21:00 なら 18〜20 時台）"""
    sh, _ = map(int, start.split(":"))
    eh, em = map(int, end.split(":"))
    last = eh if em else eh - 1
    return sh, max(sh, last)


def _scan_log(log_path, term, prices, hours=DEFAULT_OPEN):
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

    hours = list(hourly) + list(_hour_range(*hours))
    hourly_list = [{"hour": h, "amount": hourly.get(h, 0)} for h in range(min(hours), max(hours) + 1)]
    return hourly_list, _downsample(points), transactions


def _downsample(points):
    if len(points) > MAX_TREND_POINTS:
        step = len(points) / MAX_TREND_POINTS
        points = [points[int(i * step)] for i in range(MAX_TREND_POINTS - 1)] + [points[-1]]
    return [{"t": dt.strftime("%H:%M"), "v": v} for dt, v in points]
