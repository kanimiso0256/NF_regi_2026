// settings.js — 設定画面（期間・目標金額・メニュー・モバイル用パスワード）
// 管理者パスワードでログインすると、サーバーから合言葉（token）を受け取り、以降の読み書きに付ける。
"use strict";

const settings = {
    token: null,
    model: null,     // 編集中の内容 { terms: [{name, active, target}], specials: [{name, active}], menu: [...], mobile_password }
    operating: false,
    dirty: false,
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
    } catch (e) {
        $("admin-error").textContent = e.message;
    }
}

function lockSettings() {
    settings.token = null;
    settings.model = null;
    settings.dirty = false;
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
        mobile_password: s.mobile_password,
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
            <td class="center"><input type="checkbox" data-list="menu" data-i="${i}" data-k="mobile_visible" ${it.mobile_visible ? "checked" : ""}></td>
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
                    <thead><tr><th>商品名</th><th>価格（円）</th><th class="center">レジ</th><th class="center">スマホ</th><th></th></tr></thead>
                    <tbody>${menuRows || `<tr><td colspan="5" class="muted">商品がありません</td></tr>`}</tbody>
                </table>
                <button class="btn btn-ghost btn-small" data-set="add" data-list="menu">＋ 商品を追加</button>
            </article>

            <article class="panel">
                <p class="eyebrow">MOBILE</p>
                <h3 class="panel-title">モバイル注文のパスワード</h3>
                <input class="field" id="set-mobile-pass" aria-label="モバイル用パスワード" data-k="mobile_password" value="${esc(m.mobile_password)}" autocomplete="off">
            </article>
        </div>`;
}

function markDirty() {
    settings.dirty = true;
    const msg = $("settings-msg");
    if (msg) msg.textContent = "未保存の変更があります";
}

function onSettingsInput(e) {
    const el = e.target;
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
        case "lock": confirmLeaveSettings().then((ok) => ok && lockSettings()); return;
        case "add":
            list.push(b.dataset.list === "terms"
                ? { name: "", active: true, target: 0 }
                : { name: "", price: 0, visible: true, mobile_visible: false });
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
        mobile_password: m.mobile_password,
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
    const ok = await confirmModal("未保存の変更", "保存していない変更があります。破棄して移動しますか？", "破棄", false, { showKeys: false });
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
