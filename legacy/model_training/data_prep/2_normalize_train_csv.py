"""标准化训练集 CSV。

输入:
    datasets/train/usual_train.csv

输出:
    datasets/train_raw.csv

SMP2020-EWECT 的训练集本身就是 CSV，这一步主要是统一编码（utf-8-sig）和落到固定路径，
方便下一步 3_preprocess_csv.py 读取。如果未来换成别的数据源，这一步是接入点。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from constants import DATA_DIR


INPUT = DATA_DIR / 'train' / 'usual_train.csv'
OUTPUT = DATA_DIR / 'train_raw.csv'


def main() -> None:
    if not INPUT.exists():
        sys.exit(f'缺少输入文件: {INPUT}')

    print(f'读取 {INPUT} ...')
    df = pd.read_csv(INPUT)
    print(f'  行数: {len(df)}')
    print(f'  列名: {list(df.columns)}')

    df.to_csv(OUTPUT, index=False, encoding='utf-8-sig')
    print(f'已写入 {OUTPUT}')


if __name__ == '__main__':
    main()
