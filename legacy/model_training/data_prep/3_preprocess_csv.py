"""把英文标签的原始 CSV 转成可用于训练的中文标签 + 清洗过文本的 CSV。

输入:
    datasets/merged_test.csv  （由 1_merge_test_xlsx.py 产出）
    datasets/train_raw.csv    （由 2_normalize_train_csv.py 产出）

输出:
    datasets/test.csv
    datasets/train.csv

输出列：
    文本 (str, 清洗后, 最长 140 字)
    情绪标签 (str, 6 类中文)

会打印每个数据集的标签分布，便于核对样本数量是否合理。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from constants import DATA_DIR, LABEL_MAP_EN_TO_ZH
from preprocessing import process_text


JOBS = [
    (DATA_DIR / 'merged_test.csv', DATA_DIR / 'test.csv',  '测试集'),
    (DATA_DIR / 'train_raw.csv',   DATA_DIR / 'train.csv', '训练集'),
]


def analyze_label_distribution(df: pd.DataFrame, name: str) -> None:
    """打印标签的数量和占比，便于人工 sanity check。"""
    counts = df['情绪标签'].value_counts()
    pct = df['情绪标签'].value_counts(normalize=True) * 100
    print(f'\n{name}标签分布:')
    print('-' * 40)
    print(f'{"标签":<10}{"数量":<10}{"占比"}')
    print('-' * 40)
    for label in counts.index:
        print(f'{label:<10}{counts[label]:<10}{pct[label]:.2f}%')
    print('-' * 40)
    print(f'总计: {len(df)} 条\n')


def process_file(input_path: Path, output_path: Path, name: str) -> None:
    if not input_path.exists():
        sys.exit(f'缺少输入文件: {input_path}（请先跑 1_ 和 2_ 脚本）')

    print(f'\n=== 处理 {name} ({input_path.name}) ===')
    df = pd.read_csv(input_path)

    if '文本' not in df.columns or '情绪标签' not in df.columns:
        sys.exit(
            f'{input_path} 缺少必要列。当前列: {list(df.columns)}。'
            f'要求列: 文本, 情绪标签'
        )

    # 文本清洗
    print('应用 process_text ...')
    df['文本'] = df['文本'].apply(process_text)

    # 英文标签 -> 中文标签
    print('应用 LABEL_MAP_EN_TO_ZH ...')
    df['情绪标签'] = df['情绪标签'].map(LABEL_MAP_EN_TO_ZH)
    if df['情绪标签'].isna().any():
        unknown = df[df['情绪标签'].isna()]
        sys.exit(f'发现无法映射的标签 {unknown.head()}')

    analyze_label_distribution(df, name)

    df.to_csv(output_path, index=False, encoding='utf-8-sig')
    print(f'已写入 {output_path}')


def main() -> None:
    for input_path, output_path, name in JOBS:
        process_file(input_path, output_path, name)


if __name__ == '__main__':
    main()
