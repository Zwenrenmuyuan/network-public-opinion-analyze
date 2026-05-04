"""构建 SMP silver + 业务高置信训练池的混合训练数据。

保持 eval/test 不变，只把 business_train_pool 合入 train；如果存在
business_eval，也复制到输出目录，方便后续用同一 processed-root 评估。
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

import pandas as pd

SCRIPTS_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPTS_DIR))
from dataset_paths import ROOT  # noqa: E402
from npo.config import LABEL2ID, LABELS_ZH  # noqa: E402

DEFAULT_BASE_ROOT = ROOT / 'data' / 'processed_silver'
DEFAULT_PROCESSED_ROOT = ROOT / 'data' / 'processed'
DEFAULT_OUT_ROOT = ROOT / 'data' / 'processed_mixed'


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument('--track', choices=['usual', 'virus'], default='usual')
    p.add_argument('--base-root', type=Path, default=DEFAULT_BASE_ROOT,
                   help='基础训练数据目录，默认 data/processed_silver')
    p.add_argument('--business-train', type=Path, default=None,
                   help='默认 data/processed/<track>_business_train_pool.parquet')
    p.add_argument('--business-eval', type=Path, default=None,
                   help='默认 data/processed/<track>_business_eval.parquet；存在则复制到 out-root')
    p.add_argument('--out-root', type=Path, default=DEFAULT_OUT_ROOT)
    p.add_argument('--business-max-size', type=int, default=None,
                   help='可选：业务训练样本总量上限')
    p.add_argument('--business-max-per-label', type=int, default=None,
                   help='可选：每个业务标签最多采样多少条')
    p.add_argument('--seed', type=int, default=42)
    return p.parse_args()


def read_processed(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(f'缺少 parquet: {path}')
    df = pd.read_parquet(path)
    required = {'content', 'label', 'label_id'}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f'{path} 缺少列: {sorted(missing)}')
    unknown = set(df['label']) - set(LABEL2ID)
    if unknown:
        raise ValueError(f'{path} 发现非法标签: {sorted(unknown)}')
    out = df[['content', 'label', 'label_id']].dropna(subset=['content', 'label']).copy()
    out['content'] = out['content'].astype(str)
    out['label_id'] = out['label'].map(LABEL2ID).astype('int64')
    return out.reset_index(drop=True)


def cap_business(df: pd.DataFrame, max_per_label: int | None, max_size: int | None, seed: int) -> pd.DataFrame:
    out = df.copy()
    if max_per_label is not None:
        if max_per_label <= 0:
            raise ValueError('--business-max-per-label 必须 > 0')
        parts = []
        for label in LABELS_ZH:
            part = out[out['label'] == label]
            if len(part) > max_per_label:
                part = part.sample(n=max_per_label, random_state=seed)
            parts.append(part)
        out = pd.concat(parts, ignore_index=True)
    if max_size is not None and len(out) > max_size:
        if max_size <= 0:
            raise ValueError('--business-max-size 必须 > 0')
        out = out.sample(n=max_size, random_state=seed)
    return out.sample(frac=1, random_state=seed).reset_index(drop=True)


def copy_split(src: Path, dst: Path) -> None:
    if not src.exists():
        raise FileNotFoundError(f'缺少 split: {src}')
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(src, dst)


def main() -> None:
    args = parse_args()
    business_train = args.business_train or DEFAULT_PROCESSED_ROOT / f'{args.track}_business_train_pool.parquet'
    business_eval = args.business_eval or DEFAULT_PROCESSED_ROOT / f'{args.track}_business_eval.parquet'

    base_train = read_processed(args.base_root / f'{args.track}_train.parquet')
    base_eval = read_processed(args.base_root / f'{args.track}_eval.parquet')
    base_test = read_processed(args.base_root / f'{args.track}_test.parquet')
    business = read_processed(business_train)

    exclude_content = set(base_eval['content']) | set(base_test['content'])
    if business_eval.exists():
        exclude_content |= set(read_processed(business_eval)['content'])

    before = len(business)
    business = business.drop_duplicates(subset=['content'], keep='first')
    business = business[~business['content'].isin(exclude_content)].reset_index(drop=True)
    excluded = before - len(business)
    business = cap_business(business, args.business_max_per_label, args.business_max_size, args.seed)

    mixed = pd.concat([base_train, business], ignore_index=True)
    before_mixed = len(mixed)
    mixed = mixed.drop_duplicates(subset=['content'], keep='first').reset_index(drop=True)
    mixed['label_id'] = mixed['label'].map(LABEL2ID).astype('int64')

    args.out_root.mkdir(parents=True, exist_ok=True)
    train_out = args.out_root / f'{args.track}_train.parquet'
    mixed.to_parquet(train_out, index=False)
    copy_split(args.base_root / f'{args.track}_eval.parquet', args.out_root / f'{args.track}_eval.parquet')
    copy_split(args.base_root / f'{args.track}_test.parquet', args.out_root / f'{args.track}_test.parquet')
    if business_eval.exists():
        copy_split(business_eval, args.out_root / f'{args.track}_business_eval.parquet')

    print(f'base train: {len(base_train)}')
    print(f'business train pool: {before}，排除/去重: {excluded}，实际合入候选: {len(business)}')
    print(f'mixed train: {len(mixed)}，最终去重删除: {before_mixed - len(mixed)}')
    print(f'写出: {train_out}')
    print('混合训练集标签分布:')
    print(mixed['label'].value_counts().reindex(LABELS_ZH, fill_value=0).to_string())
    print('业务合入标签分布:')
    print(business['label'].value_counts().reindex(LABELS_ZH, fill_value=0).to_string())


if __name__ == '__main__':
    main()
