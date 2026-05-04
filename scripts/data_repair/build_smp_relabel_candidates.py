"""生成 SMP usual 六分类标注修复候选集。

候选来源：
  1. raw 中清洗后同 content 多标签冲突的样本；
  2. processed 中小类和高混淆类的分层抽样。

输出 parquet，供 LLM 预标注和人工复核使用。不会修改原始数据。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

SCRIPTS_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPTS_DIR))
from dataset_paths import DEFAULT_RAW_ROOT, ROOT, labeled_files  # noqa: E402
from preprocess import clean_frame, load_raw  # noqa: E402

from npo.config import LABEL2ID, LABELS_ZH  # noqa: E402

DEFAULT_PROCESSED_ROOT = ROOT / 'data' / 'processed'
DEFAULT_OUT = ROOT / 'data' / 'annotation' / 'smp_relabel_candidates.parquet'

BOUNDARY_LABELS = ('愤怒', '悲伤', '恐惧', '惊讶', '积极', '中性')
MINORITY_LABELS = ('恐惧', '惊讶')


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument('--track', choices=['usual', 'virus'], default='usual')
    p.add_argument('--raw-root', type=Path, default=DEFAULT_RAW_ROOT)
    p.add_argument('--processed-root', type=Path, default=DEFAULT_PROCESSED_ROOT)
    p.add_argument('--out', type=Path, default=DEFAULT_OUT)
    p.add_argument('--splits', nargs='+', choices=['train', 'eval', 'test'],
                   default=['train', 'eval', 'test'])
    p.add_argument('--per-label-sample', type=int, default=120,
                   help='每个 split 每个高风险标签抽样数量；0 表示只输出冲突样本')
    p.add_argument('--seed', type=int, default=42)
    return p.parse_args()


def conflict_candidates(track: str, raw_root: Path, splits: list[str]) -> pd.DataFrame:
    files = labeled_files(raw_root)
    rows: list[dict] = []

    for split in splits:
        df = clean_frame(load_raw(files[(track, split)]))
        grouped = df.groupby('content').agg(
            raw_labels=('label', lambda s: tuple(sorted(set(s)))),
            rows=('label', 'size'),
        )
        conflicts = grouped[grouped['raw_labels'].map(len) > 1]

        for i, (content, row) in enumerate(conflicts.iterrows(), 1):
            raw_labels = list(row['raw_labels'])
            rows.append({
                'sample_id': f'smp-{track}-{split}-conflict-{i:05d}',
                'source': 'smp_raw_conflict',
                'track': track,
                'split': split,
                'content': content,
                'current_label': '',
                'current_label_id': -1,
                'raw_labels': json.dumps(raw_labels, ensure_ascii=False),
                'candidate_reason': 'cleaned_content_has_multiple_raw_labels',
                'priority': 100,
            })

    return pd.DataFrame(rows)


def sampled_candidates(
    track: str,
    processed_root: Path,
    splits: list[str],
    per_label_sample: int,
    seed: int,
) -> pd.DataFrame:
    if per_label_sample <= 0:
        return pd.DataFrame()

    rows: list[pd.DataFrame] = []
    for split in splits:
        path = processed_root / f'{track}_{split}.parquet'
        if not path.exists():
            raise FileNotFoundError(f'缺少 parquet: {path}，请先跑 scripts/preprocess.py')
        df = pd.read_parquet(path)

        for label in BOUNDARY_LABELS:
            part = df[df['label'] == label]
            if part.empty:
                continue
            n = min(per_label_sample, len(part))
            priority = 80 if label in MINORITY_LABELS else 60
            sampled = part.sample(n=n, random_state=seed).copy()
            sampled['sample_id'] = [
                f'smp-{track}-{split}-{LABEL2ID[label]}-{idx:05d}'
                for idx in range(1, len(sampled) + 1)
            ]
            sampled['source'] = 'smp_processed_label_sample'
            sampled['track'] = track
            sampled['split'] = split
            sampled['current_label'] = sampled['label']
            sampled['current_label_id'] = sampled['label_id'].astype('int64')
            sampled['raw_labels'] = sampled['label'].map(lambda x: json.dumps([x], ensure_ascii=False))
            sampled['candidate_reason'] = sampled['label'].map(
                lambda x: 'minority_label_sample' if x in MINORITY_LABELS else 'boundary_label_sample'
            )
            sampled['priority'] = priority
            rows.append(sampled[[
                'sample_id', 'source', 'track', 'split', 'content',
                'current_label', 'current_label_id', 'raw_labels',
                'candidate_reason', 'priority',
            ]])

    return pd.concat(rows, ignore_index=True) if rows else pd.DataFrame()


def main() -> None:
    args = parse_args()
    if args.track != 'usual':
        print('警告：主线建议只修复 usual；virus 仅作专项参考。', file=sys.stderr)

    parts = [
        conflict_candidates(args.track, args.raw_root, args.splits),
        sampled_candidates(
            args.track, args.processed_root, args.splits,
            args.per_label_sample, args.seed,
        ),
    ]
    out = pd.concat([p for p in parts if not p.empty], ignore_index=True)
    if out.empty:
        raise SystemExit('没有生成任何候选样本')

    out = out.sort_values(['priority', 'source', 'sample_id'], ascending=[False, True, True])
    out = out.drop_duplicates(subset=['content'], keep='first').reset_index(drop=True)
    out['candidate_rank'] = range(1, len(out) + 1)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    out.to_parquet(args.out, index=False)
    print(f'写出 {args.out}: {len(out)} 条候选')
    print(out.groupby(['source', 'candidate_reason']).size().to_string())
    print('标签顺序:', ', '.join(f'{i}={lab}' for i, lab in enumerate(LABELS_ZH)))


if __name__ == '__main__':
    main()
