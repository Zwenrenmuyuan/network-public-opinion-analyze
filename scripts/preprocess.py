"""SMP2020-EWECT 数据预处理：清洗 + 去重 + 去泄露 + 写 parquet。

输入: data/raw/评测数据集/...
输出: data/processed/{usual,virus}_{train,eval,test}.parquet
      列: content (str), label (中文), label_id (int 0-5)

清洗顺序固定（顺序敏感，不要改）：
  1. NFKC 归一化（全角→半角）
  2. 繁体转简体
  3. 英文小写
  4. 去 URL（必须在 //@ 和 @ 之前）
  5. 去 //@xxx: 转发链
  6. 去 @username（含中文用户名）
  7. 处理 #话题#：保留文本，去 # 符号
  8. 折叠空白 + strip
  9. 截断到 SANITY_MAX_CHARS（512）：仅作内存与异常文本上限，
     真正的 max_length 截断交给训练时的 tokenizer，避免两次截断耦合

清洗完成后做：
  - 丢弃空 content（含原本就空的 + 清洗后变空的）
  - 文件内部去重（保留首次）
  - train 删除与 eval/test 重叠的样本（防止评估泄露）

[心][泪] 等微博表情天然保留（pattern 不匹配）。
"""

from __future__ import annotations

import argparse
import json
import re
import unicodedata
from pathlib import Path

import pandas as pd
from zhconv import convert

from dataset_paths import DEFAULT_RAW_ROOT, labeled_files
from npo.config import LABEL2ID, LABEL_MAP_EN_TO_ZH

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUT_ROOT = ROOT / 'data' / 'processed'

# 仅作 sanity 上限：极少数样本超过此长度（virus 最长 3172 字符），
# 截到 512 是为了防御性地兜底，不影响 BERT 训练（BERT 原生 max=512）。
# 训练时由 tokenizer 决定真正的 max_length。
SANITY_MAX_CHARS = 512

# 清洗正则
_URL_RE       = re.compile(r'http[s]?://\S+')
_RETWEET_RE   = re.compile(r'//\s*@[^\s:：]+[:：]?')          # //@xxx: 整段
_AT_MENTION_RE = re.compile(r'@[\w\u4e00-\u9fa5\-]+')        # 含中文用户名
_TOPIC_RE     = re.compile(r'#([^#]+)#')                      # #话题# 保留 group(1)
_WHITESPACE_RE = re.compile(r'\s+')


def clean_text(text: str) -> str:
    if not isinstance(text, str):
        return ''
    text = unicodedata.normalize('NFKC', text)
    text = convert(text, 'zh-cn')
    text = text.lower()
    text = _URL_RE.sub('', text)
    text = _RETWEET_RE.sub('', text)
    text = _AT_MENTION_RE.sub('', text)
    text = _TOPIC_RE.sub(r'\1', text)
    text = _WHITESPACE_RE.sub(' ', text).strip()
    return text[:SANITY_MAX_CHARS]


def load_raw(path: Path) -> pd.DataFrame:
    records = json.loads(path.read_text(encoding='utf-8'))
    return pd.DataFrame(records)


def clean_frame(df: pd.DataFrame) -> pd.DataFrame:
    """清洗 + 加 label 中文 + label_id。返回带 [content, label, label_id] 三列的 df。"""
    out = df.dropna(subset=['label', 'content']).copy()
    # 不能 astype(str)，否则 NaN 会变 "nan" 字符串绕过 clean_text 的 isinstance 保护
    out['content'] = out['content'].map(clean_text)
    out = out[out['content'].str.len() > 0]
    unknown = set(out['label']) - set(LABEL_MAP_EN_TO_ZH)
    if unknown:
        raise ValueError(f'未知英文标签: {unknown}')
    out['label'] = out['label'].map(LABEL_MAP_EN_TO_ZH)
    out['label_id'] = out['label'].map(LABEL2ID).astype('int64')
    return out[['content', 'label', 'label_id']].reset_index(drop=True)


def report_label_conflicts(name: str, df: pd.DataFrame) -> None:
    """统计同 content 不同 label 的样本数。

    冲突策略：当前用 dedupe_within 的 keep='first' 保留首次出现的标签。
    冲突可能来自标注者分歧或同文本不同语境下的不同标签，数量不大时影响有限；
    若后续追求训练质量，可改成丢弃冲突样本（drop_duplicates(keep=False)）。
    """
    grouped = df.groupby('content')['label'].nunique()
    conflicting_contents = grouped[grouped > 1]
    if len(conflicting_contents) == 0:
        return
    affected_rows = df[df['content'].isin(conflicting_contents.index)]
    print(f'  ⚠ {name}: 发现 {len(conflicting_contents)} 个 content 有冲突标签，'
          f'共 {len(affected_rows)} 行（保留首次出现的标签）')


def dedupe_within(df: pd.DataFrame) -> tuple[pd.DataFrame, int]:
    before = len(df)
    df = df.drop_duplicates(subset=['content'], keep='first').reset_index(drop=True)
    return df, before - len(df)


def remove_leakage(train: pd.DataFrame, others: list[pd.DataFrame]) -> tuple[pd.DataFrame, int]:
    """从 train 删除 content 与任一 other 重叠的样本。"""
    leaked = set()
    for o in others:
        leaked.update(o['content'].tolist())
    before = len(train)
    train = train[~train['content'].isin(leaked)].reset_index(drop=True)
    return train, before - len(train)


def process_track(track: str, raw_root: Path, out_root: Path) -> None:
    files = labeled_files(raw_root)
    splits = {sp: load_raw(files[(track, sp)]) for sp in ('train', 'eval', 'test')}
    cleaned = {sp: clean_frame(df) for sp, df in splits.items()}

    print(f'\n=== {track} ===')
    for sp, df in cleaned.items():
        raw_n = len(splits[sp])
        kept = len(df)
        print(f'  {sp}: raw={raw_n}, after_clean={kept}, dropped={raw_n - kept}')

    for sp, df in cleaned.items():
        report_label_conflicts(f'{track}_{sp}', df)

    cleaned['eval'], dup_e = dedupe_within(cleaned['eval'])
    cleaned['test'], dup_t = dedupe_within(cleaned['test'])
    cleaned['train'], dup_tr = dedupe_within(cleaned['train'])
    print(f'  内部去重: train={dup_tr}, eval={dup_e}, test={dup_t}')

    cleaned['train'], leak = remove_leakage(
        cleaned['train'], [cleaned['eval'], cleaned['test']]
    )
    print(f'  train 去 eval/test 泄露: 删除 {leak} 条')

    out_root.mkdir(parents=True, exist_ok=True)
    for sp, df in cleaned.items():
        out_path = out_root / f'{track}_{sp}.parquet'
        df.to_parquet(out_path, index=False)
        print(f'  写出 {out_path.name}: {len(df)} 条')


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--raw-root', type=Path, default=DEFAULT_RAW_ROOT,
                        help=f'原始数据根目录，默认 {DEFAULT_RAW_ROOT}')
    parser.add_argument('--out-root', type=Path, default=DEFAULT_OUT_ROOT,
                        help=f'输出 parquet 目录，默认 {DEFAULT_OUT_ROOT}')
    args = parser.parse_args()

    for track in ('usual', 'virus'):
        process_track(track, args.raw_root, args.out_root)
    print(f'\n全部完成，输出目录: {args.out_root}')


if __name__ == '__main__':
    main()
