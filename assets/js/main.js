/* A股新手课堂 - 交互脚本
 * 行情与分析由本地 server.py 提供（/api/quotes、/api/stock、/api/analyze）。
 * 未启动服务时自动回退演示数据。
 */

document.addEventListener("DOMContentLoaded", function () {
  highlightNav();
  initQuotes();
  initRiskProfiler();
  initAdvice();
  initWatchlist();
  initLowRisk();
  initHoldings();
  initHomeSearch();
});

function highlightNav() {
  var path = location.pathname.split("/").pop() || "index.html";
  document.querySelectorAll(".nav-links a").forEach(function (a) {
    if (a.getAttribute("href") === path) a.classList.add("active");
  });
}

/* ================= 工具函数 ================= */
function clsOf(pct) { return pct > 0 ? "up" : pct < 0 ? "down" : "flat"; }
function signOf(pct) { return pct > 0 ? "+" : ""; }
function fmt(v, digits) {
  if (v === null || v === undefined) return "--";
  return Number(v).toLocaleString("zh-CN", { minimumFractionDigits: digits === undefined ? 2 : digits });
}
function fmtAmount(v) { return v ? (v / 1e8).toFixed(2) + " 亿" : "--"; }

/* 迷你走势图（纯 SVG，无外部依赖） */
function sparkline(values, color) {
  if (!values || values.length < 2) return "";
  var w = 100, h = 30;
  var min = Math.min.apply(null, values), max = Math.max.apply(null, values);
  var range = (max - min) || 1;
  var pts = values.map(function (v, i) {
    var x = (i / (values.length - 1)) * w;
    var y = h - ((v - min) / range) * h;
    return x.toFixed(2) + "," + y.toFixed(2);
  }).join(" ");
  return '<svg class="spark" viewBox="0 0 ' + w + ' ' + h + '" preserveAspectRatio="none">' +
    '<polyline points="' + pts + '" fill="none" stroke="' + color + '" stroke-width="1.5" ' +
    'vector-effect="non-scaling-stroke"/></svg>';
}

/* ================= 首页行情条 ================= */
var DEMO_QUOTES = [
  { name: "上证指数", price: 3120.45, percent: 0.62 },
  { name: "深证成指", price: 9845.10, percent: -0.31 },
  { name: "创业板指", price: 1932.77, percent: 1.05 },
  { name: "沪深300", price: 3655.21, percent: 0.18 }
];

function renderQuotes(box, items) {
  box.innerHTML = items.map(function (q) {
    var pct = Number(q.percent) || 0;
    var cls = clsOf(pct);
    var price = (q.price === null || q.price === undefined) ? "--" : fmt(q.price);
    return '<div class="quote"><div class="name">' + q.name + '</div>' +
      '<div class="val ' + cls + '">' + price + '</div>' +
      '<div class="chg ' + cls + '">' + signOf(pct) + pct.toFixed(2) + '%</div></div>';
  }).join("");
}

function initQuotes() {
  var box = document.getElementById("market-quotes");
  if (!box) return;
  renderQuotes(box, DEMO_QUOTES);
  function load() {
    fetch("/api/quotes").then(function (r) { return r.json(); })
      .then(function (d) { if (d && d.items && d.items.length) renderQuotes(box, d.items); })
      .catch(function () {});
  }
  load();
  setInterval(load, 15000);
}

/* ================= 风险测评 ================= */
function initRiskProfiler() {
  var form = document.getElementById("risk-form");
  if (!form) return;
  form.addEventListener("submit", function (e) {
    e.preventDefault();
    var data = new FormData(form), score = 0, count = 0;
    ["q1", "q2", "q3", "q4"].forEach(function (k) {
      var v = data.get(k);
      if (v !== null) { score += Number(v); count++; }
    });
    if (count < 4) { alert("请完成全部题目"); return; }

    var pct = Math.round(((score - 4) / 12) * 100);
    var levels = [
      { max: 25, name: "保守型", desc: "优先保本，建议以货币基金、国债、银行理财为主，股票仓位不超过20%。" },
      { max: 50, name: "稳健型", desc: "可承受小幅波动，建议宽基指数基金定投为主，单只股票仓位控制在10%以内。" },
      { max: 75, name: "平衡型", desc: "可承受中等波动，可采用指数+优质个股组合，注意分散行业。" },
      { max: 100, name: "进取型", desc: "追求高收益并能承受较大回撤，仍需设置止损、避免满仓单一股票。" }
    ];
    var level = levels.find(function (l) { return pct <= l.max; }) || levels[3];
    var out = document.getElementById("risk-result");
    out.style.display = "block";
    out.innerHTML =
      '<h3>你的风险等级：<span class="up">' + level.name + '</span>（风险值 ' + pct + '/100）</h3>' +
      '<div class="risk-gauge"><div class="risk-bar"><span class="dot" style="left:' + pct + '%"></span></div></div>' +
      '<p>' + level.desc + '</p>';
  });
}

/* ================= AI 个股分析 ================= */
function scoreRingColor(score) {
  if (score >= 65) return "#f85149";
  if (score >= 45) return "#d29922";
  return "#3fb950";
}

function toneCls(tone) { return tone === "bull" ? "up" : tone === "bear" ? "down" : "flat"; }

function renderAnalysis(d, horizon) {
  var cls = clsOf(Number(d.percent) || 0);
  var ratingCls = d.rating === "偏多" ? "up" : d.rating === "偏空" ? "down" : "flat";
  var ring = scoreRingColor(d.score);
  var notes = d.notes || {};

  var head =
    '<div class="analysis-head">' +
      '<div class="score-ring" style="--v:' + d.score + ';--ring:' + ring + '">' +
        '<span>' + d.score + '</span><small>趋势分</small>' +
      '</div>' +
      '<div>' +
        '<h3>' + d.name + ' <span class="muted">' + d.code + '</span></h3>' +
        '<p class="muted">现价 <span class="' + cls + '">' + fmt(d.price) + '</span> ' +
        '<span class="' + cls + '">' + signOf(d.percent) + fmt(d.percent) + '%</span></p>' +
        '<p>综合评级：<strong class="' + ratingCls + '">' + d.rating + '</strong>' +
        ' ｜ 风险：' + d.risk + ' ｜ 周期：' + horizon + '</p>' +
      '</div>' +
    '</div>';

  // 数据解读
  var summary = d.summary ?
    '<div class="analysis-summary"><h4>📖 数据解读</h4><p>' + d.summary + '</p></div>' : '';

  // 指标卡（数值 + 白话解读）
  function metric(label, value, noteKey) {
    var n = notes[noteKey] || {};
    return '<div class="metric">' +
      '<div class="k">' + label + '</div>' +
      '<div class="v">' + value + '</div>' +
      (n.note ? '<div class="note ' + toneCls(n.tone) + '">' + n.note + '</div>' : '') +
    '</div>';
  }
  var metrics = '<div class="metric-grid">' +
    metric("现价（元）", fmt(d.price), "price") +
    metric("MA5（5日均线）", fmt(d.ma5), "ma5") +
    metric("MA20（20日均线）", fmt(d.ma20), "ma20") +
    metric("RSI14（强弱）", d.rsi14 == null ? "--" : d.rsi14, "rsi14") +
    metric("60日位置", d.pos == null ? "--" : d.pos + "%", "pos") +
    metric("量比（5日）", d.volRatio == null ? "--" : d.volRatio, "volRatio") +
    metric("成交额", fmtAmount(d.amount), "amount") +
    metric("振幅", d.amp == null ? "--" : d.amp + "%", "range") +
    metric("近20日支撑", fmt(d.support), null) +
    metric("近20日压力", fmt(d.resistance), null) +
  '</div>';

  // 操作参考（按周期，高亮所选周期）
  var sel = /短/.test(horizon) ? "short" : /长/.test(horizon) ? "long" : "mid";
  var labels = { short: "短线（1周内）", mid: "中线（1–3个月）", long: "长线（半年以上）" };
  var adviceBox = d.advice ?
    '<div class="advice-box"><h4>🎯 操作参考（按持有周期）</h4><ul>' +
      Object.keys(labels).map(function (k) {
        return '<li class="' + (k === sel ? "active" : "") + '">' +
          '<b>' + labels[k] + '</b><span>' + d.advice[k] + '</span></li>';
      }).join("") +
    '</ul><p class="muted">以上为基于公开数据的规则化参考，非投资建议。</p></div>' : '';

  var spark = '<div class="spark-wrap"><div class="muted">近 30 日收盘走势</div>' +
    sparkline(d.spark, ring) + '</div>';

  var signals = '<div class="signal-title">关键信号</div><ul class="signals">' + (d.signals || []).map(function (s) {
    return '<li><span class="sig-dot sig-' + s.type + '"></span><span>' + s.text + '</span></li>';
  }).join("") + '</ul>';

  var foot = '<div class="callout warn" style="margin-top:16px">数据更新于 ' + (d.updated || "--") +
    '。以上为基于公开行情的辅助参考，<strong>不构成投资建议</strong>，请结合基本面与风险承受能力独立决策。</div>';

  return head + summary + metrics + spark + adviceBox + signals + foot;
}

function runAdvice(code, horizon) {
  var out = document.getElementById("advice-result");
  if (!out) return;
  out.style.display = "block";
  out.innerHTML = '<p class="muted">正在分析 ' + code + ' …</p>';
  fetch("/api/analyze?code=" + encodeURIComponent(code))
    .then(function (r) { return r.json(); })
    .then(function (d) {
      if (d.error) { out.innerHTML = '<p class="up">' + d.error + '</p>'; return; }
      out.innerHTML = renderAnalysis(d, horizon);
    })
    .catch(function () {
      out.innerHTML = '<p class="muted">未启动本地服务，无法分析。请运行 <code>python server.py</code>。</p>';
    });
}

function initAdvice() {
  var form = document.getElementById("advice-form");
  if (!form) return;
  var input = document.getElementById("stock-code");
  var horizonSel = document.getElementById("horizon");

  form.addEventListener("submit", function (e) {
    e.preventDefault();
    var code = input.value.trim().replace(/\D/g, "");
    if (!code) { alert("请输入股票代码"); return; }
    runAdvice(code, horizonSel.value);
  });

  // 支持从首页跳转：ai.html?code=600519#advice
  var code = (new URLSearchParams(location.search).get("code") || "").replace(/\D/g, "");
  if (code) {
    input.value = code;
    runAdvice(code, horizonSel.value);
    var target = document.getElementById("advice");
    if (target) target.scrollIntoView({ behavior: "smooth" });
  }
}

/* 首页快捷搜索：输入代码直接跳到 AI 分析 */
function initHomeSearch() {
  var form = document.getElementById("home-search");
  if (!form) return;
  form.addEventListener("submit", function (e) {
    e.preventDefault();
    var code = document.getElementById("home-code").value.trim().replace(/\D/g, "");
    if (!/^\d{6}$/.test(code)) { alert("请输入 6 位股票代码"); return; }
    location.href = "ai.html?code=" + code + "#advice";
  });
}

/* ================= 行情监控面板 ================= */
var WATCH_KEY = "astock_watchlist";
var THRESHOLD_KEY = "astock_threshold";

function loadWatch() {
  try { return JSON.parse(localStorage.getItem(WATCH_KEY)) || []; } catch (e) { return []; }
}
function saveWatch(list) { localStorage.setItem(WATCH_KEY, JSON.stringify(list)); }
function addWatchCode(code) {
  var list = loadWatch();
  if (list.indexOf(code) === -1) { list.push(code); saveWatch(list); }
}
function loadThreshold() {
  var v = parseFloat(localStorage.getItem(THRESHOLD_KEY));
  return isNaN(v) ? 3 : v;
}

function initWatchlist() {
  var body = document.getElementById("watch-body");
  if (!body) return;

  var input = document.getElementById("watch-input");
  var addBtn = document.getElementById("watch-add");
  var emptyTip = document.getElementById("watch-empty");
  var alertLog = document.getElementById("alert-log");
  var updated = document.getElementById("watch-updated");
  var thresholdInput = document.getElementById("alert-threshold");
  var table = body.closest("table");

  thresholdInput.value = loadThreshold();

  function render(quotes) {
    var threshold = parseFloat(thresholdInput.value) || 3;
    var list = loadWatch();
    if (!list.length) {
      body.innerHTML = "";
      emptyTip.style.display = "block";
      table.style.display = "none";
      alertLog.style.display = "none";
      return;
    }
    emptyTip.style.display = "none";
    table.style.display = "";

    var alerts = [];
    body.innerHTML = list.map(function (code) {
      var q = quotes && quotes[code];
      var name = q ? q.name : "--";
      var price = q ? fmt(q.price) : "--";
      var pct = q && q.percent != null ? q.percent : null;
      var cls = pct == null ? "flat" : clsOf(pct);
      var status = '<span class="status-pill status-normal">—</span>';
      if (pct != null && Math.abs(pct) >= threshold) {
        status = '<span class="status-pill ' + (pct > 0 ? "status-alert" : "status-down") + '">' +
          (pct > 0 ? "大涨预警" : "大跌预警") + '</span>';
        alerts.push({ name: name, code: code, pct: pct });
      }
      return '<tr>' +
        '<td>' + name + '</td>' +
        '<td class="muted">' + code + '</td>' +
        '<td class="' + cls + '">' + price + '</td>' +
        '<td class="' + cls + '">' + (pct == null ? "--" : signOf(pct) + pct.toFixed(2) + "%") + '</td>' +
        '<td>' + (q ? fmtAmount(q.amount) : "--") + '</td>' +
        '<td>' + status + '</td>' +
        '<td><button class="del" data-code="' + code + '" title="移除">×</button></td>' +
      '</tr>';
    }).join("");

    if (alerts.length) {
      alertLog.style.display = "block";
      alertLog.innerHTML = '<h4>⚠ 触发预警（阈值 ±' + threshold + '%）</h4><ul>' +
        alerts.map(function (a) {
          return '<li>' + a.name + '(' + a.code + ') 当前 ' +
            signOf(a.pct) + a.pct.toFixed(2) + '%</li>';
        }).join("") + '</ul>';
    } else {
      alertLog.style.display = "none";
    }
  }

  function refresh() {
    var list = loadWatch();
    if (!list.length) { render(null); return; }
    fetch("/api/quotes?codes=" + encodeURIComponent(list.join(",")))
      .then(function (r) { return r.json(); })
      .then(function (d) {
        var map = {};
        (d.items || []).forEach(function (q) { map[q.code] = q; });
        render(map);
        updated.textContent = "更新于 " + (d.updated || "");
      })
      .catch(function () {
        updated.textContent = "未连接服务（请运行 python server.py）";
        render(null);
      });
  }

  addBtn.addEventListener("click", function () {
    var code = input.value.trim().replace(/\D/g, "");
    if (!/^\d{6}$/.test(code)) { alert("请输入 6 位股票代码"); return; }
    var list = loadWatch();
    if (list.indexOf(code) === -1) { list.push(code); saveWatch(list); }
    input.value = "";
    refresh();
  });

  input.addEventListener("keydown", function (e) { if (e.key === "Enter") addBtn.click(); });

  body.addEventListener("click", function (e) {
    var btn = e.target.closest(".del");
    if (!btn) return;
    var code = btn.getAttribute("data-code");
    saveWatch(loadWatch().filter(function (c) { return c !== code; }));
    refresh();
  });

  thresholdInput.addEventListener("change", function () {
    localStorage.setItem(THRESHOLD_KEY, thresholdInput.value);
    refresh();
  });

  document.addEventListener("watchlist:changed", refresh);
  refresh();
  setInterval(refresh, 12000);
}

/* ================= 新手低风险参考池 ================= */
function renderLowRiskCard(d) {
  var cls = clsOf(Number(d.percent) || 0);
  return '<div class="lowrisk-card">' +
    '<div class="lr-top">' +
      '<h4>' + d.name + ' <span class="muted">' + d.code + '</span></h4>' +
      '<span class="risk-badge ' + d.levelCls + '">' + d.level + '险 ' + d.score + '</span>' +
    '</div>' +
    '<div class="lr-price">现价 <b>' + fmt(d.price) + '</b> ' +
      '<span class="' + cls + '">' + signOf(d.percent) + fmt(d.percent) + '%</span></div>' +
    '<ul class="lr-metrics">' +
      '<li>波动率 <b>' + d.vol + '%</b></li>' +
      '<li>最大回撤 <b>' + d.mdd + '%</b></li>' +
      '<li>成交额 <b>' + fmtAmount(d.amount) + '</b></li>' +
    '</ul>' +
    '<p class="lr-reason">' + (d.reasons || []).join(" · ") + '</p>' +
    '<button class="btn lr-add" data-code="' + d.code + '">加入监控</button>' +
  '</div>';
}

function initLowRisk() {
  var list = document.getElementById("lowrisk-list");
  if (!list) return;
  var updated = document.getElementById("lowrisk-updated");
  var note = document.getElementById("lowrisk-note");
  var refreshBtn = document.getElementById("lowrisk-refresh");

  function load() {
    list.innerHTML = '<p class="muted">正在筛选（约需数秒）…</p>';
    fetch("/api/lowrisk")
      .then(function (r) { return r.json(); })
      .then(function (d) {
        if (d.error) { list.innerHTML = '<p class="up">' + d.error + '</p>'; return; }
        updated.textContent = "样本 " + d.universe + " 只 · 更新于 " + d.updated;
        note.textContent = d.note || "";
        list.innerHTML = (d.items || []).map(renderLowRiskCard).join("");
      })
      .catch(function () {
        list.innerHTML = '<p class="muted">未启动本地服务，请运行 <code>python server.py</code>。</p>';
      });
  }

  list.addEventListener("click", function (e) {
    var btn = e.target.closest(".lr-add");
    if (!btn) return;
    addWatchCode(btn.getAttribute("data-code"));
    document.dispatchEvent(new Event("watchlist:changed"));
    btn.textContent = "已加入监控";
    btn.disabled = true;
  });

  refreshBtn.addEventListener("click", load);
  load();
}

/* ================= 我的持仓与卖出提示 ================= */
var HOLD_KEY = "astock_holdings";

function loadHoldings() {
  try { return JSON.parse(localStorage.getItem(HOLD_KEY)) || []; } catch (e) { return []; }
}
function saveHoldings(list) { localStorage.setItem(HOLD_KEY, JSON.stringify(list)); }

function actionClsMap(cls) {
  return cls === "danger" ? "act-danger" : cls === "warn" ? "act-warn" : "act-ok";
}

function renderHoldCard(h, p) {
  if (!p || p.error) {
    return '<div class="hold-card"><div class="hold-top"><h4>' + h.code +
      '</h4><span class="action-badge act-danger">数据异常</span></div>' +
      '<p class="muted">' + ((p && p.error) || "无法获取行情") + '</p>' +
      '<button class="del" data-id="' + h.id + '">移除</button></div>';
  }
  var cls = clsOf(Number(p.profitPct) || 0);
  var profitTxt = p.profit == null ? "--" : (p.profit >= 0 ? "+" : "") + fmt(p.profit) + " 元";
  var pctTxt = p.profitPct == null ? "" : " (" + signOf(p.profitPct) + fmt(p.profitPct) + "%)";
  return '<div class="hold-card">' +
    '<div class="hold-top">' +
      '<h4>' + p.name + ' <span class="muted">' + p.code + '</span></h4>' +
      '<span class="action-badge ' + actionClsMap(p.actionCls) + '">' + p.action + '</span>' +
    '</div>' +
    '<div class="hold-pnl">浮动盈亏 <b class="' + cls + '">' + profitTxt + pctTxt + '</b></div>' +
    '<ul class="hold-metrics">' +
      '<li>成本 <b>' + fmt(p.cost) + '</b></li>' +
      '<li>现价 <b>' + fmt(p.price) + '</b></li>' +
      '<li>数量 <b>' + fmt(p.qty, 0) + '</b></li>' +
      '<li>参考止损 <b class="down">' + fmt(p.stopLoss) + '</b></li>' +
      '<li>止盈一 <b class="up">' + fmt(p.target1) + '</b></li>' +
      '<li>止盈二 <b class="up">' + fmt(p.target2) + '</b></li>' +
      (p.trailing ? '<li>移动止盈 <b>' + fmt(p.trailing) + '</b></li>' : '') +
    '</ul>' +
    '<ul class="hold-reasons">' +
      (p.reasons || []).map(function (r) { return '<li>' + r + '</li>'; }).join("") +
    '</ul>' +
    '<button class="del" data-id="' + h.id + '">移除</button>' +
  '</div>';
}

function initHoldings() {
  var listEl = document.getElementById("hold-list");
  if (!listEl) return;
  var form = document.getElementById("hold-form");
  var summary = document.getElementById("hold-summary");
  var emptyTip = document.getElementById("hold-empty");

  function render(entries, plans) {
    if (!entries.length) {
      listEl.innerHTML = "";
      emptyTip.style.display = "block";
      summary.style.display = "none";
      return;
    }
    emptyTip.style.display = "none";
    listEl.innerHTML = entries.map(function (h, i) { return renderHoldCard(h, plans[i]); }).join("");

    var totalCost = 0, totalValue = 0, totalProfit = 0, hasPnl = false;
    plans.forEach(function (p) {
      if (p && !p.error && p.costValue != null) {
        totalCost += p.costValue;
        totalValue += p.marketValue || 0;
        totalProfit += p.profit || 0;
        hasPnl = true;
      }
    });
    if (hasPnl) {
      summary.style.display = "flex";
      var tcls = clsOf(totalProfit);
      summary.innerHTML =
        '<span>总成本 <b>' + fmt(totalCost) + '</b></span>' +
        '<span>总市值 <b>' + fmt(totalValue) + '</b></span>' +
        '<span>总盈亏 <b class="' + tcls + '">' + (totalProfit >= 0 ? "+" : "") + fmt(totalProfit) + '</b></span>' +
        '<span>盈亏率 <b class="' + tcls + '">' + (totalCost ? (totalProfit / totalCost * 100 >= 0 ? "+" : "") + fmt(totalProfit / totalCost * 100) + "%" : "--") + '</b></span>';
    } else {
      summary.style.display = "none";
    }
  }

  function refresh() {
    var entries = loadHoldings();
    var valid = entries.filter(function (h) { return /^\d{6}$/.test(h.code); });
    if (!valid.length) { render([], []); return; }
    fetch("/api/sellplan", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ holdings: valid.map(function (h) { return { code: h.code, cost: h.cost, qty: h.qty }; }) })
    })
      .then(function (r) { return r.json(); })
      .then(function (d) { render(valid, d.items || []); })
      .catch(function () {
        listEl.innerHTML = '<p class="muted">未启动本地服务，请运行 <code>python server.py</code>。</p>';
        emptyTip.style.display = "none";
        summary.style.display = "none";
      });
  }

  form.addEventListener("submit", function (e) {
    e.preventDefault();
    var code = document.getElementById("hold-code").value.trim().replace(/\D/g, "");
    var cost = parseFloat(document.getElementById("hold-cost").value);
    var qty = parseFloat(document.getElementById("hold-qty").value);
    var date = document.getElementById("hold-date").value;
    if (!/^\d{6}$/.test(code)) { alert("请输入 6 位股票代码"); return; }
    if (!(cost > 0)) { alert("请输入有效的买入价"); return; }
    if (!(qty > 0)) { alert("请输入有效的数量"); return; }
    var list = loadHoldings();
    list.push({ id: String(Date.now()) + Math.floor(Math.random() * 1000), code: code, cost: cost, qty: qty, date: date });
    saveHoldings(list);
    form.reset();
    refresh();
  });

  listEl.addEventListener("click", function (e) {
    var btn = e.target.closest(".del");
    if (!btn) return;
    var id = btn.getAttribute("data-id");
    saveHoldings(loadHoldings().filter(function (h) { return h.id !== id; }));
    refresh();
  });

  refresh();
  setInterval(refresh, 12000);
}
