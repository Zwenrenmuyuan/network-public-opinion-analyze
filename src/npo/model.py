"""模型工厂：CLI 给 short key（bert/ernie），返回配好的 (model, tokenizer)。

为什么不自定义 BertPreTrainedModel 子类（legacy 的做法）：
HF 的 AutoModelForSequenceClassification 已经是 pooled→dropout→linear 的标准结构，
和 legacy 的 EmotionClassifier 一字不差，多包一层只增加维护成本。
"""

from __future__ import annotations

import logging

from transformers import AutoModelForSequenceClassification, AutoTokenizer
from transformers import PreTrainedModel, PreTrainedTokenizerBase

from npo.config import ID2LABEL, LABEL2ID, MODEL_NAMES, NUM_LABELS

logger = logging.getLogger(__name__)


def build_model(model_key: str) -> tuple[PreTrainedModel, PreTrainedTokenizerBase]:
    """按 short key 构建 model + tokenizer。

    Args:
        model_key: 'bert' 或 'ernie'，映射见 npo.config.MODEL_NAMES。

    Returns:
        (model, tokenizer)：model 已配好 num_labels=6 / id2label / label2id，
        新初始化的分类头权重会有 transformers 的警告（预期行为）。
    """
    if model_key not in MODEL_NAMES:
        raise ValueError(
            f'未知 model_key: {model_key!r}，可选: {list(MODEL_NAMES)}'
        )
    pretrained = MODEL_NAMES[model_key]
    logger.info(f'加载预训练模型: {pretrained}')

    tokenizer = AutoTokenizer.from_pretrained(pretrained)
    model = AutoModelForSequenceClassification.from_pretrained(
        pretrained,
        num_labels=NUM_LABELS,
        id2label=ID2LABEL,
        label2id=LABEL2ID,
        problem_type='single_label_classification',
    )
    return model, tokenizer
