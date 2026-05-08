# 数据交接说明（面向数据分析侧）

> 本文档由微博舆情爬虫仓库（`network-public-opinion-spider`）维护，是数据生产侧对下游数据分析 / NLP / 仪表盘项目的**数据契约**。下游项目应将本文档视为唯一对外口径；遇到与本文档不一致的现象，先回到这里核对，再向生产侧反馈。
>
> 修订时机：每次 `sql/ddl/schema.sql`、`pipeline/l*/`、`pipeline/common/topic_norm.py`、`pipeline/common/time_display.py` 有破坏性改动时同步更新。

---

## 1. 目的与读者

读者是**不接触爬虫代码、只消费数据**的角色——数据分析师、NLP / 情感分析工程师、看板开发、决策同学。读完应当能回答：

- 数据从哪来、到哪去、什么时候到？
- 哪几张表、各自存什么、字段什么含义？
- 什么字段什么时候**才会有值**？什么字段**永远是采样**？
- 怎么写不会踩 ReplacingMergeTree / 时区 / JOIN 默认值的坑？
- 看到异常数据时怎么定位是上游问题还是查询写法问题？

不在本文档范围：

- 爬虫内部架构（见 `AGENTS.md`、`plan-docs/03-pipeline-design.md`）
- 运行 / 部署 / 反爬处理（见 `operations.md`、`multi-worker-design.md`）
- 下游分析的具体方法学（情感模型、话题聚类、KOL 评分等）

---

## 2. 与生产侧的边界

| 项 | 分析侧的姿势 |
|---|---|
| 写权限 | **没有**。CK 上请使用只读账号；不建表、不 `INSERT`、不 `ALTER`、不 `OPTIMIZE`。生产侧的 `ReplacingMergeTree` merge 由 CK 后台进程负责。 |
| schema 演进 | 由生产侧 `sql/ddl/schema.sql` 单一来源；新增列优先 `ALTER TABLE ... ADD COLUMN`，旧列不立即下线。**分析侧 SQL 永远显式列出需要的列，不要 `SELECT *`**。 |
| 反爬异常 / 数据断流 | 不要直接联系微博方；通过仓库 issue 或运维渠道告诉生产侧，对方有 `tools/ops/status.py` + `logs/stage2/anti_crawl_*` 可定位。 |
| 历史数据补抓 | 一般不补。爬虫是"持续观察"模型，错过的窗口（cookie 失效 / 反爬期）通常不会回填，分析侧应当容忍稀疏并做日历级别的归因。 |
| 跨库 / 跨实例 | 当前是**单机 ClickHouse**。分析侧若需要复制到自己的实例，建议 `INSERT ... SELECT` 或者 `clickhouse-client --query="SELECT ... FORMAT Native" \| ...`；不要在生产 CK 上直接长跑分析查询，跑 `_FINAL` 或全表扫描会和爬虫写入抢 page cache。 |

---

## 3. 数据生产管线（必要最小知识）

```
L0 发现层 (热榜 / 关键词 / KOL)
        │  push  → queue:l1_post:*           (按 mid 去重)
        ▼
L1 帖子详情 (/ajax/statuses/show)
        │  写: post / post_engagement_ts(首次) / user(tier0) /
        │     post_topic / post_media / post_discovery
        │  push → queue:l2_comments:*  (按 numeric post_id 去重)
        │  push → queue:l3_user:*      (按 uid:target_tier 去重)
        │  push → queue:l4_engagement  (pending 去重，ack 后释放)
        ▼
L2 评论 (/ajax/statuses/buildComments) → comment + user(tier0)
L3 用户画像 (/ajax/profile/{info,detail}) → user upsert (tier 1/2)
L4 互动回扫 → 追加 post_engagement_ts 一行
```

关键含义（**直接影响分析口径**）：

- **L1 是必经**——任何被爬到的帖子都至少有一行 `post` + 一行 `post_engagement_ts`（首次快照）。
- **L2 是采样**——评论不是全量，是"分档抓前 N 页"（详见 §6.6）。
- **L3 是异步、有筛选的**——不是所有 uid 都会有 tier 1/2 数据；详见 §6.5。
- **L4 是衰减回扫**——`post_engagement_ts` 只在帖子发布后 7 天内会被持续追加，超 7 天就没有新行（详见 §6.4）。
- **L0.a 热榜入口** + **L0.b 关键词入口** + **L0.c KOL 入口**三路并行，同一帖子可能从多个入口被发现（`post_discovery` 多行）。

---

## 4. 接入信息

### 4.1 ClickHouse 实例

- 引擎：单机 ClickHouse（无副本、无分布式表）。
- 数据库：`weibo`（默认 schema）。
- 表清单见 §5。

### 4.2 推荐连接方式

```bash
# 命令行
clickhouse-client --host <host> --port 9000 --user <readonly> --password <...> --database weibo

# Python (clickhouse-connect, native HTTP/8123)
from clickhouse_connect import get_client
ck = get_client(
    host="<host>", port=8123, username="<readonly>",
    password="<...>", database="weibo",
    settings={"join_use_nulls": 1},   # 见 §7.5
)
```

### 4.3 推荐建只读账号（请运维或 CK 管理员配）

```sql
CREATE USER analyst IDENTIFIED WITH sha256_password BY '<...>';
GRANT SELECT ON weibo.* TO analyst;
-- 不要 GRANT INSERT / ALTER / OPTIMIZE / CREATE / DROP
```

### 4.4 大批量导出

舆情场景的训练 / 离线分析建议**导出到 Parquet** 再处理，不要在 CK 上直接跑超大 JOIN：

```bash
clickhouse-client --query "
  SELECT post_id, text_raw, created_at, region_name, has_images
  FROM weibo.post FINAL
  WHERE created_at >= '2026-04-01 00:00:00'
  FORMAT Parquet
" > posts_2026_04.parquet
```

或在 Python 里 `query_df` 后 `df.to_parquet(...)`。

---

## 5. 表清单（结构 + 字段语义）

> 字段类型来自 `sql/ddl/schema.sql`，遇到不一致以该文件为准。`*_at` 字段一律 **UTC aware DateTime**（§7.1）。

### 5.1 `topic` —— 话题事实表

| 列 | 类型 | 含义 |
|---|---|---|
| `topic_id` | UInt64 (PK) | `cityHash64(normalized_title)`，分析侧可本地复算（§7.4） |
| `title` | String | 不带 `#` 包裹的话题原文 |
| `read_count` | UInt64 | 阅读量；解析失败为 0 |
| `discuss_count` | UInt64 | 讨论量 |
| `lead` | String | 导语 / 描述（可空） |
| `hot_value` | String | 热度原始值（"124万" 等字符串，不要按数值聚合） |
| `first_seen_at` | DateTime | **immutable**，系统首次在热榜看到该话题的时间 |
| `last_seen_at` | DateTime | 系统最近一次在热榜看到 |
| `crawled_at` | DateTime | ReplacingMergeTree 版本列 |

引擎：`ReplacingMergeTree(crawled_at) PARTITION BY toYYYYMM(first_seen_at) ORDER BY topic_id`，**永久保留**。

### 5.2 `post` —— 帖子事实表

| 列 | 类型 | 含义 |
|---|---|---|
| `post_id` | UInt64 (PK) | 数值化 `idstr` |
| `mblogid` | String | base62 短 id；URL 回链 `https://weibo.com/{user_id}/{mblogid}` |
| `user_id` | UInt64 | → `user.uid` |
| `text_raw` | String | 帖子纯文本 |
| `region_name` | LowCardinality(String) | 例 "发布于 山西"，可空串 |
| `source_client` | LowCardinality(String) | 例 "iPhone 客户端"，已清洗 HTML |
| `created_at` | DateTime | 微博平台发布时间（UTC） |
| `edit_count` | UInt16 | 编辑次数 |
| `has_images` | UInt8 | `pic_num > 0`（0/1） |
| `has_video` | UInt8 | `mix_media_info` 或 `page_info` 含视频（0/1） |
| `is_long_text` | UInt8 | `isLongText` |
| `retweet_of` | UInt64 | `0` = 原创；非零 = 被转发原帖的 `post_id`（**单级展开**） |
| `mblog_type` | Int8 | 平台 `mblogtype` |
| `visible_type` | Int8 | `visible.type`：0 公开，其他=私密/可见分组 |
| `raw_json` | String | `/ajax/statuses/show` 原始响应 JSON（仅主帖；§6.3） |
| `first_crawled_at` | DateTime | **immutable**；系统首次抓到 |
| `last_crawled_at` | DateTime | ReplacingMergeTree 版本列；每次写入刷新 |

引擎：`ReplacingMergeTree(last_crawled_at) PARTITION BY toYYYYMM(created_at) ORDER BY post_id`，TTL = `created_at + 1 YEAR`。

### 5.3 `post_engagement_ts` —— 互动时序

| 列 | 类型 | 含义 |
|---|---|---|
| `post_id` | UInt64 | → `post.post_id` |
| `captured_at` | DateTime | 快照系统时间（UTC） |
| `comments_count` | UInt32 | 评论数（平台总数，非本系统采到的评论行数） |
| `attitudes_count` | UInt32 | 点赞数 |
| `reposts_count` | UInt32 | 转发数 |

引擎：`MergeTree PARTITION BY toYYYYMM(captured_at) ORDER BY (post_id, captured_at)`，TTL = `captured_at + 90 DAY`。

**关键**：`comments_count` 是**平台返回的总数**，与 `weibo.comment` 表里能数出来的行数（采样的）**不会相等**。要做"评论增量曲线"，请用本表，不要 `count(*) FROM comment`。

### 5.4 `post_topic` —— 帖子↔话题多对多

| 列 | 类型 | 含义 |
|---|---|---|
| `post_id` | UInt64 | |
| `topic_id` | UInt64 | |
| `linked_at` | DateTime | 这对关联首次被发现 |

引擎：`ReplacingMergeTree(linked_at) ORDER BY (post_id, topic_id)`，永久。

⚠️ **转发链原帖（`retweet_of != 0` 的那一行）当前没有 `post_topic` 关联**——原因见 §6.2。

### 5.5 `post_media` —— 帖子媒体

| 列 | 类型 | 含义 |
|---|---|---|
| `post_id` | UInt64 | |
| `media_type` | Enum8('image'=1,'video'=2,'gif'=3) | |
| `media_id` | String | `pic_id` 或 video `object_id` |
| `media_url` | String | 可直接访问 |
| `order_index` | UInt8 | 媒体顺序（图片集从 0 起；编辑后顺序可能变） |
| `width`, `height` | UInt32 | 原图尺寸（图片专用，可能 0） |
| `crawled_at` | DateTime | 版本列 |

引擎：`ReplacingMergeTree(crawled_at) ORDER BY (post_id, media_id)`，永久。

### 5.6 `post_discovery` —— 帖子来源溯源

| 列 | 类型 | 含义 |
|---|---|---|
| `post_id` | UInt64 | |
| `source_type` | Enum8('hot'=1,'keyword'=2,'kol'=3,'retweet'=4) | |
| `source_value` | String | 话题 title / 关键词 / KOL uid / 原帖 post_id（字符串形式） |
| `discovered_at` | DateTime | 该来源首次将该帖纳入流水线的时间 |

引擎：`MergeTree ORDER BY (post_id, discovered_at)`，永久。

**用法**：一帖被多入口发现 ⇒ 多行；按 `discovered_at` 排序得到"最早被哪个入口看到"，可回答"事件先在哪个圈子爆发"的时间线问题。

### 5.7 `comment` —— 评论（一级 + 子评论同表）

| 列 | 类型 | 含义 |
|---|---|---|
| `comment_id` | UInt64 (PK) | |
| `post_id` | UInt64 | → `post.post_id` |
| `parent_comment_id` | UInt64 | `0` = 一级；非 0 = 父评论 id（同表内） |
| `reply_to_comment_id` | UInt64 | 子评论的 `reply_comment.idstr`（具体回复对象） |
| `user_id` | UInt64 | 评论者 uid |
| `text_raw` | String | |
| `region_name` | LowCardinality(String) | 可空 |
| `source_client` | LowCardinality(String) | 可空 |
| `like_count` | UInt32 | |
| `floor_number` | UInt32 | |
| `created_at` | DateTime | 评论平台时间（UTC） |
| `first_crawled_at` | DateTime | **immutable**；版本列 |

引擎：`ReplacingMergeTree(first_crawled_at) PARTITION BY toYYYYMM(created_at) ORDER BY (post_id, comment_id)`，TTL = `created_at + 6 MONTH`。

⚠️ **本表是采样数据**，不是某帖的全部评论；详见 §6.6。

### 5.8 `user` —— 用户画像（tier 0/1/2 同表）

| 列 | 类型 | 含义 | 何时有值 |
|---|---|---|---|
| `uid` | UInt64 (PK) | | 总是 |
| `screen_name` | String | 昵称 | tier 0+ |
| `verified` | UInt8 | 是否认证 | tier 0+ |
| `verified_type` | Int16 | 认证类别 | tier 0+ |
| `mbrank` / `mbtype` | UInt8 | 会员等级 / 类别 | tier 0+ |
| `avatar_hd` | String | 头像 URL | tier 0+ |
| `profile_url` | String | 主页 URL | tier 0+ |
| `followers_count` | UInt32 | 精确粉丝数 | **tier 1+** |
| `friends_count` | UInt32 | 精确关注数 | **tier 1+** |
| `statuses_count` | UInt32 | 微博数 | **tier 1+** |
| `description` | String | 简介 | **tier 1+** |
| `location` | LowCardinality(String) | 注册地域 | **tier 1+** |
| `verified_reason` | String | 认证原因 | **tier 1+** |
| `gender` | LowCardinality(String) | `m` / `f` / `n` | **tier 1+** |
| `registered_at` | Nullable(DateTime) | 注册时间（UTC） | **tier 2** |
| `ip_location` | LowCardinality(String) | 例 "IP属地:北京" | **tier 2** |
| `labels` | Array(String) | 博主标签 | **tier 2** |
| `birthday` | String | 原样字符串（含星座等） | **tier 2** |
| `profile_tier` | UInt8 | **本行**覆盖到的 tier（0/1/2） | 总是 |
| `profile_fetched_at` | DateTime | 本行写入时间；版本列 | 总是 |
| `first_seen_at` | DateTime | **immutable**；系统首次见到该 uid | 总是 |

引擎：`ReplacingMergeTree(profile_fetched_at) ORDER BY uid`，**永久保留**。

⚠️ 大量 uid 永远停留在 `profile_tier = 0`——只有满足规则 A/B/C/D（认证 / 高频 / 跨话题 / 7 天刷新）才会被 L3 拉到 tier 1/2。详见 §6.5。

---

## 6. 数据完整性 / 覆盖度（必读）

### 6.1 ReplacingMergeTree 与 `FINAL`

`post`、`comment`、`user`、`topic`、`post_topic`、`post_media` 都是 `ReplacingMergeTree`。

- 同一主键多写几次只会**最终**收敛到最新版本，但合并是**异步**的，未合并时 `SELECT *` 会看到多行。
- 正确读法二选一：

  ```sql
  -- A: FINAL (准确但慢，会触发 merge)
  SELECT post_id, text_raw FROM weibo.post FINAL WHERE post_id = 123;

  -- B: argMax (快，不依赖 merge)
  SELECT post_id, argMax(text_raw, last_crawled_at) AS text_raw
  FROM weibo.post WHERE post_id = 123 GROUP BY post_id;
  ```

- **不要** 在大范围扫描时全程 `FINAL`；窄过滤再 `FINAL` 或者用 argMax 自己分组。

### 6.2 转发链：原帖单级展开 + 话题缺失

- L1 见到 `retweeted_status` 就把**主帖** + **原帖**各写一行 `post`，主帖的 `retweet_of = 原帖 post_id`，原帖的 `retweet_of = 0`。
- **不会无限递归**——只展开一级。原帖如果**也是**转发，那个再上一级原帖不会单独入库。
- 原帖的 `raw_json` **空**（只有主帖会写 `raw_json`，因为 `show` 接口只调一次）。
- **原帖没有 `post_topic` 关联**：`retweeted_status` 里没有 `topic_struct`（P1.3 验证过）。如果需要原帖的话题，等它被独立入口（热榜/关键词/KOL）抓到，那时候才会补上。
- 想统计"事件总传播量" = 原帖一行 `comments/attitudes/reposts` + 主帖一行；想统计"独立帖子数"按 `post_id` 去重。

### 6.3 `post.raw_json`

- 是 `/ajax/statuses/show` 顶层 JSON 的字符串形式。
- **只有主帖才填**（原帖不调接口、为空串）。
- 用于回看 schema 之外的字段，例如：

  ```sql
  SELECT post_id, JSONExtractString(raw_json, 'page_info', 'type') AS page_type
  FROM weibo.post FINAL
  WHERE created_at >= today() - 7 AND raw_json != ''
  ```

- TTL 跟 `post` 一致（1 年）；不要拿它当唯一可信源做长期归档。

### 6.4 `post_engagement_ts` 的稀疏度

L4 回扫频率分档（写死在 `pipeline/l4_engagement/watch.py`，未来可能调整）：

| 帖子年龄 | 回扫间隔 | 该档内每小时新增快照 |
|---|---|---|
| < 1 小时 | 5 分钟 | 12 |
| 1~6 小时 | 30 分钟 | 2 |
| 6~24 小时 | 2 小时 | 0.5 |
| 1~7 天 | 12 小时 | ≈ 0.083（一天 2 条） |
| ≥ 7 天 | **停止回扫** | 0 |

- 一帖在前 7 天内的累计快照数 ≈ `12 (首小时) + 5×2 (1-6h) + 18×0.5 (6-24h) + 6×2 (天 1-7) = 43` 条左右；之后**不再追加**新行。
- 已经写入的行**仍然保留**，直到 `captured_at + 90 DAY` 命中 TTL 才被 CK 后台清掉。所以"7 天前的帖" ≠ "没有时序数据"，只是**没有新的**时序数据。
- L4 还有候选筛选：`fetch_due_posts` 按 `(comments_count + attitudes_count + reposts_count)` heat 倒序、`limit` 截断；冷帖即使在 7 天窗口内也可能轮不到回扫。
- 反爬期 / cookie 失效期会出现整段时间无新行——这是正常现象，**不要解读为帖子降温**。

### 6.5 `user.profile_tier` 的实际分布

- **tier 0**：只要在 `post.user_id` 或 `comment.user_id` 见过就会写——**最大量**，但只有 7 个基础字段有值。
- **tier 1**（`/ajax/profile/info`）：只对满足以下条件的 uid 触发——
  - 规则 A：`verified = True`
  - 规则 B：当天高频活跃（在 ≥ N 条 post/comment 出现，N 可调）
- **tier 2**（`/ajax/profile/detail`）：只对满足以下条件的 uid 触发——
  - 规则 C：当天跨 ≥ K 个不同话题
  - 自动升级路径：tier 1 → tier 2 仅对跨话题 / KOL
- **规则 D**：tier 1/2 已有的用户每 7 天会自动刷新一次。

具体阈值看 `pipeline/l3_user/candidates.py` 与 `pipeline/run/l3_candidates.py`。**分析时不要假设"普通用户也有 followers_count"**；做相关计算先 `WHERE profile_tier >= 1`。

### 6.6 `comment` 是采样数据

L2 按 `comments_count` 分档（写死在 `pipeline/l2_comment/comments.py`）：

| 档次 | 触发条件 | 一级评论页数 × 页大小 | 子评论页数 × 页大小（仅当一级 `total_number > 0`） |
|---|---|---|---|
| 默认档 | `comments_count ≤ 500` | 3 × 10 ≈ 30 条一级 | 1 × 20 ≈ 20 条 / 一级 |
| 热帖档 | `comments_count > 500` | 10 × 10 ≈ 100 条一级 | 3 × 20 ≈ 60 条 / 一级 |

含义：

- 想要"某帖评论的精确总数"——读 `post_engagement_ts.comments_count`（最新 `argMax`），**不要**对 `comment` 表 `count(*)`。
- 评论的代表性：抓的是平台**默认排序前 N 页**（一般是高赞 + 时间近），**不是随机抽样**——情感分析时要意识到样本有偏（高赞偏向"被多数认同"的观点）。
- 子评论同理且更稀疏。
- 同一帖在不同时间被重新 enqueue 时**不会重抓评论**（L2 队列对 `post_id` 去重）；偶有重新发现的也只是按当时档位再抓一遍。

### 6.7 `post_discovery` 的多行性

- 每个 `(post_id, source_type, source_value, discovered_at)` 一行，**不去重**。
- 一帖被同一入口重新发现也会再写一行（适合做"被持续看到的频率"分析）。
- 想知道"最早怎么被发现的"：

  ```sql
  SELECT post_id, source_type, source_value
  FROM weibo.post_discovery
  WHERE post_id = 123
  ORDER BY discovered_at ASC
  LIMIT 1
  ```

### 6.8 `post_media.order_index` 不稳定

- `media_id`（pic_id / video object_id）才是稳定主键。
- `order_index` 在帖子被编辑后可能变化；**不要**依赖它做"封面图 = order_index = 0"，要业务上接受最新一次抓到的顺序。

---

## 7. 关键不变量（写 SQL 前先确认）

### 7.1 时区：CK 中所有 `DateTime` 列都是 UTC aware

- 写入侧用 `datetime.now(timezone.utc)`，读出来在 Python 里也是 UTC。
- 转东八区**只在展示层做**：

  ```sql
  -- 读 UTC，按 UTC 比较
  SELECT count() FROM weibo.post FINAL
  WHERE created_at >= toDateTime('2026-04-01 00:00:00', 'UTC');

  -- 展示按东八区
  SELECT toDateTime(created_at, 'Asia/Shanghai') AS created_cst, count()
  FROM weibo.post FINAL
  GROUP BY created_cst ORDER BY created_cst DESC LIMIT 10;
  ```

- 千万不要把 naive datetime（没有 tzinfo）写回 CK，驱动会按 server timezone 解释，每往返一次掉 8 小时。

### 7.2 immutable 时间列

`topic.first_seen_at`、`post.first_crawled_at`、`comment.first_crawled_at`、`user.first_seen_at` —— 后台合并时按版本列保留**最早**的一份，不会被新数据覆盖。所以这四个字段是稳定的"系统首次观察时间"。

### 7.3 LowCardinality 字段建议直接用

`region_name`、`source_client`、`location`、`gender`、`ip_location` 是 `LowCardinality(String)`，等值过滤极快。`WHERE region_name = '发布于 北京'` 比 `WHERE region_name LIKE '%北京%'` 快一两个量级。

### 7.4 `topic_id` 可以本地复算

```python
# pipeline/common/topic_norm.py 的等价 Python 实现
import re
from cityhash import CityHash64  # pip install cityhash

def topic_id_input(title: str) -> str:
    return re.sub(r"^#+|#+$", "", title.strip()).strip().lower()

def topic_id(title: str) -> int:
    return CityHash64(topic_id_input(title))
```

CK 端 `cityHash64(lower(trim(BOTH '#' FROM trim(title))))` 与上式比特相等（P0.3 验证过）。需要从话题名 JOIN `topic` 表时，可以本地算好 `topic_id` 直接 `WHERE topic_id = X`，比 `WHERE title = '...'` 走索引。

### 7.5 LEFT JOIN 默认 `join_use_nulls = 0`

CK 默认对未匹配行**填类型默认值**（不是 NULL）。这会让 `count(DISTINCT ...)` 把 0 当真实 uid 算进去，造成误差。

```sql
-- 推荐：会话级别打开 NULL
SET join_use_nulls = 1;

-- 或在 clickhouse-connect 里 settings={"join_use_nulls": 1}

-- 或显式过滤
SELECT count(DISTINCT u.uid)
FROM weibo.post p LEFT JOIN weibo.user u ON u.uid = p.user_id
WHERE u.uid != 0;
```

### 7.6 分区裁剪

`post`、`comment`、`post_engagement_ts` 都按 `toYYYYMM(...)` 分区。**WHERE 子句加上时间范围**（`created_at` 或 `captured_at`）才会真正裁剪，否则全库扫描。

```sql
-- ✅ 走分区裁剪
WHERE created_at >= '2026-04-01' AND created_at < '2026-05-01'

-- ❌ 全表扫
WHERE toYYYYMM(created_at) = 202604   -- 函数包裹后无法裁剪
```

---

## 8. 常用查询模式

### 8.1 取某帖最新版

```sql
SELECT post_id, text_raw, last_crawled_at
FROM weibo.post FINAL
WHERE post_id = {pid:UInt64};
```

### 8.2 某话题最近 7 天的帖

```sql
SELECT p.post_id, p.text_raw, p.created_at
FROM weibo.post FINAL AS p
INNER JOIN weibo.post_topic FINAL AS pt USING (post_id)
WHERE pt.topic_id = cityHash64(lower(trim(BOTH '#' FROM '该话题原文')))
  AND p.created_at >= now() - INTERVAL 7 DAY
ORDER BY p.created_at DESC;
```

### 8.3 某帖互动增长曲线

```sql
SELECT captured_at, comments_count, attitudes_count, reposts_count
FROM weibo.post_engagement_ts
WHERE post_id = {pid:UInt64}
  AND captured_at >= now() - INTERVAL 24 HOUR
ORDER BY captured_at;
```

### 8.4 某帖最新互动总数

```sql
SELECT
    argMax(comments_count, captured_at)  AS comments,
    argMax(attitudes_count, captured_at) AS likes,
    argMax(reposts_count, captured_at)   AS reposts,
    max(captured_at)                     AS as_of
FROM weibo.post_engagement_ts
WHERE post_id = {pid:UInt64}
GROUP BY post_id;
```

### 8.5 高频用户 Top N（带 tier 1 画像）

```sql
SET join_use_nulls = 1;

SELECT
    p.user_id,
    u.screen_name,
    u.verified,
    u.followers_count,
    count() AS post_cnt
FROM weibo.post FINAL AS p
LEFT JOIN (SELECT * FROM weibo.user FINAL WHERE profile_tier >= 1) AS u
       ON u.uid = p.user_id
WHERE p.created_at >= now() - INTERVAL 1 DAY
GROUP BY p.user_id, u.screen_name, u.verified, u.followers_count
ORDER BY post_cnt DESC
LIMIT 50;
```

### 8.6 转发链回溯

```sql
SELECT
    src.post_id  AS retweet_post,
    src.user_id  AS retweet_user,
    orig.post_id AS original_post,
    orig.user_id AS original_user,
    orig.text_raw
FROM weibo.post FINAL AS src
INNER JOIN weibo.post FINAL AS orig
    ON orig.post_id = src.retweet_of
WHERE src.retweet_of != 0
  AND src.created_at >= now() - INTERVAL 1 DAY;
```

### 8.7 事件最早入口（溯源）

```sql
SELECT post_id, source_type, source_value, discovered_at
FROM weibo.post_discovery
WHERE post_id IN (123, 456)
ORDER BY post_id, discovered_at ASC;
-- 每个 post_id 取第一行就是"最早被哪个入口看到"
```

### 8.8 评论情感分析输入（注意是采样）

```sql
SELECT c.comment_id, c.text_raw, c.like_count, c.created_at,
       u.verified, u.followers_count
FROM weibo.comment FINAL AS c
LEFT JOIN (SELECT uid, verified, followers_count FROM weibo.user FINAL) AS u
       ON u.uid = c.user_id
WHERE c.post_id = {pid:UInt64}
  AND c.created_at >= '2026-04-01'
ORDER BY c.like_count DESC
LIMIT 1000;
```

---

## 9. 常见陷阱速查

| 症状 | 原因 | 修法 |
|---|---|---|
| 同一 post_id 出现多行 | ReplacingMergeTree 还没 merge | `FINAL` 或 `argMax` |
| 时间戳整体 -8 小时 | naive datetime 进过驱动 | 写入侧 `datetime.now(timezone.utc)`，读侧明确指定 'UTC' |
| `count(DISTINCT user_id)` 偏大 | LEFT JOIN 填了 0 | `SET join_use_nulls = 1` 或 `WHERE uid != 0` |
| 全表扫描很慢 | 未走分区裁剪 | `WHERE created_at >= ...` 直接比较，别套函数 |
| 评论行数 ≠ 平台显示评论数 | `comment` 是采样 | 取数用 `post_engagement_ts.comments_count` |
| 转发原帖搜不到话题 | `retweeted_status` 无 `topic_struct` | 等独立入口抓到 / 用主帖的 `post_topic` 间接归属 |
| 7 天前的帖没有新 engagement 行 | L4 衰减曲线设计如此 | 不要解读为帖子降温；接受稀疏 |
| 普通用户 `followers_count = 0` | `profile_tier = 0`，本就没拉 profile | `WHERE profile_tier >= 1` 后再聚合 |
| `hot_value` 求和报错 / 失真 | 这是字符串原值（"124万"） | 想要数值用 `read_count` / `discuss_count` |
| `post_media.order_index` 同一图变化 | 帖子被编辑顺序会变 | 用 `media_id` 做唯一键，`order_index` 仅参考 |

---

## 10. schema 演进协议

1. 生产侧改 `sql/ddl/schema.sql` 时同步更新本文档的 §5 / §6 / §7。
2. 加列：`ALTER TABLE ... ADD COLUMN` + 默认值，分析侧 SQL 不需要立即改（但建议显式列出列名，新列要时再补）。
3. 删 / 改语义：通过 issue / 例会预告至少一个迭代周期，给分析侧时间适配。
4. 大动作（重命名表、改主键、删 PARTITION BY）：当成断流处理，分析侧停服、双方约定切换时间点。

---

## 11. 进一步阅读（仓库内）

- `sql/ddl/schema.sql` — 字段类型 / 引擎 / TTL 的**唯一权威**
- `plan-docs/04-storage-design.md` — 选型理由、字段语义详解、设计点说明
- `plan-docs/03-pipeline-design.md` — L0-L4 各层职责
- `plan-docs/05-user-profile-strategy.md` — tier 0/1/2 候选规则
- `plan-docs/06-risks-and-todo.md` — 已验证的关键假设（含 P1.3 转发链结构）
- `AGENTS.md` — 仓库导航与代码约束
- `docs/operations.md` — 运行 / 部署 / 反爬处理
- `pipeline/common/topic_norm.py` — `topic_id` 算法实现
- `pipeline/common/time_display.py` — 展示层时区 helper（如果分析侧需要复用同一格式）
- `tools/ops/status.py` — 想知道当前实例数据量 / 写入速率，跑这个看实时

---

## 12. 联系点

- 数据异常 / 字段语义不清：先核对 §5 / §6，仍不一致时附带 SQL + 输出截图找生产侧。
- 想新增字段 / 新表 / 新指标：走 issue，避免分析侧自己拉 raw_json 凑合。
- schema 变更通知：以本仓库 `sql/ddl/schema.sql` 的 git history 为准。
