"""SMP2020-EWECT 数据集探索。

按 readme 描述加载所有 labeled 文件，输出：
  - 每个文件的样本数、标签分布、文本长度分位数
  - usual / virus 两个 track 的对比
  - 含混淆数据集中 None 标签（混淆样本）占比
  - 文件内重复 + train↔eval/test 跨集泄露
  - 文本特征占比（URL / @用户 / #话题# / //@转发 / [微博表情]）
  - 异常 sample（空文本、超长文本）
  - 清洗后字符长度分位数（读 data/processed/，需先跑 preprocess.py）

train/eval/真实 test 用 .txt（JSON），含混淆数据集的 usual 用 .xlsx（实际是 OLE2 .xls）；
两种格式的列已在 load() 里统一成 id/content/label。
"""

from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path

import pandas as pd

from dataset_paths import ROOT, labeled_files, mixed_test_files

LABELS = ['happy', 'angry', 'sad', 'fear', 'surprise', 'neutral']

# 文本特征正则。每个 pattern 命中即算这条样本含该特征。
FEATURE_PATTERNS: dict[str, re.Pattern] = {
    'url':        re.compile(r'http[s]?://\S+'),
    'at_mention': re.compile(r'@[\w\u4e00-\u9fa5\-]+'),  # 含中文用户名
    'topic':      re.compile(r'#[^#\s]+#'),
    'retweet':    re.compile(r'//\s*@'),                 # 转发标记
    'wb_emoji':   re.compile(r'\[[^\[\]]{1,8}\]'),       # 微博表情 [心] [doge]
}


def load(path: Path) -> pd.DataFrame:
    if path.suffix == '.txt':
        records = json.loads(path.read_text(encoding='utf-8'))
        return pd.DataFrame(records)
    # 含混淆数据集里某些 .xlsx 实际是 WPS 存的 OLE2 (.xls) 格式，openpyxl 读不了，回退 xlrd
    try:
        df = pd.read_excel(path, engine='openpyxl')
    except Exception:
        df = pd.read_excel(path, engine='xlrd')
    # xlsx 用中文列名，统一成 txt 的英文 key
    return df.rename(columns={'数据编号': 'id', '文本': 'content', '情绪标签': 'label'})


def _valid_view(df: pd.DataFrame) -> pd.DataFrame:
    """剔除 None 标签和空 / 缺失 content，得到有效样本视图。"""
    cols_to_dropna = [c for c in ('label', 'content') if c in df.columns]
    out = df.dropna(subset=cols_to_dropna).copy()
    return out[out['content'].str.len() > 0]


def summarize(name: str, df: pd.DataFrame) -> dict:
    n = len(df)
    label_col = 'label' if 'label' in df.columns else None
    none_count = df[label_col].isna().sum() if label_col else 0
    valid = df.dropna(subset=[label_col]) if label_col else df

    label_dist = Counter(valid[label_col]) if label_col else Counter()
    lengths = valid['content'].astype(str).str.len()

    return {
        'name': name,
        'rows': n,
        'none_label': int(none_count),
        'labels': dict(label_dist),
        'len_min': int(lengths.min()) if len(lengths) else 0,
        'len_p50': int(lengths.median()) if len(lengths) else 0,
        'len_p95': int(lengths.quantile(0.95)) if len(lengths) else 0,
        'len_max': int(lengths.max()) if len(lengths) else 0,
        'empty_content': int((lengths == 0).sum()),
    }


def print_overview(stats: list[dict]) -> None:
    print('=' * 110)
    print(f'{"file":<22} {"rows":>7} {"None":>6} {"empty":>6} '
          f'{"len min/p50/p95/max":>22}')
    print('-' * 110)
    for s in stats:
        len_str = f'{s["len_min"]}/{s["len_p50"]}/{s["len_p95"]}/{s["len_max"]}'
        print(f'{s["name"]:<22} {s["rows"]:>7} {s["none_label"]:>6} '
              f'{s["empty_content"]:>6} {len_str:>22}')


def print_label_table(stats: list[dict]) -> None:
    print('\n' + '=' * 110)
    print('标签分布（仅有效标签，None 已剔除）')
    print('-' * 110)
    header = f'{"file":<22}' + ''.join(f'{lab:>10}' for lab in LABELS) + f'{"total":>10}'
    print(header)
    for s in stats:
        if not s['labels']:
            continue
        total = sum(s['labels'].values())
        row = f'{s["name"]:<22}'
        for lab in LABELS:
            cnt = s['labels'].get(lab, 0)
            pct = cnt / total * 100 if total else 0
            row += f'  {cnt:>4}/{pct:>2.0f}%'
        row += f'{total:>10}'
        print(row)


def print_unknown_labels(stats: list[dict]) -> None:
    """检查是否有出现在数据里但不在 6 类 taxonomy 里的标签。"""
    known = set(LABELS)
    surprises = {}
    for s in stats:
        unknown = set(s['labels']) - known
        if unknown:
            surprises[s['name']] = {k: s['labels'][k] for k in unknown}
    if surprises:
        print('\n!!! 发现未知标签:')
        for name, labs in surprises.items():
            print(f'  {name}: {labs}')
    else:
        print('\n所有标签都落在 6 类 taxonomy 内（happy/angry/sad/fear/surprise/neutral）。')


def print_dup_table(bundles: list[tuple[str, pd.DataFrame]]) -> None:
    """文件内部重复（按 content 完全一致，去 None 与空文本后）。"""
    print('\n' + '=' * 110)
    print('文件内部重复（基于 content 完全一致，已去 None 与空文本）')
    print('-' * 110)
    print(f'{"file":<22} {"valid":>8} {"unique":>8} {"dup_rows":>10} {"dup_pct":>8}')
    for name, df in bundles:
        v = _valid_view(df)
        unique = v['content'].nunique()
        dup = len(v) - unique
        pct = dup / len(v) * 100 if len(v) else 0
        print(f'{name:<22} {len(v):>8} {unique:>8} {dup:>10} {pct:>7.2f}%')


def print_leakage_table(bundles: list[tuple[str, pd.DataFrame]]) -> None:
    """train 与 eval/test 之间的内容重叠（leakage）。"""
    by_name = {name: set(_valid_view(df)['content']) for name, df in bundles}
    print('\n' + '=' * 110)
    print('train ↔ eval/test 内容重叠（按 content 完全一致）')
    print('-' * 110)
    print(f'{"train":<18} {"vs":<22} {"overlap":>8} {"of_eval/test":>14}')
    pairs = [
        ('usual_train', 'usual_eval'),
        ('usual_train', 'usual_test'),
        ('virus_train', 'virus_eval'),
        ('virus_train', 'virus_test'),
    ]
    for a, b in pairs:
        if a not in by_name or b not in by_name:
            continue
        overlap = len(by_name[a] & by_name[b])
        pct = overlap / len(by_name[b]) * 100 if by_name[b] else 0
        print(f'{a:<18} {b:<22} {overlap:>8} {pct:>13.2f}%')


def print_feature_table(bundles: list[tuple[str, pd.DataFrame]]) -> None:
    """每个文件含各种文本特征的样本占比。"""
    print('\n' + '=' * 110)
    print('文本特征占比（含该模式的样本数 / 有效样本数）')
    print('-' * 110)
    header = f'{"file":<22}' + ''.join(f'{k:>12}' for k in FEATURE_PATTERNS)
    print(header)
    for name, df in bundles:
        v = _valid_view(df)
        row = f'{name:<22}'
        for k, pat in FEATURE_PATTERNS.items():
            # 不用 pandas 的 str.contains，走 PyArrow 时会拒绝 \u 转义
            hit = sum(1 for s in v['content'] if pat.search(s))
            pct = hit / len(v) * 100 if len(v) else 0
            row += f'   {hit:>5}/{pct:>3.0f}%'
        print(row)


def print_outliers(bundles: list[tuple[str, pd.DataFrame]]) -> None:
    """打印空文本和超长文本的代表样本。"""
    print('\n' + '=' * 110)
    print('空 content 样本')
    print('-' * 110)
    for name, df in bundles:
        empty = df[df['content'].astype(str).str.len() == 0]
        if not len(empty):
            continue
        print(f'\n[{name}] 共 {len(empty)} 条')
        for _, row in empty.head(3).iterrows():
            print(f'  id={row.get("id")}, label={row.get("label")}, content=<EMPTY>')

    print('\n' + '=' * 110)
    print('超长文本样本（> 500 字符）')
    print('-' * 110)
    for name, df in bundles:
        v = _valid_view(df)
        lengths = v['content'].str.len()
        longs = v[lengths > 500]
        if not len(longs):
            continue
        long_lengths = longs['content'].str.len()
        print(f'\n[{name}] 共 {len(longs)} 条 > 500 字符，最长 {long_lengths.max()}')
        for _, row in longs.iloc[long_lengths.argsort()[::-1][:2]].iterrows():
            text = row['content']
            print(f'  id={row.get("id")}, label={row.get("label")}, '
                  f'len={len(text)}, head={text[:80]}...')


def print_processed_length_stats(processed_root: Path) -> None:
    """对清洗后的 parquet 文件统计字符长度分位数，用于敲定训练 max_length。

    BERT 中文 tokenizer 对中文几乎是字粒度，token 数 ≈ 字符数；
    `[心]` 等表情会被切成 `[`, `心`, `]` 仍是 1:1，所以字符数是 token 数的良好近似。
    """
    if not processed_root.exists():
        print(f'\n（跳过 processed 长度统计：{processed_root} 不存在，请先跑 preprocess.py）')
        return

    files = sorted(processed_root.glob('*.parquet'))
    if not files:
        return

    print('\n' + '=' * 110)
    print('清洗后文本字符长度分位数（决定训练时 tokenizer 的 max_length）')
    print('-' * 110)
    print(f'{"file":<22} {"rows":>7} {"min":>5} {"p50":>5} {"p90":>5} '
          f'{"p95":>5} {"p99":>5} {"max":>5}  {">128":>6} {">192":>6} {">256":>6}')
    for f in files:
        df = pd.read_parquet(f)
        lens = df['content'].str.len()
        n = len(lens)
        gt = lambda t: f'{(lens > t).sum() / n * 100:>5.1f}%' if n else '   na'
        print(f'{f.stem:<22} {n:>7} {lens.min():>5} {int(lens.median()):>5} '
              f'{int(lens.quantile(0.90)):>5} {int(lens.quantile(0.95)):>5} '
              f'{int(lens.quantile(0.99)):>5} {lens.max():>5}  '
              f'{gt(128)} {gt(192)} {gt(256)}')


def main() -> None:
    bundles: list[tuple[str, pd.DataFrame]] = []
    stats: list[dict] = []
    files = {**labeled_files(), **mixed_test_files()}
    for (track, split), path in files.items():
        if not path.exists():
            print(f'缺少文件: {path}')
            continue
        name = f'{track}_{split}'
        df = load(path)
        bundles.append((name, df))
        stats.append(summarize(name, df))

    print_overview(stats)
    print_label_table(stats)
    print_unknown_labels(stats)
    print_dup_table(bundles)
    print_leakage_table(bundles)
    print_feature_table(bundles)
    print_outliers(bundles)
    print_processed_length_stats(ROOT / 'data' / 'processed')


if __name__ == '__main__':
    main()
