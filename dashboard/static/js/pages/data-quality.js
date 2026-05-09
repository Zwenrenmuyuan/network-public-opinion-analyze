// 独立数据口径页：拉取 meta / data-quality / overview 三个 endpoint，
// 渲染时间窗口、模型版本、采样比例、tier 分布饼图。
// helper 故意不复用 dashboard.js（不同页面），只复制这里需要的 4-5 个小函数。

const EMOTIONS = ["积极", "愤怒", "悲伤", "恐惧", "惊讶", "中性"];
const COLORS = {
  积极: "#22a06b",
  愤怒: "#dc3f45",
  悲伤: "#3578d4",
  恐惧: "#7c4cc2",
  惊讶: "#f59e2f",
  中性: "#8b95a1",
};

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

function formatLargeNumber(n) {
  if (n == null || Number.isNaN(Number(n))) return "—";
  const v = Number(n);
  if (Math.abs(v) >= 1e8) return (v / 1e8).toFixed(2) + " 亿";
  if (Math.abs(v) >= 1e4) return (v / 1e4).toFixed(2) + " 万";
  return v.toLocaleString("zh-CN");
}

function formatDateTime(iso) {
  if (!iso) return "—";
  const m = String(iso).match(/^(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2})/);
  return m ? `${m[1]}-${m[2]}-${m[3]} ${m[4]}:${m[5]}` : String(iso);
}

function renderHero(meta) {
  const w = meta && meta.data_window;
  if (!w) {
    el("#dataWindowSpan").textContent = "数据窗口加载失败";
    el("#modelSpan").textContent = "—";
    return;
  }
  el("#dataWindowSpan").textContent =
    `${formatDateTime(w.start)} ~ ${formatDateTime(w.end)}（${w.available_days} 天）`;
  el("#modelSpan").textContent = `模型版本：${meta.model && meta.model.name}`;
  el("#modelPill").textContent = `主模型版本：${meta.model && meta.model.model_version}`;
  el("#modelCkpt").textContent = (meta.model && meta.model.checkpoint) || "—";

  el("#emotionLegend").innerHTML = EMOTIONS.map((n) => `
    <span><i style="background:${COLORS[n]}"></i>${escapeHTML(n)}</span>
  `).join("");
}

function renderWindowKPI(meta, overview) {
  const w = meta && meta.data_window;
  if (!w) return;
  el("#windowMeta").innerHTML = `
    <div><span>稳定起点（东八区）</span><strong>${escapeHTML(formatDateTime(w.start))}</strong></div>
    <div><span>窗口结束</span><strong>${escapeHTML(formatDateTime(w.end))}</strong></div>
    <div><span>可用天数</span><strong>${escapeHTML(String(w.available_days))} 天</strong></div>
    <div><span>历史是否较短</span><strong>${w.is_partial_history ? "是（< 30 天）" : "否"}</strong></div>
    <div><span>帖子数</span><strong>${escapeHTML(formatLargeNumber(overview && overview.post_count))}</strong></div>
    <div><span>采样评论数</span><strong>${escapeHTML(formatLargeNumber(overview && overview.sampled_comment_count))}</strong></div>
    <div><span>累计互动（快照）</span><strong>${escapeHTML(formatLargeNumber(overview && overview.latest_interactions))}</strong></div>
    <div><span>活跃话题</span><strong>${escapeHTML(formatLargeNumber(overview && overview.active_topic_count))}</strong></div>
  `;
}

function renderNotices(dq) {
  const notices = [
    dq.history_window_notice,
    dq.comment_sampling_notice,
    dq.engagement_notice,
    dq.timezone_notice,
    dq.user_tier_notice,
    dq.post_discovery_notice,
  ].filter(Boolean);
  el("#dataQualityList").innerHTML = notices.map((t) => `<li>${escapeHTML(t)}</li>`).join("");
}

function renderTierChart(dq) {
  const tier = (dq && dq.profile_tier_distribution) || {};
  const data = Object.entries(tier)
    .sort(([a], [b]) => Number(a) - Number(b))
    .map(([t, p]) => ({ name: `tier ${t}`, value: Number(p) }));
  const node = document.getElementById("tierChart");
  if (!node) return;
  if (typeof window === "undefined" || !window.echarts || !data.length) {
    node.innerHTML = '<p class="muted">ECharts 未加载或暂无 tier 数据</p>';
    return;
  }
  const chart = window.echarts.init(node);
  chart.setOption({
    tooltip: {
      trigger: "item",
      formatter: (p) => `${escapeHTML(p.name)}：${(p.value * 100).toFixed(2)}%`,
    },
    legend: { bottom: 0, textStyle: { color: "#667085" }, itemWidth: 10, itemHeight: 10 },
    series: [{
      type: "pie",
      radius: ["42%", "66%"],
      center: ["50%", "44%"],
      avoidLabelOverlap: true,
      label: { formatter: "{b} {d}%", color: "#172033", fontSize: 11 },
      labelLine: { length: 6, length2: 6 },
      data,
    }],
  });
  window.addEventListener("resize", () => { if (!chart.isDisposed()) chart.resize(); });
}

async function bootstrap() {
  const [metaR, dqR, overviewR] = await Promise.allSettled([
    fetchJSON("/api/dashboard/meta"),
    fetchJSON("/api/dashboard/data-quality"),
    fetchJSON("/api/dashboard/overview?range=all_available"),
  ]);

  if (metaR.status === "fulfilled") {
    renderHero(metaR.value);
  } else {
    el("#dataWindowSpan").textContent = "数据窗口加载失败";
    el("#modelSpan").textContent = metaR.reason && metaR.reason.message;
  }

  if (metaR.status === "fulfilled" && overviewR.status === "fulfilled") {
    renderWindowKPI(metaR.value, overviewR.value);
  } else {
    el("#windowMeta").innerHTML = '<div><span>加载失败</span><strong>—</strong></div>';
  }

  if (dqR.status === "fulfilled") {
    renderNotices(dqR.value);
    renderTierChart(dqR.value);
  } else {
    el("#dataQualityList").innerHTML = `<li class="muted error">加载失败：${escapeHTML(dqR.reason && dqR.reason.message)}</li>`;
  }
}

bootstrap();
