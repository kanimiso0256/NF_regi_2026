// register.js — ブラウザ版レジの画面切り替えとレジ画面の動き
// 売上の計算・保存はサーバー側（register_state.py）が行い、ここでは表示と未確定の入力（ドラフト）だけを扱う。
// ダッシュボードは dashboard.js、設定画面は settings.js。
"use strict";

const PTYPES = ["cash", "paypay"];
const PTYPE_JP = { cash: "現金", paypay: "Square" };   // キーは過去の CSV と合わせて "paypay" のまま
const POLL_MS = 1000;

const ui = {
    view: null,
    state: null,        // サーバーから受け取った最新の状態
    drafts: {},         // 商品名 → { cash, paypay }（未確定の入力）
    modal: null,        // 開いているモーダル { actions, onKey }
    cardsKey: "",       // 商品の並びが変わったときだけカードを作り直すための目印
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
const VIEWS = ["dashboard", "register", "settings"];

function showView(name) {
    $("view-login").hidden = name !== "login";
    $("app").hidden = name === "login";
    for (const v of VIEWS) $(`view-${v}`).hidden = v !== name;
    for (const b of document.querySelectorAll("[data-nav]")) {
        b.classList.toggle("active", b.dataset.nav === name);
    }
    ui.view = name;
}

// サイドバーの Dashboard / Register / Settings
async function navigate(target) {
    if (ui.view === "settings" && target !== "settings" && !(await confirmLeaveSettings())) return;
    if (target === "dashboard") await openDashboard();
    else if (target === "register") await openRegister();
    else if (target === "settings") await openSettings();
}

function applyState(s) {
    ui.state = s;
    $("side-user").textContent = s.terminal_user;
}

async function init() {
    bindEvents();
    bindSettingsEvents();
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
        enterRegister(true);
    } else {
        await openDashboard();
    }
    setInterval(poll, POLL_MS);
    setInterval(() => ui.view === "dashboard" && refreshDashboard(), DASH_POLL_MS);
}

async function poll() {
    if (!ui.state?.logged_in) return;
    try {
        applyState(await api("/pc/api/state"));
    } catch {
        return;
    }
    if (ui.view !== "register") return;
    if (!ui.state.active) {
        // ほかの端末などで販売が終了されたとき
        if (!$("reg-body").hidden) {
            closeModal();
            showRegIdle();
        }
        return;
    }
    renderRegister();
}

// ---------- ログイン ----------
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

// ---------- レジ上部の期間タブ ----------
// Register を開く。販売中ならレジ画面、そうでなければ「タブから選ぶ」案内を出す
async function openRegister() {
    await loadRegTerms();
    if (ui.state.active) enterRegister();
    else showRegIdle();
}

// 期間の一覧（Settings での「レジで選択可」も含む）をサーバーから読み直す
async function loadRegTerms() {
    try {
        ui.regTerms = (await api("/pc/api/dashboard")).terms;
    } catch {
        ui.regTerms = ui.regTerms || [];
    }
    ui.regTabsKey = "";
    renderRegTabs();
}

function renderRegTabs() {
    const terms = ui.regTerms || [];
    const current = ui.state.active ? ui.state.mode : null;
    const key = current + "|" + JSON.stringify(terms);
    if (key === ui.regTabsKey) return;
    ui.regTabsKey = key;
    const tab = (t) => `
        <button class="tab tab-${t.kind} ${t.name === current ? "active" : ""}" data-reg-term="${esc(t.name)}"
            ${t.enabled ? "" : `disabled title="Settings で「レジで選択可」にすると選べます"`}>${esc(t.name)}</button>`;
    const normal = terms.filter((t) => t.kind === "normal");
    const special = terms.filter((t) => t.kind !== "normal");
    $("reg-tabs").innerHTML = normal.map(tab).join("")
        + (special.length ? `<span class="tab-sep"></span>${special.map(tab).join("")}` : "");
}

function showRegIdle() {
    $("reg-idle").hidden = false;
    $("reg-body").hidden = true;
    renderRegTabs();
    showView("register");
}

async function selectRegTerm(mode) {
    const t = (ui.regTerms || []).find((x) => x.name === mode);
    if (!t || !t.enabled) return;
    const s = ui.state;
    if (!s.active) {
        await startOperation(mode);
        return;
    }
    if (mode === s.mode) return;
    // 販売中の切り替えは担当者をそのまま引き継ぐ。消えてしまう入力があるときだけ確認する
    if (draftRows().length) {
        const ok = await confirmModal(
            "期間の切り替え",
            `「${s.mode}」から「${mode}」に切り替えますか？\n未確定の入力は削除されます。`,
            "切り替える", false,
        );
        if (!ok) return;
    }
    try {
        applyState(await api("/pc/api/start", { mode, operator: s.operator }));
        enterRegister(true);
    } catch (e) {
        alert(e.message);
    }
}

// 担当者はログインした人（端末使用者）。途中で替わるときはレジ画面の「変更」から
async function startOperation(mode) {
    try {
        applyState(await api("/pc/api/start", { mode, operator: ui.state.terminal_user }));
        enterRegister(true);
    } catch (e) {
        alert(e.message);
    }
}

// ---------- レジ画面 ----------
// fresh: 販売を始めたとき（またはページを開き直したとき）。ほかの画面から戻ってきただけなら、未確定の入力は残す
function enterRegister(fresh = false) {
    if (fresh) {
        ui.drafts = {};
    }
    ui.cardsKey = "";
    $("reg-idle").hidden = true;
    $("reg-body").hidden = false;
    if (!ui.regTerms) loadRegTerms();
    showView("register");
    renderRegister();
    resetRegSquare();
}

function renderRegister() {
    const s = ui.state;
    renderRegTabs();
    $("mode-name").textContent = s.mode;
    // 期間名（テスト・調整）はすぐ下に大きく出ているので、注意だけを短く出す
    $("mode-note").textContent = s.is_test ? "保存されません" : s.allow_negative ? "マイナス入力可" : "";
    $("mode-note").dataset.kind = s.is_test ? "test" : s.allow_negative ? "adjust" : "";
    $("operator-name").textContent = s.operator;
    $("total-term").textContent = yen(s.totals.term);
    $("total-cumulative").textContent = yen(s.totals.cumulative);
    $("total-total").textContent = yen(s.totals.total);
    document.documentElement.style.setProperty("--card-width", `${s.card_width}px`);
    renderCards();
    updateCards();
    updateDraftBar();
    onRegisterSquareState();
}

async function confirmExit() {
    const ok = await confirmModal(
        "モード終了",
        "販売を終了しますか？\n未確定の入力は削除されます",
        "終了する",
    );
    if (!ok) return;
    try {
        applyState(await api("/pc/api/exit", {}));
        showRegIdle();
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
function renderCards() {
    const key = ui.state.mode + "\n" + ui.state.items.map((it) => it.name).join("\n");
    if (key === ui.cardsKey) return;
    ui.cardsKey = key;
    $("cards").innerHTML = ui.state.items.map(cardHtml).join("")
        || `<p class="empty">表示する商品がありません（管理者設定 → メニュー管理で登録してください）</p>`;
}

function cardHtml(it) {
    const k = it.keys || ["", "", "", "", "", ""];
    // 支払い方法ごとに 1 段：見出しと個数、その下に －・テンキー・＋ のボタン
    const row = (ptype, [kAdd, kPad, kSub]) => `
        <div class="pay-row pay-${ptype}">
            <span class="pay-title">${PTYPE_JP[ptype]}</span>
            <span class="pay-num">
                <span class="pay-count" data-f="count-${ptype}">0</span>
                <span class="pay-draft" data-f="draft-${ptype}"></span>
            </span>
            <div class="pay-btns">
                <button class="pay-btn pay-sub" data-act="sub" data-ptype="${ptype}">－<kbd>${esc(kSub)}</kbd></button>
                <button class="pay-btn pay-pad" data-act="pad" data-ptype="${ptype}">⌨<kbd>${esc(kPad)}</kbd></button>
                <button class="pay-btn pay-add" data-act="add" data-ptype="${ptype}">＋<kbd>${esc(kAdd)}</kbd></button>
            </div>
        </div>`;
    return `
        <article class="card">
            <div class="card-head">
                <div class="item-name" title="${esc(it.name)}">${esc(it.name)}</div>
                <div class="item-price"><span class="yen">¥</span>${it.price.toLocaleString()}</div>
            </div>
            <div class="card-stats">
                <div><span>Term</span><b data-f="term">¥0</b></div>
                <div><span>総合</span><b data-f="total">¥0</b></div>
            </div>
            <div class="pay-rows">${row("cash", k.slice(0, 3))}${row("paypay", k.slice(3, 6))}</div>
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
        el.classList.toggle("has-draft", Boolean(d.cash || d.paypay));
    });
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
        refreshRegSquare();
    });
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

// ボタンにキーの表示は付けないが、Enter で OK・Esc でキャンセルが効く
function confirmModal(title, message, okLabel, danger = false) {
    return new Promise((resolve) => {
        const done = (v) => { closeModal(); resolve(v); };
        openModal(`
            <h2>${esc(title)}</h2>
            <p class="modal-message">${esc(message)}</p>
            <div class="modal-actions">
                <button class="btn btn-ghost" data-modal="cancel">キャンセル</button>
                <button class="btn ${danger ? "btn-danger" : "btn-primary"}" data-modal="ok">${esc(okLabel)}</button>
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
                <button class="btn btn-ghost" data-modal="cancel">キャンセル</button>
                <button class="btn btn-primary" data-modal="ok">OK</button>
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
            <button class="btn btn-ghost" data-modal="cancel">戻る</button>
            <button class="btn btn-primary" data-modal="ok">確定</button>
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
            <button class="btn btn-ghost" data-modal="cancel">閉じる</button>
            <button class="btn btn-primary" data-modal="ok">追加</button>
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

// ---------- キーボード操作 ----------
function onKeyDown(e) {
    if (e.isComposing || e.keyCode === 229) return;  // 日本語入力の変換中は無視
    if (ui.modal) {
        handleModalKey(e);
        return;
    }
    if (ui.view !== "register" || !ui.state.active || $("reg-body").hidden) return;
    if (e.target.matches("input, textarea") || e.ctrlKey || e.altKey || e.metaKey) return;

    const k = e.key;
    const handlers = {
        Enter: openPcSummary,
        F1: () => moveDrafts("cash"),
        F2: () => moveDrafts("paypay"),
        Escape: confirmExit,
        Backspace: clearDrafts,
        Delete: clearDrafts,
    };
    if (handlers[k]) {
        e.preventDefault();
        handlers[k]();
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

function bindEvents() {
    $("login-btn").addEventListener("click", doLogin);
    $("login-name").addEventListener("keydown", (e) => {
        if (e.key === "Enter" && !e.isComposing && e.keyCode !== 229) doLogin();
    });

    document.querySelector(".nav").addEventListener("click", (e) => {
        const b = e.target.closest("[data-nav]");
        if (b) navigate(b.dataset.nav);
    });

    $("dash-tabs").addEventListener("click", (e) => {
        const b = e.target.closest("[data-dash-term]");
        if (b) selectDashTerm(b.dataset.dashTerm);
    });

    $("reg-tabs").addEventListener("click", (e) => {
        const b = e.target.closest("[data-reg-term]");
        if (b && !b.disabled) selectRegTerm(b.dataset.regTerm);
    });

    document.addEventListener("click", (e) => {
        const b = e.target.closest("[data-action]");
        if (!b) return;
        const actions = {
            exit: confirmExit,
            "change-operator": changeOperator,
            commit: openPcSummary,
            "square-check": squareCheckClicked,
            "square-retry": squareRetryClicked,
            "square-unmatched": () => openUnmatched(),
        };
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
