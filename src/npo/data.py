"""从 parquet 读情感分类数据 + 预编码 + 计算类权重。

EmotionDataset 在 __init__ 里一次性 tokenize 全量样本（usual 27K × 128 ≈ 27MB，可忽略），
后续 epoch 直接复用 tensor，省每 epoch 的 tokenize 开销。
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import torch
from sklearn.utils.class_weight import compute_class_weight
from torch.utils.data import Dataset

from npo.config import COL_CONTENT, COL_LABEL_ID, NUM_LABELS


class EmotionDataset(Dataset):
    """读 preprocess.py 输出的 parquet (列: content/label/label_id)，按 tokenizer 预编码。

    返回每条样本 = {input_ids, attention_mask, labels}，全部是 torch.Tensor。
    """

    def __init__(self, parquet_path: Path, tokenizer, max_length: int):
        df = pd.read_parquet(parquet_path)
        if COL_CONTENT not in df.columns or COL_LABEL_ID not in df.columns:
            raise ValueError(
                f'{parquet_path} 缺少必需列 {COL_CONTENT!r} / {COL_LABEL_ID!r}，'
                f'实际列: {list(df.columns)}'
            )

        # tokenize 全量；padding='max_length' 使所有样本等长，便于直接 stack
        encodings = tokenizer(
            df[COL_CONTENT].tolist(),
            max_length=max_length,
            padding='max_length',
            truncation=True,
            return_tensors='pt',
        )
        self.input_ids: torch.Tensor = encodings['input_ids']
        self.attention_mask: torch.Tensor = encodings['attention_mask']
        self.labels: torch.Tensor = torch.tensor(
            df[COL_LABEL_ID].to_numpy(), dtype=torch.long
        )
        self.max_length = max_length

    def __len__(self) -> int:
        return len(self.labels)

    def __getitem__(self, idx: int) -> dict[str, torch.Tensor]:
        return {
            'input_ids':      self.input_ids[idx],
            'attention_mask': self.attention_mask[idx],
            'labels':         self.labels[idx],
        }


def compute_class_weights(parquet_path: Path, mode: str = 'balanced') -> torch.Tensor | None:
    """对 train parquet 按 sklearn 'balanced' 算类权重，返回 shape=(NUM_LABELS,) 的 float32 tensor。

    weights[i] = n_samples / (n_classes * count[i])，少数类拿到更大权重。
    传给 torch.nn.CrossEntropyLoss(weight=...) 用。

    Args:
        mode: 'balanced' 用 sklearn 公式；'none' 返回 None（不加权）。
    """
    if mode == 'none':
        return None
    if mode != 'balanced':
        raise ValueError(f'未知 class_weights mode: {mode!r}，应为 balanced/none')

    df = pd.read_parquet(parquet_path)
    y = df[COL_LABEL_ID].to_numpy()
    classes = np.arange(NUM_LABELS)
    weights = compute_class_weight('balanced', classes=classes, y=y)
    return torch.tensor(weights, dtype=torch.float32)
