"""Dashboard API shared helpers."""

from __future__ import annotations

import json
import math
from datetime import datetime, timedelta, timezone
from pathlib import Path

from flask import request

from npo.config import LABELS_ZH

from .config import DISPLAY_TZ, STABLE_DAY_THRESHOLD


def get_data_window(ck) -> dict:
    """返回实际可展示数据窗口。"""
    row = ck.query_one(f"""
        SELECT
          (SELECT min(d) FROM (
            SELECT toDate(first_crawled_at, 'Asia/Shanghai') AS d, count() AS n
            FROM weibo.post GROUP BY d HAVING n >= {STABLE_DAY_THRESHOLD}
          )) AS stable_start_cst,
          max(created_at) AS end_utc
        FROM weibo.post
    """)
    if not row or not row.get('end_utc'):
        raise RuntimeError('weibo.post 无数据，无法计算 data_window')

    raw_start = row.get('stable_start_cst')
    if raw_start and raw_start != '0000-00-00':
        start_cst = datetime.strptime(raw_start, '%Y-%m-%d').replace(tzinfo=DISPLAY_TZ)
    else:
        fb = ck.query_one('SELECT min(first_crawled_at) AS m FROM weibo.post')
        start_cst = (datetime.strptime(fb['m'], '%Y-%m-%d %H:%M:%S')
                     .replace(tzinfo=timezone.utc).astimezone(DISPLAY_TZ))

    end_cst = (datetime.strptime(row['end_utc'], '%Y-%m-%d %H:%M:%S')
               .replace(tzinfo=timezone.utc).astimezone(DISPLAY_TZ))
    available_days = max(1, (end_cst.date() - start_cst.date()).days + 1)
    return {
        'start_cst': start_cst,
        'end_cst': end_cst,
        'available_days': available_days,
        'start_utc_str': start_cst.astimezone(timezone.utc).strftime('%Y-%m-%d %H:%M:%S'),
        'end_utc_str': end_cst.astimezone(timezone.utc).strftime('%Y-%m-%d %H:%M:%S'),
    }


def resolve_window(ck) -> dict:
    """根据 query 参数解析展示窗口；默认 all_available。"""
    base = get_data_window(ck)
    range_key = request.args.get('range', 'all_available')
    end_cst = base['end_cst']
    if range_key == '24h':
        start_cst = max(base['start_cst'], end_cst - timedelta(hours=24))
    elif range_key == '7d':
        start_cst = max(base['start_cst'], end_cst - timedelta(days=7))
    else:
        range_key = 'all_available'
        start_cst = base['start_cst']

    return {
        **base,
        'range': range_key,
        'start_cst': start_cst,
        'end_cst': end_cst,
        'available_days': max(1, (end_cst.date() - start_cst.date()).days + 1),
        'start_utc_str': start_cst.astimezone(timezone.utc).strftime('%Y-%m-%d %H:%M:%S'),
        'end_utc_str': end_cst.astimezone(timezone.utc).strftime('%Y-%m-%d %H:%M:%S'),
    }


def limit_arg(name: str, default: int, maximum: int) -> int:
    raw = request.args.get(name, str(default))
    try:
        value = int(raw)
    except ValueError:
        return default
    return max(1, min(value, maximum))


def topic_id_arg() -> int | None:
    raw = request.args.get('topic_id')
    if raw in (None, '', 'all'):
        return None
    try:
        value = int(raw)
    except ValueError:
        return None
    return value if value > 0 else None


def to_float(value, default: float = 0.0) -> float:
    if value is None:
        return default
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def to_int(value, default: int = 0) -> int:
    if value is None:
        return default
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value) if math.isfinite(value) else default
    try:
        return int(str(value))
    except (TypeError, ValueError):
        try:
            return int(float(value))
        except (TypeError, ValueError):
            return default


def ratio(part: float, total: float) -> float:
    return float(part) / float(total) if total else 0.0


def round_float(value: float | None, digits: int = 4) -> float | None:
    if value is None:
        return None
    return round(to_float(value), digits)


def utc_to_cst_iso(value: str | None) -> str | None:
    if not value:
        return None
    dt = datetime.strptime(value, '%Y-%m-%d %H:%M:%S')
    return dt.replace(tzinfo=timezone.utc).astimezone(DISPLAY_TZ).isoformat(timespec='seconds')


def p95(values: list[float]) -> float:
    vals = sorted(v for v in values if v > 0)
    if not vals:
        return 1.0
    idx = min(len(vals) - 1, max(0, math.ceil(len(vals) * 0.95) - 1))
    return vals[idx] or 1.0


def norm(value: float, cap: float) -> float:
    return min(max(value, 0.0) / max(cap, 1e-9), 1.0)


def risk_level(score: float) -> str:
    if score >= 80:
        return 'high'
    if score >= 60:
        return 'medium_high'
    if score >= 40:
        return 'medium'
    return 'low'


def format_growth(value: float) -> str:
    return f'+{value * 100:.0f}%' if value >= 0 else f'{value * 100:.0f}%'


def display_text(raw_text: str | None) -> str:
    """展示文本出口；目前返回原文，后续可在这里接脱敏/摘要。"""
    return raw_text or ''


def profile_tier_distribution(ck, start_utc_str: str) -> dict[str, float]:
    rows = ck.query_json(f"""
        SELECT profile_tier AS tier, count(DISTINCT uid) AS n
        FROM weibo.user FINAL
        WHERE uid IN (
          SELECT DISTINCT user_id FROM weibo.post WHERE created_at >= '{start_utc_str}'
          UNION DISTINCT
          SELECT DISTINCT user_id FROM weibo.comment WHERE created_at >= '{start_utc_str}'
        )
        GROUP BY profile_tier ORDER BY profile_tier
    """)
    total = sum(int(r['n']) for r in rows)
    if total == 0:
        return {}
    return {str(r['tier']): round(int(r['n']) / total, 4) for r in rows}


def scalar(ck, sql: str) -> int:
    row = ck.query_one(sql)
    if not row or row.get('n') is None:
        return 0
    return int(row['n'])


def load_json(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except FileNotFoundError:
        return None


def extract_eval(report: dict | None) -> dict | None:
    if not report:
        return None
    labels = report.get('labels') or list(LABELS_ZH)
    per_class = report.get('per_class_f1') or []
    return {
        'samples': report.get('samples'),
        'accuracy': round(report.get('accuracy', 0.0), 4),
        'macro_f1': round(report.get('macro_f1', 0.0), 4),
        'per_class_f1': {label: round(float(f1), 4) for label, f1 in zip(labels, per_class)},
    }


def top_confusions(matrix: list[list[int]] | None, labels: list[str], top_n: int = 3) -> list[dict]:
    if not matrix:
        return []
    cells = []
    for i, row in enumerate(matrix):
        for j, count in enumerate(row):
            if i == j or not count:
                continue
            cells.append({'true': labels[i], 'pred': labels[j], 'count': int(count)})
    cells.sort(key=lambda c: c['count'], reverse=True)
    return cells[:top_n]
