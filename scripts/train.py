"""训练 CLI。

典型用法:
    uv run python scripts/train.py --track usual --model bert
    uv run python scripts/train.py --track virus --model bert --max-length 192

输出 runs/{model}-{track}-{timestamp}/ 包含:
    train.log              全程 stdout
    train_args.json        本次跑的所有超参（含解析后的实际值）
    eval_history.jsonl     每 epoch 一行 {epoch, train_loss, macro_f1, ...}
    best/                  按 macro_f1 选出的最佳 checkpoint（HF 格式）
    last/                  最后一 epoch 的 checkpoint
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime
from pathlib import Path

from torch.utils.data import DataLoader

# scripts/ 不是包，让 dataset_paths 能直接 import
sys.path.insert(0, str(Path(__file__).resolve().parent))
from dataset_paths import ROOT  # noqa: E402

from npo.config import DEFAULT_MAX_LENGTH, MODEL_NAMES  # noqa: E402
from npo.data import EmotionDataset, compute_class_weights  # noqa: E402
from npo.device import get_device, select_amp_dtype  # noqa: E402
from npo.model import build_model  # noqa: E402
from npo.trainer import Trainer, TrainerConfig, set_seed  # noqa: E402

DEFAULT_PROCESSED_ROOT = ROOT / 'data' / 'processed'
DEFAULT_RUNS_ROOT = ROOT / 'runs'


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])

    p.add_argument('--track', choices=['usual', 'virus'], required=True,
                   help='SMP2020 track')
    p.add_argument('--model', choices=list(MODEL_NAMES), default='bert',
                   help='模型 short key (bert/ernie)')

    p.add_argument('--processed-root', type=Path, default=DEFAULT_PROCESSED_ROOT,
                   help=f'parquet 根目录，默认 {DEFAULT_PROCESSED_ROOT}')
    p.add_argument('--max-length', type=int, default=None,
                   help=f'tokenizer max_length，默认按 track 取 {DEFAULT_MAX_LENGTH}')

    p.add_argument('--batch-size', type=int, default=32)
    p.add_argument('--learning-rate', type=float, default=2e-5)
    p.add_argument('--weight-decay', type=float, default=0.01)
    p.add_argument('--warmup-ratio', type=float, default=0.1)
    p.add_argument('--max-grad-norm', type=float, default=1.0)
    p.add_argument('--epochs', type=int, default=5)
    p.add_argument('--early-stop-patience', type=int, default=2)

    p.add_argument('--class-weights', choices=['balanced', 'none'], default='balanced',
                   help='类权重策略')
    p.add_argument('--mixed-precision', choices=['auto', 'fp32', 'fp16', 'bf16'], default='auto',
                   help='auto: cuda→fp16，mps/cpu→fp32')

    p.add_argument('--seed', type=int, default=42)
    p.add_argument('--num-workers', type=int, default=0,
                   help='DataLoader worker 数；MPS 上建议 0 防 hang')
    p.add_argument('--log-interval', type=int, default=50,
                   help='每多少个 batch 打一次 train loss')

    p.add_argument('--output-dir', type=Path, default=None,
                   help=f'默认 {DEFAULT_RUNS_ROOT}/{{model}}-{{track}}-{{YYYYMMDD-HHMM}}')

    return p.parse_args()


def setup_logging(log_file: Path) -> None:
    """同时输出到 stdout 和 log_file。重置 root logger 防止重复 handler。"""
    fmt = logging.Formatter(
        '%(asctime)s | %(levelname)s | %(name)s | %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S',
    )
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.handlers.clear()

    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(fmt)
    root.addHandler(sh)

    fh = logging.FileHandler(log_file, encoding='utf-8')
    fh.setFormatter(fmt)
    root.addHandler(fh)

    # 静音 transformers 关于新初始化分类头的警告（这是预期的微调行为）
    logging.getLogger('transformers.modeling_utils').setLevel(logging.ERROR)


def main() -> None:
    args = parse_args()

    # 解析 max_length
    max_length = args.max_length if args.max_length is not None else DEFAULT_MAX_LENGTH[args.track]

    # 解析 output_dir
    if args.output_dir is None:
        ts = datetime.now().strftime('%Y%m%d-%H%M')
        args.output_dir = DEFAULT_RUNS_ROOT / f'{args.model}-{args.track}-{ts}'
    args.output_dir.mkdir(parents=True, exist_ok=True)

    setup_logging(args.output_dir / 'train.log')
    logger = logging.getLogger(__name__)

    set_seed(args.seed)
    device = get_device()
    amp_dtype = select_amp_dtype(device, args.mixed_precision)

    logger.info(f'track={args.track} model={args.model} device={device} amp={amp_dtype}')
    logger.info(f'output_dir={args.output_dir}')

    # 数据
    train_path = args.processed_root / f'{args.track}_train.parquet'
    eval_path  = args.processed_root / f'{args.track}_eval.parquet'
    for p in (train_path, eval_path):
        if not p.exists():
            raise FileNotFoundError(f'缺少 parquet: {p}，请先跑 scripts/preprocess.py')

    model, tokenizer = build_model(args.model)

    train_ds = EmotionDataset(train_path, tokenizer, max_length)
    eval_ds  = EmotionDataset(eval_path,  tokenizer, max_length)
    logger.info(f'train_ds={len(train_ds)} eval_ds={len(eval_ds)} max_length={max_length}')

    train_loader = DataLoader(train_ds, batch_size=args.batch_size, shuffle=True,
                              num_workers=args.num_workers, pin_memory=(device.type == 'cuda'))
    eval_loader  = DataLoader(eval_ds, batch_size=args.batch_size, shuffle=False,
                              num_workers=args.num_workers, pin_memory=(device.type == 'cuda'))

    class_weights = compute_class_weights(train_path, args.class_weights)
    if class_weights is not None:
        logger.info(f'class_weights({args.class_weights}) = {class_weights.tolist()}')
    else:
        logger.info('class_weights = none (普通 CE)')

    cfg = TrainerConfig(
        epochs=args.epochs,
        learning_rate=args.learning_rate,
        weight_decay=args.weight_decay,
        warmup_ratio=args.warmup_ratio,
        max_grad_norm=args.max_grad_norm,
        early_stop_patience=args.early_stop_patience,
        output_dir=args.output_dir,
        mixed_precision_dtype=amp_dtype,
        class_weights=class_weights,
        seed=args.seed,
        log_interval=args.log_interval,
    )

    # 落盘 train_args.json（注意 Path / dtype 不能直接 json，转字符串）
    train_args_dump = {
        **{k: (str(v) if isinstance(v, Path) else v) for k, v in vars(args).items()},
        'resolved_max_length': max_length,
        'resolved_device':     str(device),
        'resolved_amp_dtype':  str(amp_dtype),
        'pretrained':          MODEL_NAMES[args.model],
    }
    (args.output_dir / 'train_args.json').write_text(
        json.dumps(train_args_dump, ensure_ascii=False, indent=2), encoding='utf-8'
    )

    trainer = Trainer(model, tokenizer, train_loader, eval_loader, cfg, device)
    result = trainer.train()
    logger.info(f'结果: best_epoch={result["best_epoch"]} best_macro_f1={result["best_macro_f1"]:.4f}')


if __name__ == '__main__':
    main()
