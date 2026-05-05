"""从第二轮业务仲裁结果构建训练池，不修改 business_eval。"""

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

DEFAULT_PROCESSED_ROOT = ROOT / 'data' / 'processed'
DEFAULT_ADJUDICATED = ROOT / 'data' / 'annotation' / 'business_targeted_adjudicated.jsonl'
DEFAULT_OUT = ROOT / 'data' / 'processed' / 'usual_business_train_pool_v2.parquet'


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument('--adjudicated', type=Path, default=DEFAULT_ADJUDICATED)
    p.add_argument('--existing-train-pool', type=Path,
                   default=DEFAULT_PROCESSED_ROOT / 'usual_business_train_pool.parquet')
    p.add_argument('--processed-root', type=Path, default=DEFAULT_PROCESSED_ROOT)
    p.add_argument('--track', choices=['usual', 'virus'], default='usual')
    p.add_argument('--out', type=Path, default=DEFAULT_OUT)
    p.add_argument('--auto-status-prefix', default='auto_accept')
    p.add_argument('--include-human-required', action='store_true',
                   help='仅在人工已确认 human_required 样本标签时使用')
    return p.parse_args()


def read_table(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(f'缺少输入: {path}')
    if path.suffix == '.parquet':
        return pd.read_parquet(path)
    if path.suffix == '.csv':
        return pd.read_csv(path)
    if path.suffix in ('.jsonl', '.ndjson'):
        rows = [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines() if line.strip()]
        return pd.DataFrame(rows)
    raise ValueError(f'不支持的输入格式: {path.suffix}')


def read_processed(path: Path) -> pd.DataFrame:
    df = read_table(path)
    required = {'content', 'label'}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f'{path} 缺少列: {sorted(missing)}')
    out = df[['content', 'label']].dropna(subset=['content', 'label']).copy()
    out['content'] = out['content'].astype(str)
    out['label'] = out['label'].astype(str)
    return to_processed_schema(out)


def to_processed_schema(df: pd.DataFrame) -> pd.DataFrame:
    out = df[['content', 'label']].dropna(subset=['content', 'label']).copy()
    unknown = set(out['label']) - set(LABEL2ID)
    if unknown:
        raise ValueError(f'发现非法标签: {sorted(unknown)}')
    out['label_id'] = out['label'].map(LABEL2ID).astype('int64')
    return out[['content', 'label', 'label_id']]


def accepted_second_round(df: pd.DataFrame, auto_prefix: str, include_human_required: bool) -> pd.DataFrame:
    required = {'content', 'adjudicated_label', 'adjudication_status'}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f'adjudicated 缺少列: {sorted(missing)}')

    status = df['adjudication_status'].astype(str)
    mask = status.str.startswith(auto_prefix)
    if include_human_required:
        mask |= status.str.startswith('human_required')
    out = df[mask].dropna(subset=['content', 'adjudicated_label']).copy()
    out = out.rename(columns={'adjudicated_label': 'label'})
    return to_processed_schema(out)


def excluded_contents(args: argparse.Namespace) -> set[str]:
    paths = [
        args.processed_root / f'{args.track}_eval.parquet',
        args.processed_root / f'{args.track}_test.parquet',
        args.processed_root / f'{args.track}_business_eval.parquet',
    ]
    excluded: set[str] = set()
    for path in paths:
        if path.exists():
            excluded.update(read_processed(path)['content'].tolist())
    return excluded


def main() -> None:
    args = parse_args()
    existing = read_processed(args.existing_train_pool)
    second = accepted_second_round(read_table(args.adjudicated), args.auto_status_prefix, args.include_human_required)

    before_second = len(second)
    exclude = excluded_contents(args)
    second = second[~second['content'].isin(exclude)]

    combined = pd.concat([existing, second], ignore_index=True)
    before_dedupe = len(combined)
    combined = combined.drop_duplicates(subset=['content'], keep='first').reset_index(drop=True)
    combined['label_id'] = combined['label'].map(LABEL2ID).astype('int64')

    args.out.parent.mkdir(parents=True, exist_ok=True)
    combined.to_parquet(args.out, index=False)
    print(f'existing train pool: {len(existing)}')
    print(f'second-round accepted: {before_second}，排除 eval/test/business_eval: {before_second - len(second)}')
    print(f'写出 train pool v2: {args.out} ({len(combined)} 条)，合并去重删除: {before_dedupe - len(combined)}')
    print(combined['label'].value_counts().reindex(LABELS_ZH, fill_value=0).to_string())


if __name__ == '__main__':
    main()
