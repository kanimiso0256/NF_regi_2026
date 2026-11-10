// square.js — Square 連携の画面（レジ上部の「Square」欄・ダッシュボードの「Square 照合」・取り込めなかった会計）
//
// 自動取り込みがオンのときは、Square アプリで商品を選んで会計した分をサーバー（register_state.py）が
// 15 秒ごとに取り込み、レジの個数に足す。ここではその状態と、
// Square で実際に決済された金額との照合（差額 = Square 実績 − レジの記録）を表示する。
"use strict";

const SQ_REG_POLL_MS = 15000;   // レジ画面での照合の自動更新の間隔（サーバー側でも 30 秒は取り直さない）
const TOAST_MS = 4000;

const sq = {
    dashBusy: false,
    regBusy: false,
    dashData: null,     // ダッシュボードで表示中の照合結果
    regData: null,      // レジ画面で表示中の照合結果
    lastImportKey: null,
};

function squareUrl(term, refresh) {
    const q = new URLSearchParams();
    if (term) q.set("term", term);
    if (refresh) q.set("refresh", "1");
    return "/pc/api/square/reconcile?" + q;
}

const signedYen = (n) => (n > 0 ? "+" : n < 0 ? "−" : "") + yen(Math.abs(n));

// 差額の説明。0 なら「一致」
function diffLabel(diff) {
    if (diff === 0) return "一致";
    return `差 ${signedYen(diff)}`;
}

function diffTitle(diff) {
    if (diff > 0) return "Square で決済された金額のほうが多い（取り込めなかった会計、レジとの価格の違い、手入力の漏れなど）";
    if (diff < 0) return "レジの記録のほうが多い（Square の枠への手入力の重複、価格の違いなど）";
    return "レジの記録と Square の決済額が一致しています";
}

// 自動取り込みの状態の説明
function syncLabel(s) {
    if (!s || s.state === "off") return "";
    if (s.state === "error") return `取り込みエラー：${s.message}`;
    if (s.state === "paused") return `自動取り込み：停止中（${s.message}）`;
    const last = s.last_import ? `・${s.last_import.time} に ${s.last_import.orders}件 取り込み` : "";
    return `自動取り込み：オン${last}`;
}

// ---------- ダッシュボード ----------
async function refreshDashSquare(refresh = false) {
    const term = dash.term;
    if (!term || sq.dashBusy) return;
    sq.dashBusy = true;
    if (refresh) $("dash-square-body").classList.add("loading");
    try {
        if (refresh) await api("/pc/api/square/sync", {});
        const r = await api(squareUrl(term, refresh));
        if (r.term === dash.term) {
            sq.dashData = r;
            renderDashSquare(r);
            renderPayMix();
        }
    } catch (e) {
        $("dash-square-body").innerHTML = `<p class="sq-error">${esc(e.message)}</p>`;
    } finally {
        sq.dashBusy = false;
        $("dash-square-body").classList.remove("loading");
    }
}

function renderDashSquare(r) {
    const body = $("dash-square-body");
    if (!r.configured) {
        body.innerHTML = `<p class="sq-note">Settings で Square のアクセストークンを設定すると、Square アプリの会計を取り込んで照合できます。</p>`;
        return;
    }
    const kpi = (label, value, cls = "") => `
        <div><span class="kpi-label">${label}</span><strong class="kpi kpi-s ${cls}">${value}</strong></div>`;
    const diffCls = r.diff === null ? "" : r.diff === 0 ? "up" : "down";
    const kpis = kpi("レジの記録", yen(r.register))
        + kpi("Square 実績", r.square === null ? "—" : yen(r.square))
        + `<div title="${r.diff === null ? "" : diffTitle(r.diff)}">
               <span class="kpi-label">差額</span>
               <strong class="kpi kpi-s ${diffCls}">${r.diff === null ? "—" : diffLabel(r.diff)}</strong>
           </div>`
        + kpi("決済件数", r.count === null ? "—" : r.count.toLocaleString() + "件");

    // 複数の日にまたがる期間は日ごとの内訳も出す
    const days = r.days.length > 1 ? `
        <table class="sq-days">
            <thead><tr><th>日付</th><th>レジ</th><th>Square</th><th>差額</th></tr></thead>
            <tbody>${r.days.map((d) => `
                <tr>
                    <td>${esc(dayLabel(d.date))}</td>
                    <td>${yen(d.register)}</td>
                    <td>${d.square === null ? "—" : yen(d.square)}</td>
                    <td class="${d.diff === null ? "" : d.diff === 0 ? "up" : "down"}">${d.diff === null ? "—" : diffLabel(d.diff)}</td>
                </tr>`).join("")}</tbody>
        </table>` : "";

    const env = r.environment === "sandbox" ? "（サンドボックス）" : "";
    const lines = [];
    const failed = Boolean(r.error) || r.sync?.state === "error";
    if (r.error) lines.push(`<span class="sq-error">${esc(r.error)}</span>`);
    else if (r.days.length) {
        lines.push(`${esc(r.checked_at)} 時点${env}`);
        // 自動取り込みがオフだと会計がどの期間のものか分からないので、その日の決済をすべて数えている
        if (r.scope === "day") lines.push("Square 実績はその日の全決済");
    }
    else lines.push(`この期間の記録はまだありません${env}`);
    const sync = syncLabel(r.sync);
    if (sync) lines.push(`<span class="${r.sync.state === "error" ? "sq-error" : ""}">${esc(sync)}</span>`);
    const unmatched = r.unmatched?.length ? `
        <button class="btn btn-small sq-unmatched-btn" data-action="square-unmatched">
            取り込めなかった会計 ${r.unmatched.length}件
        </button>` : "";

    const retry = failed ? `<button class="btn btn-ghost btn-small" data-action="square-retry">再試行</button>` : "";

    body.innerHTML = `<div class="sq-kpis">${kpis}</div>${days}
        <div class="sq-foot"><p class="sq-meta">${lines.join("・")}</p>${retry}${unmatched}</div>`;
}

function dayLabel(iso) {
    const d = new Date(iso + "T00:00:00");
    return `${d.getMonth() + 1}/${d.getDate()}（${"日月火水木金土"[d.getDay()]}）`;
}

// ---------- レジ上部の「Square」欄 ----------
async function refreshRegSquare(refresh = false) {
    if (ui.view !== "register" || !ui.state?.active || sq.regBusy) return;
    const term = ui.state.mode;
    sq.regBusy = true;
    try {
        if (refresh) applyState(await api("/pc/api/square/sync", {}));
        const r = await api(squareUrl(term, refresh));
        if (ui.state.active && r.term === ui.state.mode) {
            sq.regData = r;
            renderRegSquare();
        }
    } catch {
        // 次の自動更新で再試行する
    } finally {
        sq.regBusy = false;
    }
}

// 照合の結果（15 秒ごと）と、取り込みの状態（毎秒の状態取得に含まれる）を合わせて表示する
function renderRegSquare() {
    const r = sq.regData, s = ui.state?.square;
    const box = $("sq-check"), label = $("sq-label"), actual = $("sq-actual"), line = $("sq-diff");
    const auto = s && s.state !== "off";
    label.textContent = auto ? "Square 自動取込" : "Square 実績";
    line.className = "sq-diff";
    if (!r) return;
    if (!r.configured) {
        actual.textContent = "未設定";
        line.textContent = "Settings で設定";
        box.title = "Settings → Square 連携 でアクセストークンを設定してください";
        return;
    }
    actual.textContent = r.error ? "—" : yen(r.square);

    const unmatched = s?.unmatched || 0;
    let text, cls, title;
    if (s?.state === "error") {
        [text, cls, title] = ["取り込みエラー・再試行", "ng", s.message + "\nクリックで再試行"];
    } else if (unmatched) {
        [text, cls, title] = [`未取込 ${unmatched}件・確認`, "ng", "メニューにない商品や、金額だけ打った会計があります。クリックで確認"];
    } else if (r.error) {
        [text, cls, title] = ["取得できません・再試行", "ng", r.error + "\nクリックで再試行"];
    } else if (s?.state === "paused") {
        [text, cls, title] = ["取り込み停止中", "", s.message];
    } else {
        [text, cls, title] = [`レジ ${yen(r.register)}・${diffLabel(r.diff)}`, r.diff === 0 ? "ok" : "ng", diffTitle(r.diff)];
    }
    line.textContent = text;
    if (cls) line.classList.add(cls);
    box.title = `${title}\n${syncLabel(s) || (r.checked_at ? r.checked_at + " 時点" : "")}`.trim();
    box.classList.toggle("actionable", Boolean(unmatched || r.error || s?.state === "error"));
}

// レジ画面の毎秒の更新から呼ぶ。新しく取り込まれたらお知らせを出し、照合も取り直す
function onRegisterSquareState() {
    const last = ui.state?.square?.last_import;
    const key = last ? JSON.stringify(last) : "";
    if (sq.lastImportKey !== null && key && key !== sq.lastImportKey) {
        showToast(`Square から ${last.orders}件（${last.qty}点）取り込みました`);
        refreshRegSquare();
    }
    sq.lastImportKey = key;
    renderRegSquare();
}

// レジ画面を開いたとき・期間が変わったとき
function resetRegSquare() {
    sq.regData = null;
    $("sq-actual").textContent = "—";
    $("sq-diff").textContent = "";
    $("sq-diff").className = "sq-diff";
    renderRegSquare();
    refreshRegSquare();
}

// レジ上部の「Square」欄：取り込めなかった会計があれば一覧を開き、エラーなら再試行する。ふだんは何もしない
function squareCheckClicked() {
    const s = ui.state?.square;
    if (s?.unmatched) openUnmatched(ui.state.mode);
    else if (s?.state === "error" || sq.regData?.error) refreshRegSquare(true);
}

// ダッシュボードの「再試行」（Square につながらなかったとき）
function squareRetryClicked() {
    refreshDashSquare(true);
}

// ---------- 取り込めなかった会計 ----------
async function openUnmatched(term = ui.view === "dashboard" ? dash.term : ui.state?.mode) {
    let r;
    try {
        r = await api(squareUrl(term));
    } catch (e) {
        alert(e.message);
        return;
    }
    const list = r.unmatched || [];
    const multiDay = new Set(list.map((u) => u.date)).size > 1;
    const rows = list.map((u) => `
        <tr>
            <td>${multiDay ? esc(dayLabel(u.date)) + " " : ""}${esc(u.time)}</td>
            <td>${esc(u.name)}</td>
            <td class="num">${u.qty}</td>
            <td class="num">${yen(u.amount)}</td>
        </tr>`).join("");
    openModal(`
        <h2>取り込めなかった会計（${esc(term)}）</h2>
        <p class="modal-message">Square アプリで、レジのメニューにない商品を選んだか、金額だけを打った会計です。
必要ならレジで手入力し、済んだら「確認済みにする」を押してください。</p>
        ${list.length ? `
        <table class="summary">
            <thead><tr><th>時刻</th><th>内容</th><th class="num">数量</th><th class="num">金額</th></tr></thead>
            <tbody>${rows}</tbody>
        </table>` : `<p class="muted">ありません</p>`}
        <p class="error" data-f="error"></p>
        <div class="modal-actions">
            <button class="btn btn-ghost" data-modal="cancel">閉じる</button>
            ${list.length ? `<button class="btn btn-primary" data-modal="resolve">確認済みにする</button>` : ""}
        </div>`, {
        actions: {
            ok: closeModal,
            cancel: closeModal,
            resolve: async () => {
                try {
                    await api("/pc/api/square/resolve", { term });
                    closeModal();
                    if (ui.view === "dashboard") {
                        refreshDashSquare();
                    } else {
                        applyState(await api("/pc/api/state"));
                        renderRegSquare();
                    }
                } catch (e) {
                    modalField("error").textContent = e.message;
                }
            },
        },
    });
}

// ---------- お知らせ（画面下に数秒だけ出る） ----------
function showToast(message) {
    const el = document.createElement("div");
    el.className = "toast";
    el.textContent = message;
    document.body.append(el);
    setTimeout(() => el.classList.add("hide"), TOAST_MS);
    setTimeout(() => el.remove(), TOAST_MS + 400);
}

setInterval(() => refreshRegSquare(), SQ_REG_POLL_MS);
