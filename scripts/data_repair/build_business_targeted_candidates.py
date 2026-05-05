"""构建第二轮业务定向补强候选集。

从离线业务 posts/comments 中按关键词召回恐惧、惊讶、愤怒/悲伤边界和
中性/积极 hard negative，再用当前 mixed 模型打分排序，输出给
llm_label_candidates.py 使用的候选 parquet。
"""

from __future__ import annotations

import argparse
import math
import re
import sys
from pathlib import Path
from typing import Iterable

import pandas as pd
import torch
from transformers import AutoModelForSequenceClassification, AutoTokenizer

SCRIPTS_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPTS_DIR))
from dataset_paths import ROOT  # noqa: E402
from preprocess import clean_text  # noqa: E402
from npo.config import DEFAULT_MAX_LENGTH, LABEL2ID, LABELS_ZH  # noqa: E402
from npo.device import get_device  # noqa: E402

DEFAULT_POSTS = ROOT / 'data' / 'business' / 'posts.parquet'
DEFAULT_COMMENTS = ROOT / 'data' / 'business' / 'comments.parquet'
DEFAULT_CHECKPOINT = ROOT / 'runs' / 'ernie-usual-mixed' / 'best'
DEFAULT_OUT = ROOT / 'data' / 'annotation' / 'business_targeted_candidates.parquet'
DEFAULT_PROCESSED_ROOT = ROOT / 'data' / 'processed'
DEFAULT_ANNOTATION_ROOT = ROOT / 'data' / 'annotation'

BUCKET_ORDER = ('fear', 'surprise', 'anger_sad_boundary', 'hard_negative')
BUCKET_LABELS = {
    'fear': ('恐惧',),
    'surprise': ('惊讶',),
    'anger_sad_boundary': ('愤怒', '悲伤'),
    'hard_negative': ('积极', '中性'),
}
BASE_QUOTAS = {
    'fear': 2200,
    'surprise': 1800,
    'anger_sad_boundary': 2500,
    'hard_negative': 1000,
}

KEYWORDS = {
    'fear': (
        '安全风险', '安全隐患', '风险', '事故', '出事', '诈骗', '被骗', '骗钱', '危险', '危急',
        '担心', '害怕', '可怕', '怕了', '吓人', '吓死', '吓坏', '恐慌', '惊恐', '焦虑',
        '不敢', '求助', '报警', '失联', '坠落', '爆炸', '起火', '火灾', '中毒',
        '感染', '传染', '过敏', '后怕', '恐怖', '威胁', '避雷', '踩雷', '黑心',
    ),
    'surprise': (
        '震惊', '惊呆', '惊了', '没想到', '想不到', '居然', '竟然', '真的假的', '真假的',
        '离谱', '离大谱', '反转', '突然', '突发', '猝不及防', '不可思议', '匪夷所思',
        '刷新认知', '破防了', '意外', '惊喜', '惊讶', '震撼', '好家伙', '万万没想到',
    ),
    'anger_sad_boundary': (
        '失望', '心寒', '寒心', '心疼', '难受', '难过', '委屈', '憋屈', '无语', '气死',
        '气炸', '凭什么', '太过分', '过分', '恶心', '离谱', '服了', '受不了', '忍不了',
        '欺负', '坑人', '坑了', '骗了', '不公平', '不公', '投诉', '维权', '退钱', '赔偿',
        '无奈', '遗憾', '累了', '心累', '崩溃', '泪目', '破防', '烦死', '糟心',
    ),
}
OBJECTIVE_CUES = (
    '公告', '通报', '通知', '提醒', '预警', '辟谣', '声明', '回应', '发布', '公布',
    '报告', '数据显示', '据悉', '记者', '官方', '警方', '消防', '医院', '法院',
    '市场监管', '召回', '处罚', '立案', '调查', '提示', '科普', '指南',
)
EMOTION_HOT_TERMS = (
    '开心', '快乐', '喜欢', '惊喜', '震惊', '离谱', '可怕', '担心', '害怕', '焦虑',
    '愤怒', '生气', '心疼', '难过', '失望', '无语', '气死', '破防', '崩溃',
)
SARCASTIC_POSITIVE_TERMS = (
    '真棒', '太棒了', '可真行', '真有你的', '谢谢你啊', '谢谢您', '笑死', '赢麻了',
    '绝了', '服了', '好家伙', '厉害了', '太会了', '真不错啊', '可太好了',
)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument('--posts', type=Path, default=DEFAULT_POSTS)
    p.add_argument('--comments', type=Path, default=DEFAULT_COMMENTS)
    p.add_argument('--checkpoint', type=Path, default=DEFAULT_CHECKPOINT)
    p.add_argument('--out', type=Path, default=DEFAULT_OUT)
    p.add_argument('--processed-root', type=Path, default=DEFAULT_PROCESSED_ROOT)
    p.add_argument('--annotation-root', type=Path, default=DEFAULT_ANNOTATION_ROOT)
    p.add_argument('--track', choices=['usual', 'virus'], default='usual')
    p.add_argument('--target-size', type=int, default=7500)
    p.add_argument('--pre-score-max', type=int, default=50000,
                   help='关键词召回后最多送入模型打分的样本数')
    p.add_argument('--min-chars', type=int, default=4)
    p.add_argument('--max-chars', type=int, default=512)
    p.add_argument('--max-length', type=int, default=None)
    p.add_argument('--batch-size', type=int, default=64)
    p.add_argument('--seed', type=int, default=42)
    p.add_argument('--include-previous-candidates', action='store_true',
                   help='默认排除已存在业务候选/LLM 标注内容，避免重复标注')
    p.add_argument('--no-model-score', action='store_true',
                   help='只按关键词启发式排序；调试用')
    return p.parse_args()


def compile_pattern(words: Iterable[str]) -> re.Pattern[str]:
    return re.compile('|'.join(re.escape(w) for w in sorted(set(words), key=len, reverse=True)))


PATTERNS = {name: compile_pattern(words) for name, words in KEYWORDS.items()}
OBJECTIVE_PATTERN = compile_pattern(OBJECTIVE_CUES)
EMOTION_HOT_PATTERN = compile_pattern(EMOTION_HOT_TERMS)
SARCASM_PATTERN = compile_pattern(SARCASTIC_POSITIVE_TERMS)
_NEAR_DEDUPE_RE = re.compile(r'[\W_]+', flags=re.UNICODE)


def read_business(path: Path, source: str, id_column: str, min_chars: int, max_chars: int) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(f'缺少业务数据: {path}')
    df = pd.read_parquet(path)
    missing = [c for c in (id_column, 'text_raw') if c not in df.columns]
    if missing:
        raise ValueError(f'{path} 缺少列: {missing}; 实际列: {list(df.columns)}')

    keep_cols = [id_column, 'text_raw']
    for optional in ('post_id', 'created_at', 'like_count', 'region_name', 'has_images', 'has_video'):
        if optional in df.columns and optional not in keep_cols:
            keep_cols.append(optional)

    out = df[keep_cols].dropna(subset=['text_raw']).copy()
    out['source'] = source
    out['source_id'] = out[id_column].astype(str)
    out['raw_text'] = out['text_raw'].astype(str)
    out['content'] = out['raw_text'].map(clean_text)
    out = out[out['content'].str.len().between(min_chars, max_chars)]
    return out.drop(columns=['text_raw', id_column], errors='ignore').reset_index(drop=True)


def read_contents(path: Path) -> set[str]:
    if not path.exists():
        return set()
    try:
        if path.suffix == '.parquet':
            df = pd.read_parquet(path)
        elif path.suffix == '.csv':
            df = pd.read_csv(path)
        elif path.suffix in ('.jsonl', '.ndjson'):
            df = pd.read_json(path, lines=True)
        else:
            return set()
    except Exception as exc:  # noqa: BLE001 - 排除文件损坏不应阻塞主流程
        print(f'跳过排除文件 {path}: {exc}')
        return set()

    values: set[str] = set()
    for col in ('content', 'text'):
        if col in df.columns:
            values.update(df[col].dropna().astype(str).tolist())
    return values


def load_excluded_contents(args: argparse.Namespace) -> set[str]:
    paths = [
        args.processed_root / f'{args.track}_eval.parquet',
        args.processed_root / f'{args.track}_test.parquet',
        args.processed_root / f'{args.track}_business_eval.parquet',
        args.processed_root / f'{args.track}_business_train_pool.parquet',
    ]
    if not args.include_previous_candidates:
        paths.extend([
            args.annotation_root / 'business_label_candidates.parquet',
            args.annotation_root / 'business_comment_candidates.parquet',
            args.annotation_root / 'business_post_candidates.parquet',
            args.annotation_root / 'business_llm_labels.jsonl',
            args.annotation_root / 'business_pro_labels.jsonl',
            args.annotation_root / 'business_adjudicated.jsonl',
        ])
    excluded: set[str] = set()
    for path in paths:
        excluded.update(read_contents(path))
    return excluded


def keyword_hits(text: str) -> tuple[list[str], dict[str, list[str]]]:
    hits: dict[str, list[str]] = {}
    for bucket, pattern in PATTERNS.items():
        found = sorted(set(pattern.findall(text)), key=lambda x: (len(x), x), reverse=True)
        if found:
            hits[bucket] = found

    objective = bool(OBJECTIVE_PATTERN.search(text))
    emotion = sorted(set(EMOTION_HOT_PATTERN.findall(text)), key=lambda x: (len(x), x), reverse=True)
    sarcasm = sorted(set(SARCASM_PATTERN.findall(text)), key=lambda x: (len(x), x), reverse=True)
    if (objective and emotion) or sarcasm:
        hard_hits = []
        if objective:
            hard_hits.append('objective_cue')
        hard_hits.extend(emotion[:4])
        hard_hits.extend(sarcasm[:4])
        hits['hard_negative'] = sorted(set(hard_hits), key=lambda x: (len(x), x), reverse=True)

    buckets = [bucket for bucket in BUCKET_ORDER if bucket in hits]
    return buckets, hits


def add_keyword_features(df: pd.DataFrame) -> pd.DataFrame:
    rows = [keyword_hits(text) for text in df['content'].tolist()]
    out = df.copy()
    out['target_buckets'] = [','.join(buckets) for buckets, _ in rows]
    out['target_bucket'] = [buckets[0] if buckets else '' for buckets, _ in rows]
    out['matched_keywords'] = [
        ';'.join(f'{bucket}:{"|".join(words[:8])}' for bucket, words in hits.items())
        for _, hits in rows
    ]
    out['keyword_count'] = [sum(len(words) for words in hits.values()) for _, hits in rows]
    return out[out['target_bucket'] != ''].reset_index(drop=True)


def near_dedupe_key(text: str) -> str:
    compact = _NEAR_DEDUPE_RE.sub('', text)
    return compact[:160]


def heuristic_score(row: pd.Series) -> float:
    bucket_base = {
        'fear': 120,
        'surprise': 105,
        'anger_sad_boundary': 95,
        'hard_negative': 75,
    }[row['target_bucket']]
    length = len(row['content'])
    length_bonus = 16 if 12 <= length <= 180 else 8 if 6 <= length <= 260 else 0
    source_bonus = 4 if row['source'].endswith('comment') else 0
    keyword_bonus = min(int(row['keyword_count']), 6) * 4
    return bucket_base + length_bonus + source_bonus + keyword_bonus


def quota_for(target_size: int) -> dict[str, int]:
    base_total = sum(BASE_QUOTAS.values())
    quotas = {bucket: max(1, math.floor(target_size * count / base_total))
              for bucket, count in BASE_QUOTAS.items()}
    while sum(quotas.values()) < target_size:
        for bucket in BUCKET_ORDER:
            quotas[bucket] += 1
            if sum(quotas.values()) == target_size:
                break
    while sum(quotas.values()) > target_size:
        for bucket in reversed(BUCKET_ORDER):
            if quotas[bucket] > 1:
                quotas[bucket] -= 1
            if sum(quotas.values()) == target_size:
                break
    return quotas


def cap_before_scoring(df: pd.DataFrame, pre_score_max: int, target_size: int, seed: int) -> pd.DataFrame:
    if len(df) <= pre_score_max:
        return df.sort_values(['heuristic_score', 'source_id'], ascending=[False, True]).reset_index(drop=True)

    quotas = quota_for(pre_score_max)
    selected_parts = []
    selected_index: set[int] = set()
    for bucket in BUCKET_ORDER:
        part = df[df['target_bucket'] == bucket].sort_values(
            ['heuristic_score', 'source_id'], ascending=[False, True]
        )
        if not part.empty:
            take = min(len(part), quotas[bucket])
            chosen = part.head(take)
            selected_parts.append(chosen)
            selected_index.update(chosen.index.tolist())

    selected = pd.concat(selected_parts, ignore_index=False) if selected_parts else df.iloc[0:0]
    if len(selected) < pre_score_max:
        fill = df[~df.index.isin(selected_index)].sort_values(
            ['heuristic_score', 'source_id'], ascending=[False, True]
        ).head(pre_score_max - len(selected))
        selected = pd.concat([selected, fill], ignore_index=False)

    selected = selected.sample(frac=1, random_state=seed).reset_index(drop=True)
    # 至少保留目标量的数倍供模型 margin 筛选；异常参数下给出明确失败。
    if len(selected) < min(target_size, pre_score_max):
        raise SystemExit(f'关键词召回不足: {len(selected)} 条，低于目标 {target_size}')
    return selected


def add_model_scores(df: pd.DataFrame, checkpoint: Path, max_length: int, batch_size: int) -> pd.DataFrame:
    if not checkpoint.exists():
        raise FileNotFoundError(f'checkpoint 不存在: {checkpoint}')
    device = get_device()
    print(f'加载打分模型: {checkpoint} device={device} max_length={max_length}')
    tokenizer = AutoTokenizer.from_pretrained(checkpoint)
    model = AutoModelForSequenceClassification.from_pretrained(checkpoint).to(device)
    model.eval()

    top1_idx: list[int] = []
    top2_idx: list[int] = []
    top1_prob: list[float] = []
    top2_prob: list[float] = []
    target_max_prob: list[float] = []
    texts = df['content'].tolist()
    target_ids = [tuple(LABEL2ID[label] for label in BUCKET_LABELS[bucket]) for bucket in df['target_bucket']]

    with torch.inference_mode():
        for start in range(0, len(texts), batch_size):
            batch_texts = texts[start:start + batch_size]
            enc = tokenizer(
                batch_texts,
                max_length=max_length,
                padding=True,
                truncation=True,
                return_tensors='pt',
            ).to(device)
            probs = torch.softmax(model(**enc).logits, dim=-1)
            top = torch.topk(probs, k=2, dim=-1)
            top1_idx.extend(top.indices[:, 0].cpu().tolist())
            top2_idx.extend(top.indices[:, 1].cpu().tolist())
            top1_prob.extend(top.values[:, 0].cpu().tolist())
            top2_prob.extend(top.values[:, 1].cpu().tolist())

            for offset, ids in enumerate(target_ids[start:start + batch_size]):
                target_max_prob.append(float(probs[offset, list(ids)].max().cpu()))
            done = min(start + batch_size, len(texts))
            if done % 5000 == 0 or done == len(texts):
                print(f'模型打分进度: {done}/{len(texts)}')

    out = df.copy()
    out['model_pred'] = [LABELS_ZH[i] for i in top1_idx]
    out['model_top1_prob'] = top1_prob
    out['model_top2_label'] = [LABELS_ZH[i] for i in top2_idx]
    out['model_top2_prob'] = top2_prob
    out['model_margin'] = out['model_top1_prob'] - out['model_top2_prob']
    out['target_max_prob'] = target_max_prob
    out['model_target_match'] = [
        pred in BUCKET_LABELS[bucket]
        for pred, bucket in zip(out['model_pred'], out['target_bucket'])
    ]
    return out


def add_fallback_scores(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out['model_pred'] = ''
    out['model_top1_prob'] = 0.0
    out['model_top2_label'] = ''
    out['model_top2_prob'] = 0.0
    out['model_margin'] = 1.0
    out['target_max_prob'] = 0.0
    out['model_target_match'] = False
    return out


def add_selection_scores(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    low_margin = (1 - out['model_margin'].clip(0, 1)).astype(float)
    low_conf = (1 - out['model_top1_prob'].clip(0, 1)).astype(float)
    target_uncertain = (1 - out['target_max_prob'].clip(0, 1)).astype(float)
    mismatch = (~out['model_target_match'].astype(bool)).astype(int)
    pred_rare_uncertain = (
        out['model_pred'].isin(['恐惧', '惊讶'])
        & (out['model_top1_prob'].astype(float) < 0.85)
    ).astype(int)
    bucket_base = out['target_bucket'].map({
        'fear': 110,
        'surprise': 98,
        'anger_sad_boundary': 88,
        'hard_negative': 68,
    }).astype(float)
    out['selection_score'] = (
        bucket_base
        + low_margin * 45
        + low_conf * 25
        + target_uncertain * 18
        + mismatch * 22
        + pred_rare_uncertain * 20
        + out['keyword_count'].clip(0, 8).astype(float) * 3
    )
    out['priority'] = out['selection_score'].round().astype(int)
    flags = []
    for row in out.itertuples(index=False):
        row_flags = []
        if row.model_margin <= 0.20:
            row_flags.append('low_margin')
        if row.model_top1_prob <= 0.70:
            row_flags.append('low_conf')
        if not row.model_target_match:
            row_flags.append('keyword_model_mismatch')
        if row.model_pred in ('恐惧', '惊讶') and row.model_top1_prob < 0.85:
            row_flags.append('rare_pred_uncertain')
        flags.append(','.join(row_flags) or 'keyword_targeted')
    out['selection_flags'] = flags
    return out


def select_final(df: pd.DataFrame, target_size: int) -> pd.DataFrame:
    if len(df) < target_size:
        raise SystemExit(f'候选不足: {len(df)} 条，低于目标 {target_size}')
    quotas = quota_for(target_size)
    selected_parts = []
    selected_index: set[int] = set()
    for bucket in BUCKET_ORDER:
        part = df[df['target_bucket'] == bucket].sort_values(
            ['selection_score', 'model_margin', 'source_id'],
            ascending=[False, True, True],
        )
        chosen = part.head(quotas[bucket])
        selected_parts.append(chosen)
        selected_index.update(chosen.index.tolist())

    selected = pd.concat(selected_parts, ignore_index=False)
    if len(selected) < target_size:
        fill = df[~df.index.isin(selected_index)].sort_values(
            ['selection_score', 'model_margin', 'source_id'],
            ascending=[False, True, True],
        ).head(target_size - len(selected))
        selected = pd.concat([selected, fill], ignore_index=False)

    selected = selected.sort_values(
        ['selection_score', 'model_margin', 'source_id'], ascending=[False, True, True]
    ).head(target_size).reset_index(drop=True)
    selected['candidate_rank'] = range(1, len(selected) + 1)
    selected['sample_id'] = [f'business-targeted-{i:07d}' for i in selected['candidate_rank']]
    selected['candidate_reason'] = selected.apply(
        lambda row: (
            'business_targeted_round2;'
            f'bucket={row.target_bucket};flags={row.selection_flags};'
            f'keywords={row.matched_keywords};'
            f'model={row.model_pred}/{row.model_top1_prob:.3f};'
            f'top2={row.model_top2_label}/{row.model_top2_prob:.3f};'
            f'margin={row.model_margin:.3f}'
        ),
        axis=1,
    )
    selected['source'] = selected['source'].map(lambda x: f'business_targeted_{x}')
    return selected


def make_parquet_safe(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    for col in out.columns:
        if out[col].dtype == 'object':
            out[col] = out[col].map(lambda x: None if pd.isna(x) else str(x))
    return out


def main() -> None:
    args = parse_args()
    if not 6000 <= args.target_size <= 8000:
        raise SystemExit('--target-size 应保持在 6000-8000，符合本轮候选规模目标')
    if args.pre_score_max < args.target_size:
        raise SystemExit('--pre-score-max 不能小于 --target-size')

    print('读取并清洗业务数据...')
    posts = read_business(args.posts, 'post', 'post_id', args.min_chars, args.max_chars)
    comments = read_business(args.comments, 'comment', 'comment_id', args.min_chars, args.max_chars)
    df = pd.concat([posts, comments], ignore_index=True)
    before_dedupe = len(df)
    df = df.drop_duplicates(subset=['content'], keep='first').reset_index(drop=True)
    print(f'清洗后: {before_dedupe} 条，按 content 去重后: {len(df)} 条')

    excluded = load_excluded_contents(args)
    before_exclude = len(df)
    if excluded:
        df = df[~df['content'].isin(excluded)].reset_index(drop=True)
    print(f'排除 eval/test/既有业务池/既有候选: {before_exclude - len(df)} 条，剩余 {len(df)} 条')

    print('按定向关键词召回...')
    candidates = add_keyword_features(df)
    before_near_dedupe = len(candidates)
    candidates['near_dedupe_key'] = candidates['content'].map(near_dedupe_key)
    candidates = candidates.drop_duplicates(subset=['near_dedupe_key'], keep='first').reset_index(drop=True)
    candidates['heuristic_score'] = candidates.apply(heuristic_score, axis=1)
    print(f'关键词召回: {before_near_dedupe} 条，近重复去重后: {len(candidates)} 条')
    print(candidates['target_bucket'].value_counts().reindex(BUCKET_ORDER, fill_value=0).to_string())

    candidates = cap_before_scoring(candidates, args.pre_score_max, args.target_size, args.seed)
    print(f'送入模型打分: {len(candidates)} 条')

    if args.no_model_score:
        scored = add_fallback_scores(candidates)
    else:
        max_length = args.max_length or DEFAULT_MAX_LENGTH[args.track]
        scored = add_model_scores(candidates, args.checkpoint, max_length, args.batch_size)

    scored = add_selection_scores(scored)
    selected = select_final(scored, args.target_size)

    columns = [
        'sample_id', 'source', 'source_id', 'content', 'raw_text', 'candidate_reason',
        'priority', 'candidate_rank', 'target_bucket', 'target_buckets', 'matched_keywords',
        'selection_flags', 'selection_score', 'model_pred', 'model_top1_prob',
        'model_top2_label', 'model_top2_prob', 'model_margin', 'target_max_prob',
        'model_target_match', 'post_id', 'created_at', 'like_count', 'region_name',
        'has_images', 'has_video',
    ]
    selected = selected[[c for c in columns if c in selected.columns]]
    args.out.parent.mkdir(parents=True, exist_ok=True)
    make_parquet_safe(selected).to_parquet(args.out, index=False)

    print(f'写出 {args.out}: {len(selected)} 条')
    print('目标桶分布:')
    print(selected['target_bucket'].value_counts().reindex(BUCKET_ORDER, fill_value=0).to_string())
    print('模型预测分布:')
    print(selected['model_pred'].value_counts().reindex(LABELS_ZH, fill_value=0).to_string())
    print('选择标记 Top:')
    print(selected['selection_flags'].value_counts().head(12).to_string())


if __name__ == '__main__':
    main()
