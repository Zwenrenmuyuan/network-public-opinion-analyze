"""Topic detail route."""

from __future__ import annotations

from datetime import timezone

from flask import Blueprint, abort, jsonify

from npo.config import LABELS_ZH

from .actors import actor_summary
from .cache import cached_endpoint
from .config import (
    ANGER_FEAR_LABEL_IDS,
    EVIDENCE_DEFAULT_LIMIT,
    EVIDENCE_MAX_LIMIT,
    NEGATIVE_LABEL_IDS,
    PRIMARY_MODEL_VERSION,
    RISK_FACTOR_LABELS,
    SOURCE_TYPES,
    TOPIC_DETAIL_ACTOR_DEFAULT_LIMIT,
)
from .evidence import evidence_samples
from .risk import add_risk_raw_values, compute_window_caps, risk_factor_points
from .utils import format_growth, limit_arg, ratio, resolve_window, risk_level, to_float, to_int, utc_to_cst_iso


def register_topic_routes(api: Blueprint, ck) -> None:
    @api.route('/topics/<int:topic_id>')
    @cached_endpoint('topic-detail')
    def api_topic_detail(topic_id: int):
        detail = topic_detail(
            ck,
            resolve_window(ck),
            topic_id,
            evidence_limit=limit_arg('limit', EVIDENCE_DEFAULT_LIMIT, EVIDENCE_MAX_LIMIT),
            actor_limit=limit_arg('actor_limit', TOPIC_DETAIL_ACTOR_DEFAULT_LIMIT, 20),
        )
        if detail is None:
            abort(404)
        return jsonify(detail)


def topic_detail(ck, window: dict, topic_id: int, evidence_limit: int, actor_limit: int) -> dict | None:
    base = _topic_base(ck, window, topic_id)
    if base is None:
        return None
    timeline, emotion = _topic_timeline(ck, window, topic_id)
    engagement_curve, engagement = _topic_engagement(ck, window, topic_id)
    source_mix, source_counts = _topic_source_mix(ck, window, topic_id)
    actor_signals = _topic_actor_signals(ck, window, topic_id)
    caps = compute_window_caps(ck, window)
    risk = _topic_risk(emotion, engagement, source_counts, actor_signals, caps)
    actors = actor_summary(ck, window, topic_id, actor_limit)
    evidence = evidence_samples(ck, window, topic_id, evidence_limit)['samples']

    return {
        'topic': {
            **base,
            **risk,
            'latest_interactions': engagement['latest_interactions'],
            'interaction_delta': engagement['interaction_delta'],
            'post_sample_count': emotion['post_sample_count'],
            'sampled_comment_count': emotion['sampled_comment_count'],
            'sample_count': emotion['total'],
            'avg_confidence': emotion['avg_confidence'],
            'kol_entry_count': actor_signals['kol_entry_count'],
            'verified_actor_count': actor_signals['verified_actor_count'],
            'high_follower_actor_count': actor_signals['high_follower_actor_count'],
        },
        'timeline': timeline,
        'emotion_distribution': {
            'counts': emotion['counts'],
            'ratios': emotion['ratios'],
            'total': emotion['total'],
            'negative_count': emotion['negative_count'],
            'negative_ratio': emotion['negative_ratio'],
            'anger_fear_count': emotion['anger_fear_count'],
            'anger_fear_ratio': emotion['anger_fear_ratio'],
        },
        'engagement_curve': engagement_curve,
        'source_mix': source_mix,
        'source_counts': source_counts,
        'top_actors': actors,
        'evidence_samples': evidence,
    }


def _topic_base(ck, window: dict, topic_id: int) -> dict | None:
    row = ck.query_one(f"""
        SELECT
          toString(topic_id) AS topic_id_str,
          any(title) AS title,
          any(lead) AS lead,
          max(read_count) AS read_count,
          max(discuss_count) AS discuss_count,
          min(first_seen_at) AS first_seen_at,
          max(last_seen_at) AS last_seen_at
        FROM weibo.topic
        WHERE topic_id = {topic_id}
        GROUP BY topic_id
    """)
    if not row:
        return None
    post_count = ck.query_one(f"""
        SELECT count(DISTINCT post_id) AS n
        FROM weibo.post_topic
        WHERE topic_id = {topic_id}
          AND post_id IN (
            SELECT DISTINCT post_id
            FROM dashboard.sentiment_prediction
            WHERE model_version = '{PRIMARY_MODEL_VERSION}'
              AND source_created_at >= '{window['start_utc_str']}'
              AND source_created_at <= '{window['end_utc_str']}'
          )
    """) or {}
    return {
        'topic_id': str(row.get('topic_id_str')),
        'title': row.get('title') or '',
        'lead': row.get('lead') or '',
        'read_count': to_int(row.get('read_count')),
        'discuss_count': to_int(row.get('discuss_count')),
        'first_seen_at': utc_to_cst_iso(row.get('first_seen_at')),
        'last_seen_at': utc_to_cst_iso(row.get('last_seen_at')),
        'post_count': to_int(post_count.get('n')),
    }


def _topic_timeline(ck, window: dict, topic_id: int) -> tuple[list[dict], dict]:
    midpoint = window['start_cst'] + (window['end_cst'] - window['start_cst']) / 2
    midpoint_utc = midpoint.astimezone(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')
    rows = ck.query_json(f"""
        SELECT
          toString(toDate(sp.source_created_at, 'Asia/Shanghai')) AS day,
          sp.pred_label AS pred_label,
          sp.pred_label_id AS pred_label_id,
          count() AS n,
          countIf(sp.source_type = 'post') AS post_samples,
          countIf(sp.source_type = 'comment') AS comment_samples,
          avg(sp.confidence) AS avg_confidence,
          countIf(sp.source_created_at >= '{midpoint_utc}') AS recent_n,
          countIf(sp.source_created_at < '{midpoint_utc}') AS previous_n
        FROM dashboard.sentiment_prediction AS sp
        INNER JOIN weibo.post_topic AS pt ON pt.post_id = sp.post_id
        WHERE sp.model_version = '{PRIMARY_MODEL_VERSION}'
          AND sp.source_created_at >= '{window['start_utc_str']}'
          AND sp.source_created_at <= '{window['end_utc_str']}'
          AND pt.topic_id = {topic_id}
        GROUP BY day, sp.pred_label, sp.pred_label_id
        ORDER BY day, sp.pred_label_id
    """)
    by_day: dict[str, dict] = {}
    emotion = _empty_emotion()
    for row in rows:
        day = row['day']
        label = row['pred_label']
        label_id = to_int(row['pred_label_id'])
        n = to_int(row['n'])
        avg_conf = to_float(row.get('avg_confidence'))
        item = by_day.setdefault(day, {
            'time': day,
            'granularity': 'day',
            'counts': {label_name: 0 for label_name in LABELS_ZH},
            'total': 0,
            'negative_count': 0,
            '_weighted_confidence': 0.0,
        })
        item['counts'][label] = n
        item['total'] += n
        item['_weighted_confidence'] += avg_conf * n
        emotion['counts'][label] += n
        emotion['total'] += n
        emotion['weighted_confidence'] += avg_conf * n
        emotion['post_sample_count'] += to_int(row.get('post_samples'))
        emotion['sampled_comment_count'] += to_int(row.get('comment_samples'))
        if label_id in NEGATIVE_LABEL_IDS:
            item['negative_count'] += n
            emotion['negative_count'] += n
            emotion['recent_negative_count'] += to_int(row.get('recent_n'))
            emotion['previous_negative_count'] += to_int(row.get('previous_n'))
        if label_id in ANGER_FEAR_LABEL_IDS:
            emotion['anger_fear_count'] += n

    timeline = [
        {
            'time': item['time'],
            'granularity': item['granularity'],
            'counts': item['counts'],
            'total': item['total'],
            'negative_ratio': round(ratio(item['negative_count'], item['total']), 4),
            'avg_confidence': round(ratio(item['_weighted_confidence'], item['total']), 4),
        }
        for item in by_day.values()
    ]
    emotion['negative_ratio'] = round(ratio(emotion['negative_count'], emotion['total']), 4)
    emotion['anger_fear_ratio'] = round(ratio(emotion['anger_fear_count'], emotion['total']), 4)
    emotion['avg_confidence'] = round(ratio(emotion['weighted_confidence'], emotion['total']), 4)
    emotion['ratios'] = {label: round(ratio(count, emotion['total']), 4) for label, count in emotion['counts'].items()}
    return timeline, emotion


def _topic_engagement(ck, window: dict, topic_id: int) -> tuple[list[dict], dict]:
    rows = ck.query_json(f"""
        SELECT
          toString(day) AS day,
          sum(comment_snapshot) AS comments_count,
          sum(attitude_snapshot) AS attitudes_count,
          sum(repost_snapshot) AS reposts_count,
          sum(comment_snapshot + attitude_snapshot + repost_snapshot) AS interaction_count
        FROM (
          SELECT
            toDate(e.captured_at, 'Asia/Shanghai') AS day,
            e.post_id AS post_id,
            argMax(e.comments_count, e.captured_at) AS comment_snapshot,
            argMax(e.attitudes_count, e.captured_at) AS attitude_snapshot,
            argMax(e.reposts_count, e.captured_at) AS repost_snapshot
          FROM weibo.post_engagement_ts AS e
          INNER JOIN weibo.post_topic AS pt ON pt.post_id = e.post_id
          WHERE pt.topic_id = {topic_id}
            AND e.captured_at >= '{window['start_utc_str']}'
            AND e.captured_at <= '{window['end_utc_str']}'
          GROUP BY day, e.post_id
        )
        GROUP BY day
        ORDER BY day
    """)
    curve = [
        {
            'time': row['day'],
            'comments_count': to_int(row.get('comments_count')),
            'attitudes_count': to_int(row.get('attitudes_count')),
            'reposts_count': to_int(row.get('reposts_count')),
            'interaction_count': to_int(row.get('interaction_count')),
        }
        for row in rows
    ]
    return curve, _topic_engagement_summary(ck, window, topic_id)


def _topic_engagement_summary(ck, window: dict, topic_id: int) -> dict:
    row = ck.query_one(f"""
        SELECT
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
          WHERE captured_at >= '{window['start_utc_str']}'
            AND captured_at <= '{window['end_utc_str']}'
            AND post_id IN (
              SELECT DISTINCT post_id
              FROM weibo.post_topic
              WHERE topic_id = {topic_id}
            )
          GROUP BY post_id
        ) AS e ON e.post_id = pt.post_id
        WHERE pt.topic_id = {topic_id}
    """) or {}
    earliest = to_float(row.get('earliest_interactions'))
    latest = to_float(row.get('latest_interactions'))
    delta = to_float(row.get('interaction_delta'))
    return {
        'earliest_interactions': earliest,
        'latest_interactions': latest,
        'interaction_delta': delta,
        'interaction_growth': round(ratio(delta, max(earliest, 1)), 4),
    }


def _topic_source_mix(ck, window: dict, topic_id: int) -> tuple[dict[str, float], dict[str, int]]:
    rows = ck.query_json(f"""
        SELECT
          toString(pd.source_type) AS source_type,
          count(DISTINCT pd.post_id) AS n
        FROM weibo.post_discovery AS pd
        INNER JOIN weibo.post_topic AS pt ON pt.post_id = pd.post_id
        WHERE pt.topic_id = {topic_id}
          AND pd.post_id IN (
            SELECT DISTINCT post_id
            FROM dashboard.sentiment_prediction
            WHERE model_version = '{PRIMARY_MODEL_VERSION}'
              AND source_created_at >= '{window['start_utc_str']}'
              AND source_created_at <= '{window['end_utc_str']}'
          )
        GROUP BY pd.source_type
    """)
    counts = {name: 0 for name in SOURCE_TYPES}
    for row in rows:
        source_type = row.get('source_type')
        if source_type in counts:
            counts[source_type] = to_int(row.get('n'))
    total = sum(counts.values())
    return {name: round(ratio(counts[name], total), 4) for name in SOURCE_TYPES}, counts


def _topic_actor_signals(ck, window: dict, topic_id: int) -> dict:
    row = ck.query_one(f"""
        SELECT
          uniqExactIf(pd.post_id, pd.source_type = 'kol') AS kol_entry_count,
          uniqExactIf(u.uid, u.verified = 1) AS verified_actor_count,
          uniqExactIf(u.uid, u.profile_tier >= 1 AND u.followers_count >= 10000) AS high_follower_actor_count
        FROM weibo.post_topic AS pt
        INNER JOIN weibo.post AS p ON p.post_id = pt.post_id
        LEFT JOIN weibo.post_discovery AS pd ON pd.post_id = pt.post_id
        LEFT JOIN weibo.user AS u FINAL ON u.uid = p.user_id
        WHERE pt.topic_id = {topic_id}
          AND p.created_at >= '{window['start_utc_str']}'
          AND p.created_at <= '{window['end_utc_str']}'
    """) or {}
    return {
        'kol_entry_count': to_int(row.get('kol_entry_count')),
        'verified_actor_count': to_int(row.get('verified_actor_count')),
        'high_follower_actor_count': to_int(row.get('high_follower_actor_count')),
    }


def _topic_risk(emotion: dict, engagement: dict, source_counts: dict[str, int],
                actor_signals: dict, caps: dict[str, float]) -> dict:
    """与 risk-topics 列表共用同一公式（窗口候选 p95 归一化），保证列表分 == 详情分。"""
    item = {
        'sample_count': emotion['total'],
        'negative_count': emotion['negative_count'],
        'recent_negative_count': emotion['recent_negative_count'],
        'previous_negative_count': emotion['previous_negative_count'],
        'anger_fear_count': emotion['anger_fear_count'],
        'earliest_interactions': engagement.get('earliest_interactions', 0.0),
        'interaction_delta': engagement['interaction_delta'],
        'source_counts': source_counts,
        'kol_entry_count': actor_signals['kol_entry_count'],
        'verified_actor_count': actor_signals['verified_actor_count'],
        'high_follower_actor_count': actor_signals['high_follower_actor_count'],
    }
    add_risk_raw_values(item)
    factors = risk_factor_points(item, caps)
    score = round(sum(factors.values()), 1)
    dominant_emotion = max(emotion['counts'].items(), key=lambda kv: kv[1])[0] if emotion['total'] else '中性'
    return {
        'risk_score': score,
        'risk_level': risk_level(score),
        'dominant_emotion': dominant_emotion,
        'negative_ratio': emotion['negative_ratio'],
        'negative_growth': round(item['negative_growth_raw'], 4),
        'negative_growth_label': format_growth(item['negative_growth_raw']),
        'interaction_growth': round(item['interaction_growth_ratio'], 4),
        'interaction_growth_label': format_growth(item['interaction_growth_ratio']),
        'risk_factors': {key: round(value, 1) for key, value in factors.items()},
        'risk_factor_labels': RISK_FACTOR_LABELS,
        'note': (
            f"负面率 {emotion['negative_ratio'] * 100:.1f}%，主导情绪为{dominant_emotion}；"
            '风险分采用与风险话题榜一致的公式（窗口候选 p95 归一化）。'
        ),
    }


def _empty_emotion() -> dict:
    return {
        'counts': {label: 0 for label in LABELS_ZH},
        'ratios': {label: 0.0 for label in LABELS_ZH},
        'total': 0,
        'negative_count': 0,
        'anger_fear_count': 0,
        'recent_negative_count': 0,
        'previous_negative_count': 0,
        'post_sample_count': 0,
        'sampled_comment_count': 0,
        'weighted_confidence': 0.0,
        'negative_ratio': 0.0,
        'anger_fear_ratio': 0.0,
        'avg_confidence': None,
    }
