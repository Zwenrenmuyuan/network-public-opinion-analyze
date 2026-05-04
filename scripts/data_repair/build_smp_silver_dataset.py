"""用两级 LLM 自动仲裁结果生成 SMP silver 派生数据集。

默认只修复 train split，eval/test 原样复制，避免改变最终评测口径。
原始 SMP 和 data/processed 不会被修改。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

SCRIPTS_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPTS_DIR))
from dataset_paths import ROOT
from npo.config import LABEL2ID, LABELS_ZH

DEFAULT_PROCESSED_ROOT = ROOT / 'data' / 'processed'
DEFAULT_ADJUDICATED = ROOT / 'data' / 'annotation' / 'smp_adjudicated.jsonl'
DEFAULT_OUT_ROOT = ROOT / 'data' / 'processed_silver'


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument('--track', choices=['usual', 'virus'], default='usual')
    p.add_argument('--processed-root', type=Path, default=DEFAULT_PROCESSED_ROOT)
    p.add_argument('--adjudicated', type=Path, default=DEFAULT_ADJUDICATED)
    p.add_argument('--out-root', type=Path, default=DEFAULT_OUT_ROOT)
    p.add_argument('--apply-splits', nargs='+', choices=['train', 'eval', 'test'],
                   default=['train'],
                   help='默认只修 train；显式传 eval/test 才会改验证/测试标签')
    p.add_argument('--auto-status-prefix', default='auto_accept')
    return p.parse_args()


def read_adjudicated(path: Path) -> pd.DataFrame:
    rows = []
    for line in path.read_text(encoding='utf-8').splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return pd.DataFrame(rows)


def build_relabel_map(adj: pd.DataFrame, track: str, split: str, status_prefix: str) -> dict[str, str]:
    required = {'content', 'track', 'split', 'adjudicated_label', 'adjudication_status'}
    missing = required - set(adj.columns)
    if missing:
        raise ValueError(f'adjudicated 缺少列: {sorted(missing)}')

    part = adj[
        (adj['track'] == track)
        & (adj['split'] == split)
        & (adj['adjudication_status'].astype(str).str.startswith(status_prefix))
    ].copy()
    if part.empty:
        return {}

    unknown = set(part['adjudicated_label']) - set(LABEL2ID)
    if unknown:
        raise ValueError(f'发现非法标签: {unknown}')

    conflicts = part.groupby('content')['adjudicated_label'].nunique()
    conflicts = conflicts[conflicts > 1]
    if len(conflicts):
        raise ValueError(f'{split} 有 {len(conflicts)} 个 content 被自动仲裁为多个标签')

    return dict(zip(part['content'], part['adjudicated_label']))


def apply_relabels(df: pd.DataFrame, relabels: dict[str, str]) -> tuple[pd.DataFrame, pd.DataFrame]:
    out = df.copy()
    if not relabels:
        return out, pd.DataFrame()

    mask = out['content'].isin(relabels)
    changes = out[mask].copy()
    if changes.empty:
        return out, changes

    changes['old_label'] = changes['label']
    changes['new_label'] = changes['content'].map(relabels)
    changes = changes[changes['old_label'] != changes['new_label']].copy()

    out.loc[mask, 'label'] = out.loc[mask, 'content'].map(relabels)
    out['label_id'] = out['label'].map(LABEL2ID).astype('int64')
    return out[['content', 'label', 'label_id']], changes


def main() -> None:
    args = parse_args()
    adj = read_adjudicated(args.adjudicated)
    args.out_root.mkdir(parents=True, exist_ok=True)

    all_changes = []
    for split in ('train', 'eval', 'test'):
        src = args.processed_root / f'{args.track}_{split}.parquet'
        if not src.exists():
            raise FileNotFoundError(f'缺少 processed parquet: {src}')
        df = pd.read_parquet(src)

        relabels = {}
        if split in args.apply_splits:
            relabels = build_relabel_map(adj, args.track, split, args.auto_status_prefix)
        repaired, changes = apply_relabels(df, relabels)
        if not changes.empty:
            changes.insert(0, 'split', split)
            all_changes.append(changes[['split', 'content', 'old_label', 'new_label']])

        out_path = args.out_root / f'{args.track}_{split}.parquet'
        repaired.to_parquet(out_path, index=False)
        print(f'写出 {out_path}: {len(repaired)} 条，应用候选={len(relabels)}，实际改标={len(changes)}')

    if all_changes:
        change_df = pd.concat(all_changes, ignore_index=True)
        report_path = args.out_root / f'{args.track}_silver_label_changes.csv'
        change_df.to_csv(report_path, index=False, encoding='utf-8-sig')
        print(f'写出 {report_path}: {len(change_df)} 条改标记录')
        print(change_df.groupby(['split', 'old_label', 'new_label']).size().to_string())
    else:
        print('没有实际改标')
    print('标签顺序:', ', '.join(f'{i}={lab}' for i, lab in enumerate(LABELS_ZH)))


if __name__ == '__main__':
    main()
