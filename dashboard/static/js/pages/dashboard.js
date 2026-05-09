// ===========================================================================
// 全局静态常量
// ===========================================================================
const colors = {
  积极: "#22a06b",
  愤怒: "#dc3f45",
  悲伤: "#3578d4",
  恐惧: "#7c4cc2",
  惊讶: "#f59e2f",
  中性: "#8b95a1",
};

const emotions = ["积极", "愤怒", "悲伤", "恐惧", "惊讶", "中性"];

let trend = [];
let topics = [];
let selectedTopic = null;

// ===========================================================================
// helper
// ===========================================================================
function el(selector) {
  return document.querySelector(selector);
}

async function fetchJSON(path) {
  const r = await fetch(path);
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}

function escapeHTML(value) {
  return String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}

// 中文友好的大数字格式化：>= 1 亿 → "X.XX 亿"，>= 1 万 → "X.XX 万"，否则千分号。
function formatLargeNumber(n) {
  if (n == null) return "—";
  if (n >= 100_000_000) return (n / 100_000_000).toFixed(2) + " 亿";
  if (n >= 10_000)      return (n / 10_000).toFixed(2) + " 万";
  return n.toLocaleString("zh-CN");
}

function formatPercent(x, digits = 1) {
  if (x == null || Number.isNaN(Number(x))) return "—";
  return (Number(x) * 100).toFixed(digits) + "%";
}

function formatDateTime(iso) {
  const d = new Date(iso);
  const pad = (x) => String(x).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

function formatWindow(meta) {
  const w = meta.data_window;
  return `${formatDateTime(w.start)} ~ ${formatDateTime(w.end)}（${w.available_days} 天）`;
}

// ===========================================================================
// API-driven render
// ===========================================================================
function renderHero(meta) {
  el("#dataWindowSpan").textContent = formatWindow(meta);
  el("#modelSpan").textContent = `模型版本：${meta.model.model_version || meta.model.name}`;
  el("#riskBadge").textContent = "本地 CK 实时聚合";
}

function renderKpisFromApi(overview, meta) {
  const days = meta?.data_window?.available_days ?? null;
  const range = days ? `近 ${days} 天` : "近期";
  const cards = [
    { label: "帖子数",       value: formatLargeNumber(overview.post_count),            sub: range },
    { label: "采样评论数",   value: formatLargeNumber(overview.sampled_comment_count), sub: `${range} · 采样` },
    { label: "活跃话题",     value: formatLargeNumber(overview.active_topic_count),    sub: `热榜登记 · ${range}` },
    { label: "累计互动",     value: formatLargeNumber(overview.latest_interactions),   sub: "argMax · 平台快照" },
    {
      label: "负面舆情指数",
      value: overview.risk_index == null ? "—" : overview.risk_index.toFixed(1),
      sub:   overview.risk_index == null ? "等情绪预测就位" : `负面率 ${formatPercent(overview.negative_ratio)}`,
      placeholder: overview.risk_index == null,
    },
  ];
  el("#kpiGrid").innerHTML = cards.map((c) => `
    <article class="panel kpi-card"${c.placeholder ? ' style="opacity:0.65"' : ""}>
      <span>${c.label}</span>
      <strong>${c.value}</strong>
      <small>${c.sub}</small>
    </article>
  `).join("");
}

function renderDataQuality(dq) {
  const items = [
    dq.history_window_notice,
    dq.comment_sampling_notice,
    dq.engagement_notice,
    dq.timezone_notice,
    dq.user_tier_notice,
    dq.post_discovery_notice,
  ].filter(Boolean);

  const tier = dq.profile_tier_distribution || {};
  const tierStr = Object.entries(tier)
    .sort(([a], [b]) => Number(a) - Number(b))
    .map(([t, p]) => `tier${t} ${(p * 100).toFixed(0)}%`)
    .join(" · ");
  if (tierStr) items.push(`窗口内用户画像覆盖：${tierStr}`);

  el("#dataQualityList").innerHTML = items.map((t) => `<li>${escapeHTML(t)}</li>`).join("");
}

// ===========================================================================
// CK API 数据渲染
// ===========================================================================
function renderLegend() {
  el("#emotionLegend").innerHTML = emotions.map((name) => `
    <span><i style="background:${colors[name]}"></i>${name}</span>
  `).join("");
}

function areaPath(points, basePoints) {
  const top = points.map((p, index) => `${index === 0 ? "M" : "L"}${p.x},${p.y}`).join(" ");
  const bottom = basePoints.slice().reverse().map((p) => `L${p.x},${p.y}`).join(" ");
  return `${top} ${bottom} Z`;
}

function renderTrend() {
  const svg = el("#trendChart");
  if (!trend.length) {
    svg.innerHTML = '<text class="chart-label" x="330" y="150">暂无趋势数据</text>';
    return;
  }
  const width = 760;
  const height = 300;
  const pad = { top: 20, right: 18, bottom: 34, left: 38 };
  const innerW = width - pad.left - pad.right;
  const innerH = height - pad.top - pad.bottom;
  const totals = trend.map((row) => emotions.reduce((sum, name) => sum + (row.counts?.[name] || 0), 0));
  const maxTotal = Math.max(...totals, 1);
  const x = (index) => trend.length === 1 ? pad.left + innerW / 2 : pad.left + (innerW / (trend.length - 1)) * index;
  const y = (value) => pad.top + innerH - (value / maxTotal) * innerH;
  const stacks = trend.map(() => 0);
  const parts = [];

  [0.25, 0.5, 0.75, 1].forEach((tick) => {
    const tickValue = maxTotal * tick;
    const yy = y(tickValue);
    parts.push(`<line class="grid-line" x1="${pad.left}" y1="${yy}" x2="${width - pad.right}" y2="${yy}"></line>`);
    parts.push(`<text class="chart-label" x="8" y="${yy + 4}">${formatLargeNumber(Math.round(tickValue))}</text>`);
  });

  emotions.forEach((name) => {
    const base = trend.map((_, index) => ({ x: x(index), y: y(stacks[index]) }));
    trend.forEach((row, index) => { stacks[index] += row.counts?.[name] || 0; });
    const top = trend.map((_, index) => ({ x: x(index), y: y(stacks[index]) }));
    parts.push(`<path d="${areaPath(top, base)}" fill="${colors[name]}" opacity="0.72"></path>`);
  });

  parts.push(`<line class="axis" x1="${pad.left}" y1="${height - pad.bottom}" x2="${width - pad.right}" y2="${height - pad.bottom}"></line>`);
  trend.forEach((row, index) => {
    parts.push(`<text class="chart-label" x="${x(index) - 16}" y="${height - 10}">${escapeHTML(String(row.time || '').slice(5))}</text>`);
  });
  svg.innerHTML = parts.join("");
}

function renderTopics() {
  if (!topics.length) {
    el("#topicList").innerHTML = '<p class="muted">暂无风险话题数据</p>';
    renderExplain();
    renderEvidence([]);
    return;
  }
  el("#topicList").innerHTML = topics.map((topic) => `
    <button class="topic-item ${String(topic.topic_id) === String(selectedTopic) ? "active" : ""}" data-topic="${escapeHTML(topic.topic_id)}">
      <div class="topic-top"><span class="topic-name">#${escapeHTML(topic.title)}#</span><span class="score">${Number(topic.risk_score || 0).toFixed(1)}</span></div>
      <div class="topic-meta">
        <span class="emotion-tag"><i style="background:${colors[topic.dominant_emotion] || colors.中性}"></i>${escapeHTML(topic.dominant_emotion || "中性")}</span>
        <span>增长 ${escapeHTML(topic.negative_growth_label || "—")}</span>
        <span>负面率 ${formatPercent(topic.negative_ratio)}</span>
        <span>risk_score</span>
      </div>
    </button>
  `).join("");

  document.querySelectorAll(".topic-item").forEach((button) => {
    button.addEventListener("click", () => {
      selectedTopic = button.dataset.topic;
      renderTopics();
      renderExplain();
      loadEvidence(selectedTopic);
    });
  });
}

function renderExplain() {
  const topic = topics.find((item) => String(item.topic_id) === String(selectedTopic));
  if (!topic) {
    el("#explainTitle").textContent = "风险解释卡";
    el("#explainScore").textContent = "暂无数据";
    el("#explainNote").textContent = "等待风险话题接口返回。";
    el("#riskBars").innerHTML = "";
    return;
  }
  const labels = topic.risk_factor_labels || {};
  el("#explainTitle").textContent = `#${topic.title}#`;
  el("#explainScore").textContent = `风险分 ${Number(topic.risk_score || 0).toFixed(1)}`;
  el("#explainNote").textContent = topic.note || "风险分由情绪结构、互动增量和扩散入口共同计算。";
  el("#riskBars").innerHTML = Object.entries(topic.risk_factors || {}).map(([name, value]) => `
    <div class="bar-row">
      <span>${escapeHTML(labels[name] || name)}</span>
      <div class="bar-track"><div class="bar-fill" style="width:${Math.min(100, Number(value || 0) * 4)}%"></div></div>
      <strong>${Number(value || 0).toFixed(1)}</strong>
    </div>
  `).join("");
}

function renderEvidence(items) {
  const topic = topics.find((item) => String(item.topic_id) === String(selectedTopic));
  el("#evidenceFilter").textContent = topic ? `#${topic.title}#` : "全部话题";
  if (!items.length) {
    el("#evidenceList").innerHTML = '<p class="muted">暂无证据样本</p>';
    return;
  }
  el("#evidenceList").innerHTML = items.map((item) => `
    <article class="evidence-item">
      <p class="evidence-text">${escapeHTML(item.content)}</p>
      <div class="evidence-meta">
        <span class="emotion-tag"><i style="background:${colors[item.pred_label] || colors.中性}"></i>${escapeHTML(item.pred_label)}</span>
        <span class="metric-chip">置信度 ${Number(item.confidence || 0).toFixed(2)}</span>
        <span class="metric-chip">top2 margin ${Number(item.margin || 0).toFixed(2)}</span>
        <span class="metric-chip">${formatLargeNumber(item.interaction_count || 0)} 互动</span>
        <span class="metric-chip">${escapeHTML(item.actor_role || "普通账号")}</span>
      </div>
    </article>
  `).join("");
}

function renderModelQuality(mq) {
  const fmtPct = (x) => x == null ? "—" : (x * 100).toFixed(1) + "%";
  const fmtF1 = (x) => x == null ? "—" : x.toFixed(4);
  const be = mq.business_eval;
  const st = mq.smp_test;

  // 顶部 4 个小卡：业务集 / SMP test 各两个 (macro_f1 + accuracy)
  const metrics = [
    { v: fmtF1(be?.macro_f1),  s: "macro-F1 · 业务集" },
    { v: fmtPct(be?.accuracy), s: "accuracy · 业务集" },
    { v: fmtF1(st?.macro_f1),  s: "macro-F1 · SMP test" },
    { v: fmtPct(st?.accuracy), s: "accuracy · SMP test" },
  ];
  el("#modelMetrics").innerHTML = metrics.map((m) => `
    <div><strong>${m.v}</strong><span>${m.s}</span></div>
  `).join("");

  // 易混淆 Top 3（来自业务集混淆矩阵）
  const confusions = mq.top_confusions || [];
  el("#confusionBox").innerHTML = `
    <h3>易混淆标签（业务集 Top ${confusions.length}）</h3>
    ${confusions.length === 0
      ? '<p class="muted">无可用混淆数据</p>'
      : confusions.map((c) => `
          <p>真实「${escapeHTML(c.true)}」 → 预测「${escapeHTML(c.pred)}」：${c.count} 条</p>
        `).join("")}
  `;

  // BERT 对照
  const bc = mq.bert_comparison;
  if (!bc) {
    el("#compareBox").innerHTML = '<h3>BERT 对照说明</h3><p class="muted">无对照数据</p>';
  } else {
    el("#compareBox").innerHTML = `
      <h3>BERT 对照说明</h3>
      <p>${escapeHTML(bc.usage)}：${escapeHTML(bc.name)} 在业务集上 accuracy ${fmtPct(bc.bert_accuracy)} / macro-F1 ${fmtF1(bc.bert_macro_f1)}；
         ${escapeHTML(mq.primary_model)} 与 BERT 一致率 ${fmtPct(bc.agreement_rate)}，oracle 上限 ${fmtPct(bc.oracle_accuracy)}。</p>
      <p>分歧样本中 ${escapeHTML(mq.primary_model)} 多答对 ${bc.ernie_only_correct} 条，BERT 多答对 ${bc.bert_only_correct} 条。</p>
    `;
  }
}

async function loadEvidence(topicId) {
  if (!topicId) {
    renderEvidence([]);
    return;
  }
  el("#evidenceList").innerHTML = '<p class="muted">正在加载证据样本...</p>';
  try {
    const rows = await fetchJSON(`/api/dashboard/evidence?topic_id=${encodeURIComponent(topicId)}&limit=8`);
    renderEvidence(rows);
  } catch (err) {
    el("#evidenceList").innerHTML = `<p class="muted">证据样本加载失败：${escapeHTML(err.message)}</p>`;
  }
}

// ===========================================================================
// 启动：并行 fetch 各 API。任一 API 失败只影响对应区域。
// ===========================================================================
renderLegend();
renderTrend();
renderExplain();
renderEvidence([]);

const metaPromise = fetchJSON("/api/dashboard/meta");

metaPromise.then(renderHero).catch((err) => {
  el("#dataWindowSpan").textContent = "数据窗口加载失败";
  el("#modelSpan").textContent = err.message;
});

Promise.all([
  fetchJSON("/api/dashboard/overview"),
  metaPromise.catch(() => null),
])
  .then(([overview, meta]) => renderKpisFromApi(overview, meta))
  .catch((err) => {
    el("#kpiGrid").innerHTML = `
      <article class="panel kpi-card warn" style="grid-column: span 5">
        <span>KPI 加载失败</span>
        <strong>—</strong>
        <small>${escapeHTML(err.message)}</small>
      </article>`;
  });

fetchJSON("/api/dashboard/data-quality").then(renderDataQuality).catch((err) => {
  el("#dataQualityList").innerHTML = `<li>加载失败：${escapeHTML(err.message)}</li>`;
});

fetchJSON("/api/dashboard/model-quality").then(renderModelQuality).catch((err) => {
  el("#modelMetrics").innerHTML = `<div><strong>—</strong><span>加载失败</span></div>`;
  el("#confusionBox").innerHTML = `<h3>易混淆标签</h3><p class="muted">加载失败：${escapeHTML(err.message)}</p>`;
  el("#compareBox").innerHTML = `<h3>BERT 对照说明</h3><p class="muted">加载失败：${escapeHTML(err.message)}</p>`;
});

fetchJSON("/api/dashboard/emotion-timeseries")
  .then((rows) => {
    trend = rows;
    renderTrend();
  })
  .catch((err) => {
    el("#trendChart").innerHTML = `<text class="chart-label" x="280" y="150">趋势加载失败：${escapeHTML(err.message)}</text>`;
  });

fetchJSON("/api/dashboard/risk-topics?limit=20")
  .then((rows) => {
    topics = rows;
    selectedTopic = topics[0]?.topic_id ?? null;
    renderTopics();
    renderExplain();
    return loadEvidence(selectedTopic);
  })
  .catch((err) => {
    el("#topicList").innerHTML = `<p class="muted">风险话题加载失败：${escapeHTML(err.message)}</p>`;
    renderExplain();
    renderEvidence([]);
  });
