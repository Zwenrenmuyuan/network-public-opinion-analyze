"""项目内常量单一来源。

被 scripts/preprocess.py（标签映射）和 npo.{data,model,trainer}（标签 / 模型名 / max_length）
共同 import；不要在别处复刻 LABELS_ZH / LABEL2ID / LABEL_MAP_EN_TO_ZH 等定义，
否则 train 和 preprocess 容易漂移。
"""

from __future__ import annotations

# --------------------------------------------------------------------------
# 标签 taxonomy（顺序即模型输出 logits 的索引顺序，不要随意调整）
# --------------------------------------------------------------------------

LABELS_ZH: tuple[str, ...] = ('积极', '愤怒', '悲伤', '恐惧', '惊讶', '中性')
NUM_LABELS: int = len(LABELS_ZH)

LABEL2ID: dict[str, int] = {lab: i for i, lab in enumerate(LABELS_ZH)}
ID2LABEL: dict[int, str] = {i: lab for i, lab in enumerate(LABELS_ZH)}

# SMP2020-EWECT 原始数据用英文标签，preprocess 阶段统一转中文
LABEL_MAP_EN_TO_ZH: dict[str, str] = {
    'happy':    '积极',
    'angry':    '愤怒',
    'sad':      '悲伤',
    'fear':     '恐惧',
    'surprise': '惊讶',
    'neutral':  '中性',
}

# --------------------------------------------------------------------------
# 训练默认值
# --------------------------------------------------------------------------

# 每个 track 推荐的 tokenizer max_length（来自 explore_dataset.py 实测的 p99 字符长度）。
# 中文 BERT tokenizer 对中文几乎是字粒度，token 数 ≈ 字符数。
DEFAULT_MAX_LENGTH: dict[str, int] = {
    'usual': 128,
    'virus': 192,
}

# CLI 用 short key（bert / ernie），背后映射到 HuggingFace 模型 ID
MODEL_NAMES: dict[str, str] = {
    'bert':  'bert-base-chinese',
    'ernie': 'nghuyong/ernie-3.0-base-zh',
}

# 训练数据 parquet 的列名（preprocess.py 输出的 schema）
COL_CONTENT: str = 'content'
COL_LABEL: str = 'label'
COL_LABEL_ID: str = 'label_id'
