"""Risk topic route and aggregation."""

from __future__ import annotations

from datetime import timezone

from flask import Blueprint, jsonify

from npo.config import LABELS_ZH

from .config import (
    ANGER_FEAR_LABEL_IDS,
    NEGATIVE_LABEL_IDS,
    PRIMARY_MODEL_VERSION,
    RISK_FACTOR_LABELS,
    RISK_TOPIC_CANDIDATE_LIMIT,
    RISK_TOPIC_DEFAULT_LIMIT,
    SOURCE_TYPES,
)
from .utils import format_growth, limit_arg, norm, p95, ratio, resolve_window, risk_level, to_float, to_int


def register_risk_routes(api: Blueprint, ck) -> None:
    @api.route('/risk-topics')
    def api_risk_topics():
        limit = limit_arg('limit', RISK_TOPIC_DEFAULT_LIMIT, RISK_TOPIC_DEFAULT_LIMIT)
        return jsonify(build_risk_topics(ck, resolve_window(ck), limit))


def build_risk_topics(ck, window: dict, limit: int) -> list[dict]:
    start = window['start_utc_str']
    end = window['end_utc_str']
    midpoint = (window['start_cst'] + (window['end_cst'] - window['start_cst']) / 2)
    midpoint_utc_str = midpoint.astimezone(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')

    candidates = ck.query_json(f"""
        SELECT
          pt.topic_id AS topic_id,
          any(t.title) AS title,
          any(t.lead) AS lead,
          count(DISTINCT pt.post_id) AS post_count
        FROM weibo.post_topic AS pt
        INNER JOIN weibo.topic AS t ON t.topic_id = pt.topic_id
        WHERE pt.post_id IN (
          SELECT DISTINCT post_id
          FROM dashboard.sentiment_prediction
          WHERE model_version = '{PRIMARY_MODEL_VERSION}'
            AND source_created_at >= '{start}'
            AND source_created_at <= '{end}'
        )
        GROUP BY pt.topic_id
        HAVING post_count >= 3
        ORDER BY post_count DESC
        LIMIT {RISK_TOPIC_CANDIDATE_LIMIT}
    """)
    if not candidates:
        return []

    candidate_ids = [to_int(r['topic_id']) for r in candidates]
    ids_sql = ','.join(str(x) for x in candidate_ids)
    by_topic = {
        to_int(r['topic_id']): {
            'topic_id': str(r['topic_id']),
            'title': r.get('title') or '',
            'lead': r.get('lead') or '',
            'post_count': to_int(r.get('post_count')),
        }
        for r in candidates
    }
    metrics = _collect_topic_metrics(ck, candidate_ids, ids_sql, start, end, midpoint_utc_str)
    _add_risk_raw_values(metrics)

    caps = {
        'negative_growth': p95([x['negative_growth_raw'] for x in metrics.values()]),
        'interaction_growth': p95([x['interaction_growth_raw'] for x in metrics.values()]),
        'kol_verified': p95([x['kol_verified_raw'] for x in metrics.values()]),
    }
    out = [_render_topic(tid, by_topic, metrics, caps) for tid in candidate_ids]
    out = [item for item in out if item]
    out.sort(key=lambda x: (x['risk_score'], x['sample_count']), reverse=True)
    return out[:limit]


def _collect_topic_metrics(ck, candidate_ids: list[int], ids_sql: str, start: str, end: str, midpoint_utc_str: str) -> dict[int, dict]:
    metrics: dict[int, dict] = {tid: {'emotion_counts': {label: 0 for label in LABELS_ZH}} for tid in candidate_ids}
    _add_emotions(ck, metrics, ids_sql, start, end, midpoint_utc_str)
    _add_engagement(ck, metrics, ids_sql, start, end)
    _add_source_mix(ck, metrics, ids_sql, start, end)
    _add_actor_signals(ck, metrics, ids_sql, start, end)
    return metrics


def _add_emotions(ck, metrics: dict[int, dict], ids_sql: str, start: str, end: str, midpoint_utc_str: str) -> None:
    rows = ck.query_json(f"""
        SELECT
          pt.topic_id AS topic_id,
          sp.pred_label AS pred_label,
          sp.pred_label_id AS pred_label_id,
          count() AS n,
          countIf(sp.source_type = 'post') AS post_samples,
          countIf(sp.source_type = 'comment') AS comment_samples,
          avg(sp.confidence) AS avg_confidence,
          countIf(sp.source_created_at >= '{midpoint_utc_str}') AS recent_n,
          countIf(sp.source_created_at < '{midpoint_utc_str}') AS previous_n
        FROM dashboard.sentiment_prediction AS sp
        INNER JOIN weibo.post_topic AS pt ON pt.post_id = sp.post_id
        WHERE sp.model_version = '{PRIMARY_MODEL_VERSION}'
          AND sp.source_created_at >= '{start}'
          AND sp.source_created_at <= '{end}'
          AND pt.topic_id IN ({ids_sql})
        GROUP BY pt.topic_id, sp.pred_label, sp.pred_label_id
    """)
    for row in rows:
        tid = to_int(row['topic_id'])
        item = metrics.setdefault(tid, {'emotion_counts': {label: 0 for label in LABELS_ZH}})
        label_id = to_int(row['pred_label_id'])
        n = to_int(row['n'])
        item['emotion_counts'][row['pred_label']] = n
        item['sample_count'] = item.get('sample_count', 0) + n
        item['post_sample_count'] = item.get('post_sample_count', 0) + to_int(row['post_samples'])
        item['sampled_comment_count'] = item.get('sampled_comment_count', 0) + to_int(row['comment_samples'])
        item['weighted_confidence'] = item.get('weighted_confidence', 0.0) + to_float(row['avg_confidence']) * n
        if label_id in NEGATIVE_LABEL_IDS:
            item['negative_count'] = item.get('negative_count', 0) + n
            item['recent_negative_count'] = item.get('recent_negative_count', 0) + to_int(row['recent_n'])
            item['previous_negative_count'] = item.get('previous_negative_count', 0) + to_int(row['previous_n'])
        if label_id in ANGER_FEAR_LABEL_IDS:
            item['anger_fear_count'] = item.get('anger_fear_count', 0) + n


def _add_engagement(ck, metrics: dict[int, dict], ids_sql: str, start: str, end: str) -> None:
    rows = ck.query_json(f"""
        SELECT
          pt.topic_id AS topic_id,
          sum(e.earliest_interactions) AS earliest_interactions,
          sum(e.latest_interactions) AS latest_interactions,
          sum(greatest(e.latest_interactions - e.earliest_interactions, 0)) AS interaction_delta
        FROM weibo.post_topic AS pt
        INNER JOIN (
          SELECT
            post_id,
            argMin(comments_count + attitudes_count + reposts_count, captured_at) AS earliest_interactions,
            argMax(comments_count + attitudes_count + reposts_count, captured_at) AS latest_interactions
          FROM weibo.post_engagement_ts
          WHERE captured_at >= '{start}'
            AND captured_at <= '{end}'
            AND post_id IN (SELECT DISTINCT post_id FROM weibo.post_topic WHERE topic_id IN ({ids_sql}))
          GROUP BY post_id
        ) AS e ON e.post_id = pt.post_id
        WHERE pt.topic_id IN ({ids_sql})
        GROUP BY pt.topic_id
    """)
    for row in rows:
        item = metrics.setdefault(to_int(row['topic_id']), {'emotion_counts': {label: 0 for label in LABELS_ZH}})
        item['earliest_interactions'] = to_float(row.get('earliest_interactions'))
        item['latest_interactions'] = to_float(row.get('latest_interactions'))
        item['interaction_delta'] = to_float(row.get('interaction_delta'))


def _add_source_mix(ck, metrics: dict[int, dict], ids_sql: str, start: str, end: str) -> None:
    rows = ck.query_json(f"""
        SELECT
          pt.topic_id AS topic_id,
          toString(pd.source_type) AS source_type,
          count(DISTINCT pd.post_id) AS n
        FROM weibo.post_topic AS pt
        INNER JOIN weibo.post_discovery AS pd ON pd.post_id = pt.post_id
        WHERE pt.topic_id IN ({ids_sql})
          AND pd.post_id IN (
            SELECT DISTINCT post_id
            FROM dashboard.sentiment_prediction
            WHERE model_version = '{PRIMARY_MODEL_VERSION}'
              AND source_created_at >= '{start}'
              AND source_created_at <= '{end}'
          )
        GROUP BY pt.topic_id, pd.source_type
    """)
    for row in rows:
        item = metrics.setdefault(to_int(row['topic_id']), {'emotion_counts': {label: 0 for label in LABELS_ZH}})
        item.setdefault('source_counts', {})[row['source_type']] = to_int(row['n'])


def _add_actor_signals(ck, metrics: dict[int, dict], ids_sql: str, start: str, end: str) -> None:
    rows = ck.query_json(f"""
        SELECT
          pt.topic_id AS topic_id,
          uniqExactIf(pd.post_id, pd.source_type = 'kol') AS kol_entry_count,
          uniqExactIf(u.uid, u.verified = 1) AS verified_actor_count,
          uniqExactIf(u.uid, u.profile_tier >= 1 AND u.followers_count >= 10000) AS high_follower_actor_count
        FROM weibo.post_topic AS pt
        INNER JOIN weibo.post AS p ON p.post_id = pt.post_id
        LEFT JOIN weibo.post_discovery AS pd ON pd.post_id = pt.post_id
        LEFT JOIN weibo.user AS u FINAL ON u.uid = p.user_id
        WHERE pt.topic_id IN ({ids_sql})
          AND p.created_at >= '{start}'
          AND p.created_at <= '{end}'
        GROUP BY pt.topic_id
    """)
    for row in rows:
        item = metrics.setdefault(to_int(row['topic_id']), {'emotion_counts': {label: 0 for label in LABELS_ZH}})
        item['kol_entry_count'] = to_int(row.get('kol_entry_count'))
        item['verified_actor_count'] = to_int(row.get('verified_actor_count'))
        item['high_follower_actor_count'] = to_int(row.get('high_follower_actor_count'))


def _add_risk_raw_values(metrics: dict[int, dict]) -> None:
    for item in metrics.values():
        total = item.get('sample_count', 0)
        item['negative_ratio_raw'] = ratio(item.get('negative_count', 0), total)
        item['anger_fear_ratio_raw'] = ratio(item.get('anger_fear_count', 0), total)
        item['negative_growth_raw'] = ratio(
            item.get('recent_negative_count', 0) - item.get('previous_negative_count', 0),
            max(item.get('previous_negative_count', 0), 1),
        )
        item['interaction_growth_raw'] = to_float(item.get('interaction_delta'))
        item['interaction_growth_ratio'] = ratio(
            item.get('interaction_delta', 0.0),
            max(item.get('earliest_interactions', 0.0), 1.0),
        )
        item['kol_verified_raw'] = (
            item.get('kol_entry_count', 0)
            + item.get('verified_actor_count', 0)
            + item.get('high_follower_actor_count', 0)
        )
        source_counts = item.get('source_counts', {})
        item['source_diversity_raw'] = ratio(len([s for s in SOURCE_TYPES if source_counts.get(s, 0) > 0]), len(SOURCE_TYPES))


def _render_topic(tid: int, by_topic: dict[int, dict], metrics: dict[int, dict], caps: dict[str, float]) -> dict | None:
    topic = by_topic.get(tid, {'topic_id': str(tid), 'title': '', 'lead': '', 'post_count': 0})
    item = metrics.get(tid, {'emotion_counts': {label: 0 for label in LABELS_ZH}})
    total = item.get('sample_count', 0)
    if total <= 0:
        return None

    source_counts = item.get('source_counts', {})
    source_total = sum(source_counts.values())
    source_mix = {
        name: round(ratio(source_counts.get(name, 0), source_total), 4)
        for name in SOURCE_TYPES
    } if source_total else {name: 0.0 for name in SOURCE_TYPES}
    dominant_emotion = max(item['emotion_counts'].items(), key=lambda kv: kv[1])[0]
    factor_points = _risk_factor_points(item, caps)
    score = round(sum(factor_points.values()), 1)
    return {
        **topic,
        'risk_score': score,
        'risk_level': risk_level(score),
        'dominant_emotion': dominant_emotion,
        'negative_ratio': round(item['negative_ratio_raw'], 4),
        'negative_growth': round(item['negative_growth_raw'], 4),
        'negative_growth_label': format_growth(item['negative_growth_raw']),
        'interaction_growth': round(item['interaction_growth_ratio'], 4),
        'interaction_growth_label': format_growth(item['interaction_growth_ratio']),
        'latest_interactions': round(to_float(item.get('latest_interactions')), 2),
        'sample_count': total,
        'post_sample_count': item.get('post_sample_count', 0),
        'sampled_comment_count': item.get('sampled_comment_count', 0),
        'kol_entry_count': item.get('kol_entry_count', 0),
        'verified_actor_count': item.get('verified_actor_count', 0),
        'source_mix': source_mix,
        'emotion_counts': item['emotion_counts'],
        'avg_confidence': round(ratio(item.get('weighted_confidence', 0.0), total), 4),
        'risk_factors': {key: round(value, 1) for key, value in factor_points.items()},
        'risk_factor_labels': RISK_FACTOR_LABELS,
        'note': (
            f"负面率 {item['negative_ratio_raw'] * 100:.1f}%，主导情绪为{dominant_emotion}；"
            f"风险分由情绪结构、互动增量和 KOL/认证参与共同驱动。"
        ),
    }


def _risk_factor_points(item: dict, caps: dict[str, float]) -> dict[str, float]:
    factors_norm = {
        'negative_ratio': item['negative_ratio_raw'],
        'negative_growth': norm(item['negative_growth_raw'], caps['negative_growth']),
        'interaction_growth': norm(item['interaction_growth_raw'], caps['interaction_growth']),
        'anger_fear': item['anger_fear_ratio_raw'],
        'kol_verified': norm(item['kol_verified_raw'], caps['kol_verified']),
        'source_diversity': item['source_diversity_raw'],
    }
    return {
        'negative_ratio': 100 * 0.25 * factors_norm['negative_ratio'],
        'negative_growth': 100 * 0.20 * factors_norm['negative_growth'],
        'interaction_growth': 100 * 0.20 * factors_norm['interaction_growth'],
        'anger_fear': 100 * 0.15 * factors_norm['anger_fear'],
        'kol_verified': 100 * 0.10 * factors_norm['kol_verified'],
        'source_diversity': 100 * 0.10 * factors_norm['source_diversity'],
    }
