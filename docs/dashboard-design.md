# 舆情可视化数据设计

本文定义本仓库后续仪表盘的数据口径、数据生产链路、后端 API 契约和可视化模块。目标是支撑毕业设计展示、开源仓库说明、在线演示链接和后续真实业务分析，避免把 ClickHouse 原始表直接拼成“好看的大屏”但缺少解释性。

## 1. 设计目标

- 构建一个“舆情研判工作台”，而不是单纯情绪统计页面。
- 前端展示能回答：什么话题在升温、为什么有风险、是谁在放大、从哪里被发现、模型判断是否可信。
- 数据口径必须可解释，尤其是评论采样、用户画像 tier、互动时序稀疏、KOL 入口等限制。
- 仓库可以开源，但真实业务数据不随仓库开源；所有展示数据必须经后端 API 中转，前端不配置也不直连数据文件地址。
- 后端是必选网关：开发连接本地 ClickHouse，生产连接云端 ClickHouse；快照 JSON/parquet 仅作为 mock、缓存或答辩兜底。

## 2. 非目标

- 不做完整社交网络传播图。当前数据只有单级 `retweet_of` 和 `post_discovery` 入口，不是完整转发链。
- 不把 `comment` 表解释为全量评论民意。评论是采样数据，只能展示“采样评论中的情绪和观点”。
- 不做独立用户画像系统。用户/KOL 数据只作为舆情解释和影响力判断的一部分。
- 不在前端直接连接 ClickHouse，不暴露数据库账号、SQL 和原始生产表结构。
- 不让前端配置远程静态数据地址；数据路径、CK 连接、快照目录都属于后端配置。
- 不把真实 `data/dashboard/` 产物提交到开源仓库；仓库内只保留无业务含义的 mock 数据或数据契约示例。

## 3. 总体分析框架

舆情研判由 6 层组成：

| 层 | 数据来源 | 解决的问题 | 主要展示 |
|---|---|---|---|
| 内容层 | `post`, `comment` | 用户在说什么 | 文本流、代表性样本、原帖/评论证据 |
| 情绪层 | ERNIE 预测结果 | 情绪倾向是什么 | 六分类趋势、负面占比、低置信样本 |
| 热度层 | `post_engagement_ts` | 传播强度是否异常 | 点赞/评论/转发增长、热帖榜、峰值 |
| 话题层 | `topic`, `post_topic` | 哪些事件聚集讨论 | 风险话题榜、话题情绪矩阵、话题详情 |
| 传播层 | `post_discovery` | 从哪里被发现并扩散 | 热榜/关键词/KOL/转发入口、首次入口 |
| 账号层 | `user` | 谁在放大风险 | 认证账号、高粉账号、KOL 入口、关键用户 |

## 4. 数据生产与服务模式

### 4.1 必选架构：后端网关 + CK 查询 + 缓存

仪表盘运行时必须有后端网关。推荐主路径是后端直连 ClickHouse，只返回聚合后的小 JSON；文件快照只作为本地 mock、API 缓存或答辩兜底，不做持续同步主链路。

```text
ClickHouse 原始表
    -> 增量情感预测任务
    -> dashboard.sentiment_prediction（或同构本地 parquet）
    -> 后端 API (/api/dashboard/*)
       -> CK 只读聚合 / 预测表 JOIN / 分层缓存
    -> 前端页面
```

优点：

- 数据私有、页面可公开展示：浏览器只看到同源 API，不知道真实文件目录、对象存储地址或 CK 连接信息。
- 页面打开快，适合毕业答辩和简历演示。
- 避免前端写复杂 SQL 或拼接数据文件地址，减少口径错误和数据暴露风险。
- 避免为了持续增长的 CK 数据再维护一套复杂文件同步系统。
- 模型推理离线完成，不在页面打开时跑深度学习模型。

### 4.2 展示部署模式

仓库开源和数据展示分离：

```text
开源仓库: 前端代码 + 后端代码 + 数据契约 + mock 数据
展示环境: 浏览器 -> 同源 /api/dashboard/* -> 后端 -> CK / 预测结果表 / 私有缓存
生产数据: ClickHouse / data/dashboard/* 本地生成，不提交仓库，不直接暴露 URL
```

前端请求固定相对路径，例如：

```text
GET /api/dashboard/overview
GET /api/dashboard/risk-topics
GET /api/dashboard/topics/{topic_id}
```

部署时由后端配置 `DASHBOARD_DATA_ROOT`、ClickHouse 连接和缓存策略；前端不维护数据源地址。公开演示链接只暴露页面域名和 API 路由。

### 4.3 后端数据源模式

后端是必选的，但后端的数据源可以分阶段演进：

| 模式 | 后端读取 | 适用场景 |
|---|---|---|
| 本地开发模式 | 本地 ClickHouse + 本地预测表/parquet | SQL、API、前端联调 |
| 生产查询模式 | 云端 CK 只读查询 + 后端缓存 | 在线演示和真实业务展示 |
| 快照兜底模式 | `data/dashboard/json/*.json` 或聚合 parquet | mock、答辩固定数据、故障兜底 |

以下能力必须通过后端查询 CK 或读取后端缓存实现：

- 按任意关键词搜索原文。
- 大规模样本分页浏览。
- 动态时间范围、地区、情绪、用户分层筛选。
- 人工反馈、标注纠错、主动学习闭环。
- 实时或近实时查询 ClickHouse。

无论哪种模式，模型预测都仍应离线批处理；后端不做在线 ERNIE 推理，只负责 CK 查询、文件兜底、轻量聚合、权限、缓存和 API 输出。

### 4.4 当前数据窗口与本地 CK 开发

当前爬虫运行时间只有约 10 多天，不能把“近 30 天”当成默认数据窗口或历史基线。所有趋势、增长率和风险解释都必须基于实际可用窗口。

开发策略：

- 本地安装 ClickHouse，导入一次当前云端 CK 的可用数据窗口，用于开发 SQL、API 和前端交互。
- 本地开发不要假设有 30 天数据；默认筛选项建议是“全部可用 / 近 24 小时 / 近 7 天”。
- 前端如果展示“近 30 天”入口，必须由后端 `meta` 判断可用天数足够后再开启。
- 生产部署时后端连接云服务器 CK，前端和 API 代码不变，只切换后端连接配置。
- 云服务器是 4 核 4G 且有其他应用，生产 API 必须限制查询窗口、分页、缓存，并避免无时间范围大查询。

指标策略：

- `data_window` 使用后端实际查询到的最早/最晚时间，不写死 30 天。
- 风险增长率优先使用当前窗口内的相邻子窗口对比，例如最近 24 小时 vs 前 24 小时，或最近 7 天按天趋势。
- 暂不做“月环比”“近 30 天基线”“长期生命周期”这类需要更长历史的数据结论。

## 5. 目录与产物约定

建议后续新增 `scripts/dashboard/`，不要把仪表盘数据生产逻辑混进 `scripts/data_repair/`。

```text
dashboard/
  server.py                              # 必选后端网关：服务前端静态资源和 /api/dashboard/*
  static/                                # 前端静态资源
  templates/                             # 如使用服务端模板，可选

scripts/dashboard/
  export_dashboard_business_data.py      # 本地开发/兜底用：从 CK 只读导出所需表
  prepare_dashboard_corpus.py            # 清洗 post/comment 文本并统一语料
  predict_business_emotions.py           # 主模型批量预测业务文本
  analyze_business_disagreement.py       # 可选：ERNIE/BERT 分歧分析
  build_dashboard_json.py                # 生成 mock/缓存/答辩兜底 JSON
  build_dashboard_dataset.py             # 一键构建本地开发/兜底数据集

data/dashboard/
  raw/                                   # CK 导出的原始 parquet
  processed/                             # 清洗后的统一语料和关联表
  predictions/                           # 模型预测结果
  aggregates/                            # 中间聚合 parquet
  json/                                  # 后端可读取的缓存/兜底 JSON，私有产物
  mock/                                  # 无业务含义的本地开发 mock JSON
```

`data/dashboard/raw|processed|predictions|aggregates|json` 属于生成数据目录，正式启用时应加入 `.gitignore`。开源仓库不提交真实业务数据；若需要仓库可直接预览，只提交 `data/dashboard/mock/` 中无业务含义的示例结构。

## 6. ClickHouse 导出数据集

当前 `scripts/data_repair/export_business_data.py` 只导出 post/comment 最小字段，足够做业务标注候选，但不足以支撑本地 CK 开发、兜底缓存或固定答辩数据。Dashboard 可新增专用导出脚本，显式列出所需字段；生产主路径仍由后端直连 CK 查询，不依赖持续文件同步。

### 6.1 `posts_raw.parquet`

来源：`weibo.post`

| 字段 | 用途 | 备注 |
|---|---|---|
| `post_id` | 主键、关联互动/话题/发现入口 | 必需 |
| `mblogid` | 原帖链接构造 | 公开展示可隐藏 |
| `user_id` | 关联作者画像 | 对外展示建议 hash 或不返回 |
| `text_raw` | 情绪预测输入、证据流 | 仓库不提交；公开展示按需要控制原文范围 |
| `created_at` | 发帖时间趋势 | CK 存 UTC，前端展示东八区 |
| `region_name` | 发布地域粗粒度分析 | 可空串 |
| `source_client` | 客户端分布 | 可选 |
| `has_images` | 媒体特征 | 0/1 |
| `has_video` | 媒体特征 | 0/1 |
| `retweet_of` | 转发/原创结构 | 只单级展开 |
| `visible_type` | 可见性过滤 | 可选 |

导出原则：

- 必须带 `created_at` 时间范围，利用分区裁剪。
- 大范围查询优先用 `argMax` 或窄范围 `FINAL`，不要无条件全表 `FINAL`。
- 不使用 `SELECT *`。

### 6.2 `comments_raw.parquet`

来源：`weibo.comment`

| 字段 | 用途 | 备注 |
|---|---|---|
| `comment_id` | 主键 | 必需 |
| `post_id` | 关联原帖和话题 | 必需 |
| `parent_comment_id` | 一级/子评论区分 | `0` 为一级评论 |
| `reply_to_comment_id` | 回复对象 | 可选 |
| `user_id` | 关联评论者画像 | 对外展示建议 hash 或不返回 |
| `text_raw` | 情绪预测输入、证据流 | 必需 |
| `region_name` | 评论地域粗粒度分析 | 可空 |
| `source_client` | 客户端分布 | 可选 |
| `like_count` | 高赞评论筛选 | 采样内点赞 |
| `floor_number` | 评论楼层 | 可选 |
| `created_at` | 评论时间趋势 | UTC 存储 |

口径限制：

- `comment` 是采样数据，不代表全量评论。
- 不得用 `count(*) FROM comment` 当平台评论总数。
- 评论总数使用 `post_engagement_ts.comments_count` 的最新快照。

### 6.3 `engagement_raw.parquet`

来源：`weibo.post_engagement_ts`

| 字段 | 用途 | 备注 |
|---|---|---|
| `post_id` | 关联帖子 | 必需 |
| `captured_at` | 快照时间 | UTC 存储 |
| `comments_count` | 平台评论总数 | 不是采样评论行数 |
| `attitudes_count` | 点赞总数 | 平台快照 |
| `reposts_count` | 转发总数 | 平台快照 |

派生能力：

- 最新互动数：按 `post_id` 对 `captured_at` 做 `argMax`。
- 互动增长：同一 `post_id` 的首末快照差值。
- 爆发速度：单位时间内互动增量。

口径限制：

- 快照是稀疏的，不是连续分钟级时间序列。
- 帖子发布 7 天后停止新增回扫，但旧快照仍保留到 TTL。
- 冷帖可能因为 L4 heat limit 在 7 天内也缺少快照。

### 6.4 `topics_raw.parquet`

来源：`weibo.topic`

| 字段 | 用途 | 备注 |
|---|---|---|
| `topic_id` | 话题主键 | `cityHash64(normalized_title)` |
| `title` | 话题标题 | 不带 `#` 包裹 |
| `read_count` | 阅读量排序 | 数值字段 |
| `discuss_count` | 讨论量排序 | 数值字段 |
| `lead` | 话题导语 | 可空 |
| `hot_value` | 平台热度原文 | 字符串，不做数值聚合 |
| `first_seen_at` | 首次热榜观察 | immutable |
| `last_seen_at` | 最近热榜观察 | 可做生命周期 |

### 6.5 `post_topics_raw.parquet`

来源：`weibo.post_topic`

| 字段 | 用途 | 备注 |
|---|---|---|
| `post_id` | 帖子主键 | 必需 |
| `topic_id` | 话题主键 | 必需 |
| `linked_at` | 关联首次发现时间 | 可做话题聚集时间 |

口径限制：

- 转发链原帖当前没有 `post_topic`，因为 `retweeted_status` 中没有 `topic_struct`。
- 话题分析代表“显式携带话题的帖子”，不是所有相关文本。

### 6.6 `discovery_raw.parquet`

来源：`weibo.post_discovery`

| 字段 | 用途 | 备注 |
|---|---|---|
| `post_id` | 关联帖子 | 必需 |
| `source_type` | 发现入口 | hot/keyword/kol/retweet |
| `source_value` | 入口值 | 话题名/关键词/KOL uid/原帖 id |
| `discovered_at` | 发现时间 | 用于首次入口和入口演化 |

派生能力：

- 首次发现入口：每个 `post_id` 按 `discovered_at` 排序取第一条。
- 入口贡献：按去重 `post_id` 统计 hot/keyword/kol/retweet 覆盖。
- 跨入口扩散度：同一话题下不同 `source_type` 的多样性。

口径限制：

- `post_discovery` 是发现事件，一帖可多行。
- 不得直接 `count(*)` 当帖子数。
- `source_type='kol'` 表示从 KOL 入口发现，不等于该帖作者一定是 KOL。

### 6.7 `users_raw.parquet`

来源：`weibo.user`

| 字段 | 用途 | 备注 |
|---|---|---|
| `uid` | 用户主键 | 对外展示建议 hash 或不返回 |
| `screen_name` | 展示名 | 公开展示可替换为角色名 |
| `verified` | 是否认证 | tier 0+ 可用 |
| `verified_type` | 认证类别 | tier 0+ 可用 |
| `verified_reason` | 认证说明 | tier 1+ 可用 |
| `followers_count` | 粉丝数 | 仅 `profile_tier >= 1` 可信 |
| `friends_count` | 关注数 | 仅 `profile_tier >= 1` 可信 |
| `statuses_count` | 微博数 | 仅 `profile_tier >= 1` 可信 |
| `location` | 注册地域 | 仅 `profile_tier >= 1` 可信 |
| `gender` | 性别 | 仅 `profile_tier >= 1` 可信 |
| `ip_location` | IP 属地 | 仅 `profile_tier = 2` 可信 |
| `labels` | 博主标签 | 仅 `profile_tier = 2` 可信 |
| `profile_tier` | 画像完整度 | 必须展示覆盖率 |
| `first_seen_at` | 系统首次见到 | immutable |

用户数据使用原则：

- 先展示 `profile_tier` 覆盖率，再展示粉丝、地域、性别等画像。
- `followers_count = 0` 不代表真实 0 粉丝，可能只是 tier 0 未拉取。
- 用户/KOL 用于解释舆情放大，不做个人画像产品。

### 6.8 `media_raw.parquet`（可选）

来源：`weibo.post_media`

媒体数据不是 MVP 必需，但可用于后续增强“图文/视频内容是否更易扩散”的解释。

| 字段 | 用途 | 备注 |
|---|---|---|
| `post_id` | 关联帖子 | 必需 |
| `media_type` | 图片/视频/gif 分布 | 可做媒体类型筛选 |
| `media_id` | 稳定媒体主键 | 比 `order_index` 稳定 |
| `media_url` | 内容回看 | 仓库不提交；公开展示按权限控制 |
| `order_index` | 展示顺序参考 | 编辑后可能变化，不可当稳定封面 |
| `width` | 图片宽度 | 可选 |
| `height` | 图片高度 | 可选 |
| `crawled_at` | 抓取时间 | 版本列 |

口径限制：

- `order_index` 不稳定，帖子编辑后顺序可能变化。
- 对外公开展示默认不暴露真实 `media_url`，只保留媒体类型和数量；内部演示可按权限打开。

## 7. 文本语料与模型预测

### 7.1 `business_corpus.parquet`

来源：`posts_raw.parquet` + `comments_raw.parquet`

| 字段 | 说明 |
|---|---|
| `source` | `post` 或 `comment` |
| `source_id` | `post_id` 或 `comment_id` 字符串 |
| `post_id` | 评论保留所属 post；post 自身等于 post_id |
| `user_id` | 作者/评论者，对外展示建议 hash 或不返回 |
| `raw_text` | 原始文本 |
| `content` | 清洗后文本，复用 `scripts/preprocess.py:clean_text` 语义 |
| `created_at` | 原始 UTC 时间 |
| `created_cst` | 展示层东八区时间，可在 JSON 层生成 |
| `region_name` | 发布/评论地域 |
| `like_count` | 评论点赞数；post 可为空 |
| `has_images` | post 媒体特征；comment 为空 |
| `has_video` | post 媒体特征；comment 为空 |
| `content_hash` | 去重与稳定引用 |

清洗规则必须沿用现有预处理约定：保留微博表情如 `[心]`，去 URL、转发链、@ 提及，话题去 `#` 保留文本，繁体转简体。

### 7.2 `business_predictions.parquet` / `dashboard.sentiment_prediction`

主模型默认：`runs/ernie-usual-mixed-v2/best`

生产展示推荐把预测结果写入 ClickHouse 分析表 `dashboard.sentiment_prediction`，方便后端与 `post`、`comment`、`post_topic`、`user` 等表 JOIN 查询。本地开发或答辩固定数据可使用同构 parquet 文件 `business_predictions.parquet`。

| 字段 | 说明 |
|---|---|
| 业务字段 | 继承 `business_corpus.parquet` |
| `pred_label` | 预测标签：积极/愤怒/悲伤/恐惧/惊讶/中性 |
| `pred_label_id` | 与 `src/npo/config.py:LABELS_ZH` 一致 |
| `confidence` | top1 softmax 分数，用作排序置信信号 |
| `second_label` | top2 标签 |
| `second_prob` | top2 softmax 分数 |
| `margin` | `confidence - second_prob`，越低越不确定 |
| `prob_积极` | 六类概率之一 |
| `prob_愤怒` | 六类概率之一 |
| `prob_悲伤` | 六类概率之一 |
| `prob_恐惧` | 六类概率之一 |
| `prob_惊讶` | 六类概率之一 |
| `prob_中性` | 六类概率之一 |
| `model_key` | `ernie` |
| `checkpoint` | checkpoint 路径或版本名 |
| `predicted_at` | 预测生成时间 |

说明：`confidence` 不是严格校准概率，不应写成“模型有 91% 概率绝对正确”，而应解释为“模型对 top1 标签的相对置信信号”。

预测任务策略：

- 定时扫描新增 `post` / `comment` 文本，只预测未出现在预测表中的 `source + source_id`。
- 预测结果按 `model_version` 保留，模型升级时允许并存多版本，后端默认读取当前主模型版本。
- 云服务器资源有限，预测任务应限速、分批，避免和爬虫、CK 查询抢资源；重训练或大批量预测优先在本地/GPU 环境完成。

### 7.3 `business_disagreement.parquet`（可选）

只对高价值样本跑 BERT 对照，避免成本过高。

候选条件：

- `confidence < 0.70`
- `margin < 0.20`
- `pred_label in ('愤怒', '悲伤', '恐惧')`
- 高互动或高影响账号参与
- 最近 N 天样本

字段：

| 字段 | 说明 |
|---|---|
| `ernie_pred` | 主模型标签 |
| `ernie_confidence` | 主模型置信信号 |
| `bert_pred` | 对照模型标签 |
| `bert_confidence` | 对照模型置信信号 |
| `agree` | 两模型 top1 是否一致 |
| `disagreement_type` | `same` / `label_disagree` / `low_margin` |
| `active_learning_score` | 困难样本优先级 |

BERT 不作为最终主模型，只用于困难样本发现、主动学习和模型解释页。

### 7.4 ClickHouse 新表：`dashboard.sentiment_prediction`

生产展示需要一张新的分析侧预测结果表。原始 `weibo.post` / `weibo.comment` 不写回情绪字段，避免污染采集层数据；情绪预测作为派生结果单独存放，后端查询时再按 `source_type + source_id` 或 `post_id` JOIN。

建库建议：

```sql
CREATE DATABASE IF NOT EXISTS dashboard;
```

建表建议：

```sql
CREATE TABLE IF NOT EXISTS dashboard.sentiment_prediction
(
    source_type LowCardinality(String),      -- post / comment
    source_id UInt64,                        -- post_id 或 comment_id
    post_id UInt64,                          -- comment 归属 post；post 自身等于 post_id
    source_created_at DateTime,              -- 原 post/comment created_at，用于分区裁剪
    content_hash UInt64,                     -- cityHash64(cleaned content)，用于去重和追踪

    model_key LowCardinality(String),         -- ernie / bert
    model_version LowCardinality(String),     -- 例如 ernie-usual-mixed-v2
    checkpoint String,                       -- checkpoint 路径或发布版本

    pred_label LowCardinality(String),        -- 积极/愤怒/悲伤/恐惧/惊讶/中性
    pred_label_id UInt8,                     -- 与 LABELS_ZH 顺序一致
    confidence Float32,
    second_label LowCardinality(String),
    second_label_id UInt8,
    second_prob Float32,
    margin Float32,

    prob_positive Float32,
    prob_angry Float32,
    prob_sad Float32,
    prob_fear Float32,
    prob_surprise Float32,
    prob_neutral Float32,

    predicted_at DateTime DEFAULT now()
)
ENGINE = ReplacingMergeTree(predicted_at)
PARTITION BY toYYYYMM(source_created_at)
ORDER BY (model_version, source_type, source_id)
SETTINGS index_granularity = 8192;
```

写入规则：

- `source_type + source_id + model_version` 是一条预测结果的逻辑唯一键。
- 同一模型版本重复预测同一文本时，`ReplacingMergeTree(predicted_at)` 保留最新结果；查询强一致需要窄范围 `FINAL` 或按 `argMax` 取最新。
- 模型升级不覆盖旧版本，写入新的 `model_version`，后端默认读取当前主模型版本。
- `source_created_at` 必须来自原始 post/comment，用于分区裁剪；不要只靠 `predicted_at` 过滤业务时间范围。
- 概率列使用英文列名，避免 SQL、前端和不同驱动处理中文列名时出现兼容问题。

后端常用查询口径：

```sql
-- 查当前主模型在时间窗口内的情绪分布
SELECT pred_label, count() AS n
FROM dashboard.sentiment_prediction
WHERE model_version = {model_version:String}
  AND source_created_at >= {start:DateTime}
  AND source_created_at < {end:DateTime}
GROUP BY pred_label;
```

```sql
-- 查某话题下帖子的预测情绪，先用 post_topic 缩小 post_id 集合
SELECT sp.pred_label, count() AS n
FROM dashboard.sentiment_prediction AS sp
INNER JOIN weibo.post_topic AS pt ON pt.post_id = sp.post_id
WHERE sp.model_version = {model_version:String}
  AND pt.topic_id = {topic_id:UInt64}
  AND sp.source_created_at >= {start:DateTime}
  AND sp.source_created_at < {end:DateTime}
GROUP BY sp.pred_label;
```

是否需要更多新表：

- MVP 阶段只要求 `dashboard.sentiment_prediction`。
- 风险分、话题榜、KOL 贡献等优先由后端查询 CK 后缓存到内存/本地文件，不急于创建聚合表。
- 如果后续云服务器查询压力过大，再考虑增加 `dashboard.topic_risk_snapshot` 这类按小时/天聚合的缓存表。

## 8. 派生指标定义

### 8.1 标签与负面情绪

标签顺序必须与 `src/npo/config.py:LABELS_ZH` 一致：

```text
0=积极, 1=愤怒, 2=悲伤, 3=恐惧, 4=惊讶, 5=中性
```

负面情绪定义：

```text
negative = 愤怒 + 悲伤 + 恐惧
```

惊讶不直接算负面，但作为“突发/异常”信号参与解释。

### 8.2 互动指标

最新互动数：

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

展示中必须标注互动数来自平台快照 `post_engagement_ts`。

### 8.3 用户影响力分

用户影响力分只用于排序和解释，不表示绝对影响力。

```text
actor_influence_score =
  verified_bonus
+ follower_bucket_score
+ event_activity_score
+ interaction_contribution_score
+ kol_entry_bonus
```

建议取值：

| 组成 | 计算方式 |
|---|---|
| `verified_bonus` | 认证用户加分，普通用户为 0 |
| `follower_bucket_score` | 仅 `profile_tier >= 1` 时按粉丝区间加分 |
| `event_activity_score` | 同一话题内发帖/评论次数归一化 |
| `interaction_contribution_score` | 该用户内容带来的互动量归一化 |
| `kol_entry_bonus` | 该用户或其关联帖子来自 KOL 入口时加分 |

粉丝区间建议：

| 区间 | 展示 |
|---|---|
| unknown | `tier0 未覆盖` |
| `<1k` | 小影响力 |
| `1k-1w` | 中低影响力 |
| `1w-10w` | 中影响力 |
| `10w-100w` | 高影响力 |
| `100w+` | 超高影响力 |

### 8.4 KOL 定义

KOL 不等于单一字段，应分三类解释：

| 类型 | 判定 | 用途 |
|---|---|---|
| 入口型 KOL | `post_discovery.source_type = 'kol'` | 表示系统通过 KOL 入口发现该帖 |
| 身份型 KOL | `verified = 1` 或 `profile_tier >= 1` 且粉丝数高 | 表示账号自身可能有扩散能力 |
| 事件型关键用户 | 当前话题内高频、高互动、跨话题出现 | 表示在该事件中影响突出 |

前端文案必须区分“来自 KOL 入口”和“作者是 KOL”。

### 8.5 跨入口扩散度

用于衡量一个话题是否从单一入口扩展到多个发现来源。

```text
source_types = distinct source_type for posts in topic
source_diversity = count(source_types) / 4
```

可选增强：使用 Shannon entropy 表示入口分布均衡程度。

### 8.6 风险分

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

定义：

| 因子 | 说明 |
|---|---|
| `negative_ratio` | 话题内负面样本占比 |
| `negative_growth_score` | 近窗口负面样本增长，按 p95 截断归一化 |
| `interaction_growth_score` | 互动增长，按 p95 截断归一化 |
| `anger_fear_ratio` | 愤怒 + 恐惧占比，强调危机和对抗情绪 |
| `kol_verified_score` | KOL 入口、认证账号、高粉账号参与度 |
| `source_diversity_score` | hot/keyword/kol/retweet 多入口扩散程度 |

归一化建议：

```text
norm(x) = min(x / p95(x in current snapshot), 1.0)
```

风险等级：

| 分数 | 等级 | 展示 |
|---:|---|---|
| `>= 80` | 高风险 | 需要人工关注 |
| `60-79` | 中高风险 | 持续跟踪 |
| `40-59` | 中风险 | 观察 |
| `< 40` | 低风险 | 常规监测 |

### 8.7 证据样本排序

证据流不应只按发布时间排序，应优先展示能解释风险的样本。

```text
evidence_score =
  0.30 * sample_risk
+ 0.20 * interaction_rank
+ 0.20 * actor_influence_rank
+ 0.15 * confidence
+ 0.15 * low_margin_bonus
```

其中 `low_margin_bonus` 用于展示模型不确定样本，帮助说明“为什么需要人工关注”。

## 9. 后端 API 响应契约

前端 MVP 只请求同源 `/api/dashboard/*`，不直接读取 `data/dashboard/json/*.json`，也不直接读 parquet。后端负责查询 CK、读取预测结果表，或读取私有兜底缓存，并按以下 JSON 契约返回响应。

建议 API 路由：

| API | 后端默认数据源 | 用途 |
|---|---|---|
| `GET /api/dashboard/meta` | CK 元信息查询或 `meta.json` 兜底 | 数据窗口、模型版本、标签顺序 |
| `GET /api/dashboard/overview` | CK 聚合 + 缓存 | 总览 KPI |
| `GET /api/dashboard/emotion-timeseries` | 预测表聚合 + 缓存 | 情绪趋势 |
| `GET /api/dashboard/risk-topics` | topic/post/prediction/engagement 聚合 | 风险话题榜 |
| `GET /api/dashboard/topics/{topic_id}` | topic 相关明细查询 + 缓存 | 话题详情 |
| `GET /api/dashboard/actors` | user/post/comment/prediction 聚合 | 关键账号/KOL |
| `GET /api/dashboard/influence-emotion` | actor 聚合 | 影响力-情绪矩阵 |
| `GET /api/dashboard/evidence` | 证据样本查询 + 分页 | 证据样本 |
| `GET /api/dashboard/model-quality` | 本地结果文件或 CK 配置表 | 模型解释 |
| `GET /api/dashboard/data-quality` | 规则配置 + CK 覆盖率查询 | 数据口径说明 |

后端可以在 API 层做分页、字段裁剪、缓存和权限控制；前端不感知真实文件路径或 CK 查询细节。下方 JSON 名称表示响应结构或兜底缓存文件名，不代表浏览器直接读取这些文件。

### 9.1 `meta.json`

```json
{
  "schema_version": "dashboard.v1",
  "generated_at": "2026-05-08T12:00:00+08:00",
  "data_window": {
    "start": "2026-05-01T00:00:00+08:00",
    "end": "2026-05-07T23:59:59+08:00",
    "available_days": 7,
    "is_partial_history": true
  },
  "time_range_options": ["all_available", "24h", "7d"],
  "model": {
    "name": "ERNIE mixed-v2",
    "checkpoint": "runs/ernie-usual-mixed-v2/best"
  },
  "labels": ["积极", "愤怒", "悲伤", "恐惧", "惊讶", "中性"],
  "negative_labels": ["愤怒", "悲伤", "恐惧"]
}
```

### 9.2 `overview.json`

```json
{
  "post_count": 18426,
  "sampled_comment_count": 96280,
  "active_topic_count": 42,
  "latest_interactions": 1284000,
  "negative_ratio": 0.438,
  "risk_index": 73.8,
  "avg_confidence": 0.86,
  "low_confidence_count": 718,
  "kol_entry_post_count": 126,
  "verified_actor_count": 84,
  "profile_tier_distribution": {
    "0": 0.74,
    "1": 0.21,
    "2": 0.05
  }
}
```

### 9.3 `emotion_timeseries.json`

```json
[
  {
    "time": "2026-05-01",
    "granularity": "day",
    "counts": {"积极": 220, "愤怒": 180, "悲伤": 120, "恐惧": 80, "惊讶": 90, "中性": 310},
    "negative_ratio": 0.38,
    "avg_confidence": 0.85
  }
]
```

### 9.4 `risk_topics.json`

```json
[
  {
    "topic_id": "123456",
    "title": "售后退款进度",
    "risk_score": 86.0,
    "risk_level": "high",
    "dominant_emotion": "愤怒",
    "negative_ratio": 0.68,
    "interaction_growth": 0.41,
    "post_count": 1240,
    "sampled_comment_count": 3800,
    "kol_entry_count": 8,
    "verified_actor_count": 12,
    "source_mix": {"hot": 0.34, "keyword": 0.42, "kol": 0.18, "retweet": 0.06},
    "risk_factors": {
      "negative_ratio": 0.31,
      "negative_growth": 0.24,
      "interaction_growth": 0.18,
      "anger_fear": 0.20,
      "kol_verified": 0.07,
      "source_diversity": 0.06
    }
  }
]
```

### 9.5 `topic_details/<topic_id>.json`

```json
{
  "topic": {
    "topic_id": "123456",
    "title": "售后退款进度",
    "lead": "话题导语或摘要",
    "risk_score": 86.0
  },
  "timeline": [],
  "emotion_distribution": {},
  "engagement_curve": [],
  "source_mix": {},
  "top_actors": [],
  "evidence_samples": []
}
```

### 9.6 `actor_summary.json`

```json
[
  {
    "actor_id": "u_8f23a1",
    "display_name": "认证媒体 A",
    "verified": true,
    "verified_type": 3,
    "verified_reason": "媒体机构",
    "profile_tier": 1,
    "followers_bucket": "10w-100w",
    "topic_count": 4,
    "post_count": 12,
    "comment_count": 0,
    "dominant_emotion": "愤怒",
    "negative_ratio": 0.75,
    "interaction_contribution": 0.18,
    "actor_influence_score": 82.0,
    "roles": ["verified_actor", "event_key_actor"]
  }
]
```

### 9.7 `influence_emotion_matrix.json`

```json
[
  {
    "actor_id": "u_8f23a1",
    "display_name": "认证媒体 A",
    "influence_score": 82.0,
    "negative_ratio": 0.75,
    "interaction_count": 14320,
    "dominant_emotion": "愤怒",
    "topic_title": "售后退款进度"
  }
]
```

### 9.8 `evidence_samples.json`

只保留前端需要展示的 Top N 样本，不把全量原文放进仓库。若展示链接公开访问，应由数据生成侧决定是否返回原文、改写文本或摘要。

```json
[
  {
    "sample_id": "ev_000001",
    "source": "comment",
    "source_id": "c_123",
    "post_id": "p_456",
    "topic_id": "123456",
    "created_at": "2026-05-01T10:22:00+08:00",
    "content": "代表性文本或摘要",
    "pred_label": "愤怒",
    "confidence": 0.91,
    "second_label": "悲伤",
    "margin": 0.27,
    "interaction_count": 328,
    "actor_role": "verified_actor",
    "evidence_reason": "高互动 + 认证账号参与 + 愤怒高置信"
  }
]
```

### 9.9 `model_quality.json`

来源：`runs/*/final_*_report.json`、`results/model-selection-20260505.md` 和分歧分析产物。

```json
{
  "primary_model": "ERNIE mixed-v2",
  "business_eval": {
    "accuracy": 0.8260,
    "macro_f1": 0.7738,
    "per_class_f1": {
      "积极": 0.9138,
      "愤怒": 0.7565,
      "悲伤": 0.7761,
      "恐惧": 0.7299,
      "惊讶": 0.6881,
      "中性": 0.7785
    }
  },
  "smp_test": {
    "accuracy": 0.7994,
    "macro_f1": 0.7702
  },
  "bert_comparison": {
    "usage": "对照模型和困难样本发现工具",
    "agreement_rate": 0.8153,
    "oracle_accuracy": 0.8760
  }
}
```

### 9.10 `data_quality.json`

```json
{
  "comment_sampling_notice": "评论为采样集合，不代表全量评论分布。",
  "engagement_notice": "互动数来自 post_engagement_ts 平台快照。",
  "timezone_notice": "存储为 UTC，前端展示为东八区。",
  "history_window_notice": "当前爬虫仅有约 10 多天历史数据，趋势和风险分只按实际可用窗口解释。",
  "user_tier_notice": "followers_count 等画像字段仅 profile_tier >= 1 可信。",
  "post_discovery_notice": "post_discovery 是多行发现事件，不等于帖子数。",
  "profile_tier_distribution": {"0": 0.74, "1": 0.21, "2": 0.05},
  "generated_from": ["post", "comment", "post_engagement_ts", "topic", "post_topic", "post_discovery", "user"]
}
```

若启用媒体增强模块，`generated_from` 可追加 `post_media`。

## 10. 页面与数据关系

### 10.1 总览页

目标：快速判断当前舆情是否异常。

数据：

- `overview.json`
- `emotion_timeseries.json`
- `risk_topics.json`
- `data_quality.json`

模块：

- KPI：帖子数、采样评论数、活跃话题、风险指数、平均置信度。
- 六分类情绪趋势。
- 风险话题榜。
- 入口来源概览。
- 关键账号参与概览。

### 10.2 话题详情页

目标：解释一个话题为什么风险高。

数据：

- `topic_details/<topic_id>.json`
- `evidence_samples.json`
- `actor_summary.json`

模块：

- 情绪时间线。
- 互动增长曲线。
- 风险因子解释。
- 代表性帖子/评论证据流。
- 关键账号贡献榜。
- 入口来源变化。

### 10.3 传播溯源页

目标：说明事件从哪里被发现，是否跨入口扩散。

数据：

- `risk_topics.json`
- `topic_details/<topic_id>.json`

模块：

- 首次发现入口。
- hot/keyword/kol/retweet 占比。
- 入口随时间变化。
- 同一话题下多入口扩散路径。

### 10.4 账号/KOL 页

目标：解释是谁在放大风险。

数据：

- `actor_summary.json`
- `influence_emotion_matrix.json`
- `data_quality.json`

模块：

- profile tier 覆盖率。
- 认证账号参与榜。
- 事件关键用户榜。
- 影响力-情绪矩阵。
- 高影响负面样本。

### 10.5 模型解释页

目标：证明模型可靠，并说明不确定性。

数据：

- `model_quality.json`
- `evidence_samples.json`
- 可选 `business_disagreement.parquet` 聚合结果。

模块：

- ERNIE/BERT 指标对比。
- per-class F1。
- 混淆矩阵。
- 低置信样本。
- 分歧样本。

### 10.6 数据口径页

目标：让评审、展示链接访问者和开源仓库阅读者知道数据边界。

数据：

- `data_quality.json`
- `meta.json`

模块：

- 数据生产链路 L0-L4。
- 评论采样说明。
- 互动快照说明。
- 当前仅有约 10 多天历史数据，暂不展示 30 天/月度基线结论。
- 用户画像 tier 说明。
- ReplacingMergeTree 和时区说明。

## 11. 仓库开源与展示数据策略

基本原则：代码仓库可以开源，真实业务数据不随仓库开源。公开展示必须通过后端 API 提供数据，前端不配置、也不直接访问静态 JSON 目录或对象存储地址。

仓库内容：

- 提交前端代码、数据契约文档、脚本、无业务含义 mock 数据。
- 不提交 `data/dashboard/raw|processed|predictions|aggregates|json`。
- 不提交 ClickHouse 连接信息、`.env`、业务全量 parquet、模型权重。

展示环境：

- 前端只请求同源 `/api/dashboard/*`，由后端读取真实 dashboard JSON 或查询 CK。
- 生产优先由后端查询 CK 和预测结果表；若使用 JSON/parquet 缓存、对象存储、Nginx 静态目录或共享文件系统，也只能作为后端私有数据源，不能让浏览器直接访问。
- 如果展示链接公开访问，建议默认不返回真实 uid、主页 URL、头像 URL、媒体 URL、`raw_json`。
- 账号名、粉丝数、原文是否公开展示由演示目标和合规要求决定；若面向公开简历展示，推荐使用角色名、粉丝区间和代表性摘要。

可选保护规则：

- `uid`、`post_id`、`comment_id` 对外返回稳定 hash 或 demo id。
- `screen_name` 可替换为“认证媒体 A / 普通用户 B / 企业账号 C”。
- `followers_count` 可改为区间，不暴露精确值。
- 文本样本可保留原文、摘要或轻度改写，取决于展示链接访问范围。

## 12. SQL 与查询口径规范

- 显式列出字段，不使用 `SELECT *`。
- 所有大表查询都带时间范围，触发分区裁剪。
- `post`、`comment`、`user`、`topic` 等 ReplacingMergeTree 表使用窄范围 `FINAL` 或 `argMax` 去重。
- `LEFT JOIN` 用户表时设置 `join_use_nulls = 1`，或显式过滤 `uid != 0`。
- 展示层转东八区，查询和存储层按 UTC 比较。
- `hot_value` 只展示原文，不做数值聚合；排序用 `read_count` / `discuss_count`。
- 统计帖子数时对 `post_id` 去重，统计发现入口时区分“发现事件数”和“覆盖帖子数”。

## 13. 验证清单

每次生成 dashboard 数据集后应检查：

- JSON 均包含 `schema_version` 或可追溯 `meta.json`。
- 标签集合严格等于 `积极/愤怒/悲伤/恐惧/惊讶/中性`。
- `pred_label_id` 与 `LABELS_ZH` 顺序一致。
- `dashboard.sentiment_prediction` 的逻辑唯一键为 `source_type + source_id + model_version`，查询当前版本时必须显式过滤 `model_version`。
- `comment` 指标文案都标注“采样”。
- 用户画像模块显示 `profile_tier` 覆盖率。
- `meta.data_window.available_days` 反映真实可用历史，不默认展示 30 天窗口。
- 风险分因子之和可解释，且不是黑箱单值。
- 开源仓库不包含真实 dashboard JSON、业务 parquet、uid、账号名、URL、原始全量文本和数据库连接。
- 前端不硬编码、不配置数据文件地址；只请求同源 `/api/dashboard/*`。
- 后端配置数据目录、CK 连接和密钥，且不返回给浏览器。
- 前端加载 JSON 后 3 秒内完成首屏渲染。

## 14. 分阶段实施计划

### Phase 1：数据契约与静态原型

- 完成本文档。
- 保留当前 `dashboard/index.html` 静态原型。
- 将 mock 数据结构逐步调整为本文定义的 JSON 结构。
- 增加最小后端网关，前端通过同源 `/api/dashboard/*` 获取 mock 响应。
- 本地安装 ClickHouse 并导入当前可用的约 10 多天数据，作为开发和 SQL 调试环境。

### Phase 2：CK 查询 API MVP

- 后端连接本地 ClickHouse，实现 `overview`、`emotion-timeseries`、`risk-topics`、`data-quality` 等核心 API。
- 所有 API 必须有默认时间窗口、分页、缓存和查询超时。
- `scripts/dashboard/export_dashboard_business_data.py` 只作为本地导入/兜底数据构建工具，不作为生产同步主链路。

### Phase 3：文本预测结果表与风险聚合

- 在 ClickHouse 创建 `dashboard` 数据库和 `dashboard.sentiment_prediction` 表。
- 新增 `prepare_dashboard_corpus.py`。
- 新增 `predict_business_emotions.py`，默认使用 ERNIE mixed-v2。
- 生产推荐写入 `dashboard.sentiment_prediction`；本地/兜底可生成同构 parquet。
- 新增或扩展风险聚合逻辑，后端通过 CK 查询或缓存返回 API 响应。

### Phase 4：前端扩展

- 从单页原型扩展为总览、话题详情、传播溯源、账号/KOL、模型解释、数据口径。
- 前端只调用后端 API，不直接读 JSON 文件或 parquet。

### Phase 5：后端能力增强

- 后端从基础 CK 聚合 API 增强为支持搜索、分页、权限和人工反馈。
- 如需近实时数据，后端增加 ClickHouse 轻量查询和缓存。
- 后端不做在线模型推理，只查询 CK、预测结果表或后端私有缓存。

## 15. 论文与项目展示叙事

毕业设计可按四层叙述：

1. 数据采集层：微博数据生产、ClickHouse 存储、L0-L4 数据链路。
2. 数据治理层：清洗、去重、采样口径、时区、用户画像覆盖率。
3. 情感分析层：ERNIE/BERT 微调、六分类、业务验证集、模型选择。
4. 可视化研判层：趋势监控、事件发现、风险解释、KOL 影响、样本追溯。

项目展示重点：

- 不是只展示“情绪饼图”，而是解释风险形成原因。
- 不是只展示“用户排行榜”，而是解释关键账号如何影响话题风险。
- 不是只展示“模型准确率”，而是展示置信度、混淆、分歧和数据口径。
