"""评估指标：macro-F1（主选）、accuracy、per-class report、混淆矩阵。

evaluate() 在 eval / test 都用同一个；模型输出 logits 自己算 loss，loss 计算
统一交给 trainer（可以带 class weights）。这里只负责"给定 logits 和 labels，算指标"。
"""

from __future__ import annotations

import numpy as np
import torch
from sklearn.metrics import (
    accuracy_score,
    classification_report,
    confusion_matrix,
    f1_score,
)
from torch.utils.data import DataLoader

from npo.config import LABELS_ZH, NUM_LABELS


@torch.no_grad()
def evaluate(
    model: torch.nn.Module,
    loader: DataLoader,
    device: torch.device,
    loss_fn: torch.nn.Module | None = None,
) -> dict:
    """跑一遍 loader，返回指标字典。

    Returns:
        {
          'loss':              float | None,   # 若 loss_fn 提供则算
          'accuracy':          float,
          'macro_f1':          float,          # 主选指标
          'per_class_f1':      list[float],    # 长度 NUM_LABELS
          'classification_report': str,        # sklearn 文本报告（含 precision/recall）
          'confusion_matrix':  list[list[int]] # NUM_LABELS × NUM_LABELS，行=真，列=预测
        }
    """
    model.eval()
    all_preds: list[np.ndarray] = []
    all_labels: list[np.ndarray] = []
    total_loss = 0.0
    total_count = 0

    for batch in loader:
        input_ids = batch['input_ids'].to(device)
        attention_mask = batch['attention_mask'].to(device)
        labels = batch['labels'].to(device)

        outputs = model(input_ids=input_ids, attention_mask=attention_mask)
        logits = outputs.logits

        if loss_fn is not None:
            loss = loss_fn(logits, labels)
            total_loss += loss.item() * labels.size(0)
            total_count += labels.size(0)

        preds = torch.argmax(logits, dim=-1).cpu().numpy()
        all_preds.append(preds)
        all_labels.append(labels.cpu().numpy())

    y_pred = np.concatenate(all_preds)
    y_true = np.concatenate(all_labels)

    avg_loss = total_loss / total_count if total_count else None
    macro_f1 = f1_score(y_true, y_pred, average='macro', zero_division=0)
    per_class_f1 = f1_score(
        y_true, y_pred, average=None,
        labels=list(range(NUM_LABELS)), zero_division=0,
    )
    accuracy = accuracy_score(y_true, y_pred)
    report = classification_report(
        y_true, y_pred,
        labels=list(range(NUM_LABELS)),
        target_names=list(LABELS_ZH),
        digits=4,
        zero_division=0,
    )
    cm = confusion_matrix(y_true, y_pred, labels=list(range(NUM_LABELS)))

    return {
        'loss':                  avg_loss,
        'accuracy':              float(accuracy),
        'macro_f1':              float(macro_f1),
        'per_class_f1':          [float(x) for x in per_class_f1],
        'classification_report': report,
        'confusion_matrix':      cm.tolist(),
    }
