// history.js — レジ画面の右に出す「直近の会計」（表示だけ。入力・確定は register.js）
// 親機は会計が増えるたびに history_rev を 1 増やすので、変わったときだけ一覧を読み直す。
"use strict";

const HIST_PTYPE = {
    cash: ["現金", "hist-pt-cash"],
    pp: ["PayPay", "hist-pt-pp"],
    paypay: ["Square", "hist-pt-sq"],
};

const hist = {
    key: "",          // 最後に読んだ「期間:rev」
    loading: false,
    open: new Set(),  // 中身を開いている会計（ts）
    data: null,
};

// register.js の renderRegister から毎回呼ばれる
function updateHistory(s) {
    const key = `${s.mode}:${s.history_rev}`;
    if (key === hist.key || hist.loading) return;
    loadHistory(key);
}

// 期間を変えたとき・販売を始め直したときは、前の期間の一覧を出したままにしない
function resetHistory() {
    hist.key = "";
    hist.data = null;
    hist.open.clear();
    renderHistory();
}

async function loadHistory(key) {
    hist.loading = true;
    try {
        const data = await api("/pc/api/history");
        if (hist.data && hist.data.term !== data.term) hist.open.clear();
        hist.data = data;
        hist.key = key;
        renderHistory();
    } catch {
        // つながらないときは次の状態取得で読み直す（帯は register.js が出す）
    } finally {
        hist.loading = false;
    }
}

function histBadges(e) {
    const seen = [...new Set(e.items.map((i) => i.ptype))];
    return seen.map((p) => {
        const [label, cls] = HIST_PTYPE[p] || [p, ""];
        return `<span class="hist-pt ${cls}">${esc(label)}</span>`;
    }).join("");
}

function histItemsText(e) {
    return e.items.map((i) => `${esc(i.name)}×${i.qty}`).join("・");
}

function histWho(e) {
    if (e.kind === "square") return "Square 自動取込";
    return e.by && e.by !== e.terminal ? `${esc(e.terminal)}・${esc(e.by)}` : esc(e.terminal || "");
}

function renderHistory() {
    const list = document.getElementById("hist-list");
    if (!list) return;
    const d = hist.data;
    $("hist-count").textContent = d ? `${d.count}件` : "";
    if (!d) {
        list.innerHTML = "";
        return;
    }
    if (!d.entries.length) {
        list.innerHTML = `<li class="hist-empty">${ui.state?.is_test ? "テストの会計はまだありません" : "まだ会計はありません"}</li>`;
        return;
    }
    list.innerHTML = d.entries.map((e) => {
        const minus = e.amount < 0 || e.qty < 0;
        const open = hist.open.has(e.ts);
        return `<li class="hist-item${open ? " open" : ""}${minus ? " minus" : ""}" data-ts="${esc(e.ts)}">
            <div class="hist-top">
                <span class="hist-time">${esc(e.time)}</span>${histBadges(e)}
                <span class="hist-who">${histWho(e)}</span>
                <strong class="hist-amount">${minus ? "−" : ""}${yen(Math.abs(e.amount))}</strong>
            </div>
            <div class="hist-items">${minus ? "取消・修正 " : ""}${histItemsText(e)}</div>
            ${e.discount ? `<div class="hist-discount">割引 ${e.discount < 0 ? "+" : "−"}${yen(Math.abs(e.discount))}</div>` : ""}
            <div class="hist-detail">
                ${e.items.map((i) => `<div class="hist-line">
                    <span>${esc(i.name)} <span class="hist-line-pt">${esc((HIST_PTYPE[i.ptype] || [i.ptype])[0])}</span> × ${i.qty}</span>
                    <span>${i.discount ? `<span class="hist-line-discount">割引 ${i.discount < 0 ? "+" : "−"}${yen(Math.abs(i.discount))}</span>` : ""}${i.amount < 0 ? "−" : ""}${yen(Math.abs(i.amount))}</span>
                </div>`).join("")}
            </div>
        </li>`;
    }).join("");
}

// register.js より先に読み込むので、ここでは $ を使わない
function bindHistoryEvents() {
    document.getElementById("hist-list").addEventListener("click", (ev) => {
        const li = ev.target.closest(".hist-item");
        if (!li) return;
        const ts = li.dataset.ts;
        if (hist.open.has(ts)) hist.open.delete(ts);
        else hist.open.add(ts);
        li.classList.toggle("open");
    });
    // スマホでは見出しを押して開け閉めする
    document.getElementById("hist-head").addEventListener("click", () => {
        document.getElementById("reg-history").classList.toggle("collapsed");
    });
}

bindHistoryEvents();   // register.html の最後で読み込むので、要素はもうある
