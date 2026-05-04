"""合并多个标注候选文件，并按 content 去重。"""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument('--input', type=Path, nargs='+', required=True,
                   help='待合并的 parquet/csv/jsonl 候选文件')
    p.add_argument('--out', type=Path, required=True)
    p.add_argument('--dedupe-column', default='content')
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
    frames = [read_table(path) for path in args.input]
    out = pd.concat(frames, ignore_index=True)
    if args.dedupe_column not in out.columns:
        raise ValueError(f'缺少去重列 {args.dedupe_column!r}; 实际列: {list(out.columns)}')
    before = len(out)
    sort_cols = [c for c in ('priority', 'source', 'sample_id') if c in out.columns]
    if sort_cols:
        ascending = [False if c == 'priority' else True for c in sort_cols]
        out = out.sort_values(sort_cols, ascending=ascending)
    out = out.drop_duplicates(subset=[args.dedupe_column], keep='first').reset_index(drop=True)
    if 'candidate_rank' in out.columns:
        out['candidate_rank'] = range(1, len(out) + 1)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    out.to_parquet(args.out, index=False)
    print(f'写出 {args.out}: {len(out)} 条，去重删除 {before - len(out)} 条')
    if 'source' in out.columns:
        print(out['source'].value_counts().to_string())


if __name__ == '__main__':
    main()
