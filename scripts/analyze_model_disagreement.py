"""比较两个 checkpoint 的逐样本预测差异。

用于论文中的 BERT/ERNIE 双模型对照与分歧样本分析：
统计两个模型谁答对、是否存在互补，以及导出分歧样本供后续复核。
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import torch
from sklearn.metrics import accuracy_score, f1_score
from transformers import AutoModelForSequenceClassification, AutoTokenizer

sys.path.insert(0, str(Path(__file__).resolve().parent))
from dataset_paths import ROOT  # noqa: E402

from npo.config import DEFAULT_MAX_LENGTH, LABELS_ZH  # noqa: E402
from npo.device import get_device  # noqa: E402

DEFAULT_PROCESSED_ROOT = ROOT / 'data' / 'processed'
DEFAULT_OUT_DIR = ROOT / 'results' / 'model_disagreement'

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(message)s',
    datefmt='%H:%M:%S',
)
logger = logging.getLogger(__name__)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument('--primary-checkpoint', type=Path, required=True)
    p.add_argument('--secondary-checkpoint', type=Path, required=True)
    p.add_argument('--primary-name', default='ernie')
    p.add_argument('--secondary-name', default='bert')
    p.add_argument('--track', choices=['usual', 'virus'], default='usual')
    p.add_argument('--split', default='business_eval')
    p.add_argument('--processed-root', type=Path, default=DEFAULT_PROCESSED_ROOT)
    p.add_argument('--out-dir', type=Path, default=DEFAULT_OUT_DIR)
    p.add_argument('--max-length', type=int, default=None)
    p.add_argument('--batch-size', type=int, default=64)
    return p.parse_args()


def top2_from_probs(probs: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    order = np.argsort(-probs, axis=1)
    top1 = order[:, 0]
    top2 = order[:, 1]
    top1_prob = probs[np.arange(len(probs)), top1]
    top2_prob = probs[np.arange(len(probs)), top2]
    margin = top1_prob - top2_prob
    return top1, top2, top1_prob, top2_prob, margin


@torch.no_grad()
def predict_probs(checkpoint: Path, texts: list[str], max_length: int, batch_size: int, device: torch.device) -> np.ndarray:
    if not checkpoint.exists():
        raise FileNotFoundError(f'checkpoint 不存在: {checkpoint}')
    logger.info(f'加载 checkpoint: {checkpoint}')
    tokenizer = AutoTokenizer.from_pretrained(checkpoint)
    model = AutoModelForSequenceClassification.from_pretrained(checkpoint).to(device)
    model.eval()

    parts: list[np.ndarray] = []
    for start in range(0, len(texts), batch_size):
        batch_texts = texts[start:start + batch_size]
        enc = tokenizer(
            batch_texts,
            max_length=max_length,
            padding='max_length',
            truncation=True,
            return_tensors='pt',
        )
        enc = {k: v.to(device) for k, v in enc.items()}
        logits = model(**enc).logits
        parts.append(torch.softmax(logits, dim=-1).cpu().numpy())
        if (start // batch_size + 1) % 20 == 0:
            logger.info(f'  progress {min(start + batch_size, len(texts))}/{len(texts)}')

    probs = np.concatenate(parts, axis=0)
    del model
    if device.type == 'cuda':
        torch.cuda.empty_cache()
    return probs


def label_names(ids: np.ndarray) -> list[str]:
    return [LABELS_ZH[int(i)] for i in ids]


def summarize(details: pd.DataFrame, primary_name: str, secondary_name: str) -> dict:
    y_true = details['label_id'].to_numpy()
    p_pred = details[f'{primary_name}_pred_id'].to_numpy()
    s_pred = details[f'{secondary_name}_pred_id'].to_numpy()

    agreement = details[f'{primary_name}_{secondary_name}_agree']
    p_correct = details[f'{primary_name}_correct']
    s_correct = details[f'{secondary_name}_correct']
    oracle = p_correct | s_correct
    disagreement = ~agreement

    summary = {
        'samples': int(len(details)),
        primary_name: {
            'accuracy': float(accuracy_score(y_true, p_pred)),
            'macro_f1': float(f1_score(y_true, p_pred, average='macro', zero_division=0)),
        },
        secondary_name: {
            'accuracy': float(accuracy_score(y_true, s_pred)),
            'macro_f1': float(f1_score(y_true, s_pred, average='macro', zero_division=0)),
        },
        'agreement_count': int(agreement.sum()),
        'agreement_rate': float(agreement.mean()),
        'disagreement_count': int(disagreement.sum()),
        'disagreement_rate': float(disagreement.mean()),
        'both_correct': int((p_correct & s_correct).sum()),
        f'{primary_name}_only_correct': int((p_correct & ~s_correct).sum()),
        f'{secondary_name}_only_correct': int((~p_correct & s_correct).sum()),
        'both_wrong': int((~p_correct & ~s_correct).sum()),
        'oracle_accuracy': float(oracle.mean()),
    }
    if disagreement.any():
        sub = details[disagreement]
        summary['disagreement_primary_accuracy'] = float(sub[f'{primary_name}_correct'].mean())
        summary['disagreement_secondary_accuracy'] = float(sub[f'{secondary_name}_correct'].mean())
        summary['secondary_only_by_label'] = (
            details[~p_correct & s_correct]['label']
            .value_counts()
            .reindex(LABELS_ZH, fill_value=0)
            .astype(int)
            .to_dict()
        )
    return summary


def write_markdown(summary: dict, args: argparse.Namespace, path: Path) -> None:
    primary = args.primary_name
    secondary = args.secondary_name
    lines = [
        f'# {primary} / {secondary} 分歧分析',
        '',
        f'- split: `{args.split}`',
        f'- samples: {summary["samples"]}',
        f'- primary: `{args.primary_checkpoint}`',
        f'- secondary: `{args.secondary_checkpoint}`',
        '',
        '## 总体指标',
        '',
        '| 模型 | accuracy | macro-F1 |',
        '|---|---:|---:|',
        f'| {primary} | {summary[primary]["accuracy"]:.4f} | {summary[primary]["macro_f1"]:.4f} |',
        f'| {secondary} | {summary[secondary]["accuracy"]:.4f} | {summary[secondary]["macro_f1"]:.4f} |',
        '',
        '## 互补性',
        '',
        f'- agreement: {summary["agreement_count"]} ({summary["agreement_rate"]:.2%})',
        f'- disagreement: {summary["disagreement_count"]} ({summary["disagreement_rate"]:.2%})',
        f'- both_correct: {summary["both_correct"]}',
        f'- {primary}_only_correct: {summary[f"{primary}_only_correct"]}',
        f'- {secondary}_only_correct: {summary[f"{secondary}_only_correct"]}',
        f'- both_wrong: {summary["both_wrong"]}',
        f'- oracle_accuracy: {summary["oracle_accuracy"]:.4f}',
    ]
    if 'disagreement_primary_accuracy' in summary:
        lines.extend([
            f'- disagreement {primary} accuracy: {summary["disagreement_primary_accuracy"]:.4f}',
            f'- disagreement {secondary} accuracy: {summary["disagreement_secondary_accuracy"]:.4f}',
            '',
            '## secondary-only correct by label',
            '',
        ])
        for label, count in summary['secondary_only_by_label'].items():
            lines.append(f'- {label}: {count}')

    path.write_text('\n'.join(lines) + '\n', encoding='utf-8')


def main() -> None:
    args = parse_args()
    max_length = args.max_length or DEFAULT_MAX_LENGTH[args.track]
    parquet = args.processed_root / f'{args.track}_{args.split}.parquet'
    if not parquet.exists():
        raise FileNotFoundError(f'parquet 不存在: {parquet}')

    df = pd.read_parquet(parquet)
    required = {'content', 'label', 'label_id'}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f'{parquet} 缺少列: {sorted(missing)}')

    device = get_device()
    logger.info(f'split={args.split} samples={len(df)} device={device} max_length={max_length}')
    texts = df['content'].astype(str).tolist()

    p_probs = predict_probs(args.primary_checkpoint, texts, max_length, args.batch_size, device)
    s_probs = predict_probs(args.secondary_checkpoint, texts, max_length, args.batch_size, device)

    p_top1, p_top2, p_top1_prob, p_top2_prob, p_margin = top2_from_probs(p_probs)
    s_top1, s_top2, s_top1_prob, s_top2_prob, s_margin = top2_from_probs(s_probs)

    out = df[['content', 'label', 'label_id']].copy()
    primary = args.primary_name
    secondary = args.secondary_name
    out[f'{primary}_pred_id'] = p_top1
    out[f'{primary}_pred'] = label_names(p_top1)
    out[f'{primary}_confidence'] = p_top1_prob
    out[f'{primary}_second_pred'] = label_names(p_top2)
    out[f'{primary}_second_prob'] = p_top2_prob
    out[f'{primary}_margin'] = p_margin
    out[f'{secondary}_pred_id'] = s_top1
    out[f'{secondary}_pred'] = label_names(s_top1)
    out[f'{secondary}_confidence'] = s_top1_prob
    out[f'{secondary}_second_pred'] = label_names(s_top2)
    out[f'{secondary}_second_prob'] = s_top2_prob
    out[f'{secondary}_margin'] = s_margin
    out[f'{primary}_correct'] = out[f'{primary}_pred_id'] == out['label_id']
    out[f'{secondary}_correct'] = out[f'{secondary}_pred_id'] == out['label_id']
    out[f'{primary}_{secondary}_agree'] = out[f'{primary}_pred_id'] == out[f'{secondary}_pred_id']
    out['case_type'] = np.select(
        [
            out[f'{primary}_correct'] & out[f'{secondary}_correct'],
            out[f'{primary}_correct'] & ~out[f'{secondary}_correct'],
            ~out[f'{primary}_correct'] & out[f'{secondary}_correct'],
        ],
        ['both_correct', f'{primary}_only_correct', f'{secondary}_only_correct'],
        default='both_wrong',
    )

    summary = summarize(out, primary, secondary)
    args.out_dir.mkdir(parents=True, exist_ok=True)
    prefix = f'{args.track}_{args.split}_{primary}_vs_{secondary}'
    details_path = args.out_dir / f'{prefix}_details.csv'
    summary_path = args.out_dir / f'{prefix}_summary.json'
    md_path = args.out_dir / f'{prefix}_summary.md'
    out.to_csv(details_path, index=False, encoding='utf-8-sig')
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
    write_markdown(summary, args, md_path)
    logger.info(f'写出 {details_path}')
    logger.info(f'写出 {summary_path}')
    logger.info(f'写出 {md_path}')
    logger.info(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
