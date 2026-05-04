"""两级 LLM 标注复核与仲裁。

典型流程：
  1. flash 批量预标注后，用 prepare-review 生成 pro 复核输入；
  2. pro 复核后，用 adjudicate 合并两次输出并自动分流。
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import pandas as pd


def read_jsonl(path: Path) -> pd.DataFrame:
    rows = [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines() if line.strip()]
    return pd.DataFrame(rows)


def write_jsonl(df: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w', encoding='utf-8') as f:
        for row in df.to_dict(orient='records'):
            f.write(json.dumps(row, ensure_ascii=False, default=str) + '\n')


def add_common_args(p: argparse.ArgumentParser) -> None:
    p.add_argument('--primary', type=Path, required=True,
                   help='第一阶段 LLM JSONL，通常来自 mimo-v2-flash')
    p.add_argument('--confidence-threshold', type=float, default=0.75)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest='cmd', required=True)

    p_review = sub.add_parser('prepare-review', help='生成第二阶段复核输入 parquet')
    add_common_args(p_review)
    p_review.add_argument('--out', type=Path, required=True)

    p_adj = sub.add_parser('adjudicate', help='合并 primary/review 并自动分流')
    add_common_args(p_adj)
    p_adj.add_argument('--review', type=Path, required=True,
                       help='第二阶段 LLM JSONL，通常来自 mimo-v2.5-pro')
    p_adj.add_argument('--out-csv', type=Path, required=True)
    p_adj.add_argument('--out-jsonl', type=Path, default=None)
    p_adj.add_argument('--agreement-threshold', type=float, default=0.70)
    p_adj.add_argument('--review-high-confidence', type=float, default=0.85)
    p_adj.add_argument('--primary-high-confidence', type=float, default=0.75)
    return parser.parse_args()


def normalize_primary(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    rename = {
        'text': 'content',
        'llm_label': 'primary_label',
        'llm_second_label': 'primary_second_label',
        'llm_confidence': 'primary_confidence',
        'llm_reason': 'primary_reason',
        'needs_human_review': 'primary_needs_review',
        'model': 'primary_model',
    }
    out = out.rename(columns={k: v for k, v in rename.items() if k in out.columns})
    return out


def normalize_review(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    out = df.drop_duplicates(subset=['sample_id'], keep='last').copy()
    rename = {
        'llm_label': 'review_label',
        'llm_second_label': 'review_second_label',
        'llm_confidence': 'review_confidence',
        'llm_reason': 'review_reason',
        'needs_human_review': 'review_needs_review',
        'model': 'review_model',
    }
    out = out.rename(columns={k: v for k, v in rename.items() if k in out.columns})
    keep = [
        'sample_id', 'review_label', 'review_second_label', 'review_confidence',
        'review_reason', 'review_needs_review', 'review_model',
    ]
    return out[[c for c in keep if c in out.columns]]


def prepare_review(args: argparse.Namespace) -> None:
    primary = normalize_primary(read_jsonl(args.primary))
    mask = (
        primary.get('primary_needs_review', False).astype(bool)
        | (primary['primary_confidence'].astype(float) < args.confidence_threshold)
    )
    review = primary[mask].copy()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    review.to_parquet(args.out, index=False)
    print(f'写出 {args.out}: {len(review)} 条复核输入')


def decide(row: pd.Series, args: argparse.Namespace) -> tuple[str, str]:
    primary_label = row.get('primary_label', '')
    review_label = row.get('review_label', '')
    primary_conf = float(row.get('primary_confidence') or 0)
    review_conf = float(row.get('review_confidence') or 0)
    primary_needs = bool(row.get('primary_needs_review'))
    review_needs = bool(row.get('review_needs_review'))

    if not primary_needs and primary_conf >= args.primary_high_confidence:
        return primary_label, 'auto_accept_primary_high_conf'
    if not review_label or pd.isna(review_label):
        return primary_label, 'human_required_no_review'
    if primary_label == review_label and review_conf >= args.agreement_threshold:
        return review_label, 'auto_accept_two_model_agree'
    if review_conf >= args.review_high_confidence and not review_needs:
        return review_label, 'auto_accept_review_high_conf'
    return review_label, 'human_required_disagree_or_low_conf'


def adjudicate(args: argparse.Namespace) -> None:
    primary = normalize_primary(read_jsonl(args.primary))
    review = normalize_review(read_jsonl(args.review))
    merged = primary.merge(review, on='sample_id', how='left')
    merged['primary_review_agree'] = merged['primary_label'] == merged['review_label']

    decisions = [decide(row, args) for _, row in merged.iterrows()]
    merged['adjudicated_label'] = [x[0] for x in decisions]
    merged['adjudication_status'] = [x[1] for x in decisions]

    preferred = [
        'sample_id', 'source', 'track', 'split', 'content', 'current_label', 'raw_labels',
        'primary_label', 'primary_second_label', 'primary_confidence', 'primary_reason',
        'review_label', 'review_second_label', 'review_confidence', 'review_reason',
        'primary_review_agree', 'adjudicated_label', 'adjudication_status',
        'candidate_reason', 'primary_model', 'review_model',
    ]
    cols = [c for c in preferred if c in merged.columns]
    out = merged[cols].copy()

    args.out_csv.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(args.out_csv, index=False, encoding='utf-8-sig')
    if args.out_jsonl:
        write_jsonl(out, args.out_jsonl)

    print(f'写出 {args.out_csv}: {len(out)} 条')
    if args.out_jsonl:
        print(f'写出 {args.out_jsonl}: {len(out)} 条')
    print(out['adjudication_status'].value_counts().to_string())


def main() -> None:
    args = parse_args()
    if args.cmd == 'prepare-review':
        prepare_review(args)
    elif args.cmd == 'adjudicate':
        adjudicate(args)
    else:
        raise ValueError(f'unknown cmd: {args.cmd}')


if __name__ == '__main__':
    main()
