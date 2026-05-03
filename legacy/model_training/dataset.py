"""BERT 和 ERNIE 共用的 Dataset 类。

旧仓库里 bert模型训练/dataset.py 和 ERNIE模型训练/dataset.py 是几乎一字不差的两份副本，
唯一差别是注释。这里合并成一份，按 tokenizer 参数化。
"""

from __future__ import annotations

import pandas as pd
import torch
from torch.utils.data import Dataset

from constants import LABEL2ID, MAX_LENGTH


class EmotionDataset(Dataset):
    """读取预处理后的 CSV，按 tokenizer 编码后返回 batch。

    CSV 格式要求两列：
      - "文本"     ：清洗后的文本字符串
      - "情绪标签" ：中文标签，必须在 LABEL2ID 的键集合内

    数据预处理脚本 data_prep/3_preprocess_csv.py 的输出符合这个格式。
    """

    def __init__(self, file_path, tokenizer, max_length: int = MAX_LENGTH):
        self.data = pd.read_csv(file_path)
        self.tokenizer = tokenizer
        self.max_length = max_length

        # 早期校验，避免在 __getitem__ 里挨个抛 KeyError
        unknown_labels = set(self.data['情绪标签'].unique()) - set(LABEL2ID.keys())
        if unknown_labels:
            raise ValueError(
                f'CSV 包含未知标签 {unknown_labels}，'
                f'请检查 data_prep/3_preprocess_csv.py 是否正确应用了 LABEL_MAP_EN_TO_ZH'
            )

    def __len__(self) -> int:
        return len(self.data)

    def __getitem__(self, idx: int) -> dict:
        text = str(self.data.iloc[idx]['文本'])
        label = self.data.iloc[idx]['情绪标签']

        encoding = self.tokenizer(
            text,
            add_special_tokens=True,
            max_length=self.max_length,
            padding='max_length',
            truncation=True,
            return_tensors='pt',
        )

        return {
            'input_ids':      encoding['input_ids'].flatten(),
            'attention_mask': encoding['attention_mask'].flatten(),
            'labels':         torch.tensor(LABEL2ID[label], dtype=torch.long),
        }
