"""训练 BERT 情感分类模型。

数据集要求:
    datasets/train.csv
    datasets/test.csv
    （由 data_prep/3_preprocess_csv.py 产出）

输出:
    bert/saved_models/epoch_N/   （每轮一份 checkpoint）

默认超参在 constants.py 里有定义，本文件顶部可以覆盖。
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

import torch
from sklearn.metrics import classification_report
from torch.optim import AdamW
from torch.utils.data import DataLoader
from tqdm import tqdm
from transformers import BertTokenizer, get_linear_schedule_with_warmup

# 让 'from constants import ...' 能找到顶层模块
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from constants import (
    BERT_CHECKPOINT_DIR,
    BERT_PRETRAINED,
    DATA_DIR,
    DEFAULT_BATCH_SIZE,
    DEFAULT_LEARNING_RATE,
    DEFAULT_NUM_EPOCHS,
    LABELS,
)
from dataset import EmotionDataset
from bert.model import EmotionClassifier


# 超参（按需调整）
BATCH_SIZE = DEFAULT_BATCH_SIZE
LEARNING_RATE = DEFAULT_LEARNING_RATE
NUM_EPOCHS = DEFAULT_NUM_EPOCHS

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
)
logger = logging.getLogger(__name__)


def train() -> None:
    device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
    logger.info(f'使用设备: {device}')

    logger.info(f'加载预训练模型: {BERT_PRETRAINED}')
    tokenizer = BertTokenizer.from_pretrained(BERT_PRETRAINED)
    model = EmotionClassifier.from_pretrained(BERT_PRETRAINED)
    model.to(device)

    # 静音 transformers 关于分类层未初始化的警告（这是预期行为）
    logging.getLogger('transformers.modeling_utils').setLevel(logging.ERROR)

    train_dataset = EmotionDataset(DATA_DIR / 'train.csv', tokenizer)
    test_dataset = EmotionDataset(DATA_DIR / 'test.csv', tokenizer)

    train_loader = DataLoader(train_dataset, batch_size=BATCH_SIZE, shuffle=True)
    test_loader = DataLoader(test_dataset, batch_size=BATCH_SIZE)

    optimizer = AdamW(model.parameters(), lr=LEARNING_RATE)
    num_training_steps = NUM_EPOCHS * len(train_loader)
    scheduler = get_linear_schedule_with_warmup(
        optimizer,
        num_warmup_steps=0,
        num_training_steps=num_training_steps,
    )

    BERT_CHECKPOINT_DIR.mkdir(parents=True, exist_ok=True)

    for epoch in range(NUM_EPOCHS):
        # 训练
        model.train()
        total_loss = 0.0
        bar = tqdm(train_loader, desc=f'Epoch {epoch + 1}/{NUM_EPOCHS}', ncols=100)
        for batch in bar:
            input_ids = batch['input_ids'].to(device)
            attention_mask = batch['attention_mask'].to(device)
            labels = batch['labels'].to(device)

            optimizer.zero_grad()
            loss, _ = model(
                input_ids=input_ids,
                attention_mask=attention_mask,
                labels=labels,
            )
            loss.backward()
            optimizer.step()
            scheduler.step()

            total_loss += loss.item()
            bar.set_postfix({'loss': f'{loss.item():.4f}'})

        avg_loss = total_loss / len(train_loader)
        logger.info(f'Epoch {epoch + 1}/{NUM_EPOCHS} 平均训练损失: {avg_loss:.4f}')

        # 评估
        model.eval()
        predictions = []
        true_labels = []
        with torch.no_grad():
            for batch in tqdm(test_loader, desc='评估', ncols=100):
                input_ids = batch['input_ids'].to(device)
                attention_mask = batch['attention_mask'].to(device)
                labels = batch['labels'].to(device)

                _, logits = model(
                    input_ids=input_ids,
                    attention_mask=attention_mask,
                )
                preds = torch.argmax(logits, dim=1).cpu().numpy()
                predictions.extend(preds)
                true_labels.extend(labels.cpu().numpy())

        report = classification_report(
            true_labels, predictions,
            target_names=list(LABELS), digits=4,
        )
        logger.info('\n' + report)

        # 保存
        save_path = BERT_CHECKPOINT_DIR / f'epoch_{epoch + 1}'
        save_path.mkdir(parents=True, exist_ok=True)
        model.save_pretrained(save_path)
        tokenizer.save_pretrained(save_path)
        logger.info(f'已保存 checkpoint 到 {save_path}')


if __name__ == '__main__':
    train()
