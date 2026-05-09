# network-public-opinion-analyze

中文社交媒体短文本六分类情感分析与舆情研判 Dashboard。项目以 SMP2020-EWECT 为基础数据，结合业务样本修复与混合训练，最终使用 ERNIE 作为主展示模型，BERT 作为对照模型和困难样本发现工具。

## 当前状态

项目主链路已经打通：

- SMP 数据解压、探索、清洗、去重和防泄露预处理。
- BERT / ERNIE 六分类情绪模型训练、评估和对比。
- LLM/人工标注辅助的数据修复与业务混合训练数据构建。
- 业务 ClickHouse 数据离线情绪预测，结果写入 `dashboard.sentiment_prediction`。
- Flask 同源 API 聚合 `/api/dashboard/*`，Vue 3 + ECharts 前端展示舆情工作台。
- 模型质量、数据口径、风险话题、关键账号、证据样本和双模型分歧分析。

当前 Dashboard 主模型：

| 项 | 值 |
|---|---|
| 主模型 | ERNIE mixed-v2 |
| 模型版本 | `ernie-usual-mixed-v2` |
| checkpoint | `runs/ernie-usual-mixed-v2/best` |
| 对照模型 | `bert-usual-mixed-v2` |
| 标签顺序 | `积极, 愤怒, 悲伤, 恐惧, 惊讶, 中性` |

模型选择记录见 `results/model-selection-20260505.md`。

## 环境

- Python 3.12，依赖使用 `uv` 管理。
- 前端使用 Vue 3 + TypeScript + Vite。
- Dashboard 后端读取根目录 `.env` 中的 ClickHouse 连接配置。

安装 Python 依赖：

```bash
uv sync
```

安装前端依赖：

```bash
cd frontend
npm install
```

## 目录结构

```text
.
├── src/npo/                    # 训练库：配置、数据集、模型、指标、训练循环
├── scripts/                    # CLI 入口：数据、训练、评估、修复、Dashboard 推理
├── scripts/data_repair/        # LLM/人工辅助数据修复与混合训练数据构建
├── scripts/dashboard/          # 业务 CK 导出、导入、建表和离线情绪预测
├── dashboard/                  # Flask 后端、ClickHouse 客户端和 Dashboard API
├── frontend/                   # Vue 3 + TypeScript + ECharts 前端
├── docs/                       # Dashboard 设计、运行说明、标注规范
├── results/                    # 模型选择和实验报告
├── data/                       # 原始/处理后/业务数据，默认不提交
└── runs/                       # 训练输出和 checkpoint，默认不提交
```

核心事实来源：

| 路径 | 作用 |
|---|---|
| `src/npo/config.py` | 标签顺序、标签映射、模型 short key、默认 `max_length`。 |
| `scripts/dataset_paths.py` | SMP 原始数据路径。 |
| `scripts/preprocess.py` | SMP 清洗、去重、去泄露和 parquet 输出。 |
| `scripts/train.py` | 训练入口，使用项目自写 `Trainer`。 |
| `dashboard/api/config.py` | Dashboard 主/对照模型版本和数据口径常量。 |
| `docs/dashboard-design.md` | Dashboard API 契约和指标定义。 |
| `docs/dashboard-runbook.md` | Dashboard 数据准备、启动和验证流程。 |

## 数据与标签

标准 parquet schema：

| 列 | 说明 |
|---|---|
| `content` | 清洗后的文本。 |
| `label` | 中文标签。 |
| `label_id` | 标签 ID，顺序与模型 logits 一致。 |

标签 ID 固定为：

| ID | 标签 |
|---:|---|
| 0 | 积极 |
| 1 | 愤怒 |
| 2 | 悲伤 |
| 3 | 恐惧 |
| 4 | 惊讶 |
| 5 | 中性 |

负面情绪口径：`愤怒 + 悲伤 + 恐惧`。

## SMP 数据处理

解压官方加密包：

```bash
uv run python scripts/extract_dataset.py
```

探索数据，不产生副作用：

```bash
uv run python scripts/explore_dataset.py
```

构建基础 parquet：

```bash
uv run python scripts/preprocess.py
```

自定义输入输出路径：

```bash
uv run python scripts/preprocess.py --raw-root <raw-root> --out-root <out-root>
```

清洗规则由 `scripts/preprocess.py:clean_text` 维护：NFKC 归一化、繁转简、英文小写、去 URL、去转发链、去 @、话题去 `#` 保留文本、折叠空白，并保留 `[心]` 等微博表情。

## 训练与评估

训练 ERNIE usual 模型：

```bash
uv run python scripts/train.py --track usual --model ernie
```

使用当前 mixed-v2 数据训练：

```bash
uv run python scripts/train.py --track usual --model ernie --processed-root data/processed_mixed_v2
```

评估 checkpoint：

```bash
uv run python scripts/evaluate.py --checkpoint runs/<run>/best --track usual
```

评估业务验证集：

```bash
uv run python scripts/evaluate.py --checkpoint runs/<run>/best --track usual --processed-root data/processed_mixed_v2 --split business_eval
```

对比已有 run：

```bash
uv run python scripts/compare_runs.py --pick best
```

训练默认行为：

- `usual` 默认 `max_length=128`，`virus` 默认 `max_length=192`。
- 默认使用 balanced class weights。
- 每轮 eval 按 macro-F1 选择 `best/` checkpoint。
- 设备选择顺序为 `cuda > mps > cpu`。
- MPS 默认 `--num-workers 0`，避免 DataLoader 卡死。

## 数据修复与混合训练

数据修复脚本集中在 `scripts/data_repair/`。常用流程：

```bash
uv run python scripts/data_repair/build_smp_relabel_candidates.py --per-label-sample 120
LLM_BASE_URL=<url> uv run python scripts/data_repair/llm_label_candidates.py --input data/annotation/smp_relabel_candidates.parquet --output data/annotation/llm_labels.jsonl --model mimo-v2-flash --concurrency 8
uv run python scripts/data_repair/adjudicate_llm_labels.py prepare-review --primary data/annotation/llm_labels.jsonl --out data/annotation/pro_review.parquet
uv run python scripts/data_repair/build_smp_silver_dataset.py --adjudicated data/annotation/smp_adjudicated.jsonl --out-root data/processed_silver
uv run python scripts/data_repair/build_mixed_training_dataset.py --base-root data/processed_silver --out-root data/processed_mixed
```

业务验证集 `business_eval` 是 held-out 集合，不参与训练。混合训练构建脚本会排除 eval/test/business_eval 内容，避免泄露。

## Dashboard 数据准备

Dashboard 架构：

```text
ClickHouse weibo.post/comment
  -> scripts/dashboard/predict_business_emotions.py
  -> dashboard.sentiment_prediction
  -> Flask /api/dashboard/*
  -> Vue SPA
```

准备本地 CK 数据：

```bash
uv run python scripts/dashboard/export_dashboard_business_data.py
uv run python scripts/dashboard/import_to_local_ck.py --host <local-ck>
uv run python scripts/dashboard/init_dashboard_schema.py
```

小批量推理 smoke：

```bash
uv run python scripts/dashboard/predict_business_emotions.py --limit 100 --dry-run
```

确认样本正确后写入 CK：

```bash
uv run python scripts/dashboard/predict_business_emotions.py
```

Dashboard 查询默认过滤 `model_version = 'ernie-usual-mixed-v2'`。BERT 只在模型质量和分歧分析接口中使用。

## 启动 Dashboard

启动后端：

```bash
uv run python dashboard/server.py --port 8000
```

前端开发模式：

```bash
cd frontend
npm run dev
```

生产构建前端：

```bash
cd frontend
npm run build
```

构建产物写入 `frontend/dist/`。Flask 会优先托管 `frontend/dist/`，不存在时降级到旧版 `dashboard/index.html`。

## Dashboard API

所有接口前缀为 `/api/dashboard`：

| API | 用途 |
|---|---|
| `GET /meta` | 数据窗口、模型版本、标签顺序。 |
| `GET /data-quality` | 数据口径、采样说明、profile tier 覆盖。 |
| `GET /overview?range=...` | KPI、负面率、风险指数、互动量。 |
| `GET /emotion-timeseries?range=...` | 六类情绪趋势。 |
| `GET /risk-topics?range=...` | 风险话题榜。 |
| `GET /topics/{topic_id}?range=...` | 话题详情。 |
| `GET /actors?range=...` | 关键账号。 |
| `GET /influence-emotion?range=...` | 影响力-情绪矩阵。 |
| `GET /evidence?range=...` | 代表性证据样本。 |
| `GET /model-quality` | 主模型指标和 BERT 对照摘要。 |
| `GET /model-disagreement` | ERNIE × BERT 业务集分歧。 |

前端与 API 均把 `topic_id`、`post_id`、`comment_id`、`source_id` 当字符串处理，避免 ClickHouse UInt64 超过 JS 安全整数。

## 验证命令

Python 语法检查：

```bash
uv run python -m py_compile dashboard/server.py dashboard/api/*.py dashboard/ck.py
```

前端构建：

```bash
cd frontend
npm run build
```

Dashboard smoke 可参考 `docs/dashboard-runbook.md` 中的接口列表。

## 数据与提交约定

以下内容属于生成物、敏感数据或体积较大文件，默认不提交：

- `.env`
- `data/raw/`
- `data/processed*/`
- `data/annotation/`
- `data/business/`
- `data/dashboard/`
- `runs/`
- `artifacts/`
- `frontend/node_modules/`
- `frontend/dist/`
- checkpoint、模型权重和业务文本导出

`legacy/model_training/` 是迁移参考代码，不是当前训练主线；当前主线使用 `src/npo/` 和 `scripts/`。
