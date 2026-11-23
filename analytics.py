# analytics.py
"""ダッシュボード用の集計。

売上金額は current_log.csv に記録した金額（売れたときの値段）で出す（レジ画面の「Term」と同じ）。
金額の書かれていない古い記録だけは今の値段で計算する（sales_log.py）。
個数は期間ごとの CSV（<期間>.csv）、時間別売上・売上の推移・会計件数はログから計算する。

予想売上（閉店時の売上の見込み）は、開店時刻が同じ前の期間すべて（4日目なら 1〜3日目）が、
同じ時刻までに閉店時刻までの売上の何割を売っていたか（の平均）から出す（_forecast）。
前の期間より閉店が遅い日は、はみ出た時間を前の期間の閉店前 2 時間のペースで延ばして考える。

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
FORECAST_MIN_SHARE = 0.05  # 前の期間が平均でこの割合も売っていない時刻（開店直後）は、予想を出さない
FORECAST_TAIL = timedelta(hours=2)   # 閉店が遅い日に延ばすときに使う、前の期間の閉店前の時間


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
    hourly, trend, transactions, _detail = _scan_log(dm.log_path, term, prices, hours)

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
    basis:  予想に使った前の期間の名前のリスト、または "pace"（今のペースが閉店まで続いた場合）
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

    # 開店時刻が同じで売上のある前の期間すべて（4日目なら 1〜3日目）の売れ方を使う。
    # 期間ごとに「今の時刻までに、今日の閉店時刻までの売上の何割を売っていたか」を出し、その平均で割る（どの日も同じ重み）
    start = open_hours(settings, term)[0]
    earlier = [t for t in terms[:terms.index(term)]
               if sales_by_term.get(t, 0) > 0 and open_hours(settings, t)[0] == start and _term_date(settings, t)]
    shares = {}
    for ref in earlier:
        ref_day = _term_date(settings, ref)
        ref_curve = _cumulative_curve(_term_points(log_path, prices, ref), *_open_window(settings, ref, ref_day))
        at_close = ref_curve(datetime.combine(ref_day, close_at.time()))
        if at_close > 0:
            shares[ref] = ref_curve(datetime.combine(ref_day, now.time())) / at_close
    if shares:
        share = sum(shares.values()) / len(shares)
        # 前の期間がまだほとんど売っていない時刻（開店直後）は、予想がぶれるので出さない
        value = max(sales, round(sales / share)) if share >= FORECAST_MIN_SHARE else None
        return {"status": "live", "value": value, "basis": list(shares)}

    return {"status": "live", "value": max(sales, round(sales / progress)), "basis": "pace"}


def _cumulative_curve(points, ref_open, ref_close):
    """時刻 → その時刻までの累計売上。閉店後の時刻は、閉店前 FORECAST_TAIL のペースが続いたとして延ばす"""
    tail_from = max(ref_open, ref_close - FORECAST_TAIL)
    tail_hours = (ref_close - tail_from).total_seconds() / 3600
    tail_rate = sum(a for dt, a in points if tail_from < dt <= ref_close) / tail_hours if tail_hours else 0

    def curve(t):
        cum = sum(a for dt, a in points if dt <= min(t, ref_close))
        if t > ref_close:
            cum += max(0, tail_rate) * (t - ref_close).total_seconds() / 3600
        return cum
    return curve


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
    """時間別売上・売上の推移・会計件数と、時間ごとの詳細 {"tx": {時: 会計件数}, "items": {時: {商品名: 個数}}}"""
    hourly = defaultdict(int)
    points = []          # (時刻, 累計売上)
    running = 0
    transactions = 0
    tx_by_hour = defaultdict(int)
    items_by_hour = defaultdict(lambda: defaultdict(int))
    commit = None        # 処理中の会計 {"loc": 期間, "qty": 個数の合計, "hour": 最初の商品の時}

    def close_commit():
        nonlocal transactions, commit
        # 取消だけの確定（個数がマイナス）は会計として数えない
        if commit and commit["loc"] == term and commit["qty"] > 0:
            transactions += 1
            tx_by_hour[commit["hour"]] += 1
        commit = None

    for row in sales_log.read_rows(log_path):
        if len(row) < 7:
            continue
        action = row[4]
        if action not in sales_log.COUNT_ACTIONS:
            close_commit()
            if action in COMMIT_ACTIONS:
                commit = {"loc": None, "qty": 0, "hour": None}
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
                commit["hour"] = dt.hour
            if commit["loc"] == e["term"]:
                commit["qty"] += e["qty"]

        if e["term"] != term:
            continue
        amount = sales_log.amount_of(e, prices)
        hourly[dt.hour] += amount
        items_by_hour[dt.hour][e["name"]] += e["qty"]
        running += amount
        points.append((dt, running))
    close_commit()

    hours = list(hourly) + list(_hour_range(*hours))
    hourly_list = [{"hour": h, "amount": hourly.get(h, 0)} for h in range(min(hours), max(hours) + 1)]
    detail = {"tx": dict(tx_by_hour), "items": {h: dict(v) for h, v in items_by_hour.items()}}
    return hourly_list, _downsample(points), transactions, detail


def hourly_detail(dm, term):
    """時間別売上の詳細（ダッシュボードの「時間別売上」を押したときのポップアップ用）。

    時間ごとの売上・会計件数・商品別の個数と、開店時刻が同じ前の期間すべて（4日目なら 1〜3日目）の
    同じ時間の売上の平均（compare）を返す。比べられる期間がなければ compare は None
    """
    settings = dm.load_settings()
    terms = settings.get("terms", [])
    if term not in terms:
        return {"term": None}
    prices = {m["name"]: int(m.get("price", 0)) for m in settings.get("menu", [])}
    hourly, _trend, _tx, detail = _scan_log(dm.log_path, term, prices, open_hours(settings, term))

    start = open_hours(settings, term)[0]
    refs = []
    for t in terms[:terms.index(term)]:
        if open_hours(settings, t)[0] != start:
            continue
        ref_hourly = _scan_log(dm.log_path, t, prices, open_hours(settings, t))[0]
        if any(h["amount"] for h in ref_hourly):
            refs.append((t, {h["hour"]: h["amount"] for h in ref_hourly}))
    compare = None
    if refs:
        compare = {
            "terms": [t for t, _ in refs],
            "hourly": {h["hour"]: round(sum(r.get(h["hour"], 0) for _, r in refs) / len(refs)) for h in hourly},
        }

    menu_order = [m["name"] for m in sorted(settings.get("menu", []), key=lambda m: m.get("order", 9999))]
    sold = {name for items in detail["items"].values() for name, q in items.items() if q}
    items = [n for n in menu_order if n in sold] + sorted(sold - set(menu_order))
    return {
        "term": term,
        "items": items,   # 表の列（メニューの順。この期間に売れたものだけ）
        "rows": [{
            "hour": h["hour"],
            "amount": h["amount"],
            "transactions": detail["tx"].get(h["hour"], 0),
            "items": detail["items"].get(h["hour"], {}),
        } for h in hourly],
        "compare": compare,
    }


def _downsample(points):
    if len(points) > MAX_TREND_POINTS:
        step = len(points) / MAX_TREND_POINTS
        points = [points[int(i * step)] for i in range(MAX_TREND_POINTS - 1)] + [points[-1]]
    return [{"t": dt.strftime("%H:%M"), "v": v} for dt, v in points]
