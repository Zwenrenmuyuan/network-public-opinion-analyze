"""SMP2020-EWECT 原始数据文件路径清单。

explore_dataset.py 和 preprocess.py 都需要这份清单，集中在这里避免漂移。

约定：
  - key = (track, split) 二元组，track ∈ {'usual', 'virus'}
  - labeled_files() 返回训练/验证/真实测试三个 split（preprocess 走这一份）
  - mixed_test_files() 返回含混淆数据的 labeled 文件（仅 explore 用，preprocess 用不到）
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_RAW_ROOT = ROOT / 'data' / 'raw' / '评测数据集'


def labeled_files(raw_root: Path = DEFAULT_RAW_ROOT) -> dict[tuple[str, str], Path]:
    """train/eval/test 真实带标签数据。"""
    return {
        ('usual', 'train'): raw_root / 'train' / 'usual_train.txt',
        ('usual', 'eval'):  raw_root / 'eval（刷榜数据集）' / 'usual_eval_labeled.txt',
        ('usual', 'test'):  raw_root / 'test（最终评测集）' / '真实评测集' / 'usual_test_labeled.txt',
        ('virus', 'train'): raw_root / 'train' / 'virus_train.txt',
        ('virus', 'eval'):  raw_root / 'eval（刷榜数据集）' / 'virus_eval_labeled.txt',
        ('virus', 'test'):  raw_root / 'test（最终评测集）' / '真实评测集' / 'virus_test_labeled.txt',
    }


def mixed_test_files(raw_root: Path = DEFAULT_RAW_ROOT) -> dict[tuple[str, str], Path]:
    """含混淆数据的 labeled 文件。usual 只有 .xlsx (实际是 OLE2 .xls)，virus 有 .txt。"""
    return {
        ('usual', 'test_mixed'): raw_root / 'test（最终评测集）' / '含混淆数据' / 'usual_test_labeled.xlsx',
        ('virus', 'test_mixed'): raw_root / 'test（最终评测集）' / '含混淆数据' / 'virus_test_labeled.txt',
    }
