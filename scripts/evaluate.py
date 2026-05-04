"""加载已训练 checkpoint，跑 test split 出 final report。

典型用法:
    uv run python scripts/evaluate.py \\
        --checkpoint runs/bert-usual-20260503-1430/best \\
        --track usual

输出:
    stdout 打印 macro_f1 / per-class report / confusion matrix
    写到 {checkpoint 的 run 目录}/final_test_report.json
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

import torch
from torch.utils.data import DataLoader
from transformers import AutoModelForSequenceClassification, AutoTokenizer

sys.path.insert(0, str(Path(__file__).resolve().parent))
from dataset_paths import ROOT  # noqa: E402

from npo.config import DEFAULT_MAX_LENGTH, LABELS_ZH  # noqa: E402
from npo.data import EmotionDataset  # noqa: E402
from npo.device import get_device  # noqa: E402
from npo.metrics import evaluate  # noqa: E402

DEFAULT_PROCESSED_ROOT = ROOT / 'data' / 'processed'

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(message)s',
    datefmt='%H:%M:%S',
)
logger = logging.getLogger(__name__)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument('--checkpoint', type=Path, required=True,
                   help='HF checkpoint 目录（含 config.json + safetensors + tokenizer files）')
    p.add_argument('--track', choices=['usual', 'virus'], required=True)
    p.add_argument('--processed-root', type=Path, default=DEFAULT_PROCESSED_ROOT)
    p.add_argument('--split', default='test',
                   help='评估哪个 split。默认 test；也可传 business_eval 等自定义 split')
    p.add_argument('--max-length', type=int, default=None)
    p.add_argument('--batch-size', type=int, default=32)
    p.add_argument('--num-workers', type=int, default=0)
    return p.parse_args()


def main() -> None:
    args = parse_args()
    if not args.checkpoint.exists():
        raise FileNotFoundError(f'checkpoint 不存在: {args.checkpoint}')

    max_length = args.max_length or DEFAULT_MAX_LENGTH[args.track]
    parquet = args.processed_root / f'{args.track}_{args.split}.parquet'
    if not parquet.exists():
        raise FileNotFoundError(f'parquet 不存在: {parquet}')

    device = get_device()
    logger.info(f'checkpoint={args.checkpoint} track={args.track} split={args.split} '
                f'device={device} max_length={max_length}')

    model = AutoModelForSequenceClassification.from_pretrained(args.checkpoint).to(device)
    tokenizer = AutoTokenizer.from_pretrained(args.checkpoint)

    ds = EmotionDataset(parquet, tokenizer, max_length)
    loader = DataLoader(ds, batch_size=args.batch_size, shuffle=False,
                        num_workers=args.num_workers, pin_memory=(device.type == 'cuda'))
    logger.info(f'samples: {len(ds)}')

    metrics = evaluate(model, loader, device, loss_fn=torch.nn.CrossEntropyLoss())

    logger.info(f'macro_f1={metrics["macro_f1"]:.4f} accuracy={metrics["accuracy"]:.4f} '
                f'loss={metrics["loss"]:.4f}')
    logger.info('\n' + metrics['classification_report'])
    logger.info('confusion matrix (行=真, 列=预测，标签顺序: %s):', list(LABELS_ZH))
    for row, name in zip(metrics['confusion_matrix'], LABELS_ZH):
        logger.info(f'  {name}: {row}')

    # 输出 json 到 run 目录（checkpoint 的父目录）
    run_dir = args.checkpoint.parent
    out_path = run_dir / f'final_{args.split}_report.json'
    payload = {
        'checkpoint': str(args.checkpoint),
        'track':      args.track,
        'split':      args.split,
        'max_length': max_length,
        'samples':    len(ds),
        **{k: metrics[k] for k in ('loss', 'accuracy', 'macro_f1',
                                   'per_class_f1', 'confusion_matrix')},
        'classification_report': metrics['classification_report'],
        'labels':     list(LABELS_ZH),
    }
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
    logger.info(f'写出 {out_path}')


if __name__ == '__main__':
    main()
