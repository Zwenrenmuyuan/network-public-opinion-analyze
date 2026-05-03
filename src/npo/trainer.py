"""训练循环：AdamW + 线性 warmup decay + 混合精度 + early stop + best/last checkpoint。

设计原则:
- 自写循环（不用 HF Trainer）：~200 行，可读、易 debug、好定制
- 损失函数显式（不依赖 model 内置 loss），便于挂 class weights
- 每 epoch 末尾跑 eval，按 macro_f1 选 best；连续 patience 个 epoch 不涨就 early stop
- best/ 给最终 test 用，last/ 给潜在 resume 用
"""

from __future__ import annotations

import json
import logging
import random
import time
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import torch
from torch.amp import GradScaler, autocast
from torch.optim import AdamW
from torch.utils.data import DataLoader
from transformers import PreTrainedModel, PreTrainedTokenizerBase, get_linear_schedule_with_warmup

from npo.metrics import evaluate

logger = logging.getLogger(__name__)


@dataclass
class TrainerConfig:
    epochs: int = 5
    learning_rate: float = 2e-5
    weight_decay: float = 0.01
    warmup_ratio: float = 0.1
    max_grad_norm: float = 1.0
    early_stop_patience: int = 2          # 连续这么多 epoch macro_f1 不涨就停
    save_best_metric: str = 'macro_f1'    # 当前只支持 macro_f1
    output_dir: Path = field(default_factory=lambda: Path('runs/default'))
    mixed_precision_dtype: torch.dtype | None = None  # None=fp32，否则 fp16/bf16
    class_weights: torch.Tensor | None = None         # shape (NUM_LABELS,) 或 None
    seed: int = 42
    log_interval: int = 50                # 每多少个 batch 打一次 train loss


def set_seed(seed: int) -> None:
    """seed 所有随机源。MPS / CUDA 上仍可能有非确定性算子，accept it。"""
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)


class Trainer:
    def __init__(
        self,
        model: PreTrainedModel,
        tokenizer: PreTrainedTokenizerBase,
        train_loader: DataLoader,
        eval_loader: DataLoader,
        config: TrainerConfig,
        device: torch.device,
    ):
        self.model = model.to(device)
        self.tokenizer = tokenizer
        self.train_loader = train_loader
        self.eval_loader = eval_loader
        self.cfg = config
        self.device = device

        self.cfg.output_dir.mkdir(parents=True, exist_ok=True)

        # 损失函数：weighted CE if class_weights 提供
        weight = self.cfg.class_weights.to(device) if self.cfg.class_weights is not None else None
        self.loss_fn = torch.nn.CrossEntropyLoss(weight=weight)

        self.optimizer = AdamW(
            self.model.parameters(),
            lr=self.cfg.learning_rate,
            weight_decay=self.cfg.weight_decay,
        )
        total_steps = len(train_loader) * self.cfg.epochs
        self.scheduler = get_linear_schedule_with_warmup(
            self.optimizer,
            num_warmup_steps=int(total_steps * self.cfg.warmup_ratio),
            num_training_steps=total_steps,
        )

        # GradScaler 仅 fp16 需要（bf16 / fp32 不需要）
        self.use_amp = self.cfg.mixed_precision_dtype is not None
        self.use_scaler = self.cfg.mixed_precision_dtype == torch.float16
        self.scaler = GradScaler(device=device.type) if self.use_scaler else None

        # best 追踪
        self.best_metric: float = -float('inf')
        self.best_epoch: int = -1
        self.epochs_since_improve: int = 0

        # history（每 epoch 一行写到 jsonl）
        self.history_path = self.cfg.output_dir / 'eval_history.jsonl'
        self.history_path.unlink(missing_ok=True)

    def train(self) -> dict:
        """主入口。返回 {'best_epoch','best_macro_f1','epochs_run','history':[...] }"""
        history: list[dict] = []
        for epoch in range(1, self.cfg.epochs + 1):
            t0 = time.time()
            train_loss = self._train_one_epoch(epoch)
            train_time = time.time() - t0

            eval_metrics = evaluate(self.model, self.eval_loader, self.device, self.loss_fn)
            eval_time = time.time() - t0 - train_time

            record = {
                'epoch':         epoch,
                'train_loss':    train_loss,
                'eval_loss':     eval_metrics['loss'],
                'eval_accuracy': eval_metrics['accuracy'],
                'macro_f1':      eval_metrics['macro_f1'],
                'per_class_f1':  eval_metrics['per_class_f1'],
                'lr':            self.scheduler.get_last_lr()[0],
                'train_time_s':  round(train_time, 1),
                'eval_time_s':   round(eval_time, 1),
            }
            history.append(record)
            with self.history_path.open('a', encoding='utf-8') as f:
                f.write(json.dumps(record, ensure_ascii=False) + '\n')

            logger.info(
                f'[epoch {epoch}/{self.cfg.epochs}] '
                f'train_loss={train_loss:.4f} eval_loss={eval_metrics["loss"]:.4f} '
                f'macro_f1={eval_metrics["macro_f1"]:.4f} '
                f'acc={eval_metrics["accuracy"]:.4f} '
                f'time={train_time:.1f}s+{eval_time:.1f}s'
            )
            logger.info('\n' + eval_metrics['classification_report'])

            improved = self._maybe_save_best(eval_metrics, epoch)
            if not improved:
                self.epochs_since_improve += 1
                if self.epochs_since_improve >= self.cfg.early_stop_patience:
                    logger.info(
                        f'连续 {self.epochs_since_improve} epoch macro_f1 未提升 '
                        f'(best={self.best_metric:.4f}@epoch{self.best_epoch})，提前停止'
                    )
                    break
            else:
                self.epochs_since_improve = 0

        # 最后一轮（无论是否最佳）也存一份
        self._save(self.cfg.output_dir / 'last')
        logger.info(f'训练结束。best macro_f1={self.best_metric:.4f} @ epoch {self.best_epoch}')

        return {
            'best_epoch':    self.best_epoch,
            'best_macro_f1': self.best_metric,
            'epochs_run':    len(history),
            'history':       history,
        }

    def _train_one_epoch(self, epoch: int) -> float:
        self.model.train()
        total_loss = 0.0
        total_count = 0

        for step, batch in enumerate(self.train_loader, 1):
            input_ids = batch['input_ids'].to(self.device, non_blocking=True)
            attention_mask = batch['attention_mask'].to(self.device, non_blocking=True)
            labels = batch['labels'].to(self.device, non_blocking=True)

            self.optimizer.zero_grad(set_to_none=True)

            if self.use_amp:
                with autocast(device_type=self.device.type, dtype=self.cfg.mixed_precision_dtype):
                    outputs = self.model(input_ids=input_ids, attention_mask=attention_mask)
                    loss = self.loss_fn(outputs.logits, labels)
            else:
                outputs = self.model(input_ids=input_ids, attention_mask=attention_mask)
                loss = self.loss_fn(outputs.logits, labels)

            if self.use_scaler:
                self.scaler.scale(loss).backward()
                self.scaler.unscale_(self.optimizer)
                torch.nn.utils.clip_grad_norm_(self.model.parameters(), self.cfg.max_grad_norm)
                self.scaler.step(self.optimizer)
                self.scaler.update()
            else:
                loss.backward()
                torch.nn.utils.clip_grad_norm_(self.model.parameters(), self.cfg.max_grad_norm)
                self.optimizer.step()
            self.scheduler.step()

            bs = labels.size(0)
            total_loss += loss.item() * bs
            total_count += bs

            if step % self.cfg.log_interval == 0:
                logger.info(
                    f'  epoch {epoch} step {step}/{len(self.train_loader)} '
                    f'loss={loss.item():.4f} lr={self.scheduler.get_last_lr()[0]:.2e}'
                )

        return total_loss / total_count

    def _maybe_save_best(self, eval_metrics: dict, epoch: int) -> bool:
        metric_value = eval_metrics[self.cfg.save_best_metric]
        if metric_value > self.best_metric:
            self.best_metric = metric_value
            self.best_epoch = epoch
            self._save(self.cfg.output_dir / 'best')
            logger.info(f'  -> 新 best：{self.cfg.save_best_metric}={metric_value:.4f}，已保存到 best/')
            return True
        return False

    def _save(self, path: Path) -> None:
        path.mkdir(parents=True, exist_ok=True)
        self.model.save_pretrained(path)
        self.tokenizer.save_pretrained(path)
