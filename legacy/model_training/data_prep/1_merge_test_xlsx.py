"""合并 SMP2020-EWECT usual 赛道的两份测试集 xlsx 为单个 CSV。

输入:
    datasets/test/usual_eval_labeled.xlsx
    datasets/test/usual_test_labeled.xlsx

输出:
    datasets/merged_test.csv

旧仓库里这个脚本（数据预处理/合并测试数据.py）用了 engine='xlrd'，但现代 xlrd >= 2.0
不再支持 xlsx，所以这里改成 openpyxl。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

# 让 'from constants import ...' 能找到顶层模块
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from constants import DATA_DIR


TEST_DIR = DATA_DIR / 'test'
EVAL_FILE = TEST_DIR / 'usual_eval_labeled.xlsx'
TEST_FILE = TEST_DIR / 'usual_test_labeled.xlsx'
OUTPUT = DATA_DIR / 'merged_test.csv'


def main() -> None:
    for f in (EVAL_FILE, TEST_FILE):
        if not f.exists():
            sys.exit(f'缺少输入文件: {f}')

    print(f'读取 {EVAL_FILE.name} ...')
    df1 = pd.read_excel(EVAL_FILE, engine='openpyxl')
    print(f'  行数: {len(df1)}')

    print(f'读取 {TEST_FILE.name} ...')
    df2 = pd.read_excel(TEST_FILE, engine='openpyxl')
    print(f'  行数: {len(df2)}')

    merged = pd.concat([df1, df2], ignore_index=True)
    if '数据编号' in merged.columns:
        merged['数据编号'] = range(1, len(merged) + 1)

    print(f'合并后行数: {len(merged)}')
    merged.to_csv(OUTPUT, index=False, encoding='utf-8-sig')
    print(f'已写入 {OUTPUT}')


if __name__ == '__main__':
    main()
