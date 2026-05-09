# Dashboard 运行说明

本文记录 dashboard 本地运行、数据准备、验证和常见排错步骤。

## 1. 环境变量

dashboard 后端从仓库根目录 `.env` 或进程环境读取 ClickHouse 配置。

必需变量：

- `CLICKHOUSE_HOST`
- `CLICKHOUSE_PORT`
- `CLICKHOUSE_DATABASE`
- `READONLY_USER`
- `READONLY_PASSWORD`

运行原则：

- 浏览器只请求同源 `/api/dashboard/*`。
- CK 地址、账号、密码只存在于后端运行环境。
- 本地 schema 初始化、导入和预测脚本可使用有写权限的开发账号。
- dashboard 服务查询应使用只读账号。

## 2. 数据准备

从业务 ClickHouse 导出 dashboard 所需表：

```bash
uv run python scripts/dashboard/export_dashboard_business_data.py
```

导入本地 ClickHouse：

```bash
uv run python scripts/dashboard/import_to_local_ck.py --host <local-ck>
```

初始化 dashboard 预测表：

```bash
uv run python scripts/dashboard/init_dashboard_schema.py
```

先做小批量预测 smoke：

```bash
uv run python scripts/dashboard/predict_business_emotions.py --limit 100 --dry-run
```

确认无误后去掉 `--dry-run` 写入 `dashboard.sentiment_prediction`。

## 3. 启动服务

启动 Flask 后端和静态页面：

```bash
uv run python dashboard/server.py --port 8000
```

打开：

```text
http://localhost:8000/
```

## 4. 数据口径

- 主模型版本：`ernie-usual-mixed-v2`。
- 主模型 checkpoint：`runs/ernie-usual-mixed-v2/best`。
- 情绪标签顺序以 `src/npo/config.py:LABELS_ZH` 为准。
- 负面情绪定义：`愤怒 + 悲伤 + 恐惧`。
- `comment` 是采样评论，不代表平台全量评论。
- 互动数来自 `weibo.post_engagement_ts` 平台快照。
- CK 时间字段按 UTC 存储，前端展示为东八区。
- `topic_id`、`post_id`、`comment_id` 返回前端时按字符串处理。

## 5. 验证命令

代码级检查：

```bash
uv run python -m py_compile dashboard/server.py dashboard/api/*.py dashboard/ck.py
node --check dashboard/static/js/pages/dashboard.js
```

接口 smoke：

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
GET /api/dashboard/model-quality
```

页面检查：

- 时间范围切换后各模块刷新。
- 点击风险话题后详情、证据、关键账号和矩阵刷新。
- 浏览器 console 无 JavaScript 错误。
- 评论相关文案标注“采样评论”。
- API 单模块失败时页面其他模块不应崩溃。

## 6. 常见排错

`.env` 缺少 CK 配置：

- 后端启动或接口请求会报 `缺少 .env 配置`。
- 检查变量名是否与 `.env.example` 一致。

ClickHouse 连接失败：

- 检查 host、port、账号、密码和网络连通性。
- dashboard API 会返回 JSON 错误，不应返回 HTML 错误页。

预测表为空：

- 确认已运行 `init_dashboard_schema.py`。
- 确认 `predict_business_emotions.py` 已去掉 `--dry-run` 并成功写入。
- 检查查询使用的 `model_version` 是否为 `ernie-usual-mixed-v2`。

模型质量字段为 null：

- 检查 `runs/ernie-usual-mixed-v2/` 下是否存在评估 JSON。
- 缺少评估文件时，接口应保留字段但返回空值。

图表没有渲染：

- 检查浏览器是否能加载 ECharts CDN。
- 检查 `/api/dashboard/*` 是否返回 JSON。
- 检查 `dashboard/static/js/pages/dashboard.js` 是否通过 `node --check`。
