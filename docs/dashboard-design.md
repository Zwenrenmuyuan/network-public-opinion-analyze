# 舆情研判 Dashboard 设计与实现

本文只保留当前 dashboard v1 的事实、接口契约、数据口径和后续待办。

## 1. 当前状态

当前 dashboard v1 已完成“本地/生产 CK -> 离线情绪预测表 -> Flask 同源 API -> 单页 ECharts 工作台”的闭环。

| 模块 | 状态 | 说明 |
|---|---|---|
| 后端网关 | 已实现 | `dashboard/server.py` 托管静态页面并注册 `/api/dashboard/*`。 |
| CK 客户端 | 已实现 | `dashboard/ck.py` 从根目录 `.env` 读取 CK 连接，浏览器不接触凭据。 |
| 预测表 | 已实现 | `dashboard.sentiment_prediction` 保存 ERNIE 主模型和 BERT 对照模型的全量预测。 |
| 总览 API | 已实现 | `meta`、`data-quality`、`overview`、`emotion-timeseries`、`risk-topics`。 |
| 详情 API | 已实现 | `topics/{topic_id}`、`actors`、`influence-emotion`、`evidence`。 |
| 模型质量 API | 已实现 | 读取 `runs/ernie-usual-mixed-v2/*` 和模型分歧摘要。 |
| 前端 v1 | 已实现 | 单页工作台，含时间范围、话题详情、关键账号、影响力矩阵。 |
| 缓存 | 未实现 | 当前直接查 CK，并记录 API 耗时；慢了再加 TTL cache 或聚合表。 |
| 搜索/分页/反馈 | 未实现 | 属于 Phase 5 后端增强。 |

当前 v1 已完成核心分析闭环，但还不是完整生产后台。生产化仍需要缓存、权限、查询超时、分页搜索和反馈闭环。

## 2. 目标与边界

目标：构建“舆情研判工作台”，而不是只展示情绪统计。

工作台需要回答：

- 什么话题在升温。
- 为什么这个话题有风险。
- 谁在放大风险。
- 从哪些入口被发现和扩散。
- 模型判断是否可信。
- 数据口径有哪些限制。

明确不做：

- 不做完整社交传播网络图。当前只有单级 `retweet_of` 和 `post_discovery` 入口。
- 不把 `comment` 表解释为全量评论民意。评论是采样数据。
- 不做独立用户画像系统。用户/KOL 只用于舆情解释。
- 不让前端直连 CK、不暴露 SQL、不暴露 CK 凭据。
- 不提交真实业务数据、导出数据、模型权重、`.env`。

## 3. 架构

```text
ClickHouse weibo.* 原始表
    -> scripts/dashboard/predict_business_emotions.py 离线批量预测
    -> dashboard.sentiment_prediction
    -> Flask /api/dashboard/* 聚合查询
    -> dashboard/index.html 单页工作台
```

运行原则：

- 模型推理离线完成，页面打开时不跑深度学习模型。
- 浏览器只请求同源 `/api/dashboard/*`。
- API 只返回聚合后的小 JSON 或 Top N 样本。
- CK 时间字段按 UTC 存储，展示层转东八区。
- 默认时间范围来自后端 `meta.time_range_options`，当前为 `all_available`、`24h`、`7d`。
- 当前不做 30 天/月度基线，因为爬虫历史窗口较短。

## 4. 关键文件

| 路径 | 作用 |
|---|---|
| `dashboard/server.py` | Flask 入口，托管静态页面并注册 API。 |
| `dashboard/ck.py` | ClickHouse HTTP 客户端，自动读取根目录 `.env`。 |
| `dashboard/api/summary.py` | `meta`、`data-quality`、`overview`、`emotion-timeseries`。 |
| `dashboard/api/risk.py` | 风险话题榜。 |
| `dashboard/api/topics.py` | 话题详情。 |
| `dashboard/api/actors.py` | 关键账号和影响力-情绪矩阵。 |
| `dashboard/api/evidence.py` | 代表性证据样本。 |
| `dashboard/api/model_quality.py` | 模型质量与 BERT 对照摘要。 |
| `dashboard/index.html` | 单页工作台结构。 |
| `dashboard/static/js/pages/dashboard.js` | 前端状态、API 对接、ECharts 渲染。 |
| `dashboard/static/css/dashboard.css` | 页面样式。 |
| `scripts/dashboard/export_dashboard_business_data.py` | 从 CK 导出 8 张业务表为 Native 文件。 |
| `scripts/dashboard/import_to_local_ck.py` | 把 Native 导出导入本地 CK。 |
| `scripts/dashboard/init_dashboard_schema.py` | 创建 `dashboard.sentiment_prediction`。 |
| `scripts/dashboard/predict_business_emotions.py` | 批量预测 post/comment 情绪并写入 CK。 |

## 5. 数据来源与口径

| 层 | 表 | 用途 | 口径限制 |
|---|---|---|---|
| 内容层 | `weibo.post`, `weibo.comment` | 原文、证据流、预测输入 | `comment` 是采样评论，不代表全量评论。 |
| 情绪层 | `dashboard.sentiment_prediction` | 六分类预测、置信度、BERT 对照 | 查询必须过滤 `model_version`。 |
| 热度层 | `weibo.post_engagement_ts` | 点赞/评论/转发快照 | 快照稀疏，不是连续时间序列。 |
| 话题层 | `weibo.topic`, `weibo.post_topic` | 话题聚合、详情页 | 只代表显式携带话题的帖子。 |
| 传播层 | `weibo.post_discovery` | hot/keyword/kol/retweet 入口 | 一帖可多入口，不能 `count(*)` 当帖子数。 |
| 账号层 | `weibo.user` | 认证、高粉、画像 tier | `followers_count` 仅 `profile_tier >= 1` 可信。 |

标签顺序来自 `src/npo/config.py:LABELS_ZH`：

```text
0=积极, 1=愤怒, 2=悲伤, 3=恐惧, 4=惊讶, 5=中性
```

负面情绪定义：

```text
negative = 愤怒 + 悲伤 + 恐惧
```

主展示模型：

- ERNIE：`ernie-usual-mixed-v2`
- checkpoint：`runs/ernie-usual-mixed-v2/best`
- BERT 对照：已全量写入预测表，用于模型解释和分歧分析，不作为主展示模型。

## 6. `dashboard.sentiment_prediction`

预测表是 dashboard 情绪层的唯一主产物。原始 `weibo.post` / `weibo.comment` 不写回情绪字段。

关键列：

| 列 | 说明 |
|---|---|
| `source_type` | `post` 或 `comment`。 |
| `source_id` | post_id 或 comment_id。 |
| `post_id` | 关联原帖；post 自身等于 post_id。 |
| `source_created_at` | 原 post/comment 发布时间，用于时间范围裁剪。 |
| `model_key` | `ernie` 或 `bert`。 |
| `model_version` | 例如 `ernie-usual-mixed-v2`。 |
| `pred_label`, `pred_label_id` | 六分类预测结果。 |
| `confidence` | top1 softmax 分数，只作为相对置信信号。 |
| `second_label`, `second_prob`, `margin` | top2 与不确定性。 |
| `prob_positive` 等 | 六类概率，列名使用英文。 |
| `predicted_at` | 预测写入时间，也是 ReplacingMergeTree 版本列。 |

逻辑唯一键：

```text
source_type + source_id + model_version
```

查询规则：

- 主展示默认过滤 `model_version = 'ernie-usual-mixed-v2'`。
- BERT 只在模型解释和分歧分析中使用。
- 所有大表查询都带 `source_created_at` 或原表时间范围。

## 7. API 契约

所有接口前缀：`/api/dashboard`。

通用参数：

- `range`：`all_available`、`24h`、`7d`，默认 `all_available`。
- `limit`：Top N 或样本数量限制，不是完整分页。
- `topic_id`：ClickHouse `UInt64`，API 和前端都按字符串处理，前端禁止转成 JS `Number`。

| API | 参数 | 用途 | 状态 |
|---|---|---|---|
| `GET /meta` | 无 | 数据窗口、可选时间范围、模型版本、标签顺序 | 已实现 |
| `GET /data-quality` | 无 | 数据口径说明、profile tier 覆盖率 | 已实现 |
| `GET /overview` | `range` | KPI、负面率、风险指数、互动总量 | 已实现 |
| `GET /emotion-timeseries` | `range` | 六类情绪按天趋势 | 已实现 |
| `GET /risk-topics` | `range`, `limit` | 风险话题榜 | 已实现 |
| `GET /topics/{topic_id}` | `range`, `limit`, `actor_limit` | 话题详情 | 已实现 |
| `GET /actors` | `range`, `topic_id`, `limit` | 关键账号/KOL 列表 | 已实现 |
| `GET /influence-emotion` | `range`, `topic_id`, `limit` | 影响力-情绪散点图 | 已实现 |
| `GET /evidence` | `range`, `topic_id`, `limit` | 代表性证据样本 | 已实现 |
| `GET /model-quality` | 无 | ERNIE/BERT 指标、混淆、分歧摘要 | 已实现 |

### 7.1 `meta`

返回要点：

- `schema_version`
- `generated_at`
- `data_window.start/end/available_days/is_partial_history`
- `time_range_options`
- `model.name/model_version/checkpoint`
- `labels`
- `negative_labels`

### 7.2 `risk-topics`

返回每个话题的：

- `topic_id`、`title`、`lead`
- `risk_score`、`risk_level`
- `dominant_emotion`
- `negative_ratio`、`negative_growth_label`
- `interaction_growth_label`、`latest_interactions`
- `sample_count`、`post_sample_count`、`sampled_comment_count`
- `source_mix`
- `risk_factors`、`risk_factor_labels`
- `kol_entry_count`、`verified_actor_count`

风险话题榜按当前窗口候选话题集合做 p95 归一化，更适合横向排序。

### 7.3 `topics/{topic_id}`

用于点击话题后的详情面板。返回：

- `topic`：话题基础信息、风险因子、样本数、互动数、关键账号信号。
- `timeline`：话题内按天情绪趋势。
- `emotion_distribution`：当前窗口情绪分布。
- `engagement_curve`：互动快照曲线。
- `source_mix` / `source_counts`：入口结构。
- `top_actors`：话题内关键账号。
- `evidence_samples`：话题内证据样本。

详情接口风险分用于解释当前话题，不应与榜单重新严格排序。

### 7.4 `actors`

账号接口不返回真实 `uid`、`screen_name`、主页 URL 或头像 URL。

返回字段：

- `actor_id`：稳定 hash。
- `display_name`：角色化名称，例如“认证账号 A”。
- `verified`、`verified_type`、`profile_tier`
- `followers_bucket`
- `topic_count`、`top_topic_id`、`top_topic_title`
- `post_count`、`comment_count`、`sample_count`
- `dominant_emotion`、`negative_ratio`
- `interaction_count`、`interaction_contribution`
- `actor_influence_score`
- `roles`
- `emotion_counts`

影响力分是排序信号，不代表绝对影响力。当前近似规则：互动量 `log1p` 归一化，`profile_tier >= 1` 时粉丝数 `log1p` 归一化，认证账号和画像覆盖加分。

### 7.5 `influence-emotion`

从 `actors` 聚合结果裁剪出的散点图数据：

- x：`influence_score`
- y：`negative_ratio`
- size：`interaction_count`
- color：`dominant_emotion`
- tooltip：`display_name`、`topic_title`、`roles`

### 7.6 `evidence`

证据流优先展示能解释风险的样本，而不是简单按时间排序。

返回字段：

- `sample_id`
- `source`：`post` 或 `comment`
- `source_id`、`post_id`、`topic_id`，均为字符串。
- `created_at`：东八区 ISO。
- `content`
- `pred_label`、`confidence`、`second_label`、`margin`
- `interaction_count`
- `actor_role`
- `evidence_reason`

评论证据必须标注为“采样评论”。

## 8. 派生指标

### 8.1 互动指标

```text
latest_comments = argMax(comments_count, captured_at)
latest_likes = argMax(attitudes_count, captured_at)
latest_reposts = argMax(reposts_count, captured_at)
latest_interactions = latest_comments + latest_likes + latest_reposts
```

互动增长：

```text
interaction_delta = latest_interactions - earliest_interactions_in_window
interaction_growth_rate = interaction_delta / max(earliest_interactions_in_window, 1)
```

展示时必须标注互动数来自 `post_engagement_ts` 平台快照。

### 8.2 风险分

风险分服务于排序和解释，不是绝对真值。

```text
risk_score = 100 * (
  0.25 * negative_ratio
+ 0.20 * negative_growth_score
+ 0.20 * interaction_growth_score
+ 0.15 * anger_fear_ratio
+ 0.10 * kol_verified_score
+ 0.10 * source_diversity_score
)
```

风险等级：

| 分数 | 等级 | 展示 |
|---:|---|---|
| `>= 80` | 高风险 | 需要人工关注 |
| `60-79` | 中高风险 | 持续跟踪 |
| `40-59` | 中风险 | 观察 |
| `< 40` | 低风险 | 常规监测 |

### 8.3 KOL 解释

KOL 分三类解释：

| 类型 | 判定 | 用途 |
|---|---|---|
| 入口型 KOL | `post_discovery.source_type = 'kol'` | 表示系统通过 KOL 入口发现该帖。 |
| 身份型 KOL | `verified = 1` 或 `profile_tier >= 1` 且粉丝数高 | 表示账号自身可能有扩散能力。 |
| 事件型关键用户 | 当前话题内高频、高互动、跨话题出现 | 表示在该事件中影响突出。 |

前端文案必须区分“来自 KOL 入口”和“作者是 KOL”。

## 9. 前端 v1

当前前端是单页，不是多页面应用。

已实现区域：

- 顶部数据窗口和模型版本。
- 时间范围切换：全部可用、近 24 小时、近 7 天。
- KPI 总览。
- 六类情绪趋势。
- 风险话题榜。
- 风险解释卡。
- 话题详情：情绪结构、情绪趋势、互动曲线、入口结构。
- 证据流。
- 关键账号/KOL。
- 影响力-情绪矩阵。
- 模型解释小面板。
- 数据口径提示。

前端约束：

- 只请求 `/api/dashboard/*`。
- 不配置 CK 地址、账号、密码或本地数据路径。
- `topic_id` 始终按字符串处理。
- 评论相关文案必须出现“采样评论”。
- ECharts CDN 不可用时页面不能白屏。
- API 失败只影响对应模块，不能导致整页崩溃。

后续前端重构方向：

- 做完整视觉重构和信息架构，而不是继续堆单页。
- 可拆分为总览、话题详情、账号/KOL、模型解释、数据口径页。
- 可改成工程化前端并固定 ECharts 依赖，不再依赖 CDN。
- API 契约尽量保持不变。

## 10. 验证

代码级检查：

```bash
uv run python -m py_compile dashboard/server.py dashboard/api/*.py dashboard/ck.py
node --check dashboard/static/js/pages/dashboard.js
```

接口 smoke 覆盖：

```text
GET /
GET /api/dashboard/meta
GET /api/dashboard/overview?range=all_available
GET /api/dashboard/emotion-timeseries?range=all_available
GET /api/dashboard/risk-topics?range=all_available&limit=1
GET /api/dashboard/topics/{topic_id}?range=all_available&limit=3&actor_limit=3
GET /api/dashboard/actors?range=all_available&limit=3
GET /api/dashboard/influence-emotion?range=all_available&limit=3
GET /api/dashboard/evidence?range=all_available&topic_id={topic_id}&limit=3
```

人工验收：

- 浏览器打开 `http://localhost:8000/`。
- 切换三个时间范围，确认各模块刷新。
- 点击多个风险话题，确认详情、证据、账号和矩阵刷新。
- 浏览器 console 无 JS 错误。
- 页面中评论口径显示为“采样评论”。

## 11. 后续待办

优先级高：

- 清理 API 小债：避免任何无意义 `SELECT *`，统一错误响应格式。
- 根据 API 耗时决定是否加 TTL cache。
- 给生产部署增加查询超时、只读账号和最小权限说明。
- 补模型解释页的 per-class F1、低置信样本和分歧样本详情。

优先级中：

- 关键词搜索。
- 证据样本大规模分页。
- 独立数据口径页。
- 传播溯源增强：首次发现入口、入口随时间变化、多入口扩散路径。

优先级低：

- 人工反馈/标注纠错。
- 主动学习闭环。
