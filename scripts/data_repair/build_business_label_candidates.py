"""从离线导出的爬虫业务 Parquet 生成 LLM 标注候选集。

本脚本不连接 ClickHouse；先按 docs/data-handover.md 从 CK 导出 post/comment，
再把导出的 Parquet 作为输入。输出供 llm_label_candidates.py 使用。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

SCRIPTS_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPTS_DIR))
from dataset_paths import ROOT
from preprocess import clean_text

DEFAULT_OUT = ROOT / 'data' / 'annotation' / 'business_label_candidates.parquet'


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument('--input', type=Path, nargs='+', required=True,
                   help='从 CK 离线导出的 Parquet/CSV/JSONL，可传多个')
    p.add_argument('--out', type=Path, default=DEFAULT_OUT)
    p.add_argument('--source', choices=['post', 'comment'], required=True)
    p.add_argument('--id-column', default=None,
                   help='post 用 post_id，comment 用 comment_id；不填则自动推断')
    p.add_argument('--text-column', default='text_raw')
    p.add_argument('--min-chars', type=int, default=4)
    p.add_argument('--max-chars', type=int, default=512)
    p.add_argument('--sample-size', type=int, default=None,
                   help='清洗去重后随机抽样数量；不填则全量输出')
    p.add_argument('--seed', type=int, default=42)
    return p.parse_args()


def read_table(path: Path) -> pd.DataFrame:
    if path.suffix == '.parquet':
        return pd.read_parquet(path)
    if path.suffix == '.csv':
        return pd.read_csv(path)
    if path.suffix in ('.jsonl', '.ndjson'):
        return pd.read_json(path, lines=True)
    raise ValueError(f'不支持的输入格式: {path.suffix}')


def main() -> None:
    args = parse_args()
    id_column = args.id_column or ('comment_id' if args.source == 'comment' else 'post_id')

    frames = []
    for path in args.input:
        df = read_table(path)
        missing = [c for c in (id_column, args.text_column) if c not in df.columns]
        if missing:
            raise ValueError(f'{path} 缺少列: {missing}; 实际列: {list(df.columns)}')
        keep_cols = [id_column, args.text_column]
        for optional in ('post_id', 'created_at', 'like_count', 'region_name', 'has_images', 'has_video'):
            if optional in df.columns and optional not in keep_cols:
                keep_cols.append(optional)
        frames.append(df[keep_cols].copy())

    df = pd.concat(frames, ignore_index=True)
    df = df.dropna(subset=[args.text_column])
    df['raw_text'] = df[args.text_column].astype(str)
    df['content'] = df['raw_text'].map(clean_text)
    df = df[df['content'].str.len().between(args.min_chars, args.max_chars)]
    df = df.drop_duplicates(subset=['content'], keep='first').reset_index(drop=True)

    if args.sample_size is not None and len(df) > args.sample_size:
        df = df.sample(n=args.sample_size, random_state=args.seed).reset_index(drop=True)

    source_prefix = f'business_{args.source}'
    out = pd.DataFrame({
        'sample_id': [f'{source_prefix}-{i:07d}' for i in range(1, len(df) + 1)],
        'source': source_prefix,
        'source_id': df[id_column].astype(str),
        'content': df['content'],
        'raw_text': df['raw_text'],
        'candidate_reason': 'business_offline_export',
        'priority': 50,
    })

    for optional in ('post_id', 'created_at', 'like_count', 'region_name', 'has_images', 'has_video'):
        if optional in df.columns:
            out[optional] = df[optional]

    args.out.parent.mkdir(parents=True, exist_ok=True)
    out.to_parquet(args.out, index=False)
    print(f'写出 {args.out}: {len(out)} 条候选')
    print(f'source={source_prefix}, text_column={args.text_column}, id_column={id_column}')


if __name__ == '__main__':
    main()
