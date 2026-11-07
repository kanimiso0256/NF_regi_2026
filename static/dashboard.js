// dashboard.js — ダッシュボード（時間別売上・種類別売上内訳・目標達成状況・売上サマリー）
// 集計はサーバー側（analytics.py）。ここでは受け取った数字を SVG のグラフにして表示するだけ。
// 外部のグラフライブラリは使わない（ネットにつながらない会場でも動くように）。
"use strict";

const DASH_POLL_MS = 5000;
const MIX_COLORS = ["#f43f5e", "#f97316", "#eab308", "#22c55e", "#3b82f6"];
const MIX_OTHER_COLOR = "#b0bec5";
const SVG_NS = 'xmlns="http://www.w3.org/2000/svg"';

const dash = { term: null, data: null };

const yenJp = (n) => Math.round(n).toLocaleString() + "円";
const pct = (n, digits = 1) => n.toFixed(digits) + "%";
const signedPct = (n) => (n > 0 ? "+" : "") + pct(n);

async function openDashboard() {
    showView("dashboard");
    await refreshDashboard();
}

async function refreshDashboard() {
    const q = dash.term ? `?term=${encodeURIComponent(dash.term)}` : "";
    let data;
    try {
        data = await api("/pc/api/analytics" + q);
    } catch {
        return;   // 次の更新で再試行する
    }
    dash.data = data;
    dash.term = data.term;
    renderDashboard(data);
}

// グラフの表示場所の大きさが変わったら（ウィンドウの拡大縮小など）、その大きさで描き直す
let hourlySize = "";
new ResizeObserver(([entry]) => {
    const { width, height } = entry.contentRect;
    const size = `${Math.round(width)}x${Math.round(height)}`;
    if (!width || size === hourlySize) return;
    hourlySize = size;
    if (dash.data?.term) $("hourly-chart").innerHTML = lineChart(dash.data.hourly, $("hourly-chart"));
}).observe(document.getElementById("hourly-chart"));

function selectDashTerm(term) {
    if (term === dash.term) return;
    dash.term = term;
    refreshDashboard();
}

function renderDashboard(d) {
    $("dash-tabs").innerHTML = d.terms.map((t) => `
        <button class="tab ${t === d.term ? "active" : ""}" data-dash-term="${esc(t)}">${esc(t)}</button>`).join("")
        || `<span class="tab-empty">Settings で期間を登録してください</span>`;
    if (!d.term) return;

    // 時間別売上
    $("peak-hour").textContent = d.peak ? `${d.peak.hour}:00` : "—";
    $("peak-amount").textContent = d.peak ? yenJp(d.peak.amount) : "—";
    $("hourly-chart").innerHTML = lineChart(d.hourly, $("hourly-chart"));

    // 種類別売上内訳
    $("mix").innerHTML = d.mix.length ? mixChart(d.mix) : `<p class="chart-empty">まだ売上がありません</p>`;

    // 目標額の達成状況
    $("gauge").innerHTML = gaugeChart(d.rate);
    $("target-sales").textContent = yenJp(d.sales);
    $("target-amount").textContent = d.target ? yenJp(d.target) : "未設定";

    // 売上サマリー
    $("ov-sales").textContent = yenJp(d.sales);
    const delta = $("ov-delta");
    delta.hidden = d.change === null;
    if (d.change !== null) {
        delta.className = "delta " + (d.change >= 0 ? "up" : "down");
        delta.textContent = `${d.change >= 0 ? "↗" : "↘"} ${signedPct(d.change)}`;
        delta.title = `${d.prev_term} との比較`;
    }
    $("spark").innerHTML = sparkline(d.trend);
    $("ov-count").textContent = d.transactions.toLocaleString() + "件";
    $("ov-average").textContent = d.average === null ? "—" : yenJp(d.average);
    const change = $("ov-change");
    change.textContent = d.change === null ? "—" : signedPct(d.change);
    change.className = "kpi kpi-s" + (d.change === null ? "" : d.change >= 0 ? " up" : " down");
}

// ---------- 時間別売上（折れ線） ----------
// 目盛りがきりのいい数字になるよう、1 段の幅を 1・2・2.5・5 × 10^n に切り上げる
function niceMax(v, steps) {
    if (v <= 0) return 10000;
    const raw = (v * 1.1) / steps;
    const mag = 10 ** Math.floor(Math.log10(raw));
    const step = [1, 2, 2.5, 5, 10].find((s) => s * mag >= raw) * mag;
    return step * steps;
}

// 画面の大きさに合わせて縮めると文字まで小さくなるので、表示する場所の実際の大きさで描く。
// 高さが足りないとき（ノートパソコンなど）は、凡例を省き目盛りを減らす
function lineChart(hourly, el) {
    const W = Math.max(280, el.clientWidth || 560), H = Math.max(90, el.clientHeight || 300);
    const compact = H < 200;
    const steps = compact ? 3 : 5;
    const L = 58, R = 16, T = 8, B = compact ? 24 : 50;
    const max = niceMax(Math.max(...hourly.map((h) => h.amount)), steps);
    const n = hourly.length;
    const x = (i) => L + (n === 1 ? (W - L - R) / 2 : (i * (W - L - R)) / (n - 1));
    const y = (v) => T + (H - T - B) * (1 - Math.max(0, v) / max);

    const ticks = Array.from({ length: steps + 1 }, (_, i) => (max / steps) * i);
    const grid = ticks.map((v) => `
        <line class="grid" x1="${L}" x2="${W - R}" y1="${y(v)}" y2="${y(v)}"/>
        <text class="axis" x="${L - 10}" y="${y(v) + 4}" text-anchor="end">${v.toLocaleString()}</text>`).join("");
    const cols = hourly.map((h, i) => `
        <line class="grid" x1="${x(i)}" x2="${x(i)}" y1="${T}" y2="${H - B}"/>
        <text class="axis" x="${x(i)}" y="${H - B + 17}" text-anchor="middle">${h.hour}:00</text>`).join("");
    const pts = hourly.map((h, i) => [x(i), y(h.amount)]);
    const dots = hourly.map((h, i) => `
        <circle class="line-dot" cx="${pts[i][0]}" cy="${pts[i][1]}" r="${compact ? 4 : 5}"><title>${h.hour}:00  ${yenJp(h.amount)}</title></circle>`).join("");
    const legend = compact ? "" : `
        <g class="legend" transform="translate(${(L + W - R) / 2 - 30} ${H - 6})">
            <circle class="line-dot" cx="0" cy="-4" r="6"/>
            <text class="axis" x="12" y="1">売上高</text>
        </g>`;

    return `<svg ${SVG_NS} viewBox="0 0 ${W} ${H}" role="img" aria-label="時間別売上のグラフ">
        ${grid}${cols}
        <line class="axis-line" x1="${L}" x2="${L}" y1="${T}" y2="${H - B}"/>
        <line class="axis-line" x1="${L}" x2="${W - R}" y1="${H - B}" y2="${H - B}"/>
        <polyline class="line" points="${pts.map((p) => p.join(",")).join(" ")}"/>
        ${dots}${legend}
    </svg>`;
}

// ---------- 種類別売上内訳（ドーナツ） ----------
function polar(cx, cy, r, deg) {
    const rad = ((deg - 90) * Math.PI) / 180;
    return [cx + r * Math.cos(rad), cy + r * Math.sin(rad)];
}

function arcPath(cx, cy, rOut, rIn, a0, a1) {
    const large = a1 - a0 > 180 ? 1 : 0;
    const [x0, y0] = polar(cx, cy, rOut, a0), [x1, y1] = polar(cx, cy, rOut, a1);
    const [x2, y2] = polar(cx, cy, rIn, a1), [x3, y3] = polar(cx, cy, rIn, a0);
    return `M${x0},${y0} A${rOut},${rOut} 0 ${large} 1 ${x1},${y1} L${x2},${y2} A${rIn},${rIn} 0 ${large} 0 ${x3},${y3}Z`;
}

function mixColor(row, i) {
    return row.other ? MIX_OTHER_COLOR : MIX_COLORS[i % MIX_COLORS.length];
}

function mixChart(mix) {
    const C = 130, R1 = 124, R0 = 64;
    let angle = 0;
    const slices = mix.map((m, i) => {
        // 360° ちょうどの円弧は描けないので、1 種類だけのときは少しだけ手前で止める
        const sweep = Math.min(359.99, (m.pct / 100) * 360);
        const path = arcPath(C, C, R1, R0, angle, angle + sweep);
        angle += sweep;
        return `<path d="${path}" fill="${mixColor(m, i)}"><title>${esc(m.name)}  ${yenJp(m.amount)}（${m.qty}個）</title></path>`;
    }).join("");
    const legend = mix.map((m, i) => `
        <li>
            <span class="swatch" style="background:${mixColor(m, i)}"></span>
            <span class="mix-name" title="${esc(m.name)}">${esc(m.name)}</span>
            <span class="mix-pct">${pct(m.pct)}</span>
        </li>`).join("");
    return `
        <svg ${SVG_NS} class="donut" viewBox="0 0 ${C * 2} ${C * 2}" role="img" aria-label="種類別売上内訳のグラフ">
            <g class="slices">${slices}</g>
            <text class="donut-label" x="${C}" y="${C - 22}" text-anchor="middle">TOP</text>
            <text class="donut-value" x="${C}" y="${C + 22}" text-anchor="middle">${pct(mix[0].pct)}</text>
        </svg>
        <ul class="mix-legend">${legend}</ul>`;
}

// ---------- 目標額の達成状況（ゲージ） ----------
const GAUGE_FROM = -125, GAUGE_TO = 125;   // 真上を 0° として左右に開いた円弧

function gaugeArc(cx, cy, r, a0, a1) {
    const [x0, y0] = polar(cx, cy, r, a0), [x1, y1] = polar(cx, cy, r, a1);
    return `M${x0},${y0} A${r},${r} 0 ${a1 - a0 > 180 ? 1 : 0} 1 ${x1},${y1}`;
}

function gaugeChart(rate) {
    const W = 300, H = 250, C = 150, CY = 140, R = 116;
    const filled = rate === null ? 0 : Math.min(rate, 100) / 100;
    const end = GAUGE_FROM + (GAUGE_TO - GAUGE_FROM) * filled;
    const value = rate === null ? "—" : pct(rate);
    return `<svg ${SVG_NS} viewBox="0 0 ${W} ${H}" role="img" aria-label="目標達成率 ${value}">
        <defs>
            <filter id="gauge-shadow" x="-20%" y="-20%" width="140%" height="140%">
                <feDropShadow dx="0" dy="8" stdDeviation="8" flood-color="#6c63ff" flood-opacity=".25"/>
            </filter>
        </defs>
        <path class="gauge-track" d="${gaugeArc(C, CY, R, GAUGE_FROM, GAUGE_TO)}"/>
        ${filled > 0 ? `<path class="gauge-fill" filter="url(#gauge-shadow)" d="${gaugeArc(C, CY, R, GAUGE_FROM, end)}"/>` : ""}
        <text class="gauge-label" x="${C}" y="${CY - 34}" text-anchor="middle">${rate === null ? "目標未設定" : "達成率"}</text>
        <text class="gauge-value" x="${C}" y="${CY + 22}" text-anchor="middle">${value}</text>
    </svg>`;
}

// ---------- 売上サマリー（推移の面グラフ） ----------
// 点を滑らかな曲線でつなぐ（Catmull-Rom → ベジェ曲線）
function smoothPath(pts) {
    if (pts.length < 2) return "";
    let d = `M${pts[0][0]},${pts[0][1]}`;
    for (let i = 0; i < pts.length - 1; i++) {
        const p0 = pts[i - 1] || pts[i], p1 = pts[i], p2 = pts[i + 1], p3 = pts[i + 2] || p2;
        const c1 = [p1[0] + (p2[0] - p0[0]) / 6, p1[1] + (p2[1] - p0[1]) / 6];
        const c2 = [p2[0] - (p3[0] - p1[0]) / 6, p2[1] - (p3[1] - p1[1]) / 6];
        d += ` C${c1[0]},${c1[1]} ${c2[0]},${c2[1]} ${p2[0]},${p2[1]}`;
    }
    return d;
}

function sparkline(trend) {
    const W = 560, H = 130, P = 8;
    if (trend.length < 2) return `<p class="chart-empty">売上が記録されると推移が表示されます</p>`;
    const vals = trend.map((t) => t.v);
    const min = Math.min(0, ...vals), max = Math.max(...vals) || 1;
    const pts = trend.map((t, i) => [
        P + (i * (W - P * 2)) / (trend.length - 1),
        P + (H - P * 2) * (1 - (t.v - min) / (max - min)),
    ]);
    const line = smoothPath(pts);
    const last = pts[pts.length - 1];
    return `<svg ${SVG_NS} viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" role="img"
            aria-label="売上の推移（${esc(trend[0].t)}〜${esc(trend[trend.length - 1].t)}）">
        <defs>
            <linearGradient id="spark-fill" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0" style="stop-color: var(--accent); stop-opacity: .28"/>
                <stop offset="1" style="stop-color: var(--accent); stop-opacity: 0"/>
            </linearGradient>
        </defs>
        <path d="${line} L${last[0]},${H} L${pts[0][0]},${H}Z" fill="url(#spark-fill)"/>
        <path class="spark-line" d="${line}" vector-effect="non-scaling-stroke"/>
    </svg>
    <span class="spark-dot" style="left:${(last[0] / W) * 100}%; top:${(last[1] / H) * 100}%"></span>`;
}
