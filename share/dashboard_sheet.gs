/**
 * NF会計システム：ダッシュボード共有用のスプレッドシート
 *
 * 親機のレジ（share_sheet.py）が 1 分ごとに売上を送ってくるので、
 * 「まとめ」「商品別」「時間別」の 3 つのシートに書き込み、グラフを作る。
 *
 * 使い方
 *   1. 共有用のスプレッドシートで「拡張機能」→「Apps Script」を開き、このファイルの中身をすべて貼り付けて保存
 *   2. 「デプロイ」→「新しいデプロイ」→ 種類「ウェブアプリ」
 *        次のユーザーとして実行：自分
 *        アクセスできるユーザー：全員
 *      ※「アクセスできるユーザー」を変えたときは「デプロイを管理」→ 編集 →「新バージョン」でデプロイし直す（URL は変わらない）。
 *        「新しいデプロイ」を作り直すと URL が変わるので、レジに入れた URL も入れ直すこと
 *   3. 表示された「ウェブアプリの URL」（…/exec）を、レジの Settings →「ダッシュボードの共有」に入れて保存
 *      シークレットウィンドウでこの URL を開き「正しく公開されています」と出れば、公開の設定は正しい
 *   4. スプレッドシートを「リンクを知っている全員（閲覧者）」で共有する
 *
 * ウェブアプリの URL を知っていれば誰でもデータを送れてしまうので、URL はスプレッドシートのリンクと違い、人に教えないこと。
 *
 * 売上のログのバックアップ
 *   親機はログ（current_log.csv）も少しずつ送ってくる。このスプレッドシートとは別に、自分のドライブに
 *   「NF 売上バックアップ（ログ）」というスプレッドシートを自動で作って書き足す（共有はしないので、人には見えない）。
 *   親機の PC が壊れたときは、そのスプレッドシートを CSV でダウンロードすれば、ログから売上を作り直せる。
 *   このファイルを貼り直したときは「デプロイを管理」→ 編集 →「新バージョン」でデプロイし直すこと（URL は変わらない）
 */

const SHEET_SUMMARY = "まとめ";
const SHEET_ITEMS = "商品別";
const SHEET_HOURLY = "時間別";
const YEN = "¥#,##0";
const CHART_VERSION = 3;   // グラフの作り方を変えたら上げる（次の更新で作り直す）
const BACKUP_NAME = "NF 売上バックアップ（ログ）";
const LOG_HEADER = ["Timestamp", "User", "Terminal", "Location", "Action", "Target", "Value"];

// ブラウザでウェブアプリの URL を開いたときの表示（公開の設定が正しいかの確認用）
function doGet() {
  return ContentService.createTextOutput("NF 売上ダッシュボードの受け取り口です。正しく公開されています。");
}

function doPost(e) {
  const lock = LockService.getScriptLock();
  lock.waitLock(30000);
  try {
    const data = JSON.parse(e.postData.contents);
    const ss = SpreadsheetApp.getActiveSpreadsheet();
    writeSummary(sheetOf(ss, SHEET_SUMMARY), data);
    writeItems(sheetOf(ss, SHEET_ITEMS), data);
    writeHourly(sheetOf(ss, SHEET_HOURLY), data);
    removeDefaultSheet(ss);
    const res = { ok: true };
    if (data.log) Object.assign(res, appendLog(data.log));
    return reply(res);
  } catch (err) {
    return reply({ ok: false, error: String(err) });
  } finally {
    lock.releaseLock();
  }
}

// バックアップ用のスプレッドシート（なければ作る。ID はスクリプトのプロパティに覚えておく）
function backupBook() {
  const props = PropertiesService.getScriptProperties();
  const id = props.getProperty("BACKUP_ID");
  if (id) {
    try {
      return SpreadsheetApp.openById(id);
    } catch (err) {
      // 消されていたら作り直す
    }
  }
  const book = SpreadsheetApp.create(BACKUP_NAME);
  props.setProperty("BACKUP_ID", book.getId());
  return book;
}

// ログの start 行目（0 から数える）からの rows を書き足し、書き足したあとの行数を返す。
// 送り直しで重なった行は飛ばす。間が空いている（start が今の行数より後）ときは書かずに今の行数を返す
function appendLog(log) {
  const book = backupBook();
  const sh = book.getSheets()[0];
  if (sh.getLastRow() === 0) {
    sh.getRange(1, 1, 1, LOG_HEADER.length).setValues([LOG_HEADER]).setFontWeight("bold");
    sh.setFrozenRows(1);
  }
  const count = Math.max(sh.getLastRow() - 1, 0);
  const start = Number(log.start) || 0;
  const rows = (log.rows || []).slice(Math.max(count - start, 0));
  if (start <= count && rows.length) {
    const range = sh.getRange(count + 2, 1, rows.length, LOG_HEADER.length);
    range.setNumberFormat("@");   // 日時や「+1」を数字・日付に変えられないよう、文字のまま書く
    range.setValues(rows.map((r) => LOG_HEADER.map((_, i) => String(r[i] === undefined ? "" : r[i]))));
  }
  return { log_count: Math.max(sh.getLastRow() - 1, 0), backup_url: book.getUrl() };
}

function reply(obj) {
  return ContentService.createTextOutput(JSON.stringify(obj)).setMimeType(ContentService.MimeType.JSON);
}

function sheetOf(ss, name) {
  return ss.getSheetByName(name) || ss.insertSheet(name);
}

// 新しいスプレッドシートに最初からある空の「シート1」は消す
function removeDefaultSheet(ss) {
  ["シート1", "Sheet1"].forEach((name) => {
    const sh = ss.getSheetByName(name);
    if (sh && ss.getSheets().length > 1 && sh.getLastRow() === 0) ss.deleteSheet(sh);
  });
}

// row 行目から表を書く。前に書いた分が残らないよう、その下は消す
function writeTable(sh, row, header, rows) {
  const width = header.length;
  const last = Math.max(sh.getLastRow(), row);
  sh.getRange(row, 1, last - row + 1, Math.max(width, sh.getLastColumn(), 1)).clearContent();
  sh.getRange(row, 1, 1, width).setValues([header]).setFontWeight("bold").setBackground("#eeeeee");
  if (rows.length) sh.getRange(row + 1, 1, rows.length, width).setValues(rows).setFontWeight("normal").setBackground(null);
}

function title(sh, text, updated) {
  sh.getRange("A1").setValue(text).setFontSize(16).setFontWeight("bold");
  sh.getRange("A2").setValue("最終更新：" + updated + "（親機のレジから 1 分ごとに自動で更新）").setFontColor("#666666");
}

// グラフの元になる表の大きさが変わったときだけ、グラフを作り直す
function chartNeedsRebuild(sh, key, size) {
  const props = PropertiesService.getDocumentProperties();
  const value = CHART_VERSION + ":" + size;
  if (props.getProperty(key) === value && sh.getCharts().length) return false;
  sh.getCharts().forEach((c) => sh.removeChart(c));
  props.setProperty(key, value);
  return true;
}

function writeSummary(sh, data) {
  title(sh, "売上まとめ", data.updated);
  const rows = data.summary.map((s) => [
    s.term, s.sales, s.target || "", s.target ? s.sales / s.target : "",
    s.transactions, s.transactions ? Math.round(s.sales / s.transactions) : "", s.cash, s.paypay || 0, s.square,
  ]);
  const sum = (k) => data.summary.reduce((a, s) => a + (s[k] || 0), 0);
  const sales = sum("sales"), target = sum("target"), tx = sum("transactions");
  rows.push(["合計", sales, target || "", target ? sales / target : "", tx, tx ? Math.round(sales / tx) : "",
             sum("cash"), sum("paypay"), sum("square")]);
  writeTable(sh, 4, ["期間", "売上", "目標", "達成率", "会計件数", "平均単価", "現金", "PayPay", "Square"], rows);

  const n = rows.length;
  sh.getRange(5, 2, n, 2).setNumberFormat(YEN);
  sh.getRange(5, 4, n, 1).setNumberFormat("0.0%");
  sh.getRange(5, 5, n, 1).setNumberFormat("#,##0");
  sh.getRange(5, 6, n, 4).setNumberFormat(YEN);
  sh.getRange(4 + n, 1, 1, 9).setFontWeight("bold");
  sh.setColumnWidth(1, 90);
  sh.setColumnWidths(2, 8, 100);

  if (chartNeedsRebuild(sh, "summaryRows", n) && n > 1) {
    sh.insertChart(sh.newChart()
      .setNumHeaders(1)
      .setChartType(Charts.ChartType.COLUMN)
      .addRange(sh.getRange(4, 1, n, 1))     // 期間（合計の行は含めない）
      .addRange(sh.getRange(4, 7, n, 3))     // 現金・PayPay・Square
      .setOption("title", "期間ごとの売上（現金・PayPay・Square）")
      .setOption("colors", ["#90a4ae", "#e60033", "#5b7ba6"])
      .setOption("isStacked", true)
      .setOption("legend", { position: "bottom" })
      .setOption("vAxis", { format: "¥#,##0" })
      .setPosition(4, 11, 0, 0)
      .build());
  }
}

function writeItems(sh, data) {
  title(sh, "商品別の売上", data.updated);
  const row = (term, x) => [term, x.name, x.cash + (x.paypay || 0) + x.square, x.cash, x.paypay || 0, x.square, x.amount];
  const rows = data.totals.map((t) => row("全期間", t)).concat(data.items.map((it) => row(it.term, it)));
  writeTable(sh, 4, ["期間", "商品", "個数", "うち現金", "うち PayPay", "うち Square", "売上"], rows);
  if (rows.length) {
    sh.getRange(5, 3, rows.length, 4).setNumberFormat("#,##0");
    sh.getRange(5, 7, rows.length, 1).setNumberFormat(YEN);
  }
  sh.setColumnWidth(1, 90);
  sh.setColumnWidth(2, 170);
  sh.setColumnWidths(3, 5, 90);

  const n = data.totals.length;
  if (chartNeedsRebuild(sh, "itemRows", n) && n) {
    sh.insertChart(sh.newChart()
      .setNumHeaders(1)
      .setChartType(Charts.ChartType.BAR)
      .addRange(sh.getRange(4, 2, n + 1, 1))   // 商品（全期間の行）
      .addRange(sh.getRange(4, 7, n + 1, 1))   // 売上
      .setOption("title", "商品別の売上（全期間）")
      .setOption("legend", { position: "none" })
      .setOption("hAxis", { format: "¥#,##0" })
      .setPosition(4, 9, 0, 0)
      .build());
  }
}

function writeHourly(sh, data) {
  title(sh, "時間別の売上", data.updated);
  const rows = data.hourly.map((h) => [h.hour + ":00"].concat(h.amounts));
  writeTable(sh, 4, ["時刻"].concat(data.terms), rows);
  const width = data.terms.length + 1;
  if (rows.length) sh.getRange(5, 2, rows.length, data.terms.length).setNumberFormat(YEN);
  sh.setColumnWidth(1, 70);
  sh.setColumnWidths(2, width - 1, 100);

  if (chartNeedsRebuild(sh, "hourlySize", rows.length + "x" + width) && rows.length) {
    sh.insertChart(sh.newChart()
      .setNumHeaders(1)
      .setChartType(Charts.ChartType.LINE)
      .addRange(sh.getRange(4, 1, rows.length + 1, width))
      .setOption("title", "時間別の売上（期間ごと）")
      .setOption("legend", { position: "bottom" })
      .setOption("vAxis", { format: "¥#,##0" })
      .setPosition(4, width + 2, 0, 0)
      .build());
  }
}
