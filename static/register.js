// register.js — ブラウザ版レジ画面の動き
// 売上の計算・保存はサーバー側（register_state.py）が行い、ここでは表示と未確定の入力（ドラフト）だけを扱う。
"use strict";

const PTYPES = ["cash", "paypay"];
const PTYPE_JP = { cash: "現金", paypay: "PayPay" };
const MOBILE_KEYS = "1234567890";
const POLL_MS = 1000;
const CONNECTION_POLL_MS = 5000;

const ui = {
    view: null,
    state: null,        // サーバーから受け取った最新の状態
    drafts: {},         // 商品名 → { cash, paypay }（未確定の入力）
    selected: -1,       // 選択中のモバイル注文
    modal: null,        // 開いているモーダル { actions, onKey }
    cardsKey: "",       // 商品の並びが変わったときだけカードを作り直すための目印
    notifsKey: "",
    notifCount: 0,
    knownNotifs: new Set(),
    connection: { online: false, url: null },
};

const $ = (id) => document.getElementById(id);
const yen = (n) => "¥" + Number(n).toLocaleString();
const esc = (s) => String(s).replace(/[&<>"']/g, (c) => (
    { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]
));

async function api(path, body) {
    const opts = body === undefined ? {} : {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
    };
    let res;
    try {
        res = await fetch(path, opts);
    } catch {
        throw new Error("サーバーに接続できません。web_main.py が起動しているか確認してください。");
    }
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.error || `エラーが発生しました (${res.status})`);
    return data;
}

// ---------- 画面切り替え ----------
function showView(name) {
    for (const v of ["login", "dashboard", "register"]) $(`view-${v}`).hidden = v !== name;
    $("statusbar").hidden = name === "login";
    ui.view = name;
}

function applyState(s) {
    ui.state = s;
    $("status-user").textContent = `Terminal : ${s.terminal_user}`;
}

async function init() {
    bindEvents();
    try {
        applyState(await api("/pc/api/state"));
    } catch (e) {
        alert(e.message);
        return;
    }
    if (!ui.state.logged_in) {
        showView("login");
        $("login-name").focus();
    } else if (ui.state.active) {
        enterRegister();
    } else {
        await openDashboard();
    }
    setInterval(poll, POLL_MS);
    pollConnection();
    setInterval(pollConnection, CONNECTION_POLL_MS);
}

async function poll() {
    if (ui.view !== "register") return;
    try {
        applyState(await api("/pc/api/state"));
    } catch {
        return;
    }
    if (!ui.state.active) {
        closeModal();
        await openDashboard();
        return;
    }
    renderRegister();
}

async function pollConnection() {
    try {
        ui.connection = await api("/pc/api/connection");
    } catch {
        ui.connection = { online: false, url: null };
    }
    $("statusbar").classList.toggle("online", ui.connection.online);
    $("status-channel").textContent = ui.connection.online ? "CHANNEL OPEN" : "CHANNEL CLOSED";
}

// ---------- ログイン・ダッシュボード ----------
async function doLogin() {
    const name = $("login-name").value.trim();
    if (!name) {
        $("login-error").textContent = "名前を入力してください";
        return;
    }
    try {
        applyState(await api("/pc/api/login", { name }));
        await openDashboard();
    } catch (e) {
        $("login-error").textContent = e.message;
    }
}

async function openDashboard() {
    const data = await api("/pc/api/dashboard");
    $("term-grid").innerHTML = data.terms.map((t) => `
        <button class="term-btn term-${t.kind}" data-term="${esc(t.name)}" ${t.enabled ? "" : "disabled"}>
            ${esc(t.name)}
        </button>`).join("");
    showView("dashboard");
}

async function startOperation(mode) {
    const operator = await promptModal("担当者入力", "レジ担当者の名前を入力してください");
    if (!operator) return;
    try {
        applyState(await api("/pc/api/start", { mode, operator }));
        enterRegister();
    } catch (e) {
        alert(e.message);
    }
}

// ---------- レジ画面 ----------
function enterRegister() {
    ui.drafts = {};
    ui.selected = -1;
    ui.cardsKey = "";
    ui.notifsKey = "";
    ui.notifCount = ui.state.notifications.length;
    ui.knownNotifs = new Set(ui.state.notifications.map((n) => n.id));
    showView("register");
    renderRegister();
}

function renderRegister() {
    const s = ui.state;
    $("mode-name").textContent = s.mode;
    $("mode-note").textContent = s.is_test ? "テスト：保存されません" : s.allow_negative ? "調整：マイナス入力可" : "";
    $("operator-name").textContent = s.operator;
    $("total-term").textContent = yen(s.totals.term);
    $("total-cumulative").textContent = yen(s.totals.cumulative);
    $("total-total").textContent = yen(s.totals.total);
    document.documentElement.style.setProperty("--card-width", `${s.card_width}px`);
    renderCards();
    updateCards();
    renderNotifications();
    updateDraftBar();
}

async function confirmExit() {
    const ok = await confirmModal(
        "モード終了",
        "ダッシュボードに戻りますか？\n・モバイル連携はこのモードで停止します\n・未処理のモバイル注文と未確定の入力は削除されます",
        "終了する",
    );
    if (!ok) return;
    try {
        applyState(await api("/pc/api/exit", {}));
        await openDashboard();
    } catch (e) {
        alert(e.message);
    }
}

async function changeOperator() {
    const name = await promptModal("担当者変更", "新しいレジ担当者の名前を入力してください");
    if (!name) return;
    try {
        applyState(await api("/pc/api/operator", { name }));
        renderRegister();
    } catch (e) {
        alert(e.message);
    }
}

// ---------- 商品カード ----------
function mobileKeyLabel(i) {
    if (i < 9) return String(i + 1);
    return i === 9 ? "0" : "-";
}

function renderCards() {
    const key = ui.state.mode + "\n" + ui.state.items.map((it) => it.name).join("\n");
    if (key === ui.cardsKey) return;
    ui.cardsKey = key;
    $("cards").innerHTML = ui.state.items.map(cardHtml).join("")
        || `<p class="empty">表示する商品がありません（管理者設定 → メニュー管理で登録してください）</p>`;
}

function cardHtml(it, i) {
    const k = it.keys || ["", "", "", "", "", ""];
    const col = (ptype, [kAdd, kPad, kSub]) => `
        <div class="pay-col pay-${ptype}">
            <div class="pay-title">${PTYPE_JP[ptype]}</div>
            <div class="pay-count" data-f="count-${ptype}">0</div>
            <div class="pay-draft" data-f="draft-${ptype}"></div>
            <button class="pay-btn pay-add" data-act="add" data-ptype="${ptype}">＋<kbd>${esc(kAdd)}</kbd></button>
            <button class="pay-btn pay-pad" data-act="pad" data-ptype="${ptype}">⌨<kbd>${esc(kPad)}</kbd></button>
            <button class="pay-btn pay-sub" data-act="sub" data-ptype="${ptype}">－<kbd>${esc(kSub)}</kbd></button>
        </div>`;
    return `
        <article class="card">
            <button class="mob-toggle" data-act="mob">Mob <span data-f="mob">OFF</span><kbd>${mobileKeyLabel(i)}</kbd></button>
            <div class="card-head">
                <div class="item-name" title="${esc(it.name)}">${esc(it.name)}</div>
                <div class="item-price">@${it.price.toLocaleString()}</div>
            </div>
            <div class="card-stats">
                <div><span>Term</span><b data-f="term">¥0</b></div>
                <div><span>総合</span><b data-f="total">¥0</b></div>
            </div>
            <div class="pay-cols">${col("cash", k.slice(0, 3))}${col("paypay", k.slice(3, 6))}</div>
            <div class="watchers" data-f="watchers"></div>
        </article>`;
}

function updateCards() {
    const cards = $("cards").children;
    ui.state.items.forEach((it, i) => {
        const el = cards[i];
        if (!el) return;
        const f = (name) => el.querySelector(`[data-f="${name}"]`);
        const d = ui.drafts[it.name] || { cash: 0, paypay: 0 };
        for (const p of PTYPES) {
            f(`count-${p}`).textContent = it.term[p];
            const badge = f(`draft-${p}`);
            badge.textContent = d[p] > 0 ? `+${d[p]}` : d[p] < 0 ? String(d[p]) : "";
            badge.className = "pay-draft" + (d[p] > 0 ? " pos" : d[p] < 0 ? " neg" : "");
        }
        f("term").textContent = yen((it.term.cash + it.term.paypay) * it.price);
        f("total").textContent = yen((it.total.cash + it.total.paypay) * it.price);
        f("mob").textContent = it.mobile_active ? "ON" : "OFF";
        f("watchers").textContent = it.watchers.length ? "🛒 " + it.watchers.join(", ") : "";
        el.classList.toggle("mobile-on", it.mobile_active);
        el.classList.toggle("has-draft", Boolean(d.cash || d.paypay));
        el.classList.toggle("watched", it.watchers.length > 0);
    });
}

async function toggleMobile(name) {
    try {
        applyState(await api("/pc/api/toggle_mobile", { name }));
        renderRegister();
    } catch (e) {
        alert(e.message);
    }
}

// ---------- 未確定の入力（ドラフト） ----------
function addDraft(name, ptype, amount) {
    const item = ui.state.items.find((it) => it.name === name);
    if (!item) return;
    const d = ui.drafts[name] || (ui.drafts[name] = { cash: 0, paypay: 0 });
    const next = d[ptype] + amount;
    if (!ui.state.allow_negative && item.term[ptype] + next < 0) return;
    d[ptype] = next;
    refreshDrafts();
}

function moveDrafts(target) {
    for (const d of Object.values(ui.drafts)) {
        const sum = d.cash + d.paypay;
        d.cash = target === "cash" ? sum : 0;
        d.paypay = target === "paypay" ? sum : 0;
    }
    refreshDrafts();
}

function clearDrafts() {
    ui.drafts = {};
    refreshDrafts();
}

function draftRows() {
    return ui.state.items.flatMap((it) => {
        const d = ui.drafts[it.name];
        if (!d) return [];
        return PTYPES.filter((p) => d[p] !== 0)
            .map((p) => ({ name: it.name, ptype: p, qty: d[p], subtotal: d[p] * it.price }));
    });
}

function refreshDrafts() {
    updateCards();
    updateDraftBar();
}

function updateDraftBar() {
    const rows = draftRows();
    const qty = rows.reduce((a, r) => a + r.qty, 0);
    const sum = rows.reduce((a, r) => a + r.subtotal, 0);
    $("draft-bar").classList.toggle("active", rows.length > 0);
    $("draft-summary").textContent = rows.length ? `未確定 ${qty}点　${yen(sum)}` : "未確定の入力はありません";
    $("commit-btn").disabled = rows.length === 0;
}

function openPcSummary() {
    const rows = draftRows();
    if (!rows.length) return;
    summaryModal("注文内容の確認", `担当: ${ui.state.operator}`, rows, async () => {
        const drafts = ui.state.items
            .filter((it) => ui.drafts[it.name])
            .map((it) => ({ name: it.name, ...ui.drafts[it.name] }));
        applyState(await api("/pc/api/commit", { drafts }));
        ui.drafts = {};
        renderRegister();
    });
}

// ---------- モバイル注文 ----------
let audioCtx = null;
function beep() {
    try {
        audioCtx = audioCtx || new AudioContext();
        const osc = audioCtx.createOscillator();
        const gain = audioCtx.createGain();
        osc.frequency.value = 880;
        gain.gain.value = 0.15;
        osc.connect(gain).connect(audioCtx.destination);
        osc.start();
        osc.stop(audioCtx.currentTime + 0.25);
    } catch {
        // 音が出せない環境では点滅だけにする
    }
}

function renderNotifications() {
    const list = ui.state.notifications;
    const fresh = list.filter((n) => !ui.knownNotifs.has(n.id));
    fresh.forEach((n) => ui.knownNotifs.add(n.id));

    // 最新の注文を選んでいた（または未選択）なら、新着に選択を移す
    const wasAtEnd = ui.selected === -1 || ui.selected >= ui.notifCount - 1;
    if (fresh.length && wasAtEnd) ui.selected = list.length - 1;
    if (ui.selected >= list.length) ui.selected = list.length - 1;
    ui.notifCount = list.length;

    const key = list.map((n) => n.id).join(",") + "|" + ui.selected;
    if (key !== ui.notifsKey) {
        ui.notifsKey = key;
        $("notify-list").innerHTML = list.map(notifHtml).join("")
            || `<p class="notif-empty">モバイルからの注文はまだありません</p>`;
        $("notify-list").children[ui.selected]?.scrollIntoView({ block: "nearest", inline: "nearest" });
    }

    const alerting = fresh.filter((n) => ui.state.notify_alert[n.ptype]);
    if (alerting.length) {
        beep();
        for (const n of alerting) {
            $("notify-list").children[list.indexOf(n)]?.classList.add("flash");
        }
    }
}

function notifHtml(n, i) {
    const qty = n.items.reduce((a, it) => a + it.amount, 0);
    const sum = n.items.reduce((a, it) => a + it.subtotal, 0);
    const text = n.items.map((it) => `${it.name}×${it.amount}`).join(", ");
    return `
        <div class="notif ${i === ui.selected ? "selected" : ""}" data-idx="${i}">
            <div class="notif-top"><b>${esc(n.user)}</b><time>${esc(n.timestamp)}</time></div>
            <div class="notif-type notif-${esc(n.ptype)}">${esc(PTYPE_JP[n.ptype] || n.ptype)}・${qty}点 ${yen(sum)}</div>
            <div class="notif-items" title="${esc(text)}">${esc(text)}</div>
            <div class="notif-actions">
                <button class="btn btn-small btn-ok" data-nact="approve">承認</button>
                <button class="btn btn-small btn-ng" data-nact="cancel">取消</button>
            </div>
        </div>`;
}

function selectNotification(i) {
    const len = ui.state.notifications.length;
    if (!len) return;
    ui.selected = Math.max(0, Math.min(len - 1, i));
    renderNotifications();
}

function approveNotification(n) {
    const rows = n.items.map((it) => ({ name: it.name, ptype: n.ptype, qty: it.amount, subtotal: it.subtotal }));
    summaryModal("モバイル注文の承認", `${n.user} さんからの注文`, rows, async () => {
        applyState(await api(`/pc/api/notifications/${encodeURIComponent(n.id)}/approve`, {}));
        renderRegister();
    });
}

async function cancelNotification(n) {
    const ok = await confirmModal("注文取消し確認", `${n.user} さんの注文を破棄しますか？\n売上は計上されません。`, "破棄する", true);
    if (!ok) return;
    try {
        applyState(await api(`/pc/api/notifications/${encodeURIComponent(n.id)}/cancel`, {}));
        renderRegister();
    } catch (e) {
        alert(e.message);
    }
}

// ---------- モーダル ----------
// actions: ボタンの data-modal 名 → 処理。Enter で ok、Esc で cancel が呼ばれる。
// onKey: それ以外のキーを処理したら true を返す。
function openModal(html, { actions = {}, onKey = null } = {}) {
    $("modal-body").innerHTML = html;
    $("modal").hidden = false;
    ui.modal = { actions, onKey };
}

function closeModal() {
    $("modal").hidden = true;
    $("modal-body").innerHTML = "";
    ui.modal = null;
}

function modalField(name) {
    return $("modal-body").querySelector(`[data-f="${name}"]`);
}

function runModalAction(name, data) {
    const fn = ui.modal?.actions[name];
    if (fn) fn(data);
}

function handleModalKey(e) {
    if (ui.modal.onKey && ui.modal.onKey(e)) return;
    if (e.key === "Enter") {
        // Enter の長押しで、開いた直後の確認画面まで確定してしまわないようにする
        if (e.repeat) return;
        e.preventDefault();
        runModalAction("ok");
    } else if (e.key === "Escape") {
        e.preventDefault();
        runModalAction("cancel");
    }
}

function confirmModal(title, message, okLabel, danger = false) {
    return new Promise((resolve) => {
        const done = (v) => { closeModal(); resolve(v); };
        openModal(`
            <h2>${esc(title)}</h2>
            <p class="modal-message">${esc(message)}</p>
            <div class="modal-actions">
                <button class="btn btn-ghost" data-modal="cancel">キャンセル <kbd>Esc</kbd></button>
                <button class="btn ${danger ? "btn-danger" : "btn-primary"}" data-modal="ok">${esc(okLabel)} <kbd>Enter</kbd></button>
            </div>`, { actions: { ok: () => done(true), cancel: () => done(false) } });
    });
}

function promptModal(title, message) {
    return new Promise((resolve) => {
        openModal(`
            <h2>${esc(title)}</h2>
            <p class="modal-message">${esc(message)}</p>
            <input class="input" data-f="input" autocomplete="off">
            <p class="error" data-f="error"></p>
            <div class="modal-actions">
                <button class="btn btn-ghost" data-modal="cancel">キャンセル <kbd>Esc</kbd></button>
                <button class="btn btn-primary" data-modal="ok">OK <kbd>Enter</kbd></button>
            </div>`, {
            actions: {
                ok: () => {
                    const v = modalField("input").value.trim();
                    if (!v) {
                        modalField("error").textContent = "名前を入力してください";
                        return;
                    }
                    closeModal();
                    resolve(v);
                },
                cancel: () => { closeModal(); resolve(null); },
            },
        });
        modalField("input").focus();
    });
}

function summaryModal(title, subtitle, rows, onConfirm) {
    const qty = rows.reduce((a, r) => a + r.qty, 0);
    const sum = rows.reduce((a, r) => a + r.subtotal, 0);
    let busy = false;
    openModal(`
        <h2>${esc(title)}</h2>
        <p class="modal-sub">${esc(subtitle)}</p>
        <table class="summary">
            <thead><tr><th>商品</th><th>支払</th><th class="num">数量</th><th class="num">小計</th></tr></thead>
            <tbody>${rows.map((r) => `
                <tr>
                    <td>${esc(r.name)}</td>
                    <td><span class="ptag ptag-${r.ptype}">${PTYPE_JP[r.ptype] || esc(r.ptype)}</span></td>
                    <td class="num">${r.qty}</td>
                    <td class="num">${yen(r.subtotal)}</td>
                </tr>`).join("")}
            </tbody>
        </table>
        <div class="summary-total"><span>合計 ${qty}点</span><strong>${yen(sum)}</strong></div>
        <p class="error" data-f="error"></p>
        <div class="modal-actions">
            <button class="btn btn-ghost" data-modal="cancel">戻る <kbd>Esc</kbd></button>
            <button class="btn btn-primary" data-modal="ok">確定 <kbd>Enter</kbd></button>
        </div>`, {
        actions: {
            ok: async () => {
                if (busy) return;
                busy = true;
                try {
                    await onConfirm();
                    closeModal();
                } catch (e) {
                    modalField("error").textContent = e.message;
                    busy = false;
                }
            },
            cancel: closeModal,
        },
    });
}

function openNumpad(it, ptype) {
    let value = "0";
    const parse = () => {
        const n = parseInt(value, 10);
        return Number.isNaN(n) ? 0 : n;
    };
    const press = (k) => {
        if (k === "C") value = "0";
        else if (k === "BS") value = value.length > 1 ? value.slice(0, -1) : "0";
        else if (k === "-") value = value.startsWith("-") ? value.slice(1) || "0" : value === "0" ? "-" : "-" + value;
        else if (value.replace("-", "").length < 5) value = value === "0" ? k : value + k;
        modalField("count").textContent = value;
        modalField("yen").textContent = yen(parse() * it.price);
    };
    const keys = ["7", "8", "9", "4", "5", "6", "1", "2", "3", "0", "-", "C"];
    openModal(`
        <div class="numpad-head numpad-${ptype}">
            <span>${PTYPE_JP[ptype]} 入力</span>
            <strong>${esc(it.name)}</strong>
            <small>単価 @${it.price.toLocaleString()}</small>
        </div>
        <div class="numpad-display">
            <strong data-f="yen">¥0</strong>
            <span>個数 <b data-f="count">0</b></span>
        </div>
        <div class="numpad-keys">
            ${keys.map((k) => `<button class="numpad-key" data-modal="press" data-key="${k}">${k}</button>`).join("")}
        </div>
        <div class="modal-actions">
            <button class="btn btn-ghost" data-modal="cancel">閉じる <kbd>Esc</kbd></button>
            <button class="btn btn-primary" data-modal="ok">追加 <kbd>Enter</kbd></button>
        </div>`, {
        actions: {
            press: (data) => press(data.key),
            ok: () => {
                const n = parse();
                closeModal();
                if (n) addDraft(it.name, ptype, n);
            },
            cancel: closeModal,
        },
        onKey: (e) => {
            if (/^[0-9-]$/.test(e.key)) {
                press(e.key);
                return true;
            }
            if (e.key === "Backspace" || e.key === "Delete") {
                e.preventDefault();
                press("BS");
                return true;
            }
            if (e.key === "c" || e.key === "C") {
                press("C");
                return true;
            }
            return false;
        },
    });
}

function openQr() {
    const c = ui.connection;
    const body = c.url
        ? `<img class="qr" src="/pc/qr.png?t=${Date.now()}" alt="接続用QRコード">
           <input class="input" readonly value="${esc(c.url)}">`
        : `<p class="error-box">⚠ チャンネルが閉じているか、ngrok の接続に失敗しています。<br>
           通信設定（ngrok の Authtoken）を確認してください。</p>`;
    openModal(`
        <h2>モバイル接続</h2>
        <p class="modal-sub">スマホで読み取ってください</p>
        ${body}
        <div class="modal-actions">
            <button class="btn btn-primary" data-modal="cancel">閉じる <kbd>Esc</kbd></button>
        </div>`, { actions: { ok: closeModal, cancel: closeModal } });
}

// ---------- キーボード操作 ----------
function onKeyDown(e) {
    if (e.isComposing || e.keyCode === 229) return;  // 日本語入力の変換中は無視
    if (ui.modal) {
        handleModalKey(e);
        return;
    }
    if (ui.view !== "register") return;
    if (e.target.matches("input, textarea") || e.ctrlKey || e.altKey || e.metaKey) return;

    const k = e.key;
    const handlers = {
        Enter: openPcSummary,
        F1: () => moveDrafts("cash"),
        F2: () => moveDrafts("paypay"),
        Escape: confirmExit,
        Backspace: backspace,
        Delete: backspace,
        ArrowLeft: () => selectNotification(ui.selected - 1),
        ArrowRight: () => selectNotification(ui.selected + 1),
        " ": () => {
            const n = ui.state.notifications[ui.selected];
            if (n) approveNotification(n);
        },
    };
    if (handlers[k]) {
        e.preventDefault();
        handlers[k]();
        return;
    }

    const mobileIdx = MOBILE_KEYS.indexOf(k);
    if (k.length === 1 && mobileIdx !== -1) {
        const it = ui.state.items[mobileIdx];
        if (it) toggleMobile(it.name);
        return;
    }

    for (const it of ui.state.items) {
        const idx = it.keys ? it.keys.indexOf(k) : -1;
        if (idx === -1) continue;
        e.preventDefault();
        const ptype = idx < 3 ? "cash" : "paypay";
        const op = idx % 3;
        if (op === 0) addDraft(it.name, ptype, 1);
        else if (op === 1) openNumpad(it, ptype);
        else addDraft(it.name, ptype, -1);
        return;
    }
}

// 未確定の入力があれば消し、なければ選択中のモバイル注文を取り消す
function backspace() {
    if (draftRows().length) {
        clearDrafts();
        return;
    }
    const n = ui.state.notifications[ui.selected];
    if (n) cancelNotification(n);
}

function bindEvents() {
    $("login-btn").addEventListener("click", doLogin);
    $("login-name").addEventListener("keydown", (e) => {
        if (e.key === "Enter" && !e.isComposing && e.keyCode !== 229) doLogin();
    });

    $("term-grid").addEventListener("click", (e) => {
        const b = e.target.closest("[data-term]");
        if (b && !b.disabled) startOperation(b.dataset.term);
    });

    document.addEventListener("click", (e) => {
        const b = e.target.closest("[data-action]");
        if (!b) return;
        const actions = { exit: confirmExit, "change-operator": changeOperator, commit: openPcSummary, qr: openQr };
        actions[b.dataset.action]?.();
    });

    $("cards").addEventListener("click", (e) => {
        const b = e.target.closest("[data-act]");
        if (!b) return;
        const idx = [...$("cards").children].indexOf(b.closest(".card"));
        const it = ui.state.items[idx];
        if (!it) return;
        const p = b.dataset.ptype;
        if (b.dataset.act === "add") addDraft(it.name, p, 1);
        else if (b.dataset.act === "sub") addDraft(it.name, p, -1);
        else if (b.dataset.act === "pad") openNumpad(it, p);
        else if (b.dataset.act === "mob") toggleMobile(it.name);
    });

    $("notify-list").addEventListener("click", (e) => {
        const el = e.target.closest(".notif");
        if (!el) return;
        const idx = Number(el.dataset.idx);
        const n = ui.state.notifications[idx];
        if (!n) return;
        const act = e.target.closest("[data-nact]")?.dataset.nact;
        if (act === "approve") approveNotification(n);
        else if (act === "cancel") cancelNotification(n);
        else selectNotification(idx);
    });

    $("modal-body").addEventListener("click", (e) => {
        const b = e.target.closest("[data-modal]");
        if (b && ui.modal) runModalAction(b.dataset.modal, b.dataset);
    });

    // クリックしたボタンにフォーカスが残ると Space/Enter で再度押されてしまうため外す
    document.addEventListener("click", (e) => e.target.closest("button")?.blur());
    document.addEventListener("keydown", onKeyDown);
}

init();
