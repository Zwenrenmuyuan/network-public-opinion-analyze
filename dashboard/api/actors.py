"""Actor and influence-emotion aggregation routes.

关键账号 = 多维 OR：
  入口型 KOL / 身份型 KOL / 高互动型 / 情绪极化型 / 活跃发言型 / 跨话题型
任一触发即纳入候选。排序按"匹配的 role 数"DESC，再按 influence 分。
"""

from __future__ import annotations

import base64
import hashlib
import math
from collections import Counter, defaultdict

from flask import Blueprint, jsonify

from npo.config import LABELS_ZH

from .cache import cached_endpoint
from .config import (
    ACTOR_DEFAULT_LIMIT,
    ACTOR_MAX_LIMIT,
    INFLUENCE_DEFAULT_LIMIT,
    INFLUENCE_MAX_LIMIT,
    NEGATIVE_LABEL_IDS,
    PRIMARY_MODEL_VERSION,
)
from .utils import limit_arg, ratio, resolve_window, to_int, topic_id_arg

# 候选池上限。多维 OR 后理论上每窗口最多几千 uid，2000 兜底防爆库。
CANDIDATE_HARD_LIMIT = 2000
HIGH_FOLLOWER_THRESHOLD = 10_000
NEGATIVE_POLAR_RATIO = 0.60
NEGATIVE_POLAR_MIN_SAMPLES = 3
ACTIVE_VOICE_MIN_SAMPLES = 10
CROSS_TOPIC_MIN = 3


def register_actor_routes(api: Blueprint, ck) -> None:
    @api.route('/actors')
    @cached_endpoint('actors')
    def api_actors():
        return jsonify(actor_summary(
            ck,
            resolve_window(ck),
            topic_id_arg(),
            limit_arg('limit', ACTOR_DEFAULT_LIMIT, ACTOR_MAX_LIMIT),
        ))

    @api.route('/influence-emotion')
    @cached_endpoint('influence-emotion')
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
    p95 = _p95_post_interaction(ck, window)
    candidates = ck.query_json(_actor_candidate_sql(window, topic_id, p95))
    role_markers: dict[int, dict] = {}
    for r in candidates:
        uid = to_int(r.get('uid'))
        if uid <= 0:
            continue
        role_markers[uid] = {
            'is_entry_kol': bool(to_int(r.get('is_entry_kol'))),
            'is_high_inter': bool(to_int(r.get('is_high_inter'))),
            'is_polar': bool(to_int(r.get('is_polar'))),
            'is_active': bool(to_int(r.get('is_active'))),
            'is_verified_kol': bool(to_int(r.get('is_verified_kol'))),
            'is_cross_topic': bool(to_int(r.get('is_cross_topic'))),
        }
    if not role_markers:
        return []

    actor_ids = list(role_markers.keys())
    ids_sql = ','.join(str(uid) for uid in actor_ids)
    rows = ck.query_json(_actor_detail_sql(window, topic_id, ids_sql))
    topic_rows = ck.query_json(_actor_topic_sql(window, topic_id, ids_sql))
    topic_meta = _topic_meta(topic_rows)
    actors = _merge_actor_rows(rows, topic_meta)
    return _render_actors(actors, limit, role_markers)


def _p95_post_interaction(ck, window: dict) -> int:
    """窗口内单条 post 互动量 P95，作为"高互动"role 的阈值。"""
    start = window['start_utc_str']
    end = window['end_utc_str']
    row = ck.query_one(f"""
        SELECT quantile(0.95)(interaction) AS p95
        FROM (
          SELECT post_id,
            argMax(comments_count + attitudes_count + reposts_count, captured_at) AS interaction
          FROM weibo.post_engagement_ts
          WHERE captured_at >= '{start}' AND captured_at <= '{end}'
          GROUP BY post_id
        )
    """) or {}
    try:
        return max(1, int(float(row.get('p95') or 0)))
    except (TypeError, ValueError):
        return 1


def _actor_candidate_sql(window: dict, topic_id: int | None, p95_threshold: int) -> str:
    """6 个 role 分支 union all，外层按 uid 聚合 max(marker)。"""
    start = window['start_utc_str']
    end = window['end_utc_str']

    # topic 过滤（带 post_id 集合）。两个变体：作用于 weibo.post.post_id 与 sp.post_id。
    if topic_id is not None:
        topic_post_in_post = (
            f"AND p.post_id IN (SELECT post_id FROM weibo.post_topic WHERE topic_id = {topic_id})"
        )
        topic_post_in_sp = (
            f"AND sp.post_id IN (SELECT post_id FROM weibo.post_topic WHERE topic_id = {topic_id})"
        )
        topic_post_for_user = (
            f"AND post_id IN (SELECT post_id FROM weibo.post_topic WHERE topic_id = {topic_id})"
        )
    else:
        topic_post_in_post = topic_post_in_sp = topic_post_for_user = ''

    # 跨话题 role 在指定 topic_id 下没有意义（已经限定单话题），跳过
    if topic_id is None:
        cross_topic_branch = f"""
            UNION ALL
            SELECT user_id AS uid, 0, 0, 0, 0, 0, 1
            FROM (
              SELECT p.user_id, count(DISTINCT pt.topic_id) AS topics
              FROM weibo.post AS p
              INNER JOIN weibo.post_topic AS pt ON pt.post_id = p.post_id
              WHERE p.created_at >= '{start}' AND p.created_at <= '{end}'
              GROUP BY p.user_id
              HAVING topics >= {CROSS_TOPIC_MIN}
            )
        """
    else:
        cross_topic_branch = ''

    return f"""
        SELECT
          uid,
          max(is_entry_kol)     AS is_entry_kol,
          max(is_high_inter)    AS is_high_inter,
          max(is_polar)         AS is_polar,
          max(is_active)        AS is_active,
          max(is_verified_kol)  AS is_verified_kol,
          max(is_cross_topic)   AS is_cross_topic
        FROM (
          /* 1. 入口型 KOL：被 post_discovery 标记 source_type='kol' */
          SELECT
            p.user_id AS uid,
            1 AS is_entry_kol, 0 AS is_high_inter, 0 AS is_polar,
            0 AS is_active, 0 AS is_verified_kol, 0 AS is_cross_topic
          FROM weibo.post_discovery AS pd
          INNER JOIN weibo.post AS p ON p.post_id = pd.post_id
          WHERE pd.source_type = 'kol'
            AND p.created_at >= '{start}' AND p.created_at <= '{end}'
            {topic_post_in_post}

          UNION ALL

          /* 2. 高互动型：单条 post 互动 >= 窗口 P95 */
          SELECT p.user_id AS uid, 0, 1, 0, 0, 0, 0
          FROM (
            SELECT post_id,
              argMax(comments_count + attitudes_count + reposts_count, captured_at) AS interaction
            FROM weibo.post_engagement_ts
            WHERE captured_at >= '{start}' AND captured_at <= '{end}'
            GROUP BY post_id
          ) AS e
          INNER JOIN weibo.post AS p ON p.post_id = e.post_id
          WHERE e.interaction >= {p95_threshold}
            AND p.created_at >= '{start}' AND p.created_at <= '{end}'
            {topic_post_in_post}

          UNION ALL

          /* 3 + 4. 极化 + 活跃：sentiment_prediction 聚合判定 */
          SELECT
            uid,
            0,
            0,
            if(sample_count >= {NEGATIVE_POLAR_MIN_SAMPLES} AND neg / sample_count >= {NEGATIVE_POLAR_RATIO}, 1, 0) AS is_polar,
            if(sample_count >= {ACTIVE_VOICE_MIN_SAMPLES}, 1, 0) AS is_active,
            0, 0
          FROM (
            SELECT
              uid,
              sum(n) AS sample_count,
              sum(neg_n) AS neg
            FROM (
              SELECT
                p.user_id AS uid,
                count() AS n,
                countIf(sp.pred_label_id IN {NEGATIVE_LABEL_IDS}) AS neg_n
              FROM dashboard.sentiment_prediction AS sp
              INNER JOIN weibo.post AS p ON p.post_id = sp.source_id
              WHERE sp.model_version = '{PRIMARY_MODEL_VERSION}'
                AND sp.source_type = 'post'
                AND sp.source_created_at >= '{start}' AND sp.source_created_at <= '{end}'
                {topic_post_in_sp}
              GROUP BY p.user_id

              UNION ALL

              SELECT
                c.user_id AS uid,
                count() AS n,
                countIf(sp.pred_label_id IN {NEGATIVE_LABEL_IDS}) AS neg_n
              FROM dashboard.sentiment_prediction AS sp
              INNER JOIN weibo.comment AS c ON c.post_id = sp.post_id AND c.comment_id = sp.source_id
              WHERE sp.model_version = '{PRIMARY_MODEL_VERSION}'
                AND sp.source_type = 'comment'
                AND sp.source_created_at >= '{start}' AND sp.source_created_at <= '{end}'
                {topic_post_in_sp}
              GROUP BY c.user_id
            )
            GROUP BY uid
          )
          WHERE sample_count >= {NEGATIVE_POLAR_MIN_SAMPLES}
            AND (
              sample_count >= {ACTIVE_VOICE_MIN_SAMPLES}
              OR neg / sample_count >= {NEGATIVE_POLAR_RATIO}
            )

          UNION ALL

          /* 5. 身份型 KOL：verified=1 或 (profile_tier>=1 + 高粉)，且窗口内有发言 */
          SELECT u.uid, 0, 0, 0, 0, 1, 0
          FROM weibo.user AS u FINAL
          WHERE (u.verified = 1 OR (u.profile_tier >= 1 AND u.followers_count >= {HIGH_FOLLOWER_THRESHOLD}))
            AND u.uid IN (
              SELECT user_id FROM weibo.post
              WHERE created_at >= '{start}' AND created_at <= '{end}'
                {topic_post_for_user}
              UNION DISTINCT
              SELECT user_id FROM weibo.comment
              WHERE created_at >= '{start}' AND created_at <= '{end}'
                {topic_post_for_user}
            )

          {cross_topic_branch}
        )
        GROUP BY uid
        HAVING uid > 0
        LIMIT {CANDIDATE_HARD_LIMIT}
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


def _render_actors(actors: list[dict], limit: int, role_markers: dict[int, dict]) -> list[dict]:
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
        markers = role_markers.get(item['uid'], {})
        roles = _actor_roles(item, markers, ratio(negative, total))
        out.append({
            'actor_id': _actor_hash(item['uid']),
            'evidence_token': make_actor_evidence_token(item['uid']),
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
            'roles': roles,
            'role_count': len([r for r in roles if r != 'ordinary_actor']),
            'emotion_counts': item['emotion_counts'],
        })

    out.sort(
        key=lambda x: (x['role_count'], x['actor_influence_score'], x['sample_count']),
        reverse=True,
    )
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


def make_actor_evidence_token(uid: int) -> str:
    """short token 用于 evidence?actor_id= 反查 uid（脱敏 hash 不可逆，故另发 token）。"""
    return base64.urlsafe_b64encode(str(uid).encode('utf-8')).decode('ascii').rstrip('=')


def decode_actor_evidence_token(token: str) -> int | None:
    if not token:
        return None
    pad = '=' * ((-len(token)) % 4)
    try:
        raw = base64.urlsafe_b64decode((token + pad).encode('ascii')).decode('utf-8')
        return int(raw)
    except (ValueError, UnicodeDecodeError):
        return None


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


def _actor_roles(item: dict, markers: dict, negative_ratio: float) -> list[str]:
    """6 维 OR：candidate 阶段已经按各 role 触发，这里基于 marker + detail 数据做最终标记。"""
    roles: list[str] = []
    if markers.get('is_entry_kol'):
        roles.append('entry_kol')
    if item['verified']:
        roles.append('verified_actor')
    elif item['profile_tier'] >= 1 and item['followers_count'] >= HIGH_FOLLOWER_THRESHOLD:
        roles.append('high_follower_actor')
    if markers.get('is_high_inter'):
        roles.append('high_interaction')
    if markers.get('is_polar') or (
        item['sample_count'] >= NEGATIVE_POLAR_MIN_SAMPLES and negative_ratio >= NEGATIVE_POLAR_RATIO
    ):
        roles.append('negative_polarized')
    if markers.get('is_active') or item['sample_count'] >= ACTIVE_VOICE_MIN_SAMPLES:
        roles.append('active_voice')
    if markers.get('is_cross_topic') or item.get('topic_count', 0) >= CROSS_TOPIC_MIN:
        roles.append('cross_topic')
    return roles or ['ordinary_actor']


def _assign_display_names(items: list[dict]) -> None:
    counters: Counter[str] = Counter()
    for item in items:
        prefix = _display_prefix(item)
        counters[prefix] += 1
        item['display_name'] = f'{prefix} {_display_suffix(counters[prefix])}'


def _display_prefix(item: dict) -> str:
    roles = item['roles']
    if 'verified_actor' in roles:
        return '认证账号'
    if 'entry_kol' in roles:
        return 'KOL 入口账号'
    if 'high_follower_actor' in roles:
        return '高粉账号'
    if 'high_interaction' in roles:
        return '高互动账号'
    if 'negative_polarized' in roles:
        return '负面极化账号'
    if 'cross_topic' in roles:
        return '跨话题账号'
    if 'active_voice' in roles:
        return '活跃账号'
    return '普通账号'


def _display_suffix(index: int) -> str:
    letters = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ'
    return letters[index - 1] if index <= len(letters) else str(index)
