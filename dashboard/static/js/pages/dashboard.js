// ===========================================================================
// 全局静态常量
// ===========================================================================
const EMOTIONS = ["积极", "愤怒", "悲伤", "恐惧", "惊讶", "中性"];
const COLORS = {
  积极: "#22a06b",
  愤怒: "#dc3f45",
  悲伤: "#3578d4",
  恐惧: "#7c4cc2",
  惊讶: "#f59e2f",
  中性: "#8b95a1",
};
const RANGE_LABELS = {
  all_available: "全部可用",
  "24h": "近 24 小时",
  "7d": "近 7 天",
};
const SOURCE_TYPE_LABELS = {
  hot: "热搜",
  keyword: "关键词",
  kol: "KOL",
  retweet: "转发",
};
const SOURCE_TYPE_KEYS = ["hot", "keyword", "kol", "retweet"];
const ROLE_LABELS = {
  verified_actor: "认证",
  high_follower_actor: "高粉",
  negative_actor: "负面活跃",
  active_actor: "活跃",
  event_key_actor: "事件关键",
  ordinary_actor: "普通",
};

// ===========================================================================
// 全局 state（单一可信来源）
// ===========================================================================
const state = {
  range: "all_available",
  rangeOptions: [],
  selectedTopicId: null,
  meta: null,
  overview: null,
  trend: [],
  topics: [],
  topicDetail: null,
  actors: [],
  influenceEmotion: [],
  dataQuality: null,
  modelQuality: null,
};

// 请求序号防御：切换 range / topic 时分别 +1。异步返回时校对序号，
// 序号过期则丢弃，避免旧请求覆盖新状态。
const tokens = { range: 0, topic: 0 };
const charts = {};

// ===========================================================================
// helpers
// ===========================================================================
function el(selector) {
  return document.querySelector(selector);
}

function escapeHTML(value) {
  return String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}

async function fetchJSON(path) {
  const r = await fetch(path);
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}

function rangeQS() {
  return `range=${encodeURIComponent(state.range || "all_available")}`;
}

function withTopic(qs) {
  const tid = state.selectedTopicId;
  if (!tid) return qs;
  // topic_id 始终以字符串形式拼接到 URL，避免 UInt64 → Number 的精度丢失。
  return `${qs}&topic_id=${encodeURIComponent(String(tid))}`;
}

function formatLargeNumber(n) {
  if (n == null || Number.isNaN(Number(n))) return "—";
  const v = Number(n);
  if (Math.abs(v) >= 1e8) return (v / 1e8).toFixed(2) + " 亿";
  if (Math.abs(v) >= 1e4) return (v / 1e4).toFixed(2) + " 万";
  return v.toLocaleString("zh-CN");
}

function formatPercent(x, digits = 1) {
  if (x == null || Number.isNaN(Number(x))) return "—";
  return (Number(x) * 100).toFixed(digits) + "%";
}

// API 已返回东八区 ISO；前端只剥离时区显示，不做时区再换算。
function formatDateTime(iso) {
  if (!iso) return "—";
  const m = String(iso).match(/^(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2})/);
  return m ? `${m[1]}-${m[2]}-${m[3]} ${m[4]}:${m[5]}` : String(iso);
}

function formatWindow(meta) {
  const w = meta && meta.data_window;
  if (!w) return "—";
  return `${formatDateTime(w.start)} ~ ${formatDateTime(w.end)}（${w.available_days} 天）`;
}

function rangeLabel() {
  return RANGE_LABELS[state.range] || state.range || "近期";
}

// ===========================================================================
// ECharts 包裹层：CDN 不可用时降级为提示文本，整页不白屏。
// ===========================================================================
function hasECharts() {
  return typeof window !== "undefined" && !!window.echarts;
}

function ensureChart(id) {
  const node = document.getElementById(id);
  if (!node) return null;
  if (!hasECharts()) {
    node.innerHTML = '<p class="muted">ECharts 未加载（CDN 不可用），暂不展示图表。</p>';
    return null;
  }
  let chart = charts[id];
  if (!chart || chart.isDisposed()) {
    chart = window.echarts.init(node);
    charts[id] = chart;
  }
  return chart;
}

function renderChart(id, option) {
  const chart = ensureChart(id);
  if (!chart) return;
  chart.setOption(option, true);
}

function clearChart(id, message = "暂无数据") {
  const node = document.getElementById(id);
  if (!node) return;
  if (!hasECharts()) {
    node.innerHTML = `<p class="muted">${escapeHTML(message)}</p>`;
    return;
  }
  const chart = ensureChart(id);
  if (!chart) return;
  chart.clear();
  chart.setOption({
    title: {
      text: message,
      left: "center",
      top: "middle",
      textStyle: { color: "#8b95a1", fontSize: 13, fontWeight: 400 },
    },
  });
}

window.addEventListener("resize", () => {
  Object.values(charts).forEach((c) => { if (c && !c.isDisposed()) c.resize(); });
});

// ===========================================================================
// 共用 ECharts option 构造
// ===========================================================================
function buildEmotionStackOption(rows) {
  const labels = rows.map((r) => r.time);
  const series = EMOTIONS.map((name) => ({
    name,
    type: "line",
    stack: "total",
    smooth: true,
    showSymbol: false,
    areaStyle: { opacity: 0.72 },
    lineStyle: { width: 1 },
    itemStyle: { color: COLORS[name] },
    data: rows.map((r) => Number((r && r.counts && r.counts[name]) || 0)),
  }));
  return {
    grid: { top: 24, left: 8, right: 16, bottom: 32, containLabel: true },
    tooltip: { trigger: "axis", axisPointer: { type: "line" } },
    legend: { show: false },
    xAxis: {
      type: "category",
      data: labels,
      boundaryGap: false,
      axisLabel: { color: "#667085", fontSize: 11 },
      axisLine: { lineStyle: { color: "#d8dee8" } },
    },
    yAxis: {
      type: "value",
      axisLabel: {
        color: "#667085",
        fontSize: 11,
        formatter: (val) => formatLargeNumber(val),
      },
      splitLine: { lineStyle: { color: "#edf1f6" } },
    },
    series,
  };
}

// ===========================================================================
// Range tabs
// ===========================================================================
function renderRangeTabs() {
  const opts = state.rangeOptions.length ? state.rangeOptions : ["all_available"];
  el("#rangeTabs").innerHTML = opts.map((opt) => `
    <button class="range-tab ${opt === state.range ? "active" : ""}" data-range="${escapeHTML(opt)}" type="button" role="tab" aria-selected="${opt === state.range}">
      ${escapeHTML(RANGE_LABELS[opt] || opt)}
    </button>
  `).join("");
  document.querySelectorAll(".range-tab").forEach((btn) => {
    btn.addEventListener("click", () => {
      const next = btn.dataset.range;
      if (!next || next === state.range) return;
      state.range = next;
      renderRangeTabs();
      reloadRangeScopedData();
    });
  });
}

// ===========================================================================
// Hero / KPI / data-quality / model-quality
// ===========================================================================
function renderHero() {
  const meta = state.meta;
  if (!meta) {
    el("#dataWindowSpan").textContent = "数据窗口加载失败";
    el("#modelSpan").textContent = "—";
    return;
  }
  el("#dataWindowSpan").textContent = formatWindow(meta);
  const m = meta.model || {};
  el("#modelSpan").textContent = `模型版本：${m.model_version || m.name || "—"}`;
  el("#riskBadge").textContent = "实时聚合";
}

function renderKpis() {
  const overview = state.overview;
  if (!overview) {
    el("#kpiGrid").innerHTML = `
      <article class="panel kpi-card"><span>核心指标</span><strong>—</strong><small>加载中...</small></article>
    `;
    return;
  }
  const days = state.meta && state.meta.data_window && state.meta.data_window.available_days;
  const sub = `${rangeLabel()}${days ? `（窗口 ${days} 天）` : ""}`;
  const cards = [
    { label: "帖子数",       value: formatLargeNumber(overview.post_count),            sub },
    { label: "采样评论数",   value: formatLargeNumber(overview.sampled_comment_count), sub: `${rangeLabel()} · 采样评论` },
    { label: "活跃话题",     value: formatLargeNumber(overview.active_topic_count),    sub: `热榜登记 · ${rangeLabel()}` },
    { label: "累计互动",     value: formatLargeNumber(overview.latest_interactions),   sub: "argMax · 平台快照" },
    {
      label: "负面舆情指数",
      value: overview.risk_index == null ? "—" : Number(overview.risk_index).toFixed(1),
      sub:   overview.risk_index == null ? "等情绪预测就位" : `负面率 ${formatPercent(overview.negative_ratio)}`,
      placeholder: overview.risk_index == null,
    },
  ];
  el("#kpiGrid").innerHTML = cards.map((c) => `
    <article class="panel kpi-card"${c.placeholder ? ' style="opacity:0.65"' : ""}>
      <span>${escapeHTML(c.label)}</span>
      <strong>${escapeHTML(c.value)}</strong>
      <small>${escapeHTML(c.sub)}</small>
    </article>
  `).join("");
}

function renderDataQuality() {
  const dq = state.dataQuality;
  if (!dq) {
    el("#dataQualityList").innerHTML = '<li class="muted">加载中...</li>';
    return;
  }
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
    .map(([t, p]) => `tier${t} ${(Number(p) * 100).toFixed(0)}%`)
    .join(" · ");
  if (tierStr) items.push(`窗口内用户画像覆盖：${tierStr}`);
  el("#dataQualityList").innerHTML = items.map((t) => `<li>${escapeHTML(t)}</li>`).join("");
}

function renderModelQuality() {
  const mq = state.modelQuality;
  if (!mq) {
    el("#modelMetrics").innerHTML = `<div><strong>—</strong><span>加载中...</span></div>`;
    return;
  }
  const fmtPct = (x) => x == null ? "—" : (Number(x) * 100).toFixed(1) + "%";
  const fmtF1  = (x) => x == null ? "—" : Number(x).toFixed(4);
  const be = mq.business_eval;
  const st = mq.smp_test;
  const metrics = [
    { v: fmtF1(be && be.macro_f1),  s: "macro-F1 · 业务集" },
    { v: fmtPct(be && be.accuracy), s: "accuracy · 业务集" },
    { v: fmtF1(st && st.macro_f1),  s: "macro-F1 · SMP test" },
    { v: fmtPct(st && st.accuracy), s: "accuracy · SMP test" },
  ];
  el("#modelMetrics").innerHTML = metrics.map((m) => `
    <div><strong>${escapeHTML(m.v)}</strong><span>${escapeHTML(m.s)}</span></div>
  `).join("");

  const confusions = mq.top_confusions || [];
  el("#confusionBox").innerHTML = `
    <h3>易混淆标签（业务集 Top ${confusions.length}）</h3>
    ${confusions.length === 0
      ? '<p class="muted">无可用混淆数据</p>'
      : confusions.map((c) => `<p>真实「${escapeHTML(c.true)}」 → 预测「${escapeHTML(c.pred)}」：${escapeHTML(c.count)} 条</p>`).join("")}
  `;

  const bc = mq.bert_comparison;
  if (!bc) {
    el("#compareBox").innerHTML = '<h3>BERT 对照说明</h3><p class="muted">无对照数据</p>';
  } else {
    el("#compareBox").innerHTML = `
      <h3>BERT 对照说明</h3>
      <p>${escapeHTML(bc.usage)}：${escapeHTML(bc.name)} 在业务集上 accuracy ${escapeHTML(fmtPct(bc.bert_accuracy))} / macro-F1 ${escapeHTML(fmtF1(bc.bert_macro_f1))}；
         ${escapeHTML(mq.primary_model)} 与 BERT 一致率 ${escapeHTML(fmtPct(bc.agreement_rate))}，oracle 上限 ${escapeHTML(fmtPct(bc.oracle_accuracy))}。</p>
      <p>分歧样本中 ${escapeHTML(mq.primary_model)} 多答对 ${escapeHTML(bc.ernie_only_correct)} 条，BERT 多答对 ${escapeHTML(bc.bert_only_correct)} 条。</p>
    `;
  }
}

// ===========================================================================
// Trend / Topics / Explain
// ===========================================================================
function renderLegend() {
  el("#emotionLegend").innerHTML = EMOTIONS.map((name) => `
    <span><i style="background:${COLORS[name]}"></i>${escapeHTML(name)}</span>
  `).join("");
}

function renderTrend() {
  const rows = state.trend || [];
  if (!rows.length) {
    clearChart("trendChart", "暂无趋势数据");
    return;
  }
  renderChart("trendChart", buildEmotionStackOption(rows));
}

function renderTopics() {
  const list = state.topics || [];
  if (!list.length) {
    el("#topicList").innerHTML = '<p class="muted">暂无风险话题数据</p>';
    return;
  }
  el("#topicList").innerHTML = list.map((topic) => {
    const id = String(topic.topic_id);
    const active = id === String(state.selectedTopicId) ? "active" : "";
    const emo = topic.dominant_emotion || "中性";
    return `
      <button class="topic-item ${active}" data-topic="${escapeHTML(id)}" type="button">
        <div class="topic-top">
          <span class="topic-name">#${escapeHTML(topic.title)}#</span>
          <span class="score">${escapeHTML(Number(topic.risk_score || 0).toFixed(1))}</span>
        </div>
        <div class="topic-meta">
          <span class="emotion-tag"><i style="background:${COLORS[emo] || COLORS.中性}"></i>${escapeHTML(emo)}</span>
          <span>负面率 ${escapeHTML(formatPercent(topic.negative_ratio))}</span>
          <span>互动 ${escapeHTML(topic.interaction_growth_label || "—")}</span>
          <span>样本 ${escapeHTML(formatLargeNumber(topic.sample_count))}</span>
        </div>
      </button>
    `;
  }).join("");

  document.querySelectorAll(".topic-item").forEach((button) => {
    button.addEventListener("click", () => {
      const id = button.dataset.topic;
      if (!id || String(id) === String(state.selectedTopicId)) return;
      state.selectedTopicId = id;
      renderTopics();
      renderExplain();
      reloadTopicScopedData();
    });
  });
}

function renderExplain() {
  const list = state.topics || [];
  const topic = list.find((item) => String(item.topic_id) === String(state.selectedTopicId));
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
      <strong>${escapeHTML(Number(value || 0).toFixed(1))}</strong>
    </div>
  `).join("");
}

// ===========================================================================
// Topic detail（情绪结构 + 趋势 + 互动曲线 + 入口结构）
// ===========================================================================
function renderTopicDetail() {
  const detail = state.topicDetail;
  const detailChartIds = [
    "detailEmotionChart",
    "detailTimelineChart",
    "detailEngagementChart",
    "detailSourceChart",
  ];

  if (!detail) {
    const message = state.selectedTopicId ? "正在加载话题详情..." : "请选择风险话题";
    el("#detailTitle").textContent = message;
    el("#detailLead").textContent = "";
    el("#detailMeta").innerHTML = "";
    detailChartIds.forEach((id) => clearChart(id, message));
    return;
  }

  const topic = detail.topic || {};
  el("#detailTitle").textContent = topic.title ? `#${topic.title}#` : "话题详情";
  el("#detailLead").textContent = topic.lead || "—";
  el("#detailMeta").innerHTML = [
    `<span>风险分<strong>${escapeHTML(Number(topic.risk_score || 0).toFixed(1))}</strong></span>`,
    `<span>负面率<strong>${escapeHTML(formatPercent(topic.negative_ratio))}</strong></span>`,
    `<span>采样总量<strong>${escapeHTML(formatLargeNumber(topic.sample_count))}</strong></span>`,
    `<span>累计互动<strong>${escapeHTML(formatLargeNumber(topic.latest_interactions))}</strong></span>`,
    `<span class="muted">采样口径：评论为采样评论，互动为平台快照</span>`,
  ].join("");

  // 1) 情绪结构（环图）
  const dist = (detail.emotion_distribution && detail.emotion_distribution.counts) || {};
  const distData = EMOTIONS.map((name) => ({
    name,
    value: Number(dist[name] || 0),
    itemStyle: { color: COLORS[name] },
  }));
  if (distData.every((d) => d.value === 0)) {
    clearChart("detailEmotionChart", "暂无情绪样本（采样）");
  } else {
    renderChart("detailEmotionChart", {
      tooltip: {
        trigger: "item",
        formatter: (p) => `${escapeHTML(p.name)}：${formatLargeNumber(p.value)}（${p.percent}%）`,
      },
      legend: { bottom: 0, textStyle: { color: "#667085" }, itemWidth: 10, itemHeight: 10 },
      series: [{
        type: "pie",
        radius: ["42%", "68%"],
        center: ["50%", "44%"],
        avoidLabelOverlap: true,
        label: { show: true, formatter: "{b} {d}%", color: "#172033", fontSize: 11 },
        labelLine: { length: 6, length2: 6 },
        data: distData,
      }],
    });
  }

  // 2) 情绪趋势（堆叠面积）
  if (!detail.timeline || !detail.timeline.length) {
    clearChart("detailTimelineChart", "暂无情绪趋势（采样）");
  } else {
    renderChart("detailTimelineChart", buildEmotionStackOption(detail.timeline));
  }

  // 3) 互动曲线（折线）
  const curve = detail.engagement_curve || [];
  if (!curve.length) {
    clearChart("detailEngagementChart", "暂无互动曲线");
  } else {
    renderChart("detailEngagementChart", {
      grid: { top: 28, left: 8, right: 16, bottom: 32, containLabel: true },
      tooltip: { trigger: "axis" },
      legend: { top: 0, right: 0, textStyle: { color: "#667085" }, itemWidth: 10, itemHeight: 10 },
      xAxis: { type: "category", data: curve.map((r) => r.time), axisLabel: { color: "#667085", fontSize: 11 } },
      yAxis: {
        type: "value",
        axisLabel: { color: "#667085", fontSize: 11, formatter: (v) => formatLargeNumber(v) },
        splitLine: { lineStyle: { color: "#edf1f6" } },
      },
      series: [
        { name: "评论", type: "line", smooth: true, showSymbol: false, itemStyle: { color: "#3578d4" }, data: curve.map((r) => Number(r.comments_count || 0)) },
        { name: "点赞", type: "line", smooth: true, showSymbol: false, itemStyle: { color: "#22a06b" }, data: curve.map((r) => Number(r.attitudes_count || 0)) },
        { name: "转发", type: "line", smooth: true, showSymbol: false, itemStyle: { color: "#f59e2f" }, data: curve.map((r) => Number(r.reposts_count || 0)) },
      ],
    });
  }

  // 4) 入口结构（横向条形）
  const mix = detail.source_mix || {};
  const counts = detail.source_counts || {};
  const totalSource = SOURCE_TYPE_KEYS.reduce((s, k) => s + (Number(counts[k]) || 0), 0);
  if (totalSource === 0) {
    clearChart("detailSourceChart", "暂无入口分布");
  } else {
    renderChart("detailSourceChart", {
      grid: { top: 16, left: 8, right: 32, bottom: 28, containLabel: true },
      tooltip: {
        trigger: "axis",
        axisPointer: { type: "shadow" },
        formatter: (params) => {
          const p = params[0];
          const k = SOURCE_TYPE_KEYS[p.dataIndex];
          return `${escapeHTML(SOURCE_TYPE_LABELS[k] || k)}：${formatPercent(mix[k])}（${counts[k] || 0} 条）`;
        },
      },
      xAxis: {
        type: "value",
        max: 1,
        axisLabel: { color: "#667085", fontSize: 11, formatter: (v) => `${(v * 100).toFixed(0)}%` },
        splitLine: { lineStyle: { color: "#edf1f6" } },
      },
      yAxis: {
        type: "category",
        data: SOURCE_TYPE_KEYS.map((k) => SOURCE_TYPE_LABELS[k] || k),
        axisLabel: { color: "#172033", fontSize: 12 },
      },
      series: [{
        type: "bar",
        barWidth: 16,
        data: SOURCE_TYPE_KEYS.map((k) => ({ value: Number(mix[k] || 0), itemStyle: { color: "#2f5fd0" } })),
        label: { show: true, position: "right", color: "#172033", formatter: (p) => `${(Number(p.value) * 100).toFixed(1)}%` },
      }],
    });
  }
}

// ===========================================================================
// Evidence
// ===========================================================================
function renderEvidence(items) {
  const topic = (state.topics || []).find((item) => String(item.topic_id) === String(state.selectedTopicId));
  el("#evidenceFilter").textContent = topic ? `#${topic.title}#（采样评论）` : "全部话题（采样评论）";
  if (!items || !items.length) {
    el("#evidenceList").innerHTML = '<p class="muted">暂无证据样本（采样评论，不代表全量分布）</p>';
    return;
  }
  el("#evidenceList").innerHTML = items.map((item) => {
    const sourceTag = item.source === "comment" ? "采样评论" : "帖子";
    return `
      <article class="evidence-item">
        <p class="evidence-text">${escapeHTML(item.content)}</p>
        <div class="evidence-meta">
          <span class="emotion-tag"><i style="background:${COLORS[item.pred_label] || COLORS.中性}"></i>${escapeHTML(item.pred_label)}</span>
          <span class="metric-chip">置信度 ${escapeHTML(Number(item.confidence || 0).toFixed(2))}</span>
          <span class="metric-chip">top2 margin ${escapeHTML(Number(item.margin || 0).toFixed(2))}</span>
          <span class="metric-chip">${escapeHTML(formatLargeNumber(item.interaction_count || 0))} 互动</span>
          <span class="metric-chip">${escapeHTML(item.actor_role || "普通账号")}</span>
          <span class="metric-chip muted">${escapeHTML(sourceTag)}</span>
        </div>
      </article>
    `;
  }).join("");
}

// ===========================================================================
// Actors
// ===========================================================================
function actorRowHTML(actor) {
  const roles = (actor.roles || [])
    .map((r) => `<span class="role-chip">${escapeHTML(ROLE_LABELS[r] || r)}</span>`)
    .join("");
  const emo = actor.dominant_emotion || "中性";
  return `
    <article class="actor-row">
      <div class="actor-head">
        <strong>${escapeHTML(actor.display_name || actor.actor_id || "—")}</strong>
        ${actor.verified ? '<span class="role-chip verified">认证</span>' : ""}
        <span class="metric-chip muted">${escapeHTML(actor.followers_bucket || "未覆盖")}</span>
      </div>
      <div class="actor-meta">
        <span class="emotion-tag"><i style="background:${COLORS[emo] || COLORS.中性}"></i>${escapeHTML(emo)}</span>
        <span>负面率 ${escapeHTML(formatPercent(actor.negative_ratio))}</span>
        <span>互动 ${escapeHTML(formatLargeNumber(actor.interaction_count))}</span>
        <span>影响力 ${escapeHTML(Number(actor.actor_influence_score || 0).toFixed(1))}</span>
      </div>
      <div class="actor-roles">${roles}</div>
    </article>
  `;
}

function renderActors() {
  const list = state.actors || [];
  const topic = (state.topics || []).find((item) => String(item.topic_id) === String(state.selectedTopicId));
  el("#actorScope").textContent = topic ? `#${topic.title}#（采样）` : "全部话题（采样）";
  if (!list.length) {
    el("#actorList").innerHTML = '<p class="muted">暂无关键账号（采样）</p>';
    return;
  }
  el("#actorList").innerHTML = list.map((a) => actorRowHTML(a)).join("");
}

// ===========================================================================
// Influence-Emotion 散点图
// ===========================================================================
function renderInfluenceEmotion() {
  const items = state.influenceEmotion || [];
  if (!items.length) {
    clearChart("influenceChart", "暂无影响力-情绪数据（采样）");
    return;
  }
  const grouped = {};
  items.forEach((it) => {
    const emo = it.dominant_emotion || "中性";
    if (!grouped[emo]) grouped[emo] = [];
    grouped[emo].push(it);
  });
  const maxInteraction = items.reduce((m, it) => Math.max(m, Number(it.interaction_count || 0)), 1) || 1;
  const series = EMOTIONS.filter((e) => grouped[e]).map((emo) => ({
    name: emo,
    type: "scatter",
    symbolSize: (val) => {
      const ratio = Math.sqrt(Number(val[2] || 0) / maxInteraction);
      return Math.max(10, Math.min(48, 10 + ratio * 38));
    },
    itemStyle: { color: COLORS[emo], opacity: 0.78 },
    emphasis: { itemStyle: { borderColor: "#172033", borderWidth: 1 } },
    data: grouped[emo].map((it) => ({
      name: it.display_name || it.actor_id || "",
      value: [
        Number(it.influence_score || 0),
        Number(it.negative_ratio || 0),
        Number(it.interaction_count || 0),
      ],
      _topic: it.topic_title || "—",
      _roles: (it.roles || []).map((r) => ROLE_LABELS[r] || r).join("、") || "—",
    })),
  }));
  renderChart("influenceChart", {
    grid: { top: 32, left: 8, right: 24, bottom: 48, containLabel: true },
    tooltip: {
      trigger: "item",
      formatter: (p) => {
        const v = (p.data && p.data.value) || [];
        return [
          `<strong>${escapeHTML(p.data && p.data.name)}</strong>`,
          `情绪：${escapeHTML(p.seriesName)}`,
          `话题：${escapeHTML((p.data && p.data._topic) || "—")}`,
          `角色：${escapeHTML((p.data && p.data._roles) || "—")}`,
          `影响力 ${Number(v[0] || 0).toFixed(1)}`,
          `负面率 ${(Number(v[1] || 0) * 100).toFixed(1)}%`,
          `互动 ${formatLargeNumber(Number(v[2] || 0))}`,
        ].join("<br/>");
      },
    },
    legend: { top: 0, right: 0, textStyle: { color: "#667085" }, itemWidth: 10, itemHeight: 10 },
    xAxis: {
      type: "value",
      name: "影响力",
      nameTextStyle: { color: "#667085" },
      min: 0, max: 100,
      axisLabel: { color: "#667085", fontSize: 11 },
      splitLine: { lineStyle: { color: "#edf1f6" } },
    },
    yAxis: {
      type: "value",
      name: "负面率",
      nameTextStyle: { color: "#667085" },
      min: 0, max: 1,
      axisLabel: { color: "#667085", fontSize: 11, formatter: (v) => `${(v * 100).toFixed(0)}%` },
      splitLine: { lineStyle: { color: "#edf1f6" } },
    },
    series,
  });
}

// ===========================================================================
// Loaders（每个 loader 独立 try/catch；失败只影响对应区域）
// ===========================================================================
async function loadMeta() {
  try {
    const meta = await fetchJSON("/api/dashboard/meta");
    state.meta = meta;
    const opts = Array.isArray(meta && meta.time_range_options) ? meta.time_range_options : [];
    state.rangeOptions = opts.length ? opts : ["all_available"];
    if (!state.rangeOptions.includes(state.range)) {
      state.range = state.rangeOptions[0];
    }
    renderHero();
    renderRangeTabs();
  } catch (err) {
    el("#dataWindowSpan").textContent = "数据窗口加载失败";
    el("#modelSpan").textContent = err.message;
    el("#rangeTabs").innerHTML = '<span class="muted">时间范围加载失败</span>';
  }
}

async function loadDataQuality() {
  try {
    state.dataQuality = await fetchJSON("/api/dashboard/data-quality");
    renderDataQuality();
  } catch (err) {
    el("#dataQualityList").innerHTML = `<li class="muted error">加载失败：${escapeHTML(err.message)}</li>`;
  }
}

async function loadModelQuality() {
  try {
    state.modelQuality = await fetchJSON("/api/dashboard/model-quality");
    renderModelQuality();
  } catch (err) {
    el("#modelMetrics").innerHTML = `<div><strong>—</strong><span>加载失败</span></div>`;
    el("#confusionBox").innerHTML = `<h3>易混淆标签</h3><p class="muted error">加载失败：${escapeHTML(err.message)}</p>`;
    el("#compareBox").innerHTML = `<h3>BERT 对照说明</h3><p class="muted error">加载失败：${escapeHTML(err.message)}</p>`;
  }
}

async function loadOverview(token) {
  el("#kpiGrid").innerHTML = '<article class="panel kpi-card"><span>核心指标</span><strong>—</strong><small>加载中...</small></article>';
  try {
    const overview = await fetchJSON(`/api/dashboard/overview?${rangeQS()}`);
    if (token !== tokens.range) return;
    state.overview = overview;
    renderKpis();
  } catch (err) {
    if (token !== tokens.range) return;
    el("#kpiGrid").innerHTML = `
      <article class="panel kpi-card warn" style="grid-column: span 5">
        <span>KPI 加载失败</span>
        <strong>—</strong>
        <small>${escapeHTML(err.message)}</small>
      </article>`;
  }
}

async function loadTrend(token) {
  clearChart("trendChart", "加载中...");
  try {
    const rows = await fetchJSON(`/api/dashboard/emotion-timeseries?${rangeQS()}`);
    if (token !== tokens.range) return;
    state.trend = rows || [];
    renderTrend();
  } catch (err) {
    if (token !== tokens.range) return;
    clearChart("trendChart", `趋势加载失败：${err.message}`);
  }
}

async function loadRiskTopics(token) {
  el("#topicList").innerHTML = '<p class="muted">正在加载风险话题...</p>';
  try {
    const rows = await fetchJSON(`/api/dashboard/risk-topics?${rangeQS()}&limit=20`);
    if (token !== tokens.range) return;
    state.topics = rows || [];
    const stillExists = state.topics.find((t) => String(t.topic_id) === String(state.selectedTopicId));
    if (!stillExists) {
      state.selectedTopicId = state.topics[0] ? String(state.topics[0].topic_id) : null;
    }
    renderTopics();
    renderExplain();
  } catch (err) {
    if (token !== tokens.range) return;
    state.topics = [];
    state.selectedTopicId = null;
    el("#topicList").innerHTML = `<p class="muted error">风险话题加载失败：${escapeHTML(err.message)}</p>`;
    renderExplain();
  } finally {
    if (token === tokens.range) reloadTopicScopedData();
  }
}

async function loadTopicDetail(token) {
  if (!state.selectedTopicId) {
    state.topicDetail = null;
    renderTopicDetail();
    return;
  }
  // 切换前先清空，提示加载中
  state.topicDetail = null;
  renderTopicDetail();
  try {
    const tid = encodeURIComponent(String(state.selectedTopicId));
    const detail = await fetchJSON(`/api/dashboard/topics/${tid}?${rangeQS()}&limit=8&actor_limit=8`);
    if (token !== tokens.topic) return;
    state.topicDetail = detail;
    renderTopicDetail();
  } catch (err) {
    if (token !== tokens.topic) return;
    el("#detailTitle").textContent = "话题详情加载失败";
    el("#detailLead").textContent = err.message;
    ["detailEmotionChart", "detailTimelineChart", "detailEngagementChart", "detailSourceChart"]
      .forEach((id) => clearChart(id, `加载失败：${err.message}`));
  }
}

async function loadEvidence(token) {
  el("#evidenceList").innerHTML = '<p class="muted">正在加载证据样本（采样评论）...</p>';
  try {
    const rows = await fetchJSON(`/api/dashboard/evidence?${withTopic(rangeQS())}&limit=8`);
    if (token !== tokens.topic) return;
    renderEvidence(rows);
  } catch (err) {
    if (token !== tokens.topic) return;
    el("#evidenceList").innerHTML = `<p class="muted error">证据样本加载失败：${escapeHTML(err.message)}</p>`;
  }
}

async function loadActors(token) {
  el("#actorList").innerHTML = '<p class="muted">正在加载关键账号（采样）...</p>';
  try {
    const rows = await fetchJSON(`/api/dashboard/actors?${withTopic(rangeQS())}&limit=20`);
    if (token !== tokens.topic) return;
    state.actors = rows || [];
    renderActors();
  } catch (err) {
    if (token !== tokens.topic) return;
    state.actors = [];
    el("#actorList").innerHTML = `<p class="muted error">关键账号加载失败：${escapeHTML(err.message)}</p>`;
  }
}

async function loadInfluenceEmotion(token) {
  clearChart("influenceChart", "加载中...");
  try {
    const rows = await fetchJSON(`/api/dashboard/influence-emotion?${withTopic(rangeQS())}&limit=80`);
    if (token !== tokens.topic) return;
    state.influenceEmotion = rows || [];
    renderInfluenceEmotion();
  } catch (err) {
    if (token !== tokens.topic) return;
    state.influenceEmotion = [];
    clearChart("influenceChart", `影响力-情绪加载失败：${err.message}`);
  }
}

// ===========================================================================
// Orchestrators
// ===========================================================================
function reloadRangeScopedData() {
  // 切 range：所有 range 依赖请求作废；topic-scoped 由 loadRiskTopics 完成后触发。
  tokens.range += 1;
  tokens.topic += 1;
  const rt = tokens.range;
  loadOverview(rt);
  loadTrend(rt);
  loadRiskTopics(rt);
}

function reloadTopicScopedData() {
  tokens.topic += 1;
  const tt = tokens.topic;
  loadTopicDetail(tt);
  loadActors(tt);
  loadInfluenceEmotion(tt);
  loadEvidence(tt);
}

// ===========================================================================
// Bootstrap
// ===========================================================================
async function bootstrap() {
  renderLegend();
  renderRangeTabs();
  renderTopicDetail();
  renderEvidence([]);

  await loadMeta();
  // 与 range 无关，独立并行
  loadDataQuality();
  loadModelQuality();
  // range scoped + topic scoped（topic scoped 会在 risk-topics 解析后被 reloadTopicScopedData 触发）
  reloadRangeScopedData();
}

bootstrap();
