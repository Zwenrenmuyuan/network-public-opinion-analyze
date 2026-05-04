"""从业务 LLM 仲裁结果构建 business eval 和训练候选池。"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

SCRIPTS_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPTS_DIR))
from dataset_paths import ROOT  # noqa: E402
from npo.config import LABEL2ID, LABELS_ZH  # noqa: E402

DEFAULT_ADJUDICATED = ROOT / 'data' / 'annotation' / 'business_adjudicated.jsonl'
DEFAULT_PROCESSED_ROOT = ROOT / 'data' / 'processed'
DEFAULT_POOL_OUT = ROOT / 'data' / 'processed' / 'usual_business_train_pool.parquet'


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument('--adjudicated', type=Path, default=DEFAULT_ADJUDICATED)
    p.add_argument('--track', choices=['usual', 'virus'], default='usual')
    p.add_argument('--processed-root', type=Path, default=DEFAULT_PROCESSED_ROOT)
    p.add_argument('--eval-split-name', default='business_eval')
    p.add_argument('--train-pool-out', type=Path, default=DEFAULT_POOL_OUT)
    p.add_argument('--target-size', type=int, default=1500)
    p.add_argument('--min-per-label', type=int, default=100)
    p.add_argument('--auto-status-prefix', default='auto_accept')
    p.add_argument('--seed', type=int, default=42)
    return p.parse_args()


def read_adjudicated(path: Path) -> pd.DataFrame:
    if path.suffix == '.csv':
        return pd.read_csv(path)
    rows = [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines() if line.strip()]
    return pd.DataFrame(rows)


def to_processed_schema(df: pd.DataFrame) -> pd.DataFrame:
    out = df[['content', 'adjudicated_label']].copy()
    out = out.rename(columns={'adjudicated_label': 'label'})
    unknown = set(out['label']) - set(LABEL2ID)
    if unknown:
        raise ValueError(f'发现非法标签: {sorted(unknown)}')
    out['label_id'] = out['label'].map(LABEL2ID).astype('int64')
    return out[['content', 'label', 'label_id']]


def sample_eval(df: pd.DataFrame, target_size: int, min_per_label: int, seed: int) -> pd.DataFrame:
    if target_size <= 0:
        raise ValueError('--target-size 必须 > 0')
    if min_per_label < 0:
        raise ValueError('--min-per-label 必须 >= 0')

    selected_parts = []
    selected_idx: set[int] = set()

    for label in LABELS_ZH:
        part = df[df['adjudicated_label'] == label]
        if part.empty:
            continue
        n = min(min_per_label, len(part), target_size - len(selected_idx))
        if n <= 0:
            break
        sampled = part.sample(n=n, random_state=seed)
        selected_parts.append(sampled)
        selected_idx.update(sampled.index.tolist())

    remaining_n = min(target_size, len(df)) - len(selected_idx)
    if remaining_n > 0:
        rest = df.drop(index=list(selected_idx), errors='ignore')
        if not rest.empty:
            sampled = rest.sample(n=min(remaining_n, len(rest)), random_state=seed)
            selected_parts.append(sampled)
            selected_idx.update(sampled.index.tolist())

    if not selected_parts:
        raise SystemExit('没有可用于 business eval 的样本')
    return pd.concat(selected_parts).sample(frac=1, random_state=seed).reset_index(drop=True)


def main() -> None:
    args = parse_args()
    df = read_adjudicated(args.adjudicated)
    required = {'content', 'adjudicated_label', 'adjudication_status'}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f'adjudicated 缺少列: {sorted(missing)}')

    accepted = df[df['adjudication_status'].astype(str).str.startswith(args.auto_status_prefix)].copy()
    accepted = accepted.dropna(subset=['content', 'adjudicated_label'])
    accepted = accepted.drop_duplicates(subset=['content'], keep='first').reset_index(drop=True)
    if accepted.empty:
        raise SystemExit('没有 auto_accept 样本，无法构建 business eval')

    eval_df = sample_eval(accepted, args.target_size, args.min_per_label, args.seed)
    eval_content = set(eval_df['content'])
    pool_df = accepted[~accepted['content'].isin(eval_content)].reset_index(drop=True)

    eval_out = args.processed_root / f'{args.track}_{args.eval_split_name}.parquet'
    eval_out.parent.mkdir(parents=True, exist_ok=True)
    to_processed_schema(eval_df).to_parquet(eval_out, index=False)

    args.train_pool_out.parent.mkdir(parents=True, exist_ok=True)
    to_processed_schema(pool_df).to_parquet(args.train_pool_out, index=False)

    print(f'auto_accept 去重后: {len(accepted)}')
    print(f'写出 eval: {eval_out} ({len(eval_df)} 条)')
    print(to_processed_schema(eval_df)['label'].value_counts().reindex(LABELS_ZH, fill_value=0).to_string())
    print(f'写出 train pool: {args.train_pool_out} ({len(pool_df)} 条)')


if __name__ == '__main__':
    main()
