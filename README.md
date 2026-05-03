# network-public-opinion-analyze

中文社交媒体短文本 6 分类情感分析（基于 SMP2020-EWECT 数据集）。

## 环境

- Python 3.12，依赖用 `uv` 管理
- 关键依赖：`pandas`, `pyarrow`, `openpyxl`, `xlrd`, `zhconv`

```bash
uv sync
```

## 目录结构

```
.
├── data/
│   ├── 评测数据集加密.zip              # 官方加密包（密码 smp2020ewect）
│   ├── raw/                            # extract_dataset.py 解压输出
│   └── processed/                      # preprocess.py 输出的 parquet
├── scripts/
│   ├── dataset_paths.py                # 原始数据文件路径清单
│   ├── extract_dataset.py              # 解压 zip 到 data/raw/
│   ├── explore_dataset.py              # 数据画像（探索性，无副作用）
│   └── preprocess.py                   # 清洗 + 去重 + 去泄露 + 写 parquet
└── legacy/
    └── model_training/                 # 旧仓库迁来的训练参考代码（暂未使用）
```

## 数据流水线

按顺序运行：

```bash
# 1. 解压加密 zip → data/raw/评测数据集/...
uv run python scripts/extract_dataset.py

# 2.（可选）数据画像，了解数据质量
uv run python scripts/explore_dataset.py

# 3. 清洗并产出 parquet → data/processed/{usual,virus}_{train,eval,test}.parquet
uv run python scripts/preprocess.py
#   或自定义路径
uv run python scripts/preprocess.py --raw-root /path/to/raw --out-root /path/to/out
```

## 输出 parquet schema

`data/processed/{usual,virus}_{train,eval,test}.parquet`，每个文件三列：

| 列 | 类型 | 说明 |
|---|---|---|
| `content` | string | 清洗后文本。预处理阶段仅做 512 字符防御性截断（兜底极端长文本），不做模型 `max_length` 截断 — 那个由训练 tokenizer 决定 |
| `label` | string | 中文标签：积极 / 愤怒 / 悲伤 / 恐惧 / 惊讶 / 中性 |
| `label_id` | int64 | 0=积极, 1=愤怒, 2=悲伤, 3=恐惧, 4=惊讶, 5=中性 |

行数（去重 + 去泄露后）：

| | usual | virus |
|---|---|---|
| train | 26,654 | 7,270 |
| eval | 1,992 | 1,815 |
| test | 4,970 | 2,762 |

## 清洗规则

`scripts/preprocess.py:clean_text` 按顺序应用：

1. NFKC 归一化（全角→半角）
2. 繁体转简体
3. 英文小写
4. 删 URL（`http(s)://...`）
5. 删 `//@xxx:` 转发链
6. 删 `@username`（含中文用户名）
7. `#话题#` 保留文本去 `#` 符号
8. 折叠空白 + strip
9. **仅做 512 字符防御性截断**（兜底 virus 里 3000+ 字符的极端长文本）。**不做模型 `max_length` 截断** — 留给训练 tokenizer 决定，避免两次截断耦合、避免调超参时重跑预处理

`[心][泪]` 等微博表情**保留**（情感分析里是强信号）。

## 推荐 max_length（来自 explore_dataset.py 实测）

中文 BERT tokenizer 对中文几乎是字粒度，token 数 ≈ 字符数。清洗后字符长度分位数：

| track | p50 | p95 | p99 | 推荐 max_length |
|---|---|---|---|---|
| usual | 32 | 113-118 | 138-140 | **128**（>192 = 0%） |
| virus | 28 | 130-143 | 266-291 | **192**（覆盖 p95，长尾损失 2-3%） |

## 已知数据问题

`preprocess.py` 运行时会打印警告：

- **冲突标签**：同一段 content 在数据集里出现多次但标签不同。usual_train 82 处、virus_train 65 处。**当前策略**：`drop_duplicates(keep='first')` 保留首次出现的标签。若后续追求训练质量，可改成丢弃所有冲突样本（`keep=False`）。
- **train ↔ test 泄露**：原始数据里 train 和 test 内容重叠（usual 4.67%，virus 7.39%），preprocess 会从 train 里删掉这些。
- **virus 标签不平衡**：happy 51% / surprise 2%。后续训练需要 weighted CE 或 oversampling。
- **virus 长文本**：max 3172 字符。预处理截到 512 兜底，训练 tokenizer 进一步按 max_length 截断（建议 192）。

## eval / test 用法约定

- **eval（刷榜）当 validation**：每个 epoch 跑一次，用于 early stop / 选最佳 epoch。
- **test（真实评测）做 final 评估**，训练时不碰。
- 含混淆数据集 = test + None 噪音，不用于训练或评估。

## legacy/model_training/

旧仓库 `network-public-opinion-analyze-web` 迁过来的参考代码（BERT / ERNIE 训练管线）。当前 `scripts/` 不依赖它，标签 taxonomy / 清洗规则在 `scripts/preprocess.py` 里独立维护。
