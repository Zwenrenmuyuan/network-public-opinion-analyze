"""用 OpenAI-compatible API 异步并发标注候选样本。

输入 parquet/csv/jsonl，至少包含 sample_id 和 content 两列。
输出 JSONL，每行包含原样本信息、LLM 标签、置信度、理由和复核标记。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import random
import re
import sys
from pathlib import Path
from typing import Any

import httpx
import pandas as pd

SCRIPTS_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPTS_DIR))
from dataset_paths import ROOT  # noqa: E402
from npo.config import LABELS_ZH

DEFAULT_GUIDELINE = ROOT / 'docs' / 'labeling-guideline.md'
ALLOWED_LABELS = set(LABELS_ZH)
LABEL_ALIASES = {
    '快乐': '积极',
    '开心': '积极',
    '高兴': '积极',
    '喜悦': '积极',
    '喜欢': '积极',
    '支持': '积极',
    '赞赏': '积极',
    '欣慰': '积极',
    '感动': '积极',
    '生气': '愤怒',
    '气愤': '愤怒',
    '愤慨': '愤怒',
    '不满': '愤怒',
    '抱怨': '愤怒',
    '责备': '愤怒',
    '厌恶': '愤怒',
    '反感': '愤怒',
    '吐槽': '愤怒',
    '失望': '悲伤',
    '难过': '悲伤',
    '伤心': '悲伤',
    '沮丧': '悲伤',
    '遗憾': '悲伤',
    '心疼': '悲伤',
    '委屈': '悲伤',
    '哀伤': '悲伤',
    '害怕': '恐惧',
    '担心': '恐惧',
    '焦虑': '恐惧',
    '忧虑': '恐惧',
    '惊恐': '恐惧',
    '恐慌': '恐惧',
    '紧张': '恐惧',
    '震惊': '惊讶',
    '惊奇': '惊讶',
    '意外': '惊讶',
    '吃惊': '惊讶',
    '惊喜': '惊讶',
    '无': '中性',
    '无明显情感': '中性',
    '客观': '中性',
    '平静': '中性',
    '陈述': '中性',
    '无情绪': '中性',
    '中立': '中性',
}
PASSTHROUGH_COLUMNS = (
    'source_id', 'raw_text', 'post_id', 'created_at', 'like_count',
    'region_name', 'has_images', 'has_video', 'priority', 'candidate_rank',
)


def load_env_file(path: Path) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding='utf-8').splitlines():
        line = raw_line.strip()
        if not line or line.startswith('#'):
            continue
        if line.startswith('export '):
            line = line[len('export '):].strip()
        if '=' not in line:
            continue
        key, value = line.split('=', 1)
        key = key.strip()
        value = value.strip().strip('"\'')
        if key and key not in os.environ:
            os.environ[key] = value


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument('--input', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--errors', type=Path, default=None,
                   help='默认写到 <output>.errors.jsonl')
    p.add_argument('--base-url', default=os.getenv('LLM_BASE_URL'),
                   help='OpenAI-compatible base URL，例如 https://host/v1；也可用 LLM_BASE_URL')
    p.add_argument('--api-key', default=os.getenv('LLM_API_KEY'),
                   help='可选；设置后发送 Authorization: Bearer <key>')
    p.add_argument('--model', default=os.getenv('LLM_MODEL', 'mimo-v2-flash'))
    p.add_argument('--guideline', type=Path, default=DEFAULT_GUIDELINE)
    p.add_argument('--id-column', default='sample_id')
    p.add_argument('--text-column', default='content')
    p.add_argument('--limit', type=int, default=None)
    p.add_argument('--concurrency', type=int, default=8)
    p.add_argument('--temperature', type=float, default=0.0)
    p.add_argument('--max-tokens', type=int, default=300)
    p.add_argument('--timeout', type=float, default=60.0)
    p.add_argument('--max-retries', type=int, default=3)
    p.add_argument('--no-resume', action='store_true',
                   help='默认按 output 里已有 sample_id 断点续跑')
    return p.parse_args()


def load_rows(path: Path) -> list[dict[str, Any]]:
    if path.suffix == '.parquet':
        df = pd.read_parquet(path)
    elif path.suffix == '.csv':
        df = pd.read_csv(path)
    elif path.suffix in ('.jsonl', '.ndjson'):
        records = [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines() if line.strip()]
        df = pd.DataFrame(records)
    else:
        raise ValueError(f'不支持的输入格式: {path.suffix}')
    return df.to_dict(orient='records')


def completed_ids(path: Path) -> set[str]:
    if not path.exists():
        return set()
    done: set[str] = set()
    for line in path.read_text(encoding='utf-8').splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if row.get('sample_id') and row.get('status') == 'ok':
            done.add(str(row['sample_id']))
    return done


def build_system_prompt(guideline_path: Path) -> str:
    guideline = guideline_path.read_text(encoding='utf-8')
    return (
        '你是严格的中文微博舆情六分类情感标注器。'
        '必须遵守标注规范，只返回单个 JSON 对象，不要输出 Markdown。\n\n'
        f'{guideline}'
    )


def build_user_prompt(row: dict[str, Any], text_column: str) -> str:
    context = {
        'sample_id': row.get('sample_id'),
        'source': row.get('source'),
        'track': row.get('track'),
        'split': row.get('split'),
        'current_label': row.get('current_label'),
        'raw_labels': row.get('raw_labels'),
        'candidate_reason': row.get('candidate_reason'),
    }
    text = str(row[text_column])
    return (
        '请标注以下文本的主导情感。\n'
        'label 和 second_label 都只能从：积极、愤怒、悲伤、恐惧、惊讶、中性 中选择；'
        '如果没有明确 second_label，请返回空字符串，不要返回“失望/不满/厌恶”等细分词。\n'
        '返回字段必须包含 label, second_label, confidence, reason, needs_human_review。\n\n'
        f'样本上下文：{json.dumps(context, ensure_ascii=False)}\n'
        f'文本：{text}'
    )


def extract_json_object(text: str) -> dict[str, Any]:
    text = text.strip()
    if text.startswith('```'):
        text = re.sub(r'^```(?:json)?\s*', '', text)
        text = re.sub(r'\s*```$', '', text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r'\{.*\}', text, flags=re.S)
        if not match:
            raise
        return json.loads(match.group(0))


def normalize_label(value: Any, field_name: str, allow_empty: bool = False) -> str:
    label = str(value or '').strip()
    if not label:
        if allow_empty:
            return ''
        raise ValueError(f'缺少 {field_name}')
    if label in ALLOWED_LABELS:
        return label
    if label in LABEL_ALIASES:
        return LABEL_ALIASES[label]
    if allow_empty:
        return ''
    raise ValueError(f'非法 {field_name}: {label!r}')


def validate_label_payload(payload: dict[str, Any]) -> dict[str, Any]:
    label = normalize_label(payload.get('label'), 'label')
    second = normalize_label(payload.get('second_label'), 'second_label', allow_empty=True)
    confidence = float(payload.get('confidence', 0))
    if not 0 <= confidence <= 1:
        raise ValueError(f'confidence 必须在 0-1: {confidence!r}')
    review_value = payload.get('needs_human_review', confidence < 0.75)
    if isinstance(review_value, str):
        needs_review = review_value.strip().lower() in ('1', 'true', 'yes', 'y', '是', '需要')
    else:
        needs_review = bool(review_value)
    if second == label:
        second = ''
    return {
        'label': label,
        'second_label': second,
        'confidence': confidence,
        'reason': str(payload.get('reason', '')).strip(),
        'needs_human_review': needs_review,
    }


def json_safe(value: Any) -> Any:
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    if isinstance(value, (str, int, float, bool)):
        return value
    if hasattr(value, 'isoformat'):
        return value.isoformat()
    return str(value)


def passthrough_fields(row: dict[str, Any]) -> dict[str, Any]:
    return {col: json_safe(row[col]) for col in PASSTHROUGH_COLUMNS if col in row}


async def call_llm(
    client: httpx.AsyncClient,
    url: str,
    headers: dict[str, str],
    model: str,
    system_prompt: str,
    user_prompt: str,
    temperature: float,
    max_tokens: int,
) -> str:
    payload = {
        'model': model,
        'messages': [
            {'role': 'system', 'content': system_prompt},
            {'role': 'user', 'content': user_prompt},
        ],
        'temperature': temperature,
        'max_tokens': max_tokens,
    }
    resp = await client.post(url, headers=headers, json=payload)
    resp.raise_for_status()
    data = resp.json()
    return data['choices'][0]['message']['content']


async def label_one(
    row: dict[str, Any],
    args: argparse.Namespace,
    client: httpx.AsyncClient,
    system_prompt: str,
    url: str,
    headers: dict[str, str],
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    sample_id = str(row[args.id_column])
    user_prompt = build_user_prompt(row, args.text_column)
    last_error = ''
    raw_response = ''

    for attempt in range(1, args.max_retries + 1):
        try:
            raw_response = await call_llm(
                client, url, headers, args.model, system_prompt, user_prompt,
                args.temperature, args.max_tokens,
            )
            parsed = validate_label_payload(extract_json_object(raw_response))
            return {
                'status': 'ok',
                'sample_id': sample_id,
                'source': row.get('source', ''),
                'track': row.get('track', ''),
                'split': row.get('split', ''),
                'text': str(row[args.text_column]),
                'current_label': row.get('current_label', ''),
                'raw_labels': row.get('raw_labels', ''),
                'candidate_reason': row.get('candidate_reason', ''),
                'llm_label': parsed['label'],
                'llm_second_label': parsed['second_label'],
                'llm_confidence': parsed['confidence'],
                'llm_reason': parsed['reason'],
                'needs_human_review': parsed['needs_human_review'],
                'model': args.model,
                **passthrough_fields(row),
            }, None
        except Exception as exc:  # noqa: BLE001 - CLI 要把失败样本落盘
            last_error = repr(exc)
            if attempt < args.max_retries:
                await asyncio.sleep((2 ** (attempt - 1)) + random.random())

    return None, {
        'status': 'error',
        'sample_id': sample_id,
        'text': str(row.get(args.text_column, '')),
        'error': last_error,
        'raw_response': raw_response,
        'model': args.model,
    }


async def run(args: argparse.Namespace) -> None:
    if not args.base_url:
        raise SystemExit('缺少 --base-url 或 LLM_BASE_URL')
    if args.concurrency < 1:
        raise SystemExit('--concurrency 必须 >= 1')

    rows = load_rows(args.input)
    if args.limit is not None:
        rows = rows[:args.limit]
    for col in (args.id_column, args.text_column):
        if rows and col not in rows[0]:
            raise SystemExit(f'输入缺少列: {col}')

    done = set() if args.no_resume else completed_ids(args.output)
    rows = [r for r in rows if str(r[args.id_column]) not in done]
    if not rows:
        print('没有待标注样本')
        return

    args.output.parent.mkdir(parents=True, exist_ok=True)
    errors_path = args.errors or args.output.with_suffix(args.output.suffix + '.errors.jsonl')
    errors_path.parent.mkdir(parents=True, exist_ok=True)

    url = args.base_url.rstrip('/') + '/chat/completions'
    headers = {'Content-Type': 'application/json'}
    if args.api_key:
        headers['Authorization'] = f'Bearer {args.api_key}'
    system_prompt = build_system_prompt(args.guideline)

    sem = asyncio.Semaphore(args.concurrency)
    write_lock = asyncio.Lock()
    ok_count = 0
    error_count = 0

    async with httpx.AsyncClient(timeout=args.timeout) as client:
        async def worker(row: dict[str, Any]) -> None:
            nonlocal ok_count, error_count
            async with sem:
                ok, err = await label_one(row, args, client, system_prompt, url, headers)
            async with write_lock:
                if ok is not None:
                    with args.output.open('a', encoding='utf-8') as f:
                        f.write(json.dumps(ok, ensure_ascii=False) + '\n')
                    ok_count += 1
                if err is not None:
                    with errors_path.open('a', encoding='utf-8') as f:
                        f.write(json.dumps(err, ensure_ascii=False) + '\n')
                    error_count += 1
                total = ok_count + error_count
                if total % 20 == 0 or total == len(rows):
                    print(f'progress {total}/{len(rows)} ok={ok_count} errors={error_count}')

        await asyncio.gather(*(worker(row) for row in rows))

    print(f'完成: ok={ok_count}, errors={error_count}, output={args.output}, errors={errors_path}')


def main() -> None:
    load_env_file(ROOT / '.env')
    asyncio.run(run(parse_args()))


if __name__ == '__main__':
    main()
