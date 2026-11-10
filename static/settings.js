// settings.js — 設定画面（期間・目標金額・メニュー・Square 連携）
// 管理者パスワードでログインすると、サーバーから合言葉（token）を受け取り、以降の読み書きに付ける。
"use strict";

const settings = {
    token: null,
    model: null,     // 編集中の内容 { terms: [{name, active, target}], specials: [{name, active}], menu: [...] }
    operating: false,
    dirty: false,
    // Square 連携 { environment, location_id, token_set, token_hint, token（入力中）, locations, msg }
    // 期間・メニューの「保存」とは別に、この欄の「保存」で保存する
    sq: null,
};

async function adminApi(path, body) {
    const opts = {
        method: body === undefined ? "GET" : "POST",
        headers: { "Content-Type": "application/json", "X-Admin-Token": settings.token || "" },
    };
    if (body !== undefined) opts.body = JSON.stringify(body);
    let res;
    try {
        res = await fetch(path, opts);
    } catch {
        throw new Error("サーバーに接続できません。web_main.py が起動しているか確認してください。");
    }
    if (res.status === 401) {
        lockSettings();
        throw new Error("もう一度ログインしてください");
    }
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.error || `エラーが発生しました (${res.status})`);
    return data;
}

async function openSettings() {
    showView("settings");
    if (!settings.token) {
        lockSettings();
        return;
    }
    try {
        loadSettingsModel(await adminApi("/pc/api/admin/settings"));
        await loadSquareSettings();
    } catch (e) {
        $("admin-error").textContent = e.message;
    }
}

function lockSettings() {
    settings.token = null;
    settings.model = null;
    settings.dirty = false;
    settings.sq = null;
    $("settings-body").hidden = true;
    $("settings-body").innerHTML = "";
    $("settings-lock").hidden = false;
    $("admin-pass").value = "";
    if (ui.view === "settings") $("admin-pass").focus();
}

async function adminLogin() {
    $("admin-error").textContent = "";
    try {
        const { token } = await api("/pc/api/admin/login", { password: $("admin-pass").value });
        settings.token = token;
        $("admin-pass").value = "";
        loadSettingsModel(await adminApi("/pc/api/admin/settings"));
        await loadSquareSettings();
    } catch (e) {
        $("admin-error").textContent = e.message;
    }
}

function loadSettingsModel(s) {
    const active = new Set(s.active_terms);
    settings.model = {
        terms: s.terms.map((t) => ({ name: t, active: active.has(t), target: s.targets[t] || 0 })),
        specials: s.special_terms.map((t) => ({ name: t, active: active.has(t) })),
        menu: s.menu.map((m) => ({ ...m })),
    };
    settings.operating = s.operating;
    settings.dirty = false;
    $("settings-lock").hidden = true;
    $("settings-body").hidden = false;
    renderSettings();
}

function renderSettings(message = "") {
    const m = settings.model;
    const moveBtns = (list, i) => `
        <button class="icon-btn" data-set="up" data-list="${list}" data-i="${i}" ${i === 0 ? "disabled" : ""} title="上へ">↑</button>
        <button class="icon-btn" data-set="down" data-list="${list}" data-i="${i}" ${i === m[list].length - 1 ? "disabled" : ""} title="下へ">↓</button>
        <button class="icon-btn danger" data-set="remove" data-list="${list}" data-i="${i}" title="削除">×</button>`;

    const termRows = m.terms.map((t, i) => `
        <tr>
            <td><input class="field" data-list="terms" data-i="${i}" data-k="name" value="${esc(t.name)}"></td>
            <td class="center"><input type="checkbox" data-list="terms" data-i="${i}" data-k="active" ${t.active ? "checked" : ""}></td>
            <td><input class="field num" type="number" min="0" step="1000" data-list="terms" data-i="${i}" data-k="target" value="${t.target}"></td>
            <td class="row-actions">${moveBtns("terms", i)}</td>
        </tr>`).join("");
    const specialRows = m.specials.map((t, i) => `
        <tr class="special">
            <td>${esc(t.name)}</td>
            <td class="center"><input type="checkbox" data-list="specials" data-i="${i}" data-k="active" ${t.active ? "checked" : ""}></td>
            <td class="muted">—</td>
            <td></td>
        </tr>`).join("");
    const menuRows = m.menu.map((it, i) => `
        <tr>
            <td><input class="field" data-list="menu" data-i="${i}" data-k="name" value="${esc(it.name)}"></td>
            <td><input class="field num" type="number" min="0" step="10" data-list="menu" data-i="${i}" data-k="price" value="${it.price}"></td>
            <td class="center"><input type="checkbox" data-list="menu" data-i="${i}" data-k="visible" ${it.visible ? "checked" : ""}></td>
            <td class="row-actions">${moveBtns("menu", i)}</td>
        </tr>`).join("");

    $("settings-body").innerHTML = `
        <header class="settings-head">
            <div>
                <p class="eyebrow">SETTINGS</p>
                <h2 class="page-title">設定</h2>
            </div>
            <div class="settings-actions">
                <span class="settings-msg" id="settings-msg">${esc(message)}</span>
                <button class="btn btn-ghost" data-set="lock">ロック</button>
                <button class="btn btn-primary" data-set="save">保存</button>
            </div>
        </header>
        ${settings.operating ? `<p class="notice">レジが販売中です。メニューの変更は、次にレジを開始したときに反映されます。</p>` : ""}
        <div class="settings-grid">
            <article class="panel">
                <p class="eyebrow">TERMS</p>
                <h3 class="panel-title">期間と目標金額</h3>
                <table class="edit-table">
                    <thead><tr><th>期間名</th><th class="center">レジで選択可</th><th>目標金額（円）</th><th></th></tr></thead>
                    <tbody>${termRows}${specialRows}</tbody>
                </table>
                <button class="btn btn-ghost btn-small" data-set="add" data-list="terms">＋ 期間を追加</button>
            </article>

            <article class="panel">
                <p class="eyebrow">MENU</p>
                <h3 class="panel-title">メニュー</h3>
                <table class="edit-table">
                    <thead><tr><th>商品名</th><th>価格（円）</th><th class="center">レジ</th><th></th></tr></thead>
                    <tbody>${menuRows || `<tr><td colspan="4" class="muted">商品がありません</td></tr>`}</tbody>
                </table>
                <button class="btn btn-ghost btn-small" data-set="add" data-list="menu">＋ 商品を追加</button>
            </article>

            <article class="panel sq-settings" id="sq-panel">${squarePanelHtml()}</article>
        </div>`;
}

// ---------- Square 連携 ----------
async function loadSquareSettings() {
    const s = await adminApi("/pc/api/admin/square");
    settings.sq = { ...s, token: "", locations: settings.sq?.locations || null, msg: "" };
    renderSquarePanel();
}

function renderSquarePanel() {
    const el = $("sq-panel");
    if (el) el.innerHTML = squarePanelHtml();
}

function squarePanelHtml() {
    const q = settings.sq;
    const head = `
        <p class="eyebrow">SQUARE</p>
        <h3 class="panel-title">Square 連携</h3>`;
    if (!q) return head + `<p class="muted">読み込み中…</p>`;

    const opt = (value, label, selected) =>
        `<option value="${esc(value)}" ${selected ? "selected" : ""}>${esc(label)}</option>`;
    const locs = q.locations || [];
    const locOptions = [opt("", "メインの店舗（自動）", !q.location_id)]
        .concat(locs.map((l) => opt(l.id, `${l.name}（${l.id}）`, l.id === q.location_id)));
    if (q.location_id && !locs.some((l) => l.id === q.location_id)) {
        locOptions.push(opt(q.location_id, q.location_id, true));
    }
    const placeholder = q.token_set ? `設定済み（末尾 ${q.token_hint}）・変更するときだけ入力` : "未設定";

    return head + `
        <p class="muted sq-help">
            Square アプリの会計をレジに取り込み、Square で実際に決済された金額とレジの記録を照合します。
            アクセストークンは Square Developer（developer.squareup.com）でアプリを作ると発行できます。
        </p>
        <label class="sq-field">
            <span class="kpi-label">接続先</span>
            <select class="field" data-sq="environment">
                ${opt("production", "本番", q.environment === "production")}
                ${opt("sandbox", "サンドボックス（テスト用）", q.environment === "sandbox")}
            </select>
        </label>
        <label class="sq-field">
            <span class="kpi-label">アクセストークン</span>
            <input class="field" type="password" data-sq="token" autocomplete="off" spellcheck="false"
                placeholder="${esc(placeholder)}" value="${esc(q.token)}">
        </label>
        <label class="sq-field">
            <span class="kpi-label">店舗（「接続テスト」で一覧を読み込みます）</span>
            <select class="field" data-sq="location_id">${locOptions.join("")}</select>
        </label>
        <label class="sq-check-field">
            <input type="checkbox" data-sq="auto_import" ${q.auto_import ? "checked" : ""}>
            <span>
                <strong>Square の会計を自動で取り込む</strong>
                <span class="muted">
                    Square アプリで<b>商品を選んで</b>会計すると、15 秒ほどでレジの個数に足されます（商品名はレジのメニューと同じにしてください）。
                    現金で受けた会計は「現金」、それ以外は「Square」の枠に入ります。
                    オンにした時刻より前の会計と、「テスト」「調整」の期間中は取り込みません。
                </span>
            </span>
        </label>
        <div class="sq-actions">
            <button class="btn btn-ghost" data-set="sq-test">接続テスト</button>
            <button class="btn btn-primary" data-set="sq-save">Square 設定を保存</button>
            ${q.token_set ? `<button class="btn btn-ghost sq-clear" data-set="sq-clear">トークンを削除</button>` : ""}
        </div>
        <p class="settings-msg sq-msg">${esc(q.msg)}</p>`;
}

function setSquareMsg(msg) {
    settings.sq.msg = msg;
    renderSquarePanel();
}

async function squareTest() {
    const q = settings.sq;
    setSquareMsg("Square に接続しています…");
    try {
        const { locations } = await adminApi("/pc/api/admin/square/locations", {
            environment: q.environment,
            access_token: q.token,
        });
        q.locations = locations;
        setSquareMsg(`接続できました（店舗 ${locations.length} 件）。店舗を選んで保存してください`);
    } catch (e) {
        setSquareMsg(e.message);
    }
}

async function squareSave(extra = {}) {
    const q = settings.sq;
    try {
        const s = await adminApi("/pc/api/admin/square", {
            environment: q.environment,
            access_token: q.token,
            location_id: q.location_id,
            auto_import: q.auto_import,
            ...extra,
        });
        Object.assign(q, s, { token: "" });
        setSquareMsg(extra.clear_token ? "トークンを削除しました" : "保存しました");
    } catch (e) {
        setSquareMsg(e.message);
    }
}

async function squareClearToken() {
    const ok = await confirmModal("トークンの削除", "保存されている Square のアクセストークンを削除しますか？", "削除", true);
    if (ok) squareSave({ clear_token: true });
}

function markDirty() {
    settings.dirty = true;
    const msg = $("settings-msg");
    if (msg) msg.textContent = "未保存の変更があります";
}

function onSettingsInput(e) {
    const el = e.target;
    if (el.dataset.sq && settings.sq) {
        settings.sq[el.dataset.sq] = el.type === "checkbox" ? el.checked : el.value;
        return;
    }
    const k = el.dataset.k;
    if (!k || !settings.model) return;
    let value = el.type === "checkbox" ? el.checked : el.value;
    if (el.type === "number") value = Number(value) || 0;
    if (el.dataset.list) settings.model[el.dataset.list][Number(el.dataset.i)][k] = value;
    else settings.model[k] = value;
    markDirty();
}

function onSettingsClick(e) {
    const b = e.target.closest("[data-set]");
    if (!b || !settings.model) return;
    const list = settings.model[b.dataset.list];
    const i = Number(b.dataset.i);
    switch (b.dataset.set) {
        case "save": saveSettings(); return;
        case "sq-test": squareTest(); return;
        case "sq-save": squareSave(); return;
        case "sq-clear": squareClearToken(); return;
        case "lock": confirmLeaveSettings().then((ok) => ok && lockSettings()); return;
        case "add":
            list.push(b.dataset.list === "terms"
                ? { name: "", active: true, target: 0 }
                : { name: "", price: 0, visible: true });
            break;
        case "remove": list.splice(i, 1); break;
        case "up": [list[i - 1], list[i]] = [list[i], list[i - 1]]; break;
        case "down": [list[i + 1], list[i]] = [list[i], list[i + 1]]; break;
        default: return;
    }
    renderSettings();
    markDirty();
    if (b.dataset.set === "add") {
        const inputs = $("settings-body").querySelectorAll(`[data-list="${b.dataset.list}"][data-k="name"]`);
        inputs[inputs.length - 1]?.focus();
    }
}

async function saveSettings() {
    const m = settings.model;
    const payload = {
        terms: m.terms.map((t) => t.name.trim()),
        active_terms: [...m.terms, ...m.specials].filter((t) => t.active).map((t) => t.name.trim()),
        targets: Object.fromEntries(m.terms.map((t) => [t.name.trim(), t.target])),
        menu: m.menu,
    };
    try {
        loadSettingsModel(await adminApi("/pc/api/admin/settings", payload));
        renderSettings("保存しました");
        dash.term = null;   // 期間名が変わっている場合に備えて、ダッシュボードのタブを選び直す
    } catch (e) {
        const msg = $("settings-msg");
        if (msg) msg.textContent = e.message;
    }
}

// 未保存の変更があるまま別の画面へ移るときに確認する
async function confirmLeaveSettings() {
    if (!settings.dirty) return true;
    const ok = await confirmModal("未保存の変更", "保存していない変更があります。破棄して移動しますか？", "破棄", false);
    if (ok) settings.dirty = false;
    return ok;
}

function bindSettingsEvents() {
    $("admin-login-btn").addEventListener("click", adminLogin);
    $("admin-pass").addEventListener("keydown", (e) => {
        if (e.key === "Enter" && !e.isComposing && e.keyCode !== 229) adminLogin();
    });
    $("settings-body").addEventListener("input", onSettingsInput);
    $("settings-body").addEventListener("click", onSettingsClick);
}
