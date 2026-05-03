"""基于 bert-base-chinese 的 6 类情感分类模型。"""

from __future__ import annotations

import sys
from pathlib import Path

import torch
import torch.nn as nn
from transformers import BertModel, BertPreTrainedModel

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from constants import NUM_LABELS


class EmotionClassifier(BertPreTrainedModel):
    """BERT + dropout + linear 的标准微调结构。

    输出：(loss, logits)，labels 为 None 时 loss 为 None。
    """

    def __init__(self, config):
        super().__init__(config)
        self.num_labels = NUM_LABELS
        self.bert = BertModel(config)
        self.dropout = nn.Dropout(config.hidden_dropout_prob)
        self.classifier = nn.Linear(config.hidden_size, self.num_labels)
        self.init_weights()

    def forward(
        self,
        input_ids=None,
        attention_mask=None,
        labels=None,
        return_dict=None,
    ):
        outputs = self.bert(
            input_ids,
            attention_mask=attention_mask,
            return_dict=return_dict,
        )

        pooled_output = outputs[1]
        pooled_output = self.dropout(pooled_output)
        logits = self.classifier(pooled_output)

        loss = None
        if labels is not None:
            loss_fct = nn.CrossEntropyLoss()
            loss = loss_fct(logits.view(-1, self.num_labels), labels.view(-1))

        return loss, logits
