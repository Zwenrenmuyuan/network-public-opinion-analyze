"""Summary, metadata and timeseries routes."""

from __future__ import annotations

from datetime import datetime

from flask import Blueprint, jsonify

from npo.config import LABELS_ZH

from .cache import cached_endpoint
from .config import (
    ANGER_FEAR_LABEL_IDS,
    DATA_QUALITY_NOTICES,
    DATA_QUALITY_SOURCES,
    DISPLAY_TZ,
    LOW_CONFIDENCE_THRESHOLD,
    LOW_MARGIN_THRESHOLD,
    NEGATIVE_LABELS,
    NEGATIVE_LABEL_IDS,
    PRIMARY_CHECKPOINT,
    PRIMARY_MODEL_NAME,
    PRIMARY_MODEL_VERSION,
)
from .utils import get_data_window, profile_tier_distribution, ratio, resolve_window, round_float, scalar, to_float, to_int


def register_summary_routes(api: Blueprint, ck) -> None:
    @api.route('/meta')
    def api_meta():
        w = get_data_window(ck)
        time_range_options = ['all_available']
        if w['available_days'] >= 1:
            time_range_options.append('24h')
        if w['available_days'] >= 7:
            time_range_options.append('7d')
        return jsonify({
            'schema_version': 'dashboard.v1',
            'generated_at': datetime.now(DISPLAY_TZ).isoformat(timespec='seconds'),
            'data_window': {
                'start': w['start_cst'].isoformat(timespec='seconds'),
                'end': w['end_cst'].isoformat(timespec='seconds'),
                'available_days': w['available_days'],
                'is_partial_history': w['available_days'] < 30,
            },
            'time_range_options': time_range_options,
            'model': {
                'name': PRIMARY_MODEL_NAME,
                'model_version': PRIMARY_MODEL_VERSION,
                'checkpoint': PRIMARY_CHECKPOINT,
            },
            'labels': list(LABELS_ZH),
            'negative_labels': list(NEGATIVE_LABELS),
        })

    @api.route('/data-quality')
    def api_data_quality():
        return jsonify(data_quality_payload(ck))

    @api.route('/overview')
    @cached_endpoint('overview')
    def api_overview():
        w = resolve_window(ck)
        return jsonify(overview_payload(ck, w))

    @api.route('/emotion-timeseries')
    @cached_endpoint('emotion-timeseries')
    def api_emotion_timeseries():
        return jsonify(emotion_timeseries_payload(ck, resolve_window(ck)))


def data_quality_payload(ck) -> dict:
    w = get_data_window(ck)
    return {
        **DATA_QUALITY_NOTICES,
        'profile_tier_distribution': profile_tier_distribution(ck, w['start_utc_str']),
        'generated_from': DATA_QUALITY_SOURCES,
    }


def overview_payload(ck, window: dict) -> dict:
    s = window['start_utc_str']
    e = window['end_utc_str']
    pred = prediction_summary(ck, s, e)
    return {
        'post_count': scalar(ck, f"SELECT count(DISTINCT post_id) AS n FROM weibo.post WHERE created_at >= '{s}' AND created_at <= '{e}'"),
        'sampled_comment_count': scalar(ck, f"SELECT count(DISTINCT comment_id) AS n FROM weibo.comment WHERE created_at >= '{s}' AND created_at <= '{e}'"),
        'active_topic_count': scalar(ck, f"""
            SELECT count(DISTINCT topic_id) AS n
            FROM weibo.post_topic
            WHERE topic_id IN (SELECT topic_id FROM weibo.topic)
              AND post_id IN (SELECT DISTINCT post_id FROM weibo.post WHERE created_at >= '{s}' AND created_at <= '{e}')
        """),
        'latest_interactions': scalar(ck, f"""
            SELECT sum(c) + sum(l) + sum(r) AS n
            FROM (
              SELECT post_id,
                argMax(comments_count, captured_at) AS c,
                argMax(attitudes_count, captured_at) AS l,
                argMax(reposts_count, captured_at) AS r
              FROM weibo.post_engagement_ts
              WHERE post_id IN (SELECT DISTINCT post_id FROM weibo.post WHERE created_at >= '{s}' AND created_at <= '{e}')
              GROUP BY post_id
            )
        """),
        'kol_entry_post_count': scalar(ck, f"""
            SELECT count(DISTINCT post_id) AS n
            FROM weibo.post_discovery
            WHERE source_type = 'kol'
              AND post_id IN (SELECT DISTINCT post_id FROM weibo.post WHERE created_at >= '{s}' AND created_at <= '{e}')
        """),
        'verified_actor_count': scalar(ck, f"""
            SELECT count(DISTINCT uid) AS n
            FROM weibo.user FINAL
            WHERE verified = 1
              AND uid IN (
                SELECT DISTINCT user_id FROM weibo.post WHERE created_at >= '{s}' AND created_at <= '{e}'
                UNION DISTINCT
                SELECT DISTINCT user_id FROM weibo.comment WHERE created_at >= '{s}' AND created_at <= '{e}'
              )
        """),
        'profile_tier_distribution': profile_tier_distribution(ck, s),
        'negative_ratio': pred['negative_ratio'],
        'risk_index': pred['risk_index'],
        'avg_confidence': pred['avg_confidence'],
        'low_confidence_count': pred['low_confidence_count'],
        'prediction_sample_count': pred['total'],
    }


def emotion_timeseries_payload(ck, window: dict) -> list[dict]:
    rows = ck.query_json(f"""
        SELECT
          toString(toDate(source_created_at, 'Asia/Shanghai')) AS day,
          pred_label,
          pred_label_id,
          count() AS n,
          avg(confidence) AS avg_confidence
        FROM dashboard.sentiment_prediction
        WHERE model_version = '{PRIMARY_MODEL_VERSION}'
          AND source_created_at >= '{window['start_utc_str']}'
          AND source_created_at <= '{window['end_utc_str']}'
        GROUP BY day, pred_label, pred_label_id
        ORDER BY day, pred_label_id
    """)
    by_day: dict[str, dict] = {}
    for row in rows:
        day = row['day']
        item = by_day.setdefault(day, {
            'time': day,
            'granularity': 'day',
            'counts': {label: 0 for label in LABELS_ZH},
            'total': 0,
            'negative_count': 0,
            '_weighted_confidence': 0.0,
        })
        label = row['pred_label']
        n = to_int(row['n'])
        item['counts'][label] = n
        item['total'] += n
        item['_weighted_confidence'] += to_float(row['avg_confidence']) * n
        if to_int(row['pred_label_id']) in NEGATIVE_LABEL_IDS:
            item['negative_count'] += n

    return [
        {
            'time': item['time'],
            'granularity': item['granularity'],
            'counts': item['counts'],
            'negative_ratio': round(ratio(item['negative_count'], item['total']), 4),
            'avg_confidence': round(ratio(item['_weighted_confidence'], item['total']), 4),
        }
        for item in by_day.values()
    ]


def prediction_summary(ck, start_utc_str: str, end_utc_str: str) -> dict:
    row = ck.query_one(f"""
        SELECT
          count() AS total,
          countIf(pred_label_id IN {NEGATIVE_LABEL_IDS}) AS negative,
          countIf(pred_label_id IN {ANGER_FEAR_LABEL_IDS}) AS anger_fear,
          avg(confidence) AS avg_confidence,
          countIf(confidence < {LOW_CONFIDENCE_THRESHOLD} OR margin < {LOW_MARGIN_THRESHOLD}) AS low_confidence
        FROM dashboard.sentiment_prediction
        WHERE model_version = '{PRIMARY_MODEL_VERSION}'
          AND source_created_at >= '{start_utc_str}'
          AND source_created_at <= '{end_utc_str}'
    """) or {}
    total = to_int(row.get('total'))
    negative = to_int(row.get('negative'))
    anger_fear = to_int(row.get('anger_fear'))
    negative_ratio = ratio(negative, total)
    anger_fear_ratio = ratio(anger_fear, total)
    return {
        'total': total,
        'negative_ratio': round(negative_ratio, 4),
        'anger_fear_ratio': round(anger_fear_ratio, 4),
        'risk_index': round(100 * (0.70 * negative_ratio + 0.30 * anger_fear_ratio), 1),
        'avg_confidence': round_float(row.get('avg_confidence'), 4),
        'low_confidence_count': to_int(row.get('low_confidence')),
    }
