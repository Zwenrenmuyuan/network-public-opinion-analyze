"""Dashboard 业务情绪推理：CK 拉文本 → ERNIE 推理 → 写回 CK。

流程：
  1. 加载 ERNIE checkpoint
  2. 查 dashboard.sentiment_prediction 当前 model_version 已有的 (source_type, source_id) → 跳过集
  3. 按 source_type=post 然后 comment：
       流式 SELECT weibo.{source_type}（按主键 ORDER）
       → 已存在的跳过
       → clean_text 清洗 → 空文本丢弃 → blake2b(8) 算 content_hash
       → 攒满 model_batch (默认 64) GPU 推一次
       → 攒满 write_batch (默认 5000) INSERT 一次

ReplacingMergeTree(predicted_at) 容错：即使重复写同样的
(model_version, source_type, source_id) 也只保留最新；--no-resume 强行重跑也无害。

用法：
  uv run python scripts/dashboard/predict_business_emotions.py --limit 100 --dry-run
  uv run python scripts/dashboard/predict_business_emotions.py --source post
  uv run python scripts/dashboard/predict_business_emotions.py
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import re
import sys
import time
from collections.abc import Iterator
from pathlib import Path

import torch
from transformers import AutoModelForSequenceClassification, AutoTokenizer

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / 'dashboard'))
sys.path.insert(0, str(ROOT / 'scripts'))

from ck import CKClient  # noqa: E402
from preprocess import clean_text  # noqa: E402

from npo.config import DEFAULT_MAX_LENGTH, ID2LABEL  # noqa: E402
from npo.device import get_device, select_amp_dtype  # noqa: E402

DEFAULT_CHECKPOINT = ROOT / 'runs' / 'ernie-usual-mixed-v2' / 'best'
DEFAULT_MODEL_KEY = 'ernie'
TARGET_TABLE = 'dashboard.sentiment_prediction'

# 与 LABELS_ZH 顺序对齐：LABELS_ZH = ('积极','愤怒','悲伤','恐惧','惊讶','中性')
PROB_COLS = (
    'prob_positive', 'prob_angry', 'prob_sad',
    'prob_fear', 'prob_surprise', 'prob_neutral',
)

VERSION_RE = re.compile(r'^[A-Za-z0-9_.\-]+$')

logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s | %(message)s',
                    datefmt='%H:%M:%S')
logger = logging.getLogger(__name__)


# -------- args --------

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument('--checkpoint', type=Path, default=DEFAULT_CHECKPOINT,
                   help=f'HF checkpoint 目录，默认 {DEFAULT_CHECKPOINT.relative_to(ROOT)}')
    p.add_argument('--model-key', default=DEFAULT_MODEL_KEY,
                   help='写入 model_key 列；默认 ernie')
    p.add_argument('--model-version', default=None,
                   help='写入 model_version 列；默认从 checkpoint 父目录名推断（如 ernie-usual-mixed-v2）')
    p.add_argument('--source', choices=['post', 'comment', 'both'], default='both')
    p.add_argument('--max-length', type=int, default=DEFAULT_MAX_LENGTH['usual'],
                   help=f'tokenizer 截断；默认 {DEFAULT_MAX_LENGTH["usual"]}（与训练一致）')
    p.add_argument('--model-batch', type=int, default=64,
                   help='GPU 推理 batch；3060 6G 建议 64-128，MPS 建议 32-64')
    p.add_argument('--write-batch', type=int, default=5000,
                   help='攒满多少行 INSERT 一次到 CK')
    p.add_argument('--limit', type=int, default=None,
                   help='每个 source_type 只取前 N 行（小量验证用）')
    p.add_argument('--dry-run', action='store_true',
                   help='不写 CK；走完整流程并打印前 3 行预测样例')
    p.add_argument('--no-resume', action='store_true',
                   help='不查已有预测，全量推；ReplacingMergeTree 自动去重')
    return p.parse_args()


# -------- helpers --------

def content_hash_uint64(text: str) -> int:
    """blake2b 8 字节 → UInt64。稳定、跨进程一致、不依赖 PYTHONHASHSEED。"""
    return int.from_bytes(hashlib.blake2b(text.encode('utf-8'), digest_size=8).digest(), 'big')


def infer_model_version(checkpoint: Path) -> str:
    return checkpoint.parent.name


def load_existing_ids(ck: CKClient, model_version: str,
                      source_types: list[str]) -> dict[str, set[int]]:
    """查指定 model_version 下已经预测过的 (source_type, source_id)。"""
    rows = ck.query_json(f"""
        SELECT source_type, source_id
        FROM {TARGET_TABLE}
        WHERE model_version = '{model_version}'
    """)
    out: dict[str, set[int]] = {st: set() for st in source_types}
    for r in rows:
        st = r['source_type']
        if st in out:
            out[st].add(int(r['source_id']))
    return out


# -------- inference --------

@torch.inference_mode()
def predict_batch(model, tokenizer, contents: list[str], device: torch.device,
                  max_length: int, amp_dtype: torch.dtype | None):
    """返回 (top1_idx, top2_idx, top1_prob, top2_prob, full_probs)，全 numpy。"""
    enc = tokenizer(contents, max_length=max_length, padding='max_length',
                    truncation=True, return_tensors='pt').to(device)
    if amp_dtype is not None:
        with torch.autocast(device_type=device.type, dtype=amp_dtype):
            logits = model(**enc).logits
        logits = logits.float()
    else:
        logits = model(**enc).logits
    probs = torch.softmax(logits, dim=-1)             # (B, 6)
    top2 = torch.topk(probs, k=2, dim=-1)             # values/indices (B, 2)
    return (
        top2.indices[:, 0].cpu().numpy(),
        top2.indices[:, 1].cpu().numpy(),
        top2.values[:, 0].cpu().numpy(),
        top2.values[:, 1].cpu().numpy(),
        probs.cpu().numpy(),
    )


# -------- pipeline --------

def stream_source(ck: CKClient, source_type: str, limit: int | None) -> Iterator[dict]:
    """流式拉 weibo.post / weibo.comment 的推理需要列。

    ORDER BY 主键保证断点续推时拉取顺序稳定；CK 主键就是 post_id/comment_id，
    所以 ORDER BY 走索引顺序，无额外排序成本。
    created_at 已经是 UTC 存储的 DateTime，toString 直接给 'YYYY-MM-DD HH:MM:SS'。
    """
    pk = 'post_id' if source_type == 'post' else 'comment_id'
    sql = f"""
        SELECT {pk} AS source_id,
               post_id,
               toString(created_at) AS source_created_at,
               text_raw
        FROM weibo.{source_type}
        ORDER BY {pk}
    """
    if limit:
        sql += f' LIMIT {limit}'
    return ck.stream_json(sql)


def make_row(meta: dict, src: dict, content_hash: int,
             top1: int, top2: int, conf: float, sec_prob: float, probs) -> dict:
    pred_label = ID2LABEL[int(top1)]
    second_label = ID2LABEL[int(top2)]
    row = {
        'source_type':       meta['source_type'],
        'source_id':         int(src['source_id']),
        'post_id':           int(src['post_id']),
        'source_created_at': src['source_created_at'],
        'content_hash':      content_hash,
        'model_key':         meta['model_key'],
        'model_version':     meta['model_version'],
        'checkpoint':        meta['checkpoint'],
        'pred_label':        pred_label,
        'pred_label_id':     int(top1),
        'confidence':        float(conf),
        'second_label':      second_label,
        'second_label_id':   int(top2),
        'second_prob':       float(sec_prob),
        'margin':            float(conf - sec_prob),
        # predicted_at 让 CK 用 DEFAULT now() 自填
    }
    for col, p in zip(PROB_COLS, probs):
        row[col] = float(p)
    return row


def run_one_source(args, ck: CKClient, model, tokenizer, device, amp_dtype,
                   source_type: str, meta: dict, existing_ids: set[int]) -> None:
    counters = {'pulled': 0, 'skipped_existing': 0, 'skipped_empty': 0,
                'predicted': 0, 'written': 0}
    model_buf_contents: list[str] = []
    model_buf_meta: list[tuple[dict, int]] = []   # (src_row, content_hash)
    write_buf: list[dict] = []
    sample_logged = [False]

    def flush_model():
        if not model_buf_contents:
            return
        top1, top2, conf, sec_prob, probs = predict_batch(
            model, tokenizer, model_buf_contents, device, args.max_length, amp_dtype,
        )
        for i, (src, h) in enumerate(model_buf_meta):
            row = make_row(meta, src, h,
                           top1[i], top2[i], conf[i], sec_prob[i], probs[i])
            write_buf.append(row)
        counters['predicted'] += len(model_buf_contents)
        model_buf_contents.clear()
        model_buf_meta.clear()

    def flush_write(force: bool = False):
        if not write_buf:
            return
        if not force and len(write_buf) < args.write_batch:
            return
        if args.dry_run:
            if not sample_logged[0]:
                logger.info('[dry-run] 样例前 3 行：')
                for r in write_buf[:3]:
                    logger.info('  ' + json.dumps(r, ensure_ascii=False))
                sample_logged[0] = True
        else:
            ck.insert_jsoneachrow(TARGET_TABLE, write_buf)
        counters['written'] += len(write_buf)
        write_buf.clear()

    t_start = time.time()
    for src in stream_source(ck, source_type, args.limit):
        counters['pulled'] += 1
        sid = int(src['source_id'])
        if sid in existing_ids:
            counters['skipped_existing'] += 1
            continue
        content = clean_text(src['text_raw'])
        if not content:
            counters['skipped_empty'] += 1
            continue
        h = content_hash_uint64(content)
        model_buf_contents.append(content)
        model_buf_meta.append((src, h))

        if len(model_buf_contents) >= args.model_batch:
            flush_model()
            flush_write()

        if counters['pulled'] % 50000 == 0:
            logger.info(f'  ... pulled={counters["pulled"]:,} '
                        f'skipped={counters["skipped_existing"] + counters["skipped_empty"]:,} '
                        f'predicted={counters["predicted"]:,} written={counters["written"]:,}')

    flush_model()
    flush_write(force=True)

    elapsed = time.time() - t_start
    rate = counters['predicted'] / elapsed if elapsed > 0 else 0
    logger.info(
        f'  完成 {source_type}：拉 {counters["pulled"]:,} | '
        f'跳过已存在 {counters["skipped_existing"]:,} | '
        f'清洗丢弃 {counters["skipped_empty"]:,} | '
        f'推理 {counters["predicted"]:,} | '
        f'写入 {counters["written"]:,} | '
        f'用时 {elapsed:.1f}s ({rate:.1f} rows/s)'
    )


def main() -> None:
    args = parse_args()
    if not args.checkpoint.exists():
        raise FileNotFoundError(f'checkpoint 不存在: {args.checkpoint}')

    model_version = args.model_version or infer_model_version(args.checkpoint)
    if not VERSION_RE.fullmatch(model_version):
        raise ValueError(f'非法 model_version (只允许字母数字 _ - .): {model_version!r}')

    device = get_device()
    amp_dtype = select_amp_dtype(device, 'auto')
    logger.info(f'device={device} amp={amp_dtype}')
    logger.info(f'加载 checkpoint: {args.checkpoint}')
    tokenizer = AutoTokenizer.from_pretrained(args.checkpoint)
    model = (AutoModelForSequenceClassification
             .from_pretrained(args.checkpoint).to(device).eval())

    ck = CKClient()
    logger.info(f'CK: {ck.host}:{ck.port}  →  {TARGET_TABLE}')
    logger.info(f'model_version={model_version} model_key={args.model_key} '
                f'max_length={args.max_length} model_batch={args.model_batch} '
                f'write_batch={args.write_batch} dry_run={args.dry_run}')

    sources = ['post', 'comment'] if args.source == 'both' else [args.source]
    if not args.no_resume:
        logger.info(f'查已有预测 (model_version={model_version}) ...')
        existing = load_existing_ids(ck, model_version, sources)
        for st in sources:
            logger.info(f'  {st}: {len(existing[st]):,} 条已存在 → 跳过')
    else:
        existing = {st: set() for st in sources}

    meta_base = {
        'model_key':     args.model_key,
        'model_version': model_version,
        'checkpoint':    str(args.checkpoint.relative_to(ROOT)),
    }

    for source_type in sources:
        logger.info(f'\n=== 推理 {source_type} ===')
        meta = {**meta_base, 'source_type': source_type}
        run_one_source(args, ck, model, tokenizer, device, amp_dtype,
                       source_type, meta, existing[source_type])


if __name__ == '__main__':
    main()
