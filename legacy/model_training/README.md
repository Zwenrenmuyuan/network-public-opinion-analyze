# model_training

中文社交媒体短文本 6 分类情感分析模型的训练与推理代码。从旧仓库 `network-public-opinion-analyze-web` 整理而来，去掉了和 HBase / Flask 的所有耦合，可以直接拷进新项目作为独立模块。

## 目录结构

```
model_training/
├── README.md
├── requirements.txt
├── constants.py             # 6 类标签映射、最大长度、negative 聚合定义
├── preprocessing.py         # process_text 文本清洗函数（训练和推理共用）
├── dataset.py               # EmotionDataset：BERT/ERNIE 共用的 Dataset 类
├── data_prep/
│   ├── 1_merge_test_xlsx.py    # 合并 SMP2020 的两份测试集 xlsx
│   ├── 2_normalize_train_csv.py # 标准化训练集 CSV
│   └── 3_preprocess_csv.py     # 应用 LABEL_MAP + process_text，输出 train.csv / test.csv
├── bert/
│   ├── model.py             # EmotionClassifier (基于 bert-base-chinese)
│   ├── train.py
│   └── predict.py           # 交互式单条预测，用于训练后 sanity check
└── ernie/
    ├── model.py             # ERNIEEmotionClassifier (基于 nghuyong/ernie-3.0-base-zh)
    ├── train.py
    └── predict.py
```

## 数据集

原项目使用的是 SMP2020-EWECT (微博情绪分类评测) 的 usual 赛道数据。原始文件名：

- `usual_train.csv`（训练集，CSV）
- `usual_eval_labeled.xlsx`（验证集，xlsx）
- `usual_test_labeled.xlsx`（测试集，xlsx）

下载后按以下结构放置（路径相对 `model_training/`）：

```
datasets/
├── train/
│   └── usual_train.csv
└── test/
    ├── usual_eval_labeled.xlsx
    └── usual_test_labeled.xlsx
```

数据集的 `情绪标签` 列原本是英文（`happy/angry/sad/fear/surprise/neutral`），数据预处理脚本会按 `constants.LABEL_MAP_EN_TO_ZH` 转成中文。

## 6 类情感 taxonomy

```
0: 积极 (positive)
1: 愤怒 (angry)
2: 悲伤 (sad)
3: 恐惧 (fear)
4: 惊讶 (surprise)
5: 中性 (neutral)
```

负面情感聚合定义：`negative = {愤怒, 悲伤, 恐惧}`。这个定义在原系统的统计、预警、前端展示里都用，新项目应该保持一致。

详见 `constants.py`。

## 使用流程

### 1. 安装依赖

```bash
pip install -r requirements.txt
# PyTorch 单独装，按 https://pytorch.org/get-started/locally/ 选 CUDA 版本
```

### 2. 准备数据

下载 SMP2020-EWECT 数据集到 `datasets/` 目录（结构见上），然后依次跑：

```bash
python data_prep/1_merge_test_xlsx.py    # 合并两份测试 xlsx，输出 datasets/merged_test.csv
python data_prep/2_normalize_train_csv.py # 输出 datasets/train_raw.csv
python data_prep/3_preprocess_csv.py     # 应用清洗，输出 datasets/train.csv 和 datasets/test.csv
```

### 3. 训练

```bash
python bert/train.py     # 训练 BERT，checkpoint 写入 bert/saved_models/epoch_N/
python ernie/train.py    # 训练 ERNIE，checkpoint 写入 ernie/saved_models/epoch_N/
```

默认配置：5 epochs、batch_size=32、lr=2e-5、max_length=140。改超参直接在 `train.py` 顶部修改。

### 4. 测试模型

```bash
python bert/predict.py --model_path bert/saved_models/epoch_5
python ernie/predict.py --model_path ernie/saved_models/epoch_5
```

## 复制到新项目时需要改的

1. **路径常量**：`constants.py` 里的 `DATA_DIR`、各 `train.py` 里的 `SAVED_MODELS_DIR`，都用了相对路径假设，按新项目布局调整。
2. **导入路径**：所有子目录脚本用了 `sys.path` hack 来 import 顶层模块（`constants`、`preprocessing`、`dataset`）。如果新项目把这些模块挪进了正经的 Python 包，把 hack 删掉换成正常 import。
3. **CUDA 检测**：`train.py` 默认用 GPU，CPU 上跑会非常慢，按需调整 batch_size 或加 `--device cpu` 参数。
4. **HuggingFace 模型下载**：首次运行会从 HuggingFace 拉 `bert-base-chinese` 和 `nghuyong/ernie-3.0-base-zh`，国内可能需要代理或镜像（`HF_ENDPOINT=https://hf-mirror.com`）。

## 已知问题：训练 / 推理预处理不一致

**这是从旧仓库带过来的真实 bug，建议在新项目里修掉。**

旧仓库里 `process_text` 有两份实现，对 `@用户` 的处理不同：

- `数据预处理/文本预处理.py`（训练时用）：`re.sub(r'@', '', text)` 只去掉 `@` 符号，保留用户名
- `predict_from_hbase.py`（推理时用）：`re.sub(r'@[\w\-]+', '', text)` 去掉整个 `@username`

举例 `"thanks @alice for the help"`：
- 训练侧：`"thanks alice for the help"`
- 推理侧：`"thanks for the help"`

也就是说模型在训练时 "alice" 是有效 token，推理时却看不到。这是 train/inference skew，会让模型在生产数据上表现下降一些，但具体多少没量化过。

本目录的 `preprocessing.py` 默认采用**推理侧**的实现（去掉整个 `@username`），因为：
1. 这版语义上更合理（社媒里 @username 是 metadata，不是内容）
2. 旧仓库里推理路径覆盖了所有真实数据，训练侧只覆盖标注数据
3. 如果新项目要重训模型，从一开始就用一致的预处理可以彻底消除这个偏差

如果你需要**复现旧 checkpoint 的精确行为**（比如想加载 `epoch_5` 直接做推理而不重训），把 `preprocessing.py` 里的 `_remove_at_mentions` 改成只删 `@` 符号即可。具体说明在该函数的 docstring 里。

## 资产清单（不在本目录里、需要单独迁移的）

以下东西本目录不包含，但和模型训练/推理直接相关，复制到新项目时一并处理：

- **训练好的 checkpoint**：原项目的 `bert模型训练/saved_models/epoch_5/` 和 `ERNIE模型训练/saved_models/epoch_5/`。建议传到 HuggingFace 私有 repo 或对象存储，加版本标签（训练数据集版本 + 训练日期）。
- **停用词表**：原项目的 `static/stopwords_full.txt`（19KB，约 2300 词）。本目录不需要，但分析侧词云、关键词提取需要。
- **业务规则文档**：6 类情感的 negative 聚合规则、各打分公式、预警阈值等，这些不在 `model_training/` 范围内，应该单独整理一份 spec 文档。
