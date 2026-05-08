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

// ---------------------------------------------------------------------------
// 以下数据仍是硬编码 mock。trend / topics / evidence 依赖情绪预测表
// (dashboard.sentiment_prediction)，等阶段 B 跑完业务推理 + 阶段 C 上线
// emotion-timeseries / risk-topics / evidence endpoint 后切真数据。
// ---------------------------------------------------------------------------
const trend = [
  { day: "05-01", 积极: 22, 愤怒: 18, 悲伤: 12, 恐惧: 8, 惊讶: 9, 中性: 31 },
  { day: "05-02", 积极: 19, 愤怒: 21, 悲伤: 13, 恐惧: 9, 惊讶: 8, 中性: 30 },
  { day: "05-03", 积极: 17, 愤怒: 25, 悲伤: 14, 恐惧: 11, 惊讶: 9, 中性: 24 },
  { day: "05-04", 积极: 15, 愤怒: 29, 悲伤: 13, 恐惧: 13, 惊讶: 10, 中性: 20 },
  { day: "05-05", 积极: 18, 愤怒: 27, 悲伤: 12, 恐惧: 12, 惊讶: 12, 中性: 19 },
  { day: "05-06", 积极: 20, 愤怒: 23, 悲伤: 11, 恐惧: 10, 惊讶: 11, 中性: 25 },
  { day: "05-07", 积极: 21, 愤怒: 20, 悲伤: 10, 恐惧: 9, 惊讶: 8, 中性: 32 },
];

const topics = [
  { id: "refund",  name: "#售后退款进度#", score: 86, emotion: "愤怒", growth: "+41%", negative: "68%", note: "高风险主要来自愤怒评论集中增长，且有认证账号参与扩散。", factors: { 负面占比: 31, 增长速度: 24, 互动增量: 18, "愤怒/恐惧": 20, "KOL/认证": 7 } },
  { id: "safety",  name: "#线下活动安全#", score: 78, emotion: "恐惧", growth: "+33%", negative: "61%", note: "风险由恐惧情绪和互动增量共同驱动，需优先核查事实信息。", factors: { 负面占比: 25, 增长速度: 19, 互动增量: 22, "愤怒/恐惧": 23, "KOL/认证": 11 } },
  { id: "launch",  name: "#新品发布体验#", score: 64, emotion: "惊讶", growth: "+19%", negative: "43%", note: "惊讶和中性讨论占比较高，负面主要集中在价格和供货。", factors: { 负面占比: 20, 增长速度: 14, 互动增量: 19, "愤怒/恐惧": 8,  "KOL/认证": 6 } },
  { id: "service", name: "#客服响应慢#",   score: 59, emotion: "悲伤", growth: "+12%", negative: "52%", note: "负面率偏高但传播速度较低，适合进入服务工单跟踪。",     factors: { 负面占比: 28, 增长速度: 9,  互动增量: 10, "愤怒/恐惧": 9,  "KOL/认证": 3 } },
];

const evidence = [
  { topic: "refund",  text: "申请退款已经 5 天还没有明确回复，客服每次都说继续等待，真的很影响信任。",  emotion: "愤怒", confidence: "0.91", margin: "0.27", tier: "T2 用户" },
  { topic: "refund",  text: "看到好几个认证账号也在问同一批订单，感觉这个问题不是个例。",                  emotion: "愤怒", confidence: "0.84", margin: "0.18", tier: "认证参与" },
  { topic: "safety",  text: "现场排队太密集了，如果下雨或者临时改动路线，会不会有安全隐患？",            emotion: "恐惧", confidence: "0.88", margin: "0.22", tier: "T3 用户" },
  { topic: "launch",  text: "发布会功能点挺意外，但价格比预期高不少，想再观望一下首批反馈。",            emotion: "惊讶", confidence: "0.79", margin: "0.13", tier: "T2 用户" },
  { topic: "service", text: "不是想吵架，只是问题拖太久了，反复解释真的有点疲惫。",                      emotion: "悲伤", confidence: "0.82", margin: "0.19", tier: "T1 用户" },
];

let selectedTopic = topics[0].id;

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

// 中文友好的大数字格式化：>= 1 亿 → "X.XX 亿"，>= 1 万 → "X.XX 万"，否则千分号。
function formatLargeNumber(n) {
  if (n == null) return "—";
  if (n >= 100_000_000) return (n / 100_000_000).toFixed(2) + " 亿";
  if (n >= 10_000)      return (n / 10_000).toFixed(2) + " 万";
  return n.toLocaleString("zh-CN");
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
  el("#modelSpan").textContent = `模型版本：${meta.model.name}`;
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
      sub:   overview.risk_index == null ? "等情绪预测就位" : range,
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

  el("#dataQualityList").innerHTML = items.map((t) => `<li>${t}</li>`).join("");
}

// ===========================================================================
// 静态 mock 渲染（保留，等阶段 C/D 切）
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
  const width = 760;
  const height = 300;
  const pad = { top: 20, right: 18, bottom: 34, left: 38 };
  const innerW = width - pad.left - pad.right;
  const innerH = height - pad.top - pad.bottom;
  const totals = trend.map((row) => emotions.reduce((sum, name) => sum + row[name], 0));
  const maxTotal = Math.max(...totals);
  const x = (index) => pad.left + (innerW / (trend.length - 1)) * index;
  const y = (value) => pad.top + innerH - (value / maxTotal) * innerH;
  const stacks = trend.map(() => 0);
  const parts = [];

  [25, 50, 75, 100].forEach((tick) => {
    const yy = y(tick);
    parts.push(`<line class="grid-line" x1="${pad.left}" y1="${yy}" x2="${width - pad.right}" y2="${yy}"></line>`);
    parts.push(`<text class="chart-label" x="8" y="${yy + 4}">${tick}%</text>`);
  });

  emotions.forEach((name) => {
    const base = trend.map((_, index) => ({ x: x(index), y: y(stacks[index]) }));
    trend.forEach((row, index) => { stacks[index] += row[name]; });
    const top = trend.map((_, index) => ({ x: x(index), y: y(stacks[index]) }));
    parts.push(`<path d="${areaPath(top, base)}" fill="${colors[name]}" opacity="0.72"></path>`);
  });

  parts.push(`<line class="axis" x1="${pad.left}" y1="${height - pad.bottom}" x2="${width - pad.right}" y2="${height - pad.bottom}"></line>`);
  trend.forEach((row, index) => {
    parts.push(`<text class="chart-label" x="${x(index) - 16}" y="${height - 10}">${row.day}</text>`);
  });
  svg.innerHTML = parts.join("");
}

function renderTopics() {
  el("#topicList").innerHTML = topics.map((topic) => `
    <button class="topic-item ${topic.id === selectedTopic ? "active" : ""}" data-topic="${topic.id}">
      <div class="topic-top"><span class="topic-name">${topic.name}</span><span class="score">${topic.score}</span></div>
      <div class="topic-meta">
        <span class="emotion-tag"><i style="background:${colors[topic.emotion]}"></i>${topic.emotion}</span>
        <span>增长 ${topic.growth}</span>
        <span>负面率 ${topic.negative}</span>
        <span>risk_score</span>
      </div>
    </button>
  `).join("");

  document.querySelectorAll(".topic-item").forEach((button) => {
    button.addEventListener("click", () => {
      selectedTopic = button.dataset.topic;
      renderTopics();
      renderExplain();
      renderEvidence();
    });
  });
}

function renderExplain() {
  const topic = topics.find((item) => item.id === selectedTopic);
  el("#explainTitle").textContent = topic.name;
  el("#explainScore").textContent = `风险分 ${topic.score}`;
  el("#explainNote").textContent = topic.note;
  el("#riskBars").innerHTML = Object.entries(topic.factors).map(([name, value]) => `
    <div class="bar-row">
      <span>${name}</span>
      <div class="bar-track"><div class="bar-fill" style="width:${value}%"></div></div>
      <strong>${value}</strong>
    </div>
  `).join("");
}

function renderEvidence() {
  const topic = topics.find((item) => item.id === selectedTopic);
  const items = evidence.filter((item) => item.topic === selectedTopic);
  el("#evidenceFilter").textContent = topic.name;
  el("#evidenceList").innerHTML = items.map((item) => `
    <article class="evidence-item">
      <p class="evidence-text">${item.text}</p>
      <div class="evidence-meta">
        <span class="emotion-tag"><i style="background:${colors[item.emotion]}"></i>${item.emotion}</span>
        <span class="metric-chip">置信度 ${item.confidence}</span>
        <span class="metric-chip">top2 margin ${item.margin}</span>
        <span class="metric-chip">${item.tier}</span>
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
          <p>真实「${c.true}」 → 预测「${c.pred}」：${c.count} 条</p>
        `).join("")}
  `;

  // BERT 对照
  const bc = mq.bert_comparison;
  if (!bc) {
    el("#compareBox").innerHTML = '<h3>BERT 对照说明</h3><p class="muted">无对照数据</p>';
  } else {
    el("#compareBox").innerHTML = `
      <h3>BERT 对照说明</h3>
      <p>${bc.usage}：${bc.name} 在业务集上 accuracy ${fmtPct(bc.bert_accuracy)} / macro-F1 ${fmtF1(bc.bert_macro_f1)}；
         ${mq.primary_model} 与 BERT 一致率 ${fmtPct(bc.agreement_rate)}，oracle 上限 ${fmtPct(bc.oracle_accuracy)}。</p>
      <p>分歧样本中 ${mq.primary_model} 多答对 ${bc.ernie_only_correct} 条，BERT 多答对 ${bc.bert_only_correct} 条。</p>
    `;
  }
}

// ===========================================================================
// 启动：先渲染硬编码 mock，再并行 fetch 各 API。任一 API 失败只影响对应区域。
// ===========================================================================
renderLegend();
renderTrend();
renderTopics();
renderExplain();
renderEvidence();

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
        <small>${err.message}</small>
      </article>`;
  });

fetchJSON("/api/dashboard/data-quality").then(renderDataQuality).catch((err) => {
  el("#dataQualityList").innerHTML = `<li>加载失败：${err.message}</li>`;
});

fetchJSON("/api/dashboard/model-quality").then(renderModelQuality).catch((err) => {
  el("#modelMetrics").innerHTML = `<div><strong>—</strong><span>加载失败</span></div>`;
  el("#confusionBox").innerHTML = `<h3>易混淆标签</h3><p class="muted">加载失败：${err.message}</p>`;
  el("#compareBox").innerHTML = `<h3>BERT 对照说明</h3><p class="muted">加载失败：${err.message}</p>`;
});
