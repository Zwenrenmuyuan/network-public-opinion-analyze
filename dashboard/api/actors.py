"""Actor and influence-emotion aggregation routes."""

from __future__ import annotations

import hashlib
import math
from collections import Counter, defaultdict

from flask import Blueprint, jsonify

from npo.config import LABELS_ZH

from .config import (
    ACTOR_CANDIDATE_LIMIT,
    ACTOR_DEFAULT_LIMIT,
    ACTOR_MAX_LIMIT,
    INFLUENCE_DEFAULT_LIMIT,
    INFLUENCE_MAX_LIMIT,
    NEGATIVE_LABEL_IDS,
    PRIMARY_MODEL_VERSION,
)
from .utils import limit_arg, ratio, resolve_window, to_int, topic_id_arg


def register_actor_routes(api: Blueprint, ck) -> None:
    @api.route('/actors')
    def api_actors():
        return jsonify(actor_summary(
            ck,
            resolve_window(ck),
            topic_id_arg(),
            limit_arg('limit', ACTOR_DEFAULT_LIMIT, ACTOR_MAX_LIMIT),
        ))

    @api.route('/influence-emotion')
    def api_influence_emotion():
        actors = actor_summary(
            ck,
            resolve_window(ck),
            topic_id_arg(),
            limit_arg('limit', INFLUENCE_DEFAULT_LIMIT, INFLUENCE_MAX_LIMIT),
        )
        return jsonify([
            {
                'actor_id': item['actor_id'],
                'display_name': item['display_name'],
                'influence_score': item['actor_influence_score'],
                'negative_ratio': item['negative_ratio'],
                'interaction_count': item['interaction_count'],
                'dominant_emotion': item['dominant_emotion'],
                'topic_id': item.get('top_topic_id'),
                'topic_title': item.get('top_topic_title') or '全部话题',
                'roles': item['roles'],
            }
            for item in actors
        ])


def actor_summary(ck, window: dict, topic_id: int | None, limit: int) -> list[dict]:
    candidate_limit = min(ACTOR_CANDIDATE_LIMIT, max(limit * 8, limit))
    candidates = ck.query_json(_actor_candidate_sql(window, topic_id, candidate_limit))
    actor_ids = [to_int(row.get('uid')) for row in candidates if to_int(row.get('uid')) > 0]
    if not actor_ids:
        return []

    ids_sql = ','.join(str(uid) for uid in actor_ids)
    rows = ck.query_json(_actor_detail_sql(window, topic_id, ids_sql))
    topic_rows = ck.query_json(_actor_topic_sql(window, topic_id, ids_sql))
    topic_meta = _topic_meta(topic_rows)
    actors = _merge_actor_rows(rows, topic_meta)
    return _render_actors(actors, limit)


def _actor_candidate_sql(window: dict, topic_id: int | None, candidate_limit: int) -> str:
    start = window['start_utc_str']
    end = window['end_utc_str']
    topic_filter = _topic_post_filter(topic_id)
    return f"""
        SELECT
          uid,
          sum(sample_count) AS sample_count,
          sum(interaction_count) AS interaction_count
        FROM (
          SELECT
            p.user_id AS uid,
            count() AS sample_count,
            sum(ifNull(e.interaction_count, 0)) AS interaction_count
          FROM dashboard.sentiment_prediction AS sp
          INNER JOIN weibo.post AS p ON p.post_id = sp.source_id
          LEFT JOIN (
            SELECT post_id, argMax(comments_count + attitudes_count + reposts_count, captured_at) AS interaction_count
            FROM weibo.post_engagement_ts
            WHERE captured_at >= '{start}' AND captured_at <= '{end}'
            GROUP BY post_id
          ) AS e ON e.post_id = sp.post_id
          WHERE sp.model_version = '{PRIMARY_MODEL_VERSION}'
            AND sp.source_type = 'post'
            AND sp.source_created_at >= '{start}'
            AND sp.source_created_at <= '{end}'
            {topic_filter}
          GROUP BY p.user_id

          UNION ALL

          SELECT
            c.user_id AS uid,
            count() AS sample_count,
            sum(c.like_count) AS interaction_count
          FROM dashboard.sentiment_prediction AS sp
          INNER JOIN weibo.comment AS c ON c.post_id = sp.post_id AND c.comment_id = sp.source_id
          WHERE sp.model_version = '{PRIMARY_MODEL_VERSION}'
            AND sp.source_type = 'comment'
            AND sp.source_created_at >= '{start}'
            AND sp.source_created_at <= '{end}'
            {topic_filter}
          GROUP BY c.user_id
        )
        GROUP BY uid
        ORDER BY interaction_count DESC, sample_count DESC
        LIMIT {candidate_limit}
    """


def _actor_detail_sql(window: dict, topic_id: int | None, ids_sql: str) -> str:
    start = window['start_utc_str']
    end = window['end_utc_str']
    topic_filter = _topic_post_filter(topic_id)
    return f"""
        SELECT
          s.uid AS uid,
          any(u.verified) AS verified,
          any(u.verified_type) AS verified_type,
          max(u.profile_tier) AS profile_tier,
          max(u.followers_count) AS followers_count,
          s.pred_label AS pred_label,
          s.pred_label_id AS pred_label_id,
          sum(s.sample_count) AS sample_count,
          sum(s.post_count) AS post_count,
          sum(s.comment_count) AS comment_count,
          sum(s.interaction_count) AS interaction_count
        FROM (
          SELECT
            p.user_id AS uid,
            sp.pred_label AS pred_label,
            sp.pred_label_id AS pred_label_id,
            count() AS sample_count,
            uniqExact(sp.source_id) AS post_count,
            0 AS comment_count,
            sum(ifNull(e.interaction_count, 0)) AS interaction_count
          FROM dashboard.sentiment_prediction AS sp
          INNER JOIN weibo.post AS p ON p.post_id = sp.source_id
          LEFT JOIN (
            SELECT post_id, argMax(comments_count + attitudes_count + reposts_count, captured_at) AS interaction_count
            FROM weibo.post_engagement_ts
            WHERE captured_at >= '{start}' AND captured_at <= '{end}'
            GROUP BY post_id
          ) AS e ON e.post_id = sp.post_id
          WHERE sp.model_version = '{PRIMARY_MODEL_VERSION}'
            AND sp.source_type = 'post'
            AND sp.source_created_at >= '{start}'
            AND sp.source_created_at <= '{end}'
            AND p.user_id IN ({ids_sql})
            {topic_filter}
          GROUP BY p.user_id, sp.pred_label, sp.pred_label_id

          UNION ALL

          SELECT
            c.user_id AS uid,
            sp.pred_label AS pred_label,
            sp.pred_label_id AS pred_label_id,
            count() AS sample_count,
            0 AS post_count,
            uniqExact(sp.source_id) AS comment_count,
            sum(c.like_count) AS interaction_count
          FROM dashboard.sentiment_prediction AS sp
          INNER JOIN weibo.comment AS c ON c.post_id = sp.post_id AND c.comment_id = sp.source_id
          WHERE sp.model_version = '{PRIMARY_MODEL_VERSION}'
            AND sp.source_type = 'comment'
            AND sp.source_created_at >= '{start}'
            AND sp.source_created_at <= '{end}'
            AND c.user_id IN ({ids_sql})
            {topic_filter}
          GROUP BY c.user_id, sp.pred_label, sp.pred_label_id
        ) AS s
        LEFT JOIN weibo.user AS u FINAL ON u.uid = s.uid
        GROUP BY s.uid, s.pred_label, s.pred_label_id
    """


def _actor_topic_sql(window: dict, topic_id: int | None, ids_sql: str) -> str:
    start = window['start_utc_str']
    end = window['end_utc_str']
    topic_filter = '' if topic_id is None else f'AND pt.topic_id = {topic_id}'
    return f"""
        SELECT
          s.uid AS uid,
          toString(pt.topic_id) AS topic_id,
          any(t.title) AS title,
          count(DISTINCT s.post_id) AS post_count
        FROM (
          SELECT user_id AS uid, post_id
          FROM weibo.post
          WHERE user_id IN ({ids_sql})
            AND created_at >= '{start}'
            AND created_at <= '{end}'

          UNION ALL

          SELECT user_id AS uid, post_id
          FROM weibo.comment
          WHERE user_id IN ({ids_sql})
            AND created_at >= '{start}'
            AND created_at <= '{end}'
        ) AS s
        INNER JOIN weibo.post_topic AS pt ON pt.post_id = s.post_id
        INNER JOIN weibo.topic AS t ON t.topic_id = pt.topic_id
        WHERE 1 = 1 {topic_filter}
        GROUP BY s.uid, pt.topic_id
        ORDER BY post_count DESC
    """


def _topic_post_filter(topic_id: int | None) -> str:
    if topic_id is None:
        return ''
    return f"AND sp.post_id IN (SELECT DISTINCT post_id FROM weibo.post_topic WHERE topic_id = {topic_id})"


def _topic_meta(rows: list[dict]) -> dict[int, dict]:
    meta: dict[int, dict] = defaultdict(lambda: {'topic_count': 0, 'top_topic_id': None, 'top_topic_title': None, '_max_posts': -1})
    seen: dict[int, set[str]] = defaultdict(set)
    for row in rows:
        uid = to_int(row.get('uid'))
        tid = str(row.get('topic_id') or '')
        if not uid or not tid:
            continue
        seen[uid].add(tid)
        posts = to_int(row.get('post_count'))
        if posts > meta[uid]['_max_posts']:
            meta[uid]['_max_posts'] = posts
            meta[uid]['top_topic_id'] = tid
            meta[uid]['top_topic_title'] = row.get('title') or ''
    for uid, topics in seen.items():
        meta[uid]['topic_count'] = len(topics)
        meta[uid].pop('_max_posts', None)
    return meta


def _merge_actor_rows(rows: list[dict], topic_meta: dict[int, dict]) -> list[dict]:
    by_actor: dict[int, dict] = {}
    for row in rows:
        uid = to_int(row.get('uid'))
        if uid <= 0:
            continue
        item = by_actor.setdefault(uid, {
            'uid': uid,
            'verified': bool(to_int(row.get('verified'))),
            'verified_type': to_int(row.get('verified_type'), -1),
            'profile_tier': to_int(row.get('profile_tier')),
            'followers_count': to_int(row.get('followers_count')),
            'sample_count': 0,
            'post_count': 0,
            'comment_count': 0,
            'interaction_count': 0,
            'emotion_counts': {label: 0 for label in LABELS_ZH},
            **topic_meta.get(uid, {'topic_count': 0, 'top_topic_id': None, 'top_topic_title': None}),
        })
        n = to_int(row.get('sample_count'))
        label = row.get('pred_label')
        if label in item['emotion_counts']:
            item['emotion_counts'][label] += n
        item['sample_count'] += n
        item['post_count'] += to_int(row.get('post_count'))
        item['comment_count'] += to_int(row.get('comment_count'))
        item['interaction_count'] += to_int(row.get('interaction_count'))
        item['verified'] = item['verified'] or bool(to_int(row.get('verified')))
        item['profile_tier'] = max(item['profile_tier'], to_int(row.get('profile_tier')))
        item['followers_count'] = max(item['followers_count'], to_int(row.get('followers_count')))
    return list(by_actor.values())


def _render_actors(actors: list[dict], limit: int) -> list[dict]:
    if not actors:
        return []
    max_interactions = max((item['interaction_count'] for item in actors), default=0)
    max_followers = max((item['followers_count'] for item in actors), default=0)
    total_interactions = sum(item['interaction_count'] for item in actors)
    if total_interactions <= 0:
        total_interactions = sum(item['sample_count'] for item in actors)

    out = []
    for item in actors:
        total = item['sample_count']
        negative = sum(count for label, count in item['emotion_counts'].items() if LABELS_ZH.index(label) in NEGATIVE_LABEL_IDS)
        dominant_emotion = max(item['emotion_counts'].items(), key=lambda kv: kv[1])[0] if total else '中性'
        influence_score = _influence_score(item, max_interactions, max_followers)
        interaction_basis = item['interaction_count'] if total_interactions else item['sample_count']
        out.append({
            'actor_id': _actor_hash(item['uid']),
            'display_name': '',
            'verified': item['verified'],
            'verified_type': item['verified_type'],
            'verified_reason': '已脱敏' if item['verified'] else '',
            'profile_tier': item['profile_tier'],
            'followers_bucket': _followers_bucket(item['followers_count'], item['profile_tier']),
            'topic_count': item.get('topic_count', 0),
            'top_topic_id': item.get('top_topic_id'),
            'top_topic_title': item.get('top_topic_title'),
            'post_count': item['post_count'],
            'comment_count': item['comment_count'],
            'sample_count': item['sample_count'],
            'dominant_emotion': dominant_emotion,
            'negative_ratio': round(ratio(negative, total), 4),
            'interaction_count': item['interaction_count'],
            'interaction_contribution': round(ratio(interaction_basis, total_interactions), 4),
            'actor_influence_score': influence_score,
            'roles': _actor_roles(item, influence_score, ratio(negative, total)),
            'emotion_counts': item['emotion_counts'],
        })

    out.sort(key=lambda x: (x['actor_influence_score'], x['negative_ratio'], x['sample_count']), reverse=True)
    _assign_display_names(out)
    return out[:limit]


def _influence_score(item: dict, max_interactions: int, max_followers: int) -> float:
    interaction_norm = _log_norm(item['interaction_count'], max_interactions)
    follower_norm = _log_norm(item['followers_count'], max_followers) if item['profile_tier'] >= 1 else 0.0
    score = 60 * interaction_norm + 25 * follower_norm
    if item['verified']:
        score += 10
    if item['profile_tier'] >= 1:
        score += 5
    return round(min(score, 100.0), 1)


def _log_norm(value: int, cap: int) -> float:
    if value <= 0 or cap <= 0:
        return 0.0
    return min(math.log1p(value) / math.log1p(cap), 1.0)


def _actor_hash(uid: int) -> str:
    digest = hashlib.blake2b(str(uid).encode('utf-8'), digest_size=5).hexdigest()
    return f'u_{digest}'


def _followers_bucket(followers_count: int, profile_tier: int) -> str:
    if profile_tier < 1 or followers_count <= 0:
        return '未覆盖'
    if followers_count < 10_000:
        return '<1w'
    if followers_count < 100_000:
        return '1w-10w'
    if followers_count < 1_000_000:
        return '10w-100w'
    return '100w+'


def _actor_roles(item: dict, influence_score: float, negative_ratio: float) -> list[str]:
    roles = []
    if item['verified']:
        roles.append('verified_actor')
    if item['profile_tier'] >= 1 and item['followers_count'] >= 10_000:
        roles.append('high_follower_actor')
    if negative_ratio >= 0.60 and item['sample_count'] >= 3:
        roles.append('negative_actor')
    if item['sample_count'] >= 5:
        roles.append('active_actor')
    if influence_score >= 70:
        roles.append('event_key_actor')
    return roles or ['ordinary_actor']


def _assign_display_names(items: list[dict]) -> None:
    counters: Counter[str] = Counter()
    for item in items:
        prefix = _display_prefix(item)
        counters[prefix] += 1
        item['display_name'] = f'{prefix} {_display_suffix(counters[prefix])}'


def _display_prefix(item: dict) -> str:
    if item['verified']:
        return '认证账号'
    if 'high_follower_actor' in item['roles']:
        return '高粉账号'
    if 'negative_actor' in item['roles']:
        return '负面活跃账号'
    if 'active_actor' in item['roles']:
        return '活跃账号'
    return '普通账号'


def _display_suffix(index: int) -> str:
    letters = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ'
    return letters[index - 1] if index <= len(letters) else str(index)
