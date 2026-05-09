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

可选变量：

- `REDIS_URL`：API 缓存后端，例如 `redis://localhost:16379/0` 或 `redis://:<password>@<host>:<port>/<db>`；未设或连接失败时自动降级到进程内 dict（多 worker 不共享）。

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

## 6. 生产部署考虑

### 6.1 WSGI 部署

Flask 内置 dev server 不可用于生产（性能、并发、稳定性都不足，启动会打印警告）。
生产用 gunicorn：

```bash
uv run gunicorn -w 4 -b 0.0.0.0:8000 dashboard.server:app
```

worker 数量按 CPU 核心 `2 * cores + 1` 估，全部走 sync worker（dashboard 是 IO-bound，
但 CK 客户端是同步 httpx，gevent/eventlet 没必要）。

缓存后端按 `.env` 的 `REDIS_URL` 决定：配了就用 Redis，多 worker 之间共享同一份缓存命中，
单点失效；没配或 Redis 不可达时降级到进程内 dict，多 worker 间不共享但不影响功能。
启动行会打印 `cache=redis @ host:port` 或 `cache=in-memory`，看一眼就知道生效的是哪一种。

### 6.2 ClickHouse 只读账号

dashboard 后端不应使用导入/写入用账号。生产 CK 上为 dashboard 单独建只读账号：

```sql
CREATE USER dashboard_ro IDENTIFIED WITH sha256_password BY '<strong-password>';
GRANT SELECT ON weibo.* TO dashboard_ro;
GRANT SELECT ON dashboard.* TO dashboard_ro;
-- 可选：限定单 IP 来源
ALTER USER dashboard_ro HOST IP '10.0.0.0/24';
```

`READONLY_USER` / `READONLY_PASSWORD` 在 `.env` 里写这个账号；写权限账号留给离线脚本
（`init_dashboard_schema.py` / `predict_business_emotions.py`）使用，建议放在另一份
不被 dashboard 进程读取的 env 文件，调用时 `env $(cat .env.write | xargs) uv run ...`
或显式 `--user/--password` 参数。

### 6.3 查询超时

后端层（`CKClient(timeout=30.0)`）默认 30 秒，对 dashboard 全部 endpoint 够用。要更紧可在
`server.py` 显式传 `CKClient(timeout=15.0)`，超时直接抛 `CKNetworkError` → 503。

CK 服务端层防御性配置（`config.xml` 或 `users.xml` 的 profile）：

```xml
<max_execution_time>20</max_execution_time>
<max_memory_usage>4000000000</max_memory_usage>     <!-- 4 GiB / query -->
<max_threads>4</max_threads>
<max_concurrent_queries_for_user>4</max_concurrent_queries_for_user>
```

防止前端某个慢查询把 CK 资源吃满。

### 6.4 反代 + HTTPS

生产前面建议 nginx 终结 TLS，反代到 gunicorn：

```nginx
server {
    listen 443 ssl http2;
    server_name dashboard.example.com;
    ssl_certificate     /etc/ssl/certs/dashboard.crt;
    ssl_certificate_key /etc/ssl/private/dashboard.key;

    # 静态文件 nginx 直接服务，跳过 Python
    location /static/ {
        alias /opt/dashboard/static/;
        expires 1d;
    }

    location / {
        proxy_pass         http://127.0.0.1:8000;
        proxy_set_header   Host $host;
        proxy_set_header   X-Real-IP $remote_addr;
        proxy_set_header   X-Forwarded-Proto https;
        proxy_read_timeout 60s;
    }
}

server {
    listen 80;
    server_name dashboard.example.com;
    return 301 https://$host$request_uri;
}
```

### 6.5 资源限制与监控

- gunicorn `--max-requests 1000 --max-requests-jitter 100` 避免 worker 长时间运行
  累积内存。Redis 后端时 cache 数据在 Redis 而不在 worker 内存里；fallback 到 in-memory
  时 worker 重启会清空 cache，可作隐式上限。
- Redis 端配 `maxmemory` + `maxmemory-policy allkeys-lru`，给 dashboard 缓存设硬上限，
  避免大量关键词搜索把内存吃满。
- 关注 CK 端 `system.query_log` 看慢查询，如果 `risk-topics` / `topics/<id>` 频繁慢，
  说明 cache 没命中，检查前端是否一直带不同参数。
- 后端 stdout 已经打印 `dashboard_api {path} status=... elapsed_ms=...`，接到日志
  收集即可看 P95 延迟。

## 7. 常见排错

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
